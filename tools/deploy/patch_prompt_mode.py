#!/usr/bin/env python3
"""patch_prompt_mode.py - 把 config.json 里 prompt.mode 改成指定值（只改这一处）。

用法：
    python3 patch_prompt_mode.py --file config.json --mode custom
    python3 patch_prompt_mode.py --file config.json --show
"""
import argparse
import json
import re
import shutil
import sys
import time

BLOCK = re.compile(r'("prompt"\s*:\s*\{[^}]*?"mode"\s*:\s*")([^"]*)(")', re.S)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--mode")
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()

    raw = open(args.file, encoding="utf-8").read()
    m = BLOCK.search(raw)
    if not m:
        print("ABORT: 没找到 prompt.mode", file=sys.stderr)
        return 1
    if args.show or not args.mode:
        print("prompt.mode =", m.group(2))
        return 0

    bak = args.file + ".bak-" + time.strftime("%Y%m%d-%H%M%S")
    shutil.copyfile(args.file, bak)
    new, n = BLOCK.subn(lambda x: x.group(1) + args.mode + x.group(3), raw)
    if n != 1:
        print("ABORT: 匹配到 %d 处，期望 1" % n, file=sys.stderr)
        return 1
    open(args.file, "w", encoding="utf-8", newline="").write(new)
    json.loads(new)  # 结构自检
    print("patched: %s -> %s (backup %s)" % (m.group(2), args.mode, bak))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
