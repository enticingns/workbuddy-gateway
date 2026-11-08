@echo off
rem Detached launcher for the intl zero-cert capture proxy (port 8877).
rem Kept ASCII-only on purpose: WMI-created cmd sessions mangle non-ASCII literals.
set "PY=%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
set "HERE=D:\workbuddy api2\tools\wb-capture"
"%PY%" "%HERE%\wb_capture_proxy.py" --listen 127.0.0.1:8877 --upstream https://www.workbuddy.ai --out "%HERE%\captures" >> "%HERE%\proxy.log" 2>> "%HERE%\proxy.log.err"
