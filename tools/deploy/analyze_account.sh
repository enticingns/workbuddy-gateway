#!/bin/sh
# 单账号诊断：出站身份 / 11-128 命中分布 / 请求日志
# 用法: sh analyze_account.sh <uid8>
set -u
UID8="${1:?usage: analyze_account.sh <uid8>}"
DIR=/opt/workbuddy-gateway
cd "$DIR"

echo "=== 1) 账号文件（脱敏）==="
for f in auths/*.json; do
  [ -e "$f" ] || continue
  case "$f" in *"$UID8"*) ;;
    *) continue ;;
  esac
  echo "file: $f"
  sed -e 's/\("\(access_token\|refresh_token\|device_token\|id_token\)"[[:space:]]*:[[:space:]]*"\)\([^"]\{0,8\}\)[^"]*"/\1\3…(masked)"/g' "$f" \
    | tr ',' '\n' \
    | grep -Ev '"(access_token|refresh_token|device_token|id_token)"' \
    | head -40
done

echo
echo "=== 2) 11-128 / content_blocked 在网关日志里的分布（按账号）==="
docker logs workbuddy2api --since 72h 2>&1 | grep -c 'content_blocked' || true
echo "--- 各账号命中次数 ---"
docker logs workbuddy2api --since 72h 2>&1 | grep 'content_blocked' | sed -n 's/.*acct=\([^(]*\)(\([^)]*\)).*/\2 \1/p' | sort | uniq -c | sort -rn | head -15

echo
echo "=== 3) 该账号最近命中明细（模型/时间）==="
docker logs workbuddy2api --since 72h 2>&1 | grep "$UID8" | grep -E 'content_blocked|11-128' | tail -8

echo
echo "=== 4) 该账号最近请求结果（成功/失败/模型）==="
docker logs workbuddy2api --since 6h 2>&1 | grep "$UID8" | grep '^| #' | tail -12

echo
echo "=== 5) 请求归档里该账号的分布（按模型 + 状态）==="
if ls data/request-logs/*.jsonl >/dev/null 2>&1; then
  cat data/request-logs/*.jsonl 2>/dev/null \
    | grep "$UID8" \
    | sed -n 's/.*"model":"\([^"]*\)".*"status":\([0-9]*\).*/\1 \2/p' \
    | sort | uniq -c | sort -rn | head -15
  echo "--- 归档总条数（该账号）---"
  cat data/request-logs/*.jsonl 2>/dev/null | grep -c "$UID8" || true
else
  echo "(无 request-logs 归档)"
fi
