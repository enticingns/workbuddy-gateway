@echo off
rem CN capture launcher, per docs\CN真机出站身份-20261028.md 6.1:
rem WORKBUDDY_CONFIG_DIR points at an ASCII junction (D:\wbcfg -> ~\.workbuddy),
rem otherwise BoringSSL cannot open the non-ASCII system-ca-bundle.pem path and
rem the CLI chat handshake dies (UNEXPECTED_EOF / UNABLE_TO_VERIFY_LEAF_SIGNATURE).
set "WORKBUDDY_CONFIG_DIR=D:\wbcfg"
set "HTTPS_PROXY=http://127.0.0.1:8888"
set "HTTP_PROXY=http://127.0.0.1:8888"
set "https_proxy=http://127.0.0.1:8888"
set "http_proxy=http://127.0.0.1:8888"
set "NODE_EXTRA_CA_CERTS=D:\workbuddy api2\tools\wb-capture\ca\ca.crt.pem"
cd /d "D:\workbuddy cn"
start "" "D:\workbuddy cn\WorkBuddy.exe"
