@echo off
title WorkBuddy AI 5.9.4 - MITM capture v2
rem ============================================================
rem The client bootstrap reads http.proxy from settings.json and
rem sets HTTP_PROXY/HTTPS_PROXY in its own process.
rem On Windows the CLI/daemon child does NOT auto-load the
rem system-ca-bundle.pem (buildCliProcessEnv injects it only on
rem darwin), so we must set NODE_EXTRA_CA_CERTS explicitly for the
rem Node side to trust the local capture CA.
rem ============================================================
set "HTTPS_PROXY=http://127.0.0.1:8888"
set "HTTP_PROXY=http://127.0.0.1:8888"
set "https_proxy=http://127.0.0.1:8888"
set "http_proxy=http://127.0.0.1:8888"
set "NODE_EXTRA_CA_CERTS=D:\workbuddy api2\tools\wb-capture\ca\ca.crt.pem"
cd /d "D:\workbuddy ai"
start "" "D:\workbuddy ai\WorkBuddyAI.exe"
echo launched with NODE_EXTRA_CA_CERTS and proxy env
