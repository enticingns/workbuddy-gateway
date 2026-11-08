#!/bin/sh
# 升级后验证：连打 N 条（默认 5）免费模型 + 统计 11-128
set -u
N="${1:-5}"
MODEL="${2:-}"
cd /opt/workbuddy-gateway
KEY=$(sed -n 's/.*"api_key"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' config.json | head -1)
[ -z "$KEY" ] && { echo "!! no api_key"; exit 1; }

if [ -z "$MODEL" ]; then
  MODELS=$(curl -s -m 20 http://127.0.0.1:7863/v1/models -H "Authorization: Bearer $KEY")
  MODEL=$(printf '%s' "$MODELS" | tr '{' '\n' | grep 'x0.00' | grep '"id":"cn:' | head -1 | sed -n 's/.*"id":"\([^"]*\)".*/\1/p')
  [ -z "$MODEL" ] && MODEL=$(printf '%s' "$MODELS" | tr '{' '\n' | grep 'x0.00' | head -1 | sed -n 's/.*"id":"\([^"]*\)".*/\1/p')
fi
echo "model=$MODEL  rounds=$N"
ok=0; fail=0
i=1
while [ $i -le "$N" ]; do
  code=$(curl -s -o /tmp/wb2a_resp.json -w '%{http_code}' -m 90 -X POST http://127.0.0.1:7863/v1/chat/completions \
    -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
    -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"第 $i 次探测，只回复：OK\"}],\"stream\":false}")
  if [ "$code" = "200" ]; then ok=$((ok+1)); else fail=$((fail+1)); echo "  round $i -> $code $(head -c 200 /tmp/wb2a_resp.json)"; fi
  i=$((i+1))
done
echo "ok=$ok fail=$fail"
echo "--- 11-128 / content_blocked 计数（当前容器全部日志）---"
echo -n "11-128: "; docker logs workbuddy2api 2>&1 | grep -c '11-128' || true
echo -n "content_blocked: "; docker logs workbuddy2api 2>&1 | grep -c 'content_blocked' || true
echo "--- 最近请求行 ---"
docker logs workbuddy2api 2>&1 | grep '^| #' | tail -5
