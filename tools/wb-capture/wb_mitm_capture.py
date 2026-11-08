#!/usr/bin/env python3
"""wb_mitm_capture.py - 通过 HTTPS_PROXY 做 TLS 中间人，抓官方客户端真实出站请求。

为什么需要它：CN 客户端的 chat base URL 由云配置决定（https://www.workbuddy.cn/v3/config），
改本地 product.json / ACC_PRODUCT_CONFIG_PATH 都拦不住它；但客户端确实尊重
HTTPS_PROXY（实测 CONNECT 全部落到本机）。于是走 MITM：

    客户端 --CONNECT 127.0.0.1:8888--> 本代理 --(TLS, 校验证书)--> 真实上游

产物与 wb_capture_proxy.py 同构，可直接喂给 wb_diff_capture.py。

用法：
    python wb_mitm_capture.py --listen 127.0.0.1:8888 --out captures_mitm --only www.workbuddy.cn
首次运行会生成 CA（ca/ca.key.pem、ca/ca.crt.pem），把 ca.crt.pem 导入
「当前用户 / 受信任的根证书颁发机构」即可让客户端信任。
"""
import argparse
import datetime
import json
import os
import socket
import ssl
import sys
import threading
import time
import zlib

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

MASK_HEADERS = {
    "authorization", "x-device-token", "x-refresh-token", "cookie", "set-cookie",
    "x-api-key", "access-token", "acp-session-token", "proxy-authorization",
}
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "proxy-connection",
    "content-length",
}
MAX_BODY_LOG = 512 * 1024
MAX_SSE_FRAMES = 4000

_seq_lock = threading.Lock()
_seq = 0


def mask(name, value):
    if name.lower() in MASK_HEADERS and value:
        if len(value) <= 16:
            return "***"
        return value[:10] + "...(len=%d)" % len(value)
    return value


class CertAuthority:
    def __init__(self, ca_dir):
        self.dir = ca_dir
        os.makedirs(ca_dir, exist_ok=True)
        self.key_path = os.path.join(ca_dir, "ca.key.pem")
        self.crt_path = os.path.join(ca_dir, "ca.crt.pem")
        if os.path.exists(self.key_path) and os.path.exists(self.crt_path):
            self.key = serialization.load_pem_private_key(open(self.key_path, "rb").read(), None)
            self.crt = x509.load_pem_x509_certificate(open(self.crt_path, "rb").read())
        else:
            self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "WB Capture Local CA")])
            now = datetime.datetime.now(datetime.timezone.utc)
            self.crt = (
                x509.CertificateBuilder()
                .subject_name(name).issuer_name(name)
                .public_key(self.key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(days=1))
                .not_valid_after(now + datetime.timedelta(days=3650))
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                .add_extension(
                    x509.KeyUsage(digital_signature=True, key_encipherment=False,
                                  key_cert_sign=True, crl_sign=True,
                                  content_commitment=False, data_encipherment=False,
                                  key_agreement=False, encipher_only=False, decipher_only=False),
                    critical=True)
                .add_extension(
                    x509.SubjectKeyIdentifier.from_public_key(self.key.public_key()),
                    critical=False)
                .sign(self.key, hashes.SHA256())
            )
            open(self.key_path, "wb").write(self.key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption()))
            open(self.crt_path, "wb").write(self.crt.public_bytes(serialization.Encoding.PEM))
        self.leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self._cache = {}

    def context_for(self, host):
        if host in self._cache:
            return self._cache[host]
        import ipaddress
        try:
            san = [x509.IPAddress(ipaddress.ip_address(host))]
        except ValueError:
            san = [x509.DNSName(host)]
        now = datetime.datetime.now(datetime.timezone.utc)
        leaf = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)]))
            .issuer_name(self.crt.subject)
            .public_key(self.leaf_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=397))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True, key_encipherment=True,
                    key_cert_sign=False, crl_sign=False,
                    content_commitment=False, data_encipherment=False,
                    key_agreement=False, encipher_only=False, decipher_only=False),
                critical=False)
            .add_extension(
                x509.ExtendedKeyUsage([x509.ExtendedKeyUsageOID.SERVER_AUTH]),
                critical=False)
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(self.leaf_key.public_key()),
                critical=False)
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(self.key.public_key()),
                critical=False)
            .sign(self.key, hashes.SHA256())
        )
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        # 同时提供 h2 与 http/1.1：若客户端只发 h2（chat 可能如此），则协商 h2 走原始隧道
        ctx.set_alpn_protocols(["h2", "http/1.1"])
        ctx.load_cert_chain(*self._materialize(host, leaf))
        self._cache[host] = ctx
        return ctx

    def _materialize(self, host, leaf):
        safe = "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in host)
        cert = os.path.join(self.dir, "leaf-%s.crt.pem" % safe)
        key = os.path.join(self.dir, "leaf-%s.key.pem" % safe)
        open(cert, "wb").write(leaf.public_bytes(serialization.Encoding.PEM))
        open(key, "wb").write(self.leaf_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption()))
        return cert, key


def read_headers(f):
    line = f.readline(65536)
    if not line:
        return None, []
    headers = []
    while True:
        h = f.readline(65536)
        if h in (b"\r\n", b"\n", b""):
            break
        k, _, v = h.decode("latin-1").partition(":")
        headers.append((k.strip(), v.strip()))
    return line, headers


def get(hmap, name, default=""):
    for k, v in hmap:
        if k.lower() == name:
            return v
    return default


def decode_body(body, headers):
    """按 Content-Encoding 解压后再解码，让 gzip/deflate/br 的请求体可读。"""
    if not body:
        return ""
    raw = body
    enc = get(headers, "content-encoding").lower()
    try:
        if "gzip" in enc or (raw[:2] == b"\x1f\x8b"):
            raw = zlib.decompress(raw, 16 + zlib.MAX_WBITS)
        elif "deflate" in enc:
            try:
                raw = zlib.decompress(raw)
            except Exception:
                raw = zlib.decompress(raw, -zlib.MAX_WBITS)
        elif "br" in enc:
            try:
                import brotli  # 可选依赖
                raw = brotli.decompress(raw)
            except Exception:
                pass
    except Exception:
        raw = body
    return raw[:MAX_BODY_LOG].decode("utf-8", "replace")


class Ctx:
    def __init__(self, args, ca):
        self.args = args
        self.ca = ca
        self.out_dir = os.path.join(args.out, time.strftime("%Y%m%d-%H%M%S"))
        os.makedirs(self.out_dir, exist_ok=True)
        self.index = os.path.join(self.out_dir, "_index.txt")


def save(ctx, rec):
    global _seq
    with _seq_lock:
        _seq += 1
        rec["seq"] = _seq
    safe = rec["path"].strip("/").replace("/", "_") or "root"
    name = "%04d_%s_%s.json" % (rec["seq"], rec["method"], safe[:80])
    path = os.path.join(ctx.out_dir, name)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    os.replace(path + ".tmp", path)
    with open(ctx.index, "a", encoding="utf-8") as f:
        f.write("%s %s %s%s -> %s %sms %dB\n" % (
            rec["ts"], rec["method"], rec["path"],
            ("?" + rec["query"]) if rec.get("query") else "",
            rec.get("response_status", "ERR"), rec.get("elapsed_ms"), rec.get("response_bytes", 0)))


def forward_one(ctx, tls, host, port):
    """在同一 TLS 连接上处理一个请求（keep-alive 循环）。"""
    started = time.time()
    f = tls.makefile("rb")
    reqline, headers = read_headers(f)
    if not reqline:
        return False
    parts = reqline.decode("latin-1").strip().split(" ")
    if len(parts) < 2:
        return False
    method, target = parts[0], parts[1]
    path, _, query = target.partition("?")

    body = b""
    clen = get(headers, "content-length")
    if clen.isdigit():
        body = f.read(int(clen))
    elif get(headers, "transfer-encoding").lower() == "chunked":
        chunks = []
        while True:
            size_line = f.readline(65536).strip()
            if not size_line:
                break
            try:
                n = int(size_line.split(b";")[0], 16)
            except ValueError:
                break
            if n == 0:
                f.readline(65536)
                break
            chunks.append(f.read(n))
            f.readline(65536)
        body = b"".join(chunks)

    up_ctx = ssl.create_default_context()
    up = up_ctx.wrap_socket(socket.create_connection((host, port), timeout=600),
                            server_hostname=host)
    hdrs = {k: v for k, v in headers if k.lower() not in HOP_BY_HOP}
    raw = ["%s %s HTTP/1.1" % (method, target)]
    for k, v in hdrs.items():
        raw.append("%s: %s" % (k, v))
    if body or method in ("POST", "PUT", "PATCH"):
        # 必须重新声明长度：上游靠它判断 body 边界，缺了会直接 400
        raw.append("Content-Length: %d" % len(body))
    raw.append("Connection: close")
    up.sendall(("\r\n".join(raw) + "\r\n\r\n").encode("latin-1") + body)

    uf = up.makefile("rb")
    status_line = uf.readline(65536)
    if not status_line:
        return False
    try:
        status = int(status_line.split(b" ")[1])
    except Exception:
        status = 0
    resp_headers = []
    while True:
        h = uf.readline(65536)
        if h in (b"\r\n", b"\n", b""):
            break
        k, _, v = h.decode("latin-1").partition(":")
        resp_headers.append((k.strip(), v.strip()))

    ctype = get(resp_headers, "content-type").lower()
    is_sse = "text/event-stream" in ctype
    chunked = get(resp_headers, "transfer-encoding").lower() == "chunked"
    rlen = get(resp_headers, "content-length")
    out = ["HTTP/1.1 %d %s" % (status, status_line.decode("latin-1").split(" ", 2)[-1].strip())]
    for k, v in resp_headers:
        if k.lower() in ("connection", "transfer-encoding", "content-length"):
            continue
        out.append("%s: %s" % (k, v))
    # 关键：chunked 响应必须保留 Transfer-Encoding，否则客户端会把 chunk 长度行
    # （如 "46f\r\n"）当成 body 开头，导致 JSON 解析失败（表现为 retryable_invalid）
    if chunked:
        out.append("Transfer-Encoding: chunked")
    elif (rlen or "").isdigit():
        out.append("Content-Length: %s" % rlen)
    out.append("Connection: close")
    tls.sendall(("\r\n".join(out) + "\r\n\r\n").encode("latin-1"))

    first_byte = None
    total = 0
    sse_frames = []
    buf = b""
    resp_chunks = []
    resp_cap = 0
    MAX_RESP_LOG = 65536
    if is_sse or not (rlen or "").isdigit():
        while True:
            data = uf.read(4096)
            if not data:
                break
            if first_byte is None:
                first_byte = time.time()
            total += len(data)
            if resp_cap < MAX_RESP_LOG:
                take = data[:MAX_RESP_LOG - resp_cap]
                resp_chunks.append(take)
                resp_cap += len(take)
            try:
                tls.sendall(data)
            except Exception:
                break
            if is_sse and len(sse_frames) < MAX_SSE_FRAMES:
                buf += data
                while b"\n\n" in buf:
                    fr, buf = buf.split(b"\n\n", 1)
                    sse_frames.append(fr.decode("utf-8", "replace")[:4096])
    else:
        remaining = int(rlen)
        while remaining > 0:
            data = uf.read(min(4096, remaining))
            if not data:
                break
            if first_byte is None:
                first_byte = time.time()
            remaining -= len(data)
            total += len(data)
            if resp_cap < MAX_RESP_LOG:
                take = data[:MAX_RESP_LOG - resp_cap]
                resp_chunks.append(take)
                resp_cap += len(take)
            try:
                tls.sendall(data)
            except Exception:
                break
    try:
        up.close()
    except Exception:
        pass

    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "method": method,
        "path": path,
        "query": query,
        "upstream": "https://%s:%d" % (host, port),
        "request_headers": [[k, mask(k, v)] for k, v in headers],
        "request_body_bytes": len(body),
        "request_body": decode_body(body, headers),
        "request_body_truncated": len(body) > MAX_BODY_LOG,
        "response_status": status,
        "response_headers": [[k, mask(k, v)] for k, v in resp_headers],
        "response_content_type": ctype,
        "response_bytes": total,
        "response_body": "" if is_sse else decode_body(b"".join(resp_chunks), resp_headers),
        "ttfb_ms": int((first_byte - started) * 1000) if first_byte else None,
        "elapsed_ms": int((time.time() - started) * 1000),
        "sse_frames": sse_frames,
    }
    save(ctx, rec)
    print("[mitm] %s %s %s -> %s (%dB, sse=%d)" % (
        host, method, path, status, total, len(sse_frames)), flush=True)
    return False  # 每请求一连接，简单可靠


def forward_abs(ctx, conn, f, reqline):
    """普通 HTTP 代理请求（绝对 URL 形式，如 http://127.0.0.1:56054/xxx）。
    必须正确转发，否则客户端访问本地 worker 会 405，导致 worker 指纹抖动被反复杀掉。"""
    from urllib.parse import urlsplit
    parts = reqline.split(" ")
    if len(parts) < 3:
        conn.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
        conn.close(); return
    method, url, _ver = parts[0], parts[1], parts[2]
    u = urlsplit(url)
    host = u.hostname or ""
    if not host:
        conn.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
        conn.close(); return
    port = u.port or (443 if u.scheme == "https" else 80)
    headers = []
    while True:
        h = f.readline(65536)
        if h in (b"\r\n", b"\n", b""):
            break
        k, _, v = h.decode("latin-1").partition(":")
        headers.append((k.strip(), v.strip()))
    body = b""
    clen = get(headers, "content-length")
    if clen.isdigit():
        body = f.read(int(clen))
    elif get(headers, "transfer-encoding").lower() == "chunked":
        chunks = []
        while True:
            sl = f.readline(65536).strip()
            if not sl:
                break
            try:
                n = int(sl.split(b";")[0], 16)
            except ValueError:
                break
            if n == 0:
                f.readline(65536)
                break
            chunks.append(f.read(n))
            f.readline(65536)
        body = b"".join(chunks)
    try:
        up = socket.create_connection((host, port), timeout=600)
        if u.scheme == "https":
            up = ssl.create_default_context().wrap_socket(up, server_hostname=host)
    except Exception as e:
        print("[abs] connect %s:%s failed: %s" % (host, port, e), flush=True)
        try:
            conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
        except Exception:
            pass
        conn.close(); return
    path = (u.path or "/") + (("?" + u.query) if u.query else "")
    raw = ["%s %s HTTP/1.1" % (method, path)]
    for k, v in headers:
        if k.lower() in ("proxy-connection", "connection", "keep-alive"):
            continue
        raw.append("%s: %s" % (k, v))
    if body or method in ("POST", "PUT", "PATCH"):
        raw.append("Content-Length: %d" % len(body))
    raw.append("Connection: close")
    started = time.time()
    first_byte = None
    resp_buf = b""
    CAP = 8 * 1024 * 1024
    try:
        up.sendall(("\r\n".join(raw) + "\r\n\r\n").encode("latin-1") + body)
        while True:
            d = up.recv(65536)
            if not d:
                break
            if first_byte is None:
                first_byte = time.time()
            if len(resp_buf) < CAP:
                resp_buf += d[:CAP - len(resp_buf)]
            conn.sendall(d)
    except Exception as e:
        print("[abs] relay %s:%s error: %s" % (host, port, e), flush=True)
    finally:
        try:
            up.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
    # 记录（跳过本地 worker，只看外部域名）
    if host not in ("127.0.0.1", "localhost", "::1"):
        try:
            status = 0
            resp_headers = []
            resp_body = b""
            if resp_buf:
                hdr_end = resp_buf.find(b"\r\n\r\n")
                if hdr_end > 0:
                    head = resp_buf[:hdr_end].decode("latin-1")
                    lines = head.split("\r\n")
                    try:
                        status = int(lines[0].split(" ")[1])
                    except Exception:
                        status = 0
                    for ln in lines[1:]:
                        k, _, v = ln.partition(":")
                        if k.strip():
                            resp_headers.append((k.strip(), v.strip()))
                    resp_body = resp_buf[hdr_end + 4:]
            ctype2 = get(resp_headers, "content-type").lower()
            is_sse2 = "text/event-stream" in ctype2
            sse = []
            if is_sse2:
                for fr in resp_body.split(b"\n\n"):
                    if fr.strip():
                        sse.append(fr.decode("utf-8", "replace")[:4096])
                    if len(sse) >= MAX_SSE_FRAMES:
                        break
            rec = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "method": method,
                "path": path,
                "query": u.query,
                "upstream": "%s://%s:%d" % (u.scheme, host, port),
                "via": "abs-proxy",
                "request_headers": [[k, mask(k, v)] for k, v in headers],
                "request_body_bytes": len(body),
                "request_body": decode_body(body, headers),
                "request_body_truncated": len(body) > MAX_BODY_LOG,
                "response_status": status,
                "response_headers": [[k, mask(k, v)] for k, v in resp_headers],
                "response_content_type": ctype2,
                "response_bytes": len(resp_body),
                "response_body": "" if is_sse2 else resp_body[:65536].decode("utf-8", "replace"),
                "ttfb_ms": int((first_byte - started) * 1000) if first_byte else None,
                "elapsed_ms": int((time.time() - started) * 1000),
                "sse_frames": sse,
            }
            save(ctx, rec)
            print("[abs] %s %s %s -> %s (%dB, sse=%d)" % (
                host, method, path, status, len(resp_body), len(sse)), flush=True)
        except Exception as e:
            print("[abs] record error: %s" % e, flush=True)


def handle(ctx, conn, addr):
    conn.settimeout(600)
    f = conn.makefile("rb")
    line = f.readline(65536)
    if not line:
        conn.close(); return
    line = line.decode("latin-1").strip()
    if not line.upper().startswith("CONNECT"):
        # 普通 HTTP 代理请求（绝对 URL 形式）—— 客户端访问本地 worker 走这里
        forward_abs(ctx, conn, f, line)
        return
    target = line.split(" ")[1]
    host, _, port_s = target.partition(":")
    port = int(port_s or 443)
    only = ctx.args.only
    conn.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
    if only and host not in only:
        # 不抓的域名：直接透传
        try:
            up = socket.create_connection((host, port), timeout=600)
            pipe(conn, up)
        except Exception:
            pass
        conn.close(); return
    try:
        tls = ctx.ca.context_for(host).wrap_socket(conn, server_side=True)
    except Exception as e:
        print("[mitm] TLS handshake failed for %s: %s" % (host, e), flush=True)
        conn.close(); return
    alpn = tls.selected_alpn_protocol()
    if alpn == "h2":
        # chat 等客户端强制 h2：做原始字节隧道并记录
        handle_h2(ctx, tls, host, port)
        return
    try:
        forward_one(ctx, tls, host, port)
    except Exception as e:
        print("[mitm] error %s %s: %s" % (host, target, e), flush=True)
    finally:
        try:
            tls.close()
        except Exception:
            pass


def pipe(a, b):
    def pump(src, dst):
        try:
            while True:
                d = src.recv(65536)
                if not d:
                    break
                dst.sendall(d)
        except Exception:
            pass
    t = threading.Thread(target=pump, args=(b, a), daemon=True)
    t.start()
    pump(a, b)


def handle_h2(ctx, tls, host, port):
    """客户端强制 h2：读 preface、连上游 h2、双向转发原始帧，并落盘原始字节。"""
    import select
    safe = "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in host)
    raw = os.path.join(ctx.out_dir, "_h2raw-%s-%d.bin" % (safe, time.time()))
    rf = open(raw, "wb")
    def log(dirn, data):
        try:
            if data:
                n = rf.write(b">>%s<< " % dirn.encode() + data + b"\n")
                rf.flush()
                return n
        except Exception as e:
            print("[h2] log write error: %s" % e, flush=True)
        return 0
    up_tls = None
    try:
        print("[h2] enter %s" % host, flush=True)
        # 读客户端 h2 preface（24 字节，阻塞 recv 循环；不用 makefile 避免预读丢数据）
        tls.setblocking(True)
        tls.settimeout(10)
        preface = b""
        while len(preface) < 24:
            chunk = tls.recv(24 - len(preface))
            if not chunk:
                print("[h2] client recv EOF at %d bytes" % len(preface), flush=True)
                break
            preface += chunk
        log("C", preface)
        print("[h2] preface len=%d head=%s size=%d path=%s" % (
            len(preface), preface[:24], os.path.getsize(raw), raw), flush=True)
        if len(preface) < 24:
            print("[mitm] h2 client closed before full preface (%d bytes)" % len(preface), flush=True)
            return
        up = socket.create_connection((host, port), timeout=600)
        print("[h2] upstream tcp ok", flush=True)
        up_ctx = ssl.create_default_context()
        try:
            up_ctx.set_alpn_protocols(["h2"])
        except Exception:
            pass
        up_tls = up_ctx.wrap_socket(up, server_hostname=host)
        print("[h2] upstream tls ok alpn=%s" % (up_tls.selected_alpn_protocol(),), flush=True)
        up_tls.sendall(preface)
        log("S", preface)
        print("[h2] preface sent upstream", flush=True)
        # 阻塞双线程 pump：TLS 层有解密缓冲，select 看不到，必须用阻塞 recv
        for s in (tls, up_tls):
            s.setblocking(True)
            try:
                s.settimeout(None)
            except Exception:
                pass
        done = threading.Event()

        def pump(src, dst, dirn):
            try:
                while True:
                    d = src.recv(65536)
                    if not d:
                        break
                    log(dirn, d)
                    dst.sendall(d)
            except Exception:
                pass
            done.set()

        t = threading.Thread(target=pump, args=(up_tls, tls, "S"), daemon=True)
        t.start()
        pump(tls, up_tls, "C")
        done.wait(timeout=5)
    except Exception as e:
        print("[mitm] h2 tunnel %s: %s" % (host, e), flush=True)
    finally:
        try:
            rf.close()
        except Exception:
            pass
        for s in (up_tls, tls):
            try:
                s.close()
            except Exception:
                pass
        print("[mitm] h2 raw written: %s" % raw, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", default="127.0.0.1:8888")
    ap.add_argument("--out", default="captures_mitm")
    ap.add_argument("--ca-dir", default="ca")
    ap.add_argument("--only", action="append", default=[])
    args = ap.parse_args()
    ca = CertAuthority(args.ca_dir)
    ctx = Ctx(args, ca)
    host, port = args.listen.rsplit(":", 1)
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, int(port)))
    srv.listen(128)
    print("mitm capture on %s:%s  out=%s  ca=%s" % (host, port, ctx.out_dir, ca.crt_path), flush=True)
    while True:
        c, a = srv.accept()
        threading.Thread(target=handle, args=(ctx, c, a), daemon=True).start()


if __name__ == "__main__":
    main()
