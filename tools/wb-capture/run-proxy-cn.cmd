@echo off
rem Detached launcher for the MITM capture proxy (port 8888).
rem Captures both realms + the CN chat base host.
set "PY=%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
set "HERE=D:\workbuddy api2\tools\wb-capture"
"%PY%" "%HERE%\wb_mitm_capture.py" --listen 127.0.0.1:8888 --out "%HERE%\captures_mitm" --ca-dir "%HERE%\ca" --only www.workbuddy.cn --only www.workbuddy.ai --only copilot.tencent.com >> "%HERE%\mitm.out.log" 2>> "%HERE%\mitm.err.log"
