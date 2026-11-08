#!/bin/sh
# 升级后终态确认
echo "--- container ---"
docker ps --format '{{.Names}}  {{.Image}}  {{.Status}}' | grep -i workbuddy
echo "--- images (workbuddy) ---"
docker images --format '{{.Repository}}:{{.Tag}}  {{.Size}}  {{.CreatedSince}}' | grep -i workbuddy
echo "--- healthz ---"
curl -s -m 5 http://127.0.0.1:7863/healthz; echo
echo "--- compose pin ---"
grep -n 'image:' /opt/workbuddy-gateway/docker-compose.ghcr.yml
echo "--- binary version ---"
docker exec workbuddy2api sh -c 'grep -a -o "1\.[0-9]*\.[0-9]*-panel" /app/wb2api | head -1' 2>/dev/null || echo "(n/a)"
