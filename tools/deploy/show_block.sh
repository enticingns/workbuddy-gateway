#!/bin/sh
# 拉取 content_blocked 命中行的完整内容（含上下文）
set -u
echo "=== 日志总行数 ==="
docker logs workbuddy2api 2>&1 | wc -l
echo "=== content_blocked 命中次数 ==="
docker logs workbuddy2api 2>&1 | grep -c 'content_blocked' || true
echo
echo "=== 命中行完整内容（不截断）==="
docker logs workbuddy2api 2>&1 | grep 'content_blocked' | tail -2
echo
echo "=== 命中前后 6 行上下文 ==="
docker logs workbuddy2api 2>&1 | grep -n -B2 -A6 'content_blocked' | tail -40
