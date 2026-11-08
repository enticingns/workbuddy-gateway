@echo off
set "HTTPS_PROXY=http://127.0.0.1:8888"
set "HTTP_PROXY=http://127.0.0.1:8888"
cd /d "D:\workbuddy cn"
start "" "D:\workbuddy cn\WorkBuddy.exe" --user-data-dir="D:\wbdata"
