#!/bin/sh
# 看 prompt / degrade 相关配置（脱敏）
set -u
cd /opt/workbuddy-gateway
echo "=== prompt 段 ==="
awk '/"prompt"[[:space:]]*:/,/}/' config.json | head -20
echo
echo "=== 是否有 prompt_file ==="
grep -n 'prompt' config.json | sed -e 's/\(\"api_key\"[[:space:]]*:[[:space:]]*\"\)[^\"]*\"/\1***\"/' | head -10
