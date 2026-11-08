@echo off
setlocal
chcp 65001 >nul
title WorkBuddy AI - 抓包模式

rem ============================================================
rem 双击本文件（或 explorer.exe 调用）即可：
rem   1. 起抓包代理（明文入 / TLS 出）
rem   2. 带 ACC_PRODUCT_CONFIG_PATH 注入启动国际版客户端
rem 抓到的请求落在 captures\<时间戳>\ 下
rem ============================================================

set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"
set "APP=D:\workbuddy ai"
set "CFG=%HERE%\product.capture.json"
set "OUT=%HERE%\captures"
set "PORT=8877"
set "PY=%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"

if not exist "%CFG%" (
  echo [x] 缺少 %CFG% -- 先跑 wb_launch_capture.ps1 生成
  pause & exit /b 1
)
if not exist "%OUT%" mkdir "%OUT%"

echo [*] 关掉已在运行的客户端...
taskkill /IM WorkBuddyAI.exe /F >nul 2>&1
timeout /t 2 >nul

echo [*] 代理状态检查 %PORT% ...
netstat -ano | findstr /r /c:"127.0.0.1:%PORT% .*LISTENING" >nul
if errorlevel 1 (
  echo [*] 启动抓包代理...
  start "wb-capture-proxy" /min "%PY%" "%HERE%\wb_capture_proxy.py" --listen 127.0.0.1:%PORT% --upstream https://www.workbuddy.ai --out "%OUT%"
  timeout /t 4 >nul
) else (
  echo [*] 代理已在监听
)

echo [*] 启动 WorkBuddy AI  (endpoint -> http://127.0.0.1:%PORT%)
set "ACC_PRODUCT_CONFIG_PATH=%CFG%"
start "" "%APP%\WorkBuddyAI.exe"

echo.
echo [i] 窗口起来后，随便发几条消息（新会话/多轮/带工具各一次）
echo [i] 抓包目录: %OUT%
echo [i] 关掉本窗口不影响客户端；关掉客户端即可恢复正常
timeout /t 6 >nul
exit /b 0
