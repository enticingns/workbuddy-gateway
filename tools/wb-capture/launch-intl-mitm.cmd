@echo off
chcp 65001 >nul
title WorkBuddy AI 5.9.4 - MITM 抓包
rem ============================================================
rem endpoint 注入已被云端 v3/config 覆盖（实测），改走 MITM：
rem   HTTPS_PROXY 让客户端 CONNECT 落到本地 127.0.0.1:8888
rem   CA 已装进 CurrentUser\Root，代理按需签发 leaf 证书
rem   NODE_EXTRA_CA_CERTS 给 Node 侧（daemon/CLI）双保险
rem 前置：wb_mitm_capture.py 已在 8888 运行
rem ============================================================
set "HTTPS_PROXY=http://127.0.0.1:8888"
set "HTTP_PROXY=http://127.0.0.1:8888"
set "https_proxy=http://127.0.0.1:8888"
set "http_proxy=http://127.0.0.1:8888"
set "NODE_EXTRA_CA_CERTS=D:\workbuddy api2\tools\wb-capture\ca\ca.crt.pem"
cd /d "D:\workbuddy ai"
start "" "D:\workbuddy ai\WorkBuddyAI.exe"
echo 已用 MITM 代理启动。请发 2-3 轮对话，然后回来告诉我。
timeout /t 3 >nul
