#!/usr/bin/env python3
"""wb_identity_verify.py — 在监控机上用真实账号复现「真机抓到的头族」，做消融验证。

目的：确认真机抓包的结论（哪些头是官方真实发送的、我们网关当前身份是否还能过）
在同一台机器、同一账号下可复现。

用法：
    python3 wb_identity_verify.py --account-file accounts/global/haod1461.json \
        --profile profile.real.json [--base https://www.workbuddy.ai] [--rounds 1]

场景（每个场景用同一账号真实 token 发一次真实请求）：
    real            全套真机头（UA / X-IDE-* / X-Product 均为官方真值）
    no_stainless    去掉 x-stainless-*（6 个）
    no_acp          去掉 acp-connection-id
    no_trace        去掉 traceparent / b3 / X-B3-* / X-Trace-ID
    no_misc         去掉 X-Private-Data + X-Agent-Intent + X-Agent-Type
    gateway_now     替换成网关 2026-10-28 的旧身份（WorkBuddy AI/5.9.2 … CLI/2.176.0）
    gateway_plus    同上 + 网关当时额外发的 9 个头
    real_plus       官方真值 + 网关额外发的 9 个头（验证多余头是否有害）

版本口径（2026-11-02 基线，后续官方发版请同步这里）：
    CN     桌面 5.9.3 / 内嵌 CLI 2.165.0，UA `WorkBuddy/5.9.3 WorkBuddy/5.9.3 CLI/2.165.0`
    global 桌面 5.9.4 / 内嵌 CLI 2.165.0，UA `WorkBuddy/5.9.4 workbuddy-ai/5.9.4 CLI/2.165.0`
现网网关已按 realm 分档（internal/upstream/headers.go），本脚本的 gateway_now 仅作
「旧身份」对照组保留，不代表当前网关出站值。
"""
import argparse
import json
import os
import random
import ssl
import sys
import time
import uuid
from http.client import HTTPSConnection

# 官方真机（global 5.9.4，2026-11-02 抓包基线；5.8.4 时代为 CLI 2.161.0）
OFFICIAL_UA = "WorkBuddy/5.9.4 workbuddy-ai/5.9.4 CLI/2.165.0"
# 网关 2026-10-28 旧身份（对照组，非当前值；当前网关按 realm 分档见 headers.go）
GATEWAY_UA = "WorkBuddy AI/5.9.2 WorkBuddy AI/5.9.2 CLI/2.176.0"
# 网关当时额外发送、但官方 chat 不发的头
GATEWAY_EXTRA = {
    "X-Machine-ID": "0123456789abcdef0123456789abcdef0123",
    "X-Session-ID": "abcdef0123456789abcdef0123456789abcdef01",
    "X-Forwarded-For": "203.0.113.7",
    "X-Real-IP": "203.0.113.7",
    "X-Client-IP": "203.0.113.7",
    "Origin": "https://www.workbuddy.ai",
    "Referer": "https://www.workbuddy.ai/",
    "Accept-Language": "en-US",
    "X-Auth-Refresh-Source": "plugin",
}


def uuid7() -> str:
    """粗略 UUIDv7：48 位毫秒时间戳 + 随机。"""
    ms = int(time.time() * 1000)
    rnd = random.getrandbits(74)
    b = bytearray(16)
    b[0:6] = ms.to_bytes(6, "big")
    rb = rnd.to_bytes(10, "big")
    b[6] = 0x70 | (rb[0] & 0x0F)
    b[7] = rb[1]
    b[8] = 0x80 | (rb[2] & 0x3F)
    b[9:16] = rb[3:10]
    h = b.hex()
    return "%s-%s-%s-%s-%s" % (h[0:8], h[8:12], h[12:16], h[16:20], h[20:32])


def hexid(nbytes=16) -> str:
    return os.urandom(nbytes).hex()


def load_account(path):
    d = json.load(open(path, encoding="utf-8"))
    a = d.get("auth") or {}
    acc = d.get("account") or {}
    return {
        "token": a.get("accessToken") or "",
        "device": a.get("deviceToken") or a.get("device_token") or "",
        "uid": acc.get("uid") or "",
        "nick": acc.get("nickname") or acc.get("email") or "",
        "domain": a.get("domain") or "www.workbuddy.ai",
    }


def build_ids():
    conv = uuid7()
    conv_req = hexid()
    msg = hexid()
    trace = hexid()          # 32 hex
    span = hexid(8)          # 16 hex
    parent = hexid(8)
    return {
        "{{CONVERSATION_ID}}": conv,
        "{{CONVERSATION_REQUEST_ID}}": conv_req,
        "{{MESSAGE_ID}}": msg,
        "{{ACP_CONNECTION_ID}}": uuid7(),
        "{{TRACE_ID}}": trace,
        "{{SPAN_ID}}": span,
        "{{PARENT_SPAN_ID}}": parent,
        "{{TRACEPARENT}}": "00-%s-%s-01" % (trace, span),
        "{{B3}}": "%s-%s-1-%s" % (trace, span, parent),
    }


def render(headers, subs, acc, scenario):
    out = []
    for k, v in headers:
        if v == "{{AUTHORIZATION}}":
            v = "Bearer " + acc["token"]
        elif v == "{{DEVICE_TOKEN}}":
            if not acc["device"]:
                continue            # 没有真实 device token 就不发
            v = acc["device"]
        else:
            for ph, val in subs.items():
                if v == ph:
                    v = val
                    break
        # 场景改写
        if scenario in ("gateway_now", "gateway_plus"):
            if k.lower() == "user-agent":
                v = GATEWAY_UA
            elif k.lower() in ("x-ide-name", "x-ide-type", "x-product"):
                v = "WorkBuddy AI"
            elif k.lower() == "x-ide-version":
                v = "5.9.2"
        out.append((k, v))
    if scenario in ("gateway_plus", "real_plus"):
        have = {k.lower() for k, _ in out}
        for k, v in GATEWAY_EXTRA.items():
            if k.lower() not in have:
                out.append((k, v))
    return out


def drop(headers, prefixes):
    keep = []
    for k, v in headers:
        kl = k.lower()
        if any(kl == p or kl.startswith(p) for p in prefixes):
            continue
        keep.append((k, v))
    return keep


BODY = {
    "model": "default-model",
    "stream": True,
    "messages": [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "reply with OK"},
    ],
}


def send(host, path, headers, body_bytes, timeout=60):
    ctx = ssl.create_default_context()
    conn = HTTPSConnection(host, 443, timeout=timeout, context=ctx)
    hdrs = {k: v for k, v in headers}
    hdrs["Content-Type"] = hdrs.get("Content-Type", "application/json")
    try:
        conn.request("POST", path, body=body_bytes, headers=hdrs)
        resp = conn.getresponse()
        status = resp.status
        ctype = resp.getheader("Content-Type") or ""
        raw = resp.read(3000)
        text = raw.decode("utf-8", "replace")
        conn.close()
        return status, ctype, text
    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        return -1, "", "EXC: %s" % e


def summarize(status, ctype, text):
    code = ""
    msg = ""
    if "event-stream" in ctype:
        # SSE：取第一个 data 帧
        for line in text.splitlines():
            if line.startswith("data:"):
                p = line[5:].strip()
                if p and p != "[DONE]":
                    try:
                        o = json.loads(p)
                        if isinstance(o.get("error"), dict):
                            code = str(o["error"].get("code", ""))
                            msg = str(o["error"].get("message", ""))[:100]
                        else:
                            msg = "stream ok (id=%s)" % str(o.get("id"))[:16]
                    except Exception:
                        msg = p[:100]
                break
        return code, msg
    try:
        o = json.loads(text)
        if isinstance(o, dict):
            code = str(o.get("code", ""))
            msg = str(o.get("msg") or o.get("message") or "")[:110]
    except Exception:
        msg = text[:110].replace("\n", " ")
    return code, msg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account-file", required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--base", default="https://www.workbuddy.ai")
    ap.add_argument("--path", default="/v2/chat/completions")
    ap.add_argument("--model", default="default-model")
    args = ap.parse_args()

    acc = load_account(args.account_file)
    prof = json.load(open(args.profile, encoding="utf-8"))
    base_headers = prof["headers"]
    host = args.base.split("//", 1)[1].split("/")[0]
    body = dict(BODY)
    body["model"] = args.model
    body_bytes = json.dumps(body, ensure_ascii=False).encode()

    print("账号: %s（uid=%s…）" % (acc["nick"], acc["uid"][:8]))
    print("profile: %s  头数=%d" % (os.path.basename(args.profile), len(base_headers)))
    print("device token: %s" % ("有" if acc["device"] else "无（该头省略）"))
    print("上游: %s%s" % (args.base, args.path))
    print()

    scenarios = [
        ("real", base_headers, "官方真值全套"),
        ("no_stainless", drop(base_headers, ["x-stainless-"]), "去掉 x-stainless-*"),
        ("no_acp", drop(base_headers, ["acp-connection-id"]), "去掉 acp-connection-id"),
        ("no_trace", drop(base_headers, ["traceparent", "b3", "x-b3-", "x-trace-id"]), "去掉链路头"),
        ("no_misc", drop(base_headers, ["x-private-data", "x-agent-intent", "x-agent-type"]), "去掉 X-Private-Data/Intent/Type"),
        ("gateway_now", base_headers, "网关当前身份（WorkBuddy AI/5.9.2）"),
        ("gateway_plus", base_headers, "网关当前身份 + 网关额外 9 头"),
        ("real_plus", base_headers, "官方真值 + 网关额外 9 头"),
    ]

    rows = []
    for name, hdrs, desc in scenarios:
        subs = build_ids()
        rendered = render(hdrs, subs, acc, name)
        status, ctype, text = send(host, args.path, rendered, body_bytes)
        code, msg = summarize(status, ctype, text)
        rows.append((name, status, code, msg, len(rendered)))
        print("%-14s HTTP=%-4s code=%-7s hdrs=%-3d %s" % (name, status, code, len(rendered), msg[:90]))
        time.sleep(1.2)

    print()
    ok = [r for r in rows if r[1] == 200]
    print("通过(200) %d / %d" % (len(ok), len(rows)))
    print("失败清单:")
    for r in rows:
        if r[1] != 200:
            print("  %-14s HTTP=%s code=%s %s" % (r[0], r[1], r[2], r[3][:80]))

    json.dump([{"scenario": r[0], "status": r[1], "code": r[2], "msg": r[3], "hdrs": r[4]}
               for r in rows], open("identity-verify-result.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("\n结果已写入 identity-verify-result.json")


if __name__ == "__main__":
    main()
