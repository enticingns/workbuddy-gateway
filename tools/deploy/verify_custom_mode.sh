#!/bin/sh
# 方案 A 验证：custom 模式下连打 stream + sync 请求，统计 11-128
set -u
N="${1:-6}"
cd /opt/workbuddy-gateway
KEY=$(sed -n 's/.*"api_key"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' config.json | head -1)
[ -z "$KEY" ] && { echo "!! no api_key"; exit 1; }
MODELS=$(curl -s -m 20 http://127.0.0.1:7863/v1/models -H "Authorization: Bearer $KEY")
MODEL=$(printf '%s' "$MODELS" | tr '{' '\n' | grep 'x0.00' | grep '"id":"cn:' | head -1 | sed -n 's/.*"id":"\([^"]*\)".*/\1/p')
[ -z "$MODEL" ] && MODEL=$(printf '%s' "$MODELS" | tr '{' '\n' | grep 'x0.00' | head -1 | sed -n 's/.*"id":"\([^"]*\)".*/\1/p')
echo "model=$MODEL rounds=$N (stream)"
i=1; ok=0; fail=0
while [ $i -le "$N" ]; do
  code=$(curl -s -o /tmp/wb2a_s.txt -w '%{http_code}' -N -m 90 -X POST http://127.0.0.1:7863/v1/chat/completions \
    -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
    -d "{\"model\":\"$MODEL\",\"stream\":true,\"messages\":[{\"role\":\"system\",\"content\":\"你是工程助手。\"},{\"role\":\"user\",\"content\":\"第 $i 次，只回复：OK\"}]}")
  if [ "$code" = "200" ]; then ok=$((ok+1)); else fail=$((fail+1)); echo "  round $i -> $code $(head -c 160 /tmp/wb2a_s.txt)"; fi
  i=$((i+1))
done
echo "stream ok=$ok fail=$fail"
echo -n "11-128 计数（当前容器）: "; docker logs workbuddy2api 2>&1 | grep -c '11-128' || true
echo -n "content_blocked 计数: "; docker logs workbuddy2api 2>&1 | grep -c 'content_blocked' || true
echo "--- 最近请求行 ---"
docker logs workbuddy2api 2>&1 | grep '^| #' | tail -4
