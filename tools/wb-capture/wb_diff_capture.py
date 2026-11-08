#!/usr/bin/env python3
"""wb_diff_capture.py — 把抓到的官方请求与网关当前出站做逐项对比。

用法：
    python wb_diff_capture.py captures/20261028-100000/0003_POST_v2_chat_completions.json
    python wb_diff_capture.py captures/20261028-100000/   # 自动挑 chat 请求

输出四块：
  1. 抓到的请求本体（头 / body 概要）
  2. 与「官方应有头」对比：缺失 / 未知
  3. 与「网关当前出站头」对比：官方发了我们没发的 / 我们发了官方没发的 / 取值不同
  4. SSE 帧字段审计：上游返回、但网关 normalizeFrame 白名单会丢掉的字段
"""
import json
import os
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 官方客户端在 /v2/chat/completions 上实测发的头。
# 数据来源：tools/wb-capture/captures/20261028-094322（intl 5.8.4 真机抓包）里
# 5 个 chat 请求，由 wb_extract_baseline.py 统计得出——下面 40 个头 5/5 全部出现。
# 实测结论（与 CHANGELOG 2026-10-28 一致）：
#   origin / referer / accept-language / x-machine-id / x-session-id 从不出现，
#   网关也不该发；chat 路径固定带 x-stainless-*（7 个）+ acp-connection-id + traceparent/b3 族。
CLIENT_EXPECTED = {
    "accept",
    "accept-encoding",
    "acp-connection-id",
    "authorization",
    "b3",
    "connection",
    "content-encoding",
    "content-length",
    "content-type",
    "host",
    "traceparent",
    "user-agent",
    "x-agent-intent",
    "x-agent-purpose",
    "x-agent-type",
    "x-b3-sampled",
    "x-b3-spanid",
    "x-b3-traceid",
    "x-codebuddy-request",
    "x-conversation-id",
    "x-conversation-message-id",
    "x-conversation-request-id",
    "x-device-token",
    "x-domain",
    "x-ide-name",
    "x-ide-type",
    "x-ide-version",
    "x-private-data",
    "x-product",
    "x-request-id",
    "x-requested-with",
    "x-stainless-arch",
    "x-stainless-lang",
    "x-stainless-os",
    "x-stainless-package-version",
    "x-stainless-retry-count",
    "x-stainless-runtime",
    "x-stainless-runtime-version",
    "x-trace-id",
    "x-user-id",
}

# 只在部分请求出现的头（实测 2/5）：属可选，缺失不算错
CLIENT_EXPECTED_OPTIONAL = {
    "x-b3-parentspanid",
    "x-root-request-id",
}

# HTTP 传输层头：由 Go net/http 自动生成/处理，网关不手工 Set，
# 对比时单列，避免误报成"要补"。
TRANSPORT_HEADERS = {
    "host",
    "connection",
    "content-length",
    "content-encoding",
    "accept-encoding",
    "transfer-encoding",
    "keep-alive",
}

# 网关当前出站头：internal/upstream/headers.go 里 chat 路径 Header.Set 的全部。
# 含条件分支（x-no-authorization / x-no-user-id / x-no-enterprise-id 仅在凭证缺失时发），
# 所以这里是"可能发送"的并集。
GATEWAY_SENDS = {
    "content-type", "accept", "user-agent",
    "x-codebuddy-request", "x-product", "x-domain", "x-requested-with",
    "authorization", "x-no-authorization",
    "x-user-id", "x-no-user-id",
    "x-enterprise-id", "x-no-enterprise-id",
    "x-device-token",
    "x-stainless-arch", "x-stainless-lang", "x-stainless-os",
    "x-stainless-package-version", "x-stainless-retry-count",
    "x-stainless-runtime", "x-stainless-runtime-version",
    "acp-connection-id",
    "x-conversation-id", "x-conversation-request-id", "x-conversation-message-id",
    "x-request-id", "x-root-request-id",
    "x-trace-id", "x-b3-traceid", "x-b3-spanid", "x-b3-sampled",
    "traceparent", "b3",
    "baggage", "x-agent-runtime",
    "x-agent-purpose", "x-agent-intent", "x-agent-type",
    "x-ide-name", "x-ide-type", "x-ide-version",
    "x-private-data",
}

# sse.go:normalizeFrame 保留的字段（流式路径会重建帧，其余一律丢）
NORMALIZE_KEEP_TOP = {"id", "object", "created", "model", "system_fingerprint",
                      "service_tier", "choices", "usage"}
NORMALIZE_KEEP_DELTA = {"role", "content", "reasoning_content", "refusal",
                        "tool_calls", "function_call"}
NORMALIZE_KEEP_CHOICE = {"index", "delta", "finish_reason"}


def pick_capture(path):
    if os.path.isfile(path):
        return path
    cands = []
    for dirpath, _, files in os.walk(path):
        for f in files:
            if f.endswith(".json") and "chat" in f.lower():
                cands.append(os.path.join(dirpath, f))
    if not cands:
        for dirpath, _, files in os.walk(path):
            for f in files:
                if f.endswith(".json"):
                    cands.append(os.path.join(dirpath, f))
    if not cands:
        sys.exit("没找到抓包文件: %s" % path)
    cands.sort()
    return cands[0]


def main():
    cap = pick_capture(sys.argv[1] if len(sys.argv) > 1 else "captures")
    d = json.load(open(cap, encoding="utf-8"))
    print("抓包文件:", cap)
    print("=" * 78)

    headers = d.get("request_headers") or []
    hmap = {k.lower(): v for k, v in headers}

    print("\n### 1. 请求本体")
    print("  %s %s%s" % (d.get("method"), d.get("path"),
                         ("?" + d["query"]) if d.get("query") else ""))
    print("  upstream   :", d.get("upstream"))
    print("  status     :", d.get("response_status"), d.get("response_content_type"))
    print("  ttfb/total : %sms / %sms" % (d.get("ttfb_ms"), d.get("elapsed_ms")))
    print("\n  --- 请求头（按发送顺序）---")
    for k, v in headers:
        print("    %-32s %s" % (k, v))

    body = d.get("request_body") or ""
    if d.get("request_body_b64"):
        import base64, gzip
        try:
            body = gzip.decompress(base64.b64decode(d["request_body_b64"])).decode("utf-8", "replace")
        except Exception:
            pass
    if body:
        try:
            b = json.loads(body)
            print("\n  --- body 顶层键 ---")
            print("   ", ", ".join(b.keys()))
            print("\n  --- chat 关键字段 ---")
            for k in ("model", "stream", "max_tokens", "max_completion_tokens",
                      "temperature", "top_p", "reasoning_effort", "conversationId",
                      "metadata", "tools", "tool_choice", "system_fingerprint"):
                if k in b:
                    v = b[k]
                    if isinstance(v, (list, dict)):
                        v = json.dumps(v, ensure_ascii=False)[:160]
                    print("    %-22s %s" % (k, v))
            msgs = b.get("messages") or []
            if isinstance(msgs, list):
                print("\n  --- messages（%d 条）---" % len(msgs))
                for i, m in enumerate(msgs[:6]):
                    role = m.get("role")
                    content = m.get("content")
                    if isinstance(content, list):
                        txt = json.dumps(content, ensure_ascii=False)
                    else:
                        txt = str(content)
                    print("    [%d] %-10s %s" % (i, role, txt[:150]))
        except Exception as e:
            print("  body 不是 JSON: %s" % e)
            print("  ", body[:400])

    print("\n### 2. 与「官方应有头」对比")
    missing = sorted(CLIENT_EXPECTED - set(hmap))
    optional_seen = sorted(CLIENT_EXPECTED_OPTIONAL & set(hmap))
    unknown = sorted(set(hmap) - CLIENT_EXPECTED - CLIENT_EXPECTED_OPTIONAL - GATEWAY_SENDS)
    print("  实测应有、本次没发（可能该端点不需要）:", ", ".join(missing) or "无")
    print("  可选头（实测 2/5 出现，发了也正常）:", ", ".join(optional_seen) or "无")
    print("  未知头（官方/网关都不在清单里，需人工判）:", ", ".join(unknown) or "无")

    print("\n### 3. 官方 vs 网关 出站头差异")
    both = sorted(set(hmap) & GATEWAY_SENDS)
    only_client = sorted(set(hmap) - GATEWAY_SENDS)
    only_gw = sorted(GATEWAY_SENDS - set(hmap))
    # 传输层头由 HTTP 栈（Go net/http）自动处理，网关不手工 Set，不算"要补"
    transport = [k for k in only_client if k in TRANSPORT_HEADERS]
    app_level = [k for k in only_client if k not in TRANSPORT_HEADERS]
    print("\n  [A] 官方发了、网关没发（要补）:")
    for k in app_level:
        print("      %-30s %s" % (k, hmap[k][:70]))
    if not app_level:
        print("      （无）")
    print("\n  [A2] 传输层头（HTTP 栈自动处理，不用手工补）:")
    print("      " + (", ".join(transport) or "（无）"))
    print("\n  [B] 网关发了、官方这个端点没发（要评估是否多余）:")
    print("      " + (", ".join(only_gw) or "（无）"))
    print("\n  [C] 两边都有（重点看取值）:")
    for k in both:
        print("      %-30s 官方= %s" % (k, hmap[k][:80]))

    frames = d.get("sse_frames") or []
    if frames:
        print("\n### 4. SSE 帧字段审计（上游真正返回了什么 vs 网关会丢什么）")
        top_keys, delta_keys, choice_keys = set(), set(), set()
        parsed = 0
        for f in frames:
            f = f.strip()
            if not f.startswith("data:"):
                continue
            payload = f[5:].strip()
            if payload == "[DONE]" or not payload:
                continue
            try:
                o = json.loads(payload)
            except Exception:
                continue
            parsed += 1
            top_keys |= set(o.keys())
            for ch in (o.get("choices") or []):
                if isinstance(ch, dict):
                    choice_keys |= set(ch.keys())
                    dl = ch.get("delta")
                    if isinstance(dl, dict):
                        delta_keys |= set(dl.keys())
        print("  解析到 %d 帧 / 共 %d 帧" % (parsed, len(frames)))
        print("  顶层字段:", ", ".join(sorted(top_keys)))
        print("  choice 字段:", ", ".join(sorted(choice_keys)))
        print("  delta 字段:", ", ".join(sorted(delta_keys)))
        dropped_top = sorted(top_keys - NORMALIZE_KEEP_TOP)
        dropped_delta = sorted(delta_keys - NORMALIZE_KEEP_DELTA)
        dropped_choice = sorted(choice_keys - NORMALIZE_KEEP_CHOICE)
        print("\n  ⚠ normalizeFrame 会丢掉的：")
        print("    顶层  :", ", ".join(dropped_top) or "无")
        print("    choice:", ", ".join(dropped_choice) or "无")
        print("    delta :", ", ".join(dropped_delta) or "无")
    else:
        print("\n### 4. SSE 帧审计：该请求不是流式响应，跳过")


if __name__ == "__main__":
    main()
