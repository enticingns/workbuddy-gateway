#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仓库隐私/凭据扫描（提交前与 CI 双重闸）。

背景：本项目是**公开**仓库，且历史上曾把实测数据（账号邮箱、手机号、真实客户端
IP、部署主机信息）写进文档。一次泄漏就无法从 clone 出去的分支回收，所以把拦截
做成机器可执行的规则，而不是靠人眼 review。

检查项：
  1. 邮箱（排除 github noreply / example.com 等保留域）
  2. 中国大陆手机号（排除测试占位号）
  3. 私钥块 / 常见云厂商与平台令牌前缀
  4. SSH 主机密钥指纹（SHA256:...）
  5. 真实客户端 IP（仅允许 TEST-NET / 私有网段 / 回环 / 文档示例地址）

用法：
  python scripts/privacy_scan.py            # 扫描 git 已跟踪文件（缺 git 则扫工作区）
  python scripts/privacy_scan.py --all      # 连未跟踪文件一起扫（提交前自查）
  python scripts/privacy_scan.py --quiet    # 只输出命中项与退出码

退出码：0 = 干净，1 = 有命中（CI 据此 fail）。
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

# 允许出现的「假」值（测试占位 / 文档示例 / 公共占位域）。
EMAIL_ALLOW = (
    "example.com", "example.org", "example.net", "test.local",
    "users.noreply.github.com", "noreply.github.com", "localhost",
    "upstash.io", "foo.bar", "domain.com",
)
PHONE_ALLOW = ("13800000000",)  # 单元测试里的手机号占位（校验解析用，非真人号码）
# 允许出现的 IP：回环 / 私有网段 / TEST-NET-1..3 / 公共 DNS 文档值。
IP_ALLOW_PREFIX = (
    "127.", "10.", "192.168.", "172.16.", "172.17.", "172.18.", "172.19.",
    "172.2", "172.30.", "172.31.", "0.0.0.0", "255.255.255.255",
    "192.0.2.", "198.51.100.", "203.0.113.", "169.254.", "100.64.",
)
IP_ALLOW_EXACT = {
    "223.5.5.5", "223.6.6.6",      # AliDNS（dns.go 注释里的公共解析器示例）
    "119.29.29.29", "182.254.116.116",  # DNSPod 公共 DNS
    "8.8.8.8", "1.1.1.1",          # 国际公共 DNS
}

PATTERNS = [
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("PHONE", re.compile(r"(?<![0-9])1[3-9][0-9]{9}(?![0-9])")),
    ("PRIVATE_KEY", re.compile(r"BEGIN [A-Z ]*PRIVATE KEY")),
    ("TOKEN", re.compile(
        r"ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
        r"gho_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|"
        r"AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{20,}|sk_live_[A-Za-z0-9]{10,}")),
    ("HOSTKEY", re.compile(r"SHA256:[A-Za-z0-9+/]{30,}")),
    # 前面是 "/" 的是版本号（Chrome/120.0.0.0），不是 IP。
    ("IPV4", re.compile(r"(?<![0-9./])((?:[0-9]{1,3}\.){3}[0-9]{1,3})(?![0-9.])")),
]

# 二进制/大文件跳过（模型目录 JSON 也扫，它是文本）。
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".zip", ".gz",
            ".exe", ".dll", ".so", ".dylib", ".pdf", ".woff", ".woff2", ".pyc"}


def is_allowed_email(m: str) -> bool:
    low = m.lower()
    return any(low.endswith("@" + d) or low.endswith("." + d) or d in low for d in EMAIL_ALLOW)


def is_allowed_ip(ip: str) -> bool:
    if ip in IP_ALLOW_EXACT:
        return True
    parts = ip.split(".")
    if len(parts) != 4:
        return True
    if not all(p.isdigit() for p in parts):
        return False  # 形如 1.2.3.版本号 的字符串会被这里放行
    if any(int(p) > 255 for p in parts):
        return True
    if ip.startswith(IP_ALLOW_PREFIX):
        return True
    # 形如 5.9.3.42136757 的版本号/时间戳片段不算 IP：要求四段都在 0-255，
    # 且不出现明显的四位数段（版本号常见）。
    if any(len(p) > 3 for p in parts):
        return True
    return False


def tracked_files(root: str, include_untracked: bool) -> list[str]:
    try:
        if include_untracked:
            out = subprocess.run(
                ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                cwd=root, capture_output=True, text=True, check=True).stdout
        else:
            out = subprocess.run(["git", "ls-files"], cwd=root,
                                 capture_output=True, text=True, check=True).stdout
    except Exception:
        files = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in
                           {".git", "node_modules", "auths", "data", "captures",
                            "captures_mitm", "ca", "__pycache__"}]
            for fn in filenames:
                files.append(os.path.relpath(os.path.join(dirpath, fn), root))
        return files
    return [line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()]


def scan_file(path: str) -> list[tuple[int, str, str]]:
    hits = []
    if os.path.splitext(path)[1].lower() in SKIP_EXT:
        return hits
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for lineno, line in enumerate(fh, 1):
                for name, pat in PATTERNS:
                    for m in pat.finditer(line):
                        val = m.group(0)
                        if name == "EMAIL" and is_allowed_email(val):
                            continue
                        if name == "PHONE" and val in PHONE_ALLOW:
                            continue
                        if name == "IPV4" and is_allowed_ip(val):
                            continue
                        if name == "TOKEN" and val.lower() in ("sk-xxx", "sk-test"):
                            continue
                        hits.append((lineno, name, val))
    except OSError:
        pass
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description="公开仓库隐私/凭据扫描")
    ap.add_argument("--root", default=".", help="仓库根目录（默认当前目录）")
    ap.add_argument("--all", action="store_true", help="连未跟踪文件一起扫")
    ap.add_argument("--quiet", action="store_true", help="只输出命中项")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    files = tracked_files(root, args.all)
    bad = 0
    for rel in files:
        full = os.path.join(root, rel)
        if not os.path.isfile(full):
            continue
        hits = scan_file(full)
        for lineno, name, val in hits:
            bad += 1
            print(f"{rel}:{lineno}: [{name}] {val}")
    if not args.quiet:
        print(f"-- scanned {len(files)} files, {bad} hit(s)")
    if bad:
        print("FAIL: 命中疑似隐私/凭据内容；请脱敏后重跑（允许值见脚本内 ALLOW 列表）。",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
