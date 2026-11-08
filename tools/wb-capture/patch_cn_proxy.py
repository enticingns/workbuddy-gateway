#!/usr/bin/env python3
"""patch_cn_proxy.py - 临时把国内版 settings.json 的 http.proxy 指到本机抓包代理。

用法：
    python patch_cn_proxy.py --file <settings.json> --value http://127.0.0.1:8888
    python patch_cn_proxy.py --file <settings.json> --restore <backup>

只做「一行值替换」，不重排 JSON，避免动到用户其它设置。
"""
import argparse
import re
import shutil
import sys

PAT = re.compile(r'("http\.proxy"\s*:\s*")([^"]*)(")')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--value")
    ap.add_argument("--restore")
    args = ap.parse_args()

    if args.restore:
        shutil.copyfile(args.restore, args.file)
        raw = open(args.file, encoding="utf-8").read()
        print("restored from", args.restore, "->", PAT.findall(raw))
        return 0

    raw = open(args.file, encoding="utf-8").read()
    print("before:", PAT.findall(raw))
    raw2, n = PAT.subn(lambda m: m.group(1) + args.value + m.group(3), raw)
    print("replaced:", n)
    if n != 1:
        print("ABORT: expected exactly 1 http.proxy entry", file=sys.stderr)
        return 1
    open(args.file, "w", encoding="utf-8", newline="").write(raw2)
    print("after :", PAT.findall(raw2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
