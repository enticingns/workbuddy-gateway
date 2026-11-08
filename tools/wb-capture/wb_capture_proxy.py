#!/usr/bin/env python3
"""wb_capture_proxy.py — 把官方客户端发往上游的请求原样抓下来（零证书方案）。

原理
----
官方客户端的 endpoint 来自 product config，可用 `ACC_PRODUCT_CONFIG_PATH` 注入一份
改过 endpoint 的副本。于是：

    客户端 --(http, 明文)--> 本代理 --(https)--> www.workbuddy.ai

客户端到本代理这一段是明文，不需要任何证书；本代理到上游是正常 TLS。
抓到的就是「官方客户端真实出站请求」——这正是我们要的基线。

用法
----
    python wb_capture_proxy.py --listen 127.0.0.1:8877 \
        --upstream https://www.workbuddy.ai --out captures

    # 可选：同时抓 staging / 其它域
    python wb_capture_proxy.py --listen 127.0.0.1:8877 \
        --upstream https://www.workbuddy.ai \
        --extra-upstream https://staging-codebuddy.tencent.com

产物
----
    captures/<时间戳>/0001_POST_v2_chat_completions.json
    captures/<时间戳>/_index.txt

脱敏：Authorization / X-Device-Token / X-Refresh-Token / Cookie / acp-session-token 等
只留前 10 字符与长度，**完整凭证不落盘**。
"""
import argparse
import json
import os
import ssl
import sys
import threading
import time
from http.client import HTTPSConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

MASK_HEADERS = {
    "authorization", "x-device-token", "x-refresh-token", "cookie", "set-cookie",
    "x-api-key", "access-token", "acp-session-token", "proxy-authorization",
}
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
}
MAX_BODY_LOG = 512 * 1024      # 单请求 body 最多记 512 KB
MAX_SSE_FRAMES = 4000          # SSE 帧最多记 4000 条
MAX_CHUNKS = 20000

_seq_lock = threading.Lock()
_seq = 0


def mask_value(name, value):
    if name.lower() in MASK_HEADERS and value:
        if len(value) <= 16:
            return "***"
        return value[:10] + "...(len=%d)" % len(value)
    return value


class Capture:
    def __init__(self, out_root, upstream_map):
        self.out_root = out_root
        self.upstream_map = upstream_map

    def new_dir(self):
        d = os.path.join(self.out_root, time.strftime("%Y%m%d-%H%M%S"))
        os.makedirs(d, exist_ok=True)
        return d


def pick_upstream(path, map_):
    """按路径挑上游；默认取第一个。"""
    for prefix, base in map_.items():
        if prefix and prefix != "*" and path.startswith(prefix):
            return base
    return map_.get("*")


def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "wb-capture/1.0"

    # 由 server 注入
    out_dir = None
    upstream_map = None
    index_path = None

    def log_message(self, fmt, *args):
        sys.stderr.write("[proxy] " + (fmt % args) + "\n")

    def _handle(self):
        global _seq
        started = time.time()
        u = urlsplit(self.path)
        path = u.path or "/"
        query = u.query
        target = pick_upstream(path, self.upstream_map)
        if not target:
            self.send_error(502, "no upstream")
            return
        tu = urlsplit(target)

        # 读请求体
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""

        with _seq_lock:
            _seq += 1
            seq = _seq

        req_headers = []
        for k, v in self.headers.items():
            req_headers.append([k, mask_value(k, v)])

        # 转发
        conn = HTTPSConnection(tu.hostname, tu.port or 443, timeout=600,
                               context=ssl.create_default_context())
        fwd_path = (tu.path.rstrip("/") if tu.path else "") + path
        if query:
            fwd_path += "?" + query
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
        try:
            conn.request(self.command, fwd_path, body=body or None, headers=headers)
            resp = conn.getresponse()
        except Exception as e:
            rec = {
                "seq": seq, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "method": self.command, "path": path, "query": query,
                "request_headers": req_headers,
                "request_body_bytes": len(body),
                "error": "upstream request failed: %s" % e,
                "elapsed_ms": int((time.time() - started) * 1000),
            }
            self._save(seq, path, rec)
            self.send_error(502, "upstream failed")
            return

        # 回写响应头
        self.send_response(resp.status)
        resp_headers = []
        for k, v in resp.getheaders():
            resp_headers.append([k, mask_value(k, v)])
            if k.lower() in ("content-length", "transfer-encoding", "connection"):
                continue
            self.send_header(k, v)
        self.send_header("Connection", "close")
        self.end_headers()

        ctype = (resp.getheader("Content-Type") or "").lower()
        is_sse = "text/event-stream" in ctype
        first_byte = None
        chunks = []
        sse_frames = []
        buf = b""
        total = 0
        while True:
            data = resp.read(4096)
            if not data:
                break
            if first_byte is None:
                first_byte = time.time()
            total += len(data)
            try:
                self.wfile.write(data)
                self.wfile.flush()
            except Exception:
                break
            if len(chunks) < MAX_CHUNKS:
                chunks.append({"t_ms": int((time.time() - started) * 1000), "bytes": len(data)})
            if is_sse and len(sse_frames) < MAX_SSE_FRAMES:
                buf += data
                while b"\n\n" in buf:
                    frame, buf = buf.split(b"\n\n", 1)
                    sse_frames.append(frame.decode("utf-8", "replace")[:4096])
        conn.close()

        rec = {
            "seq": seq,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "method": self.command,
            "path": path,
            "query": query,
            "upstream": target,
            "request_headers": req_headers,
            "request_body_bytes": len(body),
            "request_body": body[:MAX_BODY_LOG].decode("utf-8", "replace"),
            "request_body_truncated": len(body) > MAX_BODY_LOG,
            "response_status": resp.status,
            "response_headers": resp_headers,
            "response_content_type": ctype,
            "response_bytes": total,
            "ttfb_ms": int((first_byte - started) * 1000) if first_byte else None,
            "elapsed_ms": int((time.time() - started) * 1000),
            "chunk_count": len(chunks),
            "chunks": chunks[:200],
            "sse_frames": sse_frames,
        }
        self._save(seq, path, rec)

    def _save(self, seq, path, rec):
        safe = path.strip("/").replace("/", "_") or "root"
        name = "%04d_%s_%s.json" % (seq, rec["method"], safe[:80])
        write_json(os.path.join(self.out_dir, name), rec)
        try:
            with open(self.index_path, "a", encoding="utf-8") as f:
                f.write("%s %s %s -> %s  %sms  %dB\n" % (
                    rec["ts"], rec["method"], path,
                    rec.get("response_status", "ERR"), rec.get("elapsed_ms"), rec.get("response_bytes", 0)))
        except Exception:
            pass
        self.log_message("%s %s -> %s", rec["method"], path, rec.get("response_status", "ERR"))

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def do_PUT(self):
        self._handle()

    def do_DELETE(self):
        self._handle()

    def do_HEAD(self):
        self._handle()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", default="127.0.0.1:8877")
    ap.add_argument("--upstream", default="https://www.workbuddy.ai")
    ap.add_argument("--extra-upstream", action="append", default=[],
                    help="额外上游，形如 /v2/=https://staging-codebuddy.tencent.com")
    ap.add_argument("--out", default="captures")
    args = ap.parse_args()

    host, port = args.listen.rsplit(":", 1)
    cap = Capture(args.out, None)
    out_dir = cap.new_dir()

    upstream_map = {"*": args.upstream.rstrip("/")}
    for spec in args.extra_upstream:
        if "=" in spec:
            pfx, base = spec.split("=", 1)
            upstream_map[pfx] = base.rstrip("/")

    Handler.out_dir = out_dir
    Handler.upstream_map = upstream_map
    Handler.index_path = os.path.join(out_dir, "_index.txt")

    srv = ThreadingHTTPServer((host, int(port)), Handler)
    print("capture proxy listening on http://%s:%s" % (host, port))
    print("upstream map: %s" % json.dumps(upstream_map, ensure_ascii=False))
    print("out: %s   (Ctrl+C 结束)" % out_dir)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
