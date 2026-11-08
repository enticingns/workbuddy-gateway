#!/bin/sh
# 账号域分布 + 11-128 全量命中 + 完整 400 body
# 用法: sh analyze_domain.sh [uid8]   # uid8 可选，给了才捞该账号的归档样本
set -u
UID8="${1:-}"
DIR=/opt/workbuddy-gateway
cd "$DIR"

echo "=== 1) 各账号的 domain / realm（CN 机）==="
for f in auths/*.json; do
  [ -e "$f" ] || continue
  uid=$(sed -n 's/.*"uid"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$f" | head -1)
  dom=$(sed -n 's/.*"domain"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$f" | head -1)
  realm=$(sed -n 's/.*"realm"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$f" | head -1)
  nick=$(sed -n 's/.*"nickname"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$f" | head -1)
  printf '%-10s realm=%-7s domain=%-22s %s\n' "$(printf '%s' "$uid" | cut -c1-8)" "$realm" "$dom" "$nick"
done

echo
echo "=== 2) 网关配置里的 base（脱敏）==="
sed -e 's/\("api_key"[[:space:]]*:[[:space:]]*"\)[^"]*"/\1***"/' config.json \
  | tr ',' '\n' | grep -Ei 'chat_base|billing_base|base|client_version|cli_version|user_agent|client_name' | head -20

echo
echo "=== 3) 11-128 全量命中（所有时间，按账号）==="
docker logs workbuddy2api --since 720h 2>&1 | grep -c '11-128' || true
docker logs workbuddy2api --since 720h 2>&1 | grep '11-128' | sed -n 's/.*acct=\([^(]*\)(\([^)]*\)).*/\2 \1/p' | sort | uniq -c | sort -rn

echo
echo "=== 4) 最近一次 11-128 的完整 body ==="
docker logs workbuddy2api --since 720h 2>&1 | grep '11-128' | tail -1 | cut -c1-1500

echo
echo "=== 5) 指定账号的归档样本（uid8 参数）==="
if [ -z "$UID8" ]; then
  echo "(未传 uid8，跳过)"
elif ls data/request-logs/*.jsonl >/dev/null 2>&1; then
  grep -h "$UID8" data/request-logs/*.jsonl 2>/dev/null | tail -1 | cut -c1-900
else
  echo "(无归档)"
fi
