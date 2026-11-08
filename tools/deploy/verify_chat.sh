#!/bin/sh
# 端到端对话验证：自动挑一个免费模型（credits 含 x0.00），避免扣费
# 用法: sh verify_chat.sh [model]
set -u
cd /opt/workbuddy-gateway
KEY=$(sed -n 's/.*"api_key"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' config.json | head -1)
if [ -z "$KEY" ]; then echo "!! 没读到 api_key"; exit 1; fi

MODEL="${1:-}"
if [ -z "$MODEL" ]; then
  MODELS=$(curl -s -m 20 http://127.0.0.1:7863/v1/models -H "Authorization: Bearer $KEY")
  # 优先 cn: 前缀的免费模型，其次任意免费模型
  MODEL=$(printf '%s' "$MODELS" | tr '{' '\n' | grep 'x0.00' | grep '"id":"cn:' | head -1 | sed -n 's/.*"id":"\([^"]*\)".*/\1/p')
  [ -z "$MODEL" ] && MODEL=$(printf '%s' "$MODELS" | tr '{' '\n' | grep 'x0.00' | head -1 | sed -n 's/.*"id":"\([^"]*\)".*/\1/p')
  echo "--- 模型总数: $(printf '%s' "$MODELS" | grep -o '"id":"' | wc -l) ---"
fi
if [ -z "$MODEL" ]; then echo "!! 没找到免费模型，跳过对话测试"; exit 0; fi

echo "--- chat model=$MODEL stream=false ---"
START=$(date +%s%N)
curl -s -m 90 -X POST http://127.0.0.1:7863/v1/chat/completions \
  -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"只回复两个字：正常\"}],\"stream\":false}" | head -c 700
echo
END=$(date +%s%N)
echo "elapsed_ms=$(( (END-START)/1000000 ))"
echo "--- container ---"
docker ps --format '{{.Names}} {{.Image}} {{.Status}}' | grep -i workbuddy
echo "--- last log lines ---"
docker logs workbuddy2api --tail 12 2>&1 | tail -8
