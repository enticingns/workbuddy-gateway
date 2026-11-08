#!/bin/sh
# 网关升级：把现役镜像换成指定 sha，并验证
# 用法: sh upgrade_gateway.sh <new-tag> <rollback-tag>
# 注意：冒烟容器用临时 data 目录 + 只读挂载，绝不与生产容器共享可写数据。
set -eu

NEW_TAG="${1:?usage: upgrade_gateway.sh <new-tag> <rollback-tag>}"
ROLLBACK_TAG="${2:?usage: upgrade_gateway.sh <new-tag> <rollback-tag>}"
IMAGE="ghcr.io/enticingns/workbuddy-gateway"
DIR=/opt/workbuddy-gateway
COMPOSE="$DIR/docker-compose.ghcr.yml"
SMOKE_DATA=/tmp/wb2a-smoke-data

cd "$DIR"

CUR_IMAGE=$(docker ps --format '{{.Image}}' --filter name=workbuddy2api)
echo "=== 现役: $CUR_IMAGE ==="
echo "=== 目标: $IMAGE:$NEW_TAG ==="

echo "--- pull ---"
docker pull "$IMAGE:$NEW_TAG"

echo "--- smoke test on 127.0.0.1:7864 (isolated data) ---"
rm -rf "$SMOKE_DATA"; mkdir -p "$SMOKE_DATA"
docker rm -f wb2a-smoke >/dev/null 2>&1 || true
docker run -d --name wb2a-smoke -p 127.0.0.1:7864:7863 \
  -v "$DIR/auths:/app/auths:ro" \
  -v "$SMOKE_DATA:/app/data" \
  -v "$DIR/config.json:/app/config.json:ro" \
  "$IMAGE:$NEW_TAG" >/dev/null
ok=0; i=0
while [ $i -lt 30 ]; do
  sleep 1
  h=$(curl -s -m 3 http://127.0.0.1:7864/healthz || true)
  case "$h" in *healthy*) ok=1; break;; esac
  i=$((i+1))
done
echo "smoke healthz: ${h:-<none>}"
echo -n "smoke binary version: "
docker exec wb2a-smoke sh -c 'grep -a -o "1\.[0-9]*\.[0-9]*-panel" /app/wb2api | head -1' 2>/dev/null || echo "(grep failed)"
docker rm -f wb2a-smoke >/dev/null 2>&1 || true
rm -rf "$SMOKE_DATA"
if [ "$ok" != "1" ]; then echo "!! 冒烟失败，放弃升级"; exit 1; fi

if ! docker image inspect "$IMAGE:$ROLLBACK_TAG" >/dev/null 2>&1; then
  docker tag "$CUR_IMAGE" "$IMAGE:$ROLLBACK_TAG"
  echo "--- 回滚点已打标: $IMAGE:$ROLLBACK_TAG ---"
else
  echo "--- 回滚点已存在: $IMAGE:$ROLLBACK_TAG ---"
fi

cp -n "$COMPOSE" "$COMPOSE.bak-$(date +%Y%m%d-%H%M%S)" 2>/dev/null || true
sed -i "s|image: $IMAGE:.*|image: $IMAGE:$NEW_TAG|" "$COMPOSE"
grep -n 'image:' "$COMPOSE"

echo "--- up -d --force-recreate ---"
docker compose -f "$COMPOSE" up -d --force-recreate

echo "--- verify ---"
sleep 8
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' | grep -i workbuddy
echo -n "healthz: "; curl -s -m 5 http://127.0.0.1:7863/healthz; echo
echo "=== done ==="
