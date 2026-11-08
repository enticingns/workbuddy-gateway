@echo off
chcp 65001 >nul
title WorkBuddy AI 5.9.4 - 抓包模式
rem 用 ACC_PRODUCT_CONFIG_PATH 注入 capture 版配置（endpoint 指向 127.0.0.1:8877）
rem 代理已在运行；本脚本只负责带配置启动客户端。
set "ACC_PRODUCT_CONFIG_PATH=D:\workbuddy api2\tools\wb-capture\product.capture.intl-594.json"
cd /d "D:\workbuddy ai"
start "" "D:\workbuddy ai\WorkBuddyAI.exe"
echo 已启动（抓包模式）。请发 2-3 轮对话，然后回到会话告诉我。
timeout /t 3 >nul
