#!/bin/bash
# API key 不写死在脚本里：优先读环境变量，其次读当前目录 config.json 的 api_key。
#   export WB2A_TOKEN=wb2a-xxxx
WB2A_TOKEN="${WB2A_TOKEN:-$(python3 -c "import json;print(json.load(open('config.json'))['api_key'])" 2>/dev/null)}"
if [ -z "$WB2A_TOKEN" ]; then
  echo "缺少 API key：export WB2A_TOKEN=... 或在当前目录提供 config.json" >&2
  exit 1
fi

echo "=== MODELS ==="
curl -s http://127.0.0.1:7863/v1/models -H "Authorization: Bearer $WB2A_TOKEN" | python3 -c "
import sys,json
d=json.load(sys.stdin)
for m in d.get('data',[]):
    print(m.get('id','?'))
" 2>/dev/null

echo ""
echo "=== TEST GLOBAL CHAT ==="
curl -s -X POST http://127.0.0.1:7863/v1/chat/completions \
  -H "Authorization: Bearer $WB2A_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"model":"global:deepseek-v4-pro","messages":[{"role":"user","content":"hi"}],"stream":false}' 2>&1 | head -c 800

echo ""
echo "=== TEST GLOBAL CHAT 2 ==="
curl -s -X POST http://127.0.0.1:7863/v1/chat/completions \
  -H "Authorization: Bearer $WB2A_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"model":"global:deepseek-chat","messages":[{"role":"user","content":"hi"}],"stream":false}' 2>&1 | head -c 800

echo ""
echo "=== STATE (container) ==="
docker exec workbuddy2api cat /app/data/state.json 2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin)
for k,v in d.items():
    if isinstance(v,dict):
        print(k,':',v.get('realm','?'),v.get('account_id','?')[:20])
" 2>/dev/null

echo ""
echo "=== CONTAINER LOGS - ERRORS ==="
docker logs workbuddy2api --tail 200 2>&1 | grep -iE "global|error|fail|denied|401|403|503|upstream|register|token" | tail -20
