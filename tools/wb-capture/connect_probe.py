#!/usr/bin/env python3
"""connect_probe.py - 只记录 CONNECT/绝对 URI 目标，不做 TLS 终止。
用来判断客户端是否真的尊重 HTTPS_PROXY 环境变量。
"""
import socket, sys, threading, time

LISTEN = ("127.0.0.1", 8879)
LOG = r"D:\workbuddy api2\tools\wb-capture\connect_probe.log"


def handle(conn, addr):
    conn.settimeout(5)
    try:
        data = conn.recv(4096)
    except Exception:
        conn.close(); return
    if not data:
        conn.close(); return
    first = data.split(b"\r\n", 1)[0].decode("latin-1", "replace")
    with open(LOG, "a", encoding="utf-8") as f:
        f.write("%s %s <- %s\n" % (time.strftime("%H:%M:%S"), first, addr[0]))
    try:
        conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
    except Exception:
        pass
    conn.close()


def main():
    open(LOG, "a", encoding="utf-8").write("=== probe start %s ===\n" % time.strftime("%F %T"))
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(LISTEN)
    s.listen(64)
    print("connect probe on %s:%d" % LISTEN, flush=True)
    while True:
        c, a = s.accept()
        threading.Thread(target=handle, args=(c, a), daemon=True).start()


if __name__ == "__main__":
    main()
