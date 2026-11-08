@echo off
title WorkBuddy AI 5.9.4 - capture mode
rem ============================================================
rem Zero-cert capture: inject product config whose endpoint points
rem at the local plaintext proxy 127.0.0.1:8877. No TLS, no CA.
rem The capture proxy must already be listening on 8877.
rem ============================================================
set "ACC_PRODUCT_CONFIG_PATH=D:\workbuddy api2\tools\wb-capture\product.capture.intl-594.json"
cd /d "D:\workbuddy ai"
start "" "D:\workbuddy ai\WorkBuddyAI.exe"
echo launched capture mode via ACC_PRODUCT_CONFIG_PATH
