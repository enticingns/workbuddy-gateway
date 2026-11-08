@echo off
rem INTL capture launcher (MITM): same ASCII-junction trick as CN, because the
rem CLI CA is loaded from <configDir>\system-ca-bundle.pem and the real profile
rem path contains non-ASCII characters (BoringSSL narrow fopen fails).
set "WORKBUDDY_CONFIG_DIR=D:\wbcfg-ai"
set "HTTPS_PROXY=http://127.0.0.1:8888"
set "HTTP_PROXY=http://127.0.0.1:8888"
set "https_proxy=http://127.0.0.1:8888"
set "http_proxy=http://127.0.0.1:8888"
set "NODE_EXTRA_CA_CERTS=D:\workbuddy api2\tools\wb-capture\ca\ca.crt.pem"
cd /d "D:\workbuddy ai"
start "" "D:\workbuddy ai\WorkBuddyAI.exe"
