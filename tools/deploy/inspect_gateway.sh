#!/bin/sh
# 网关升级前巡检（只读）
set -u
echo "=== hostname / arch ==="
hostname; uname -m
echo
echo "=== 容器 ==="
docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}' | grep -i workbuddy || echo "(无 workbuddy 容器)"
echo
echo "=== 现役镜像 ==="
docker images --format '{{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedSince}}' | grep -i workbuddy || echo "(无)"
echo
echo "=== compose 文件（image 行 + 挂载）==="
cd /opt/workbuddy-gateway 2>/dev/null || { echo "!! /opt/workbuddy-gateway 不存在"; exit 1; }
grep -nE 'image:|container_name:|restart:|^\s+- ' docker-compose.ghcr.yml 2>/dev/null | head -40
echo
echo "=== git ==="
git log --oneline -1 2>/dev/null; git status --porcelain 2>/dev/null | head -10
echo
echo "=== healthz ==="
curl -s -m 5 http://127.0.0.1:7863/healthz; echo
echo "=== status(鉴权后才有账号数) ==="
curl -s -m 5 http://127.0.0.1:7863/status | head -c 400; echo
echo
echo "=== 磁盘 ==="
df -h / | tail -1
