#!/usr/bin/env python3
"""scan_logs.py - 在客户端日志里找 chat 请求的去向线索。

用法：
    python scan_logs.py --log <daemon.log> --since 2026-11-08T02:25 --keys chat/completions,model_request
"""
import argparse
import os


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--since", required=True, help="时间戳前缀，如 2026-11-08T02:25")
    ap.add_argument("--keys", default="chat/completions,model_request,model_stream,baseURL,base_url")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--width", type=int, default=400)
    args = ap.parse_args()

    keys = [k.strip().lower() for k in args.keys.split(",") if k.strip()]
    n = 0
    with open(args.log, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if args.since not in line:
                continue
            low = line.lower()
            if any(k in low for k in keys):
                print(line.rstrip()[: args.width])
                n += 1
                if n >= args.limit:
                    break
    print("matched:", n)


if __name__ == "__main__":
    main()
