#!/usr/bin/env python3
"""从真机抓包里统计 chat 请求的真实头集合，用于校正 wb_diff_capture.py 的对照表。

用法：
    python wb_extract_baseline.py tools/wb-capture/captures/20261028-094322

输出：
    - chat 请求实际发的头（并集 / 交集）
    - 各头出现次数
    - 可直接粘进 wb_diff_capture.py 的 Python 字面量
"""
import json
import os
import sys
from collections import Counter

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CHAT_MARKERS = ("chat_completions", "conversations_v2", "conversations_")


def is_chat(name):
    return any(m in name for m in CHAT_MARKERS)


def load_headers(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            d = json.load(f)
    except Exception:
        return None
    h = d.get("request_headers") or d.get("headers") or {}
    if isinstance(h, list):
        out = {}
        for item in h:
            if isinstance(item, dict) and "name" in item:
                out[str(item["name"]).lower()] = item.get("value", "")
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                # 抓包格式：[["Header-Name", "value"], ...]
                out[str(item[0]).lower()] = item[1]
            elif isinstance(item, (list, tuple)) and len(item) == 1:
                out[str(item[0]).lower()] = ""
        return out
    if isinstance(h, dict):
        return {str(k).lower(): v for k, v in h.items()}
    return None


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "tools/wb-capture/captures/20261028-094322"
    path_filter = sys.argv[2] if len(sys.argv) > 2 else "/v2/chat/completions"
    files = []
    for dirpath, _, names in os.walk(root):
        for n in names:
            if n.endswith(".json") and is_chat(n):
                files.append(os.path.join(dirpath, n))
    files.sort()
    if not files:
        print("没有找到 chat 抓包文件：", root)
        return 1

    print("chat 抓包文件数：%d（按 path 过滤：%s）" % (len(files), path_filter))
    counter = Counter()
    per_file = []
    skipped = 0
    for p in files:
        h = load_headers(p)
        if h is None:
            skipped += 1
            continue
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                d = json.load(f)
            path = d.get("path") or ""
        except Exception:
            path = ""
        if path_filter and path_filter not in path:
            continue
        per_file.append((os.path.basename(p), path, set(h)))
        for k in h:
            counter[k] += 1

    n = len(per_file)
    if n == 0:
        print("过滤后没有匹配请求。可用 path 见下：")
        seen = set()
        for p in files:
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    seen.add(json.load(f).get("path") or "?")
            except Exception:
                pass
        for s in sorted(seen):
            print("  ", s)
        return 1

    print("\n=== 匹配到的请求 ===")
    for name, path, _ in per_file:
        print("  %-70s %s" % (name, path))

    print("\n=== 头出现次数（分母 %d）===" % n)
    for k, c in counter.most_common():
        mark = "全部" if c == n else ("%d/%d" % (c, n))
        print("  %-34s %s" % (k, mark))

    always = {k for k, c in counter.items() if c == n}
    sometimes = {k for k, c in counter.items() if 0 < c < n}

    print("\n=== 始终出现的头（%d 个）===" % len(always))
    print("CLIENT_EXPECTED_ALWAYS = {")
    for k in sorted(always):
        print('    "%s",' % k)
    print("}")

    if sometimes:
        print("\n=== 部分请求才有的头（%d 个）===" % len(sometimes))
        print("CLIENT_EXPECTED_OPTIONAL = {")
        for k in sorted(sometimes):
            print('    "%s",  # %d/%d' % (k, counter[k], n))
        print("}")

    print("\n=== 明确从不出现（官方客户端没有）===")
    for k in ["origin", "referer", "accept-language", "x-machine-id", "x-session-id"]:
        print("  %-20s %s" % (k, "出现" if k in counter else "从不出现"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
