# wb_launch_capture.ps1 — 让官方客户端把请求发到本机抓包代理（零证书）
#
# 做三件事：
#   1. 从已安装的国际版 product.json 生成一份副本，只把 endpoint 指向本机代理
#   2. 起抓包代理（python，明文入 / TLS 出）
#   3. 带 ACC_PRODUCT_CONFIG_PATH 启动客户端
#
# 用法：
#   pwsh -File wb_launch_capture.ps1                       # 国际版（默认）
#   pwsh -File wb_launch_capture.ps1 -AppDir "D:\workbuddy cn" -Port 8878
#
param(
  [string]$AppDir  = "D:\workbuddy ai",
  [string]$ExeName = "WorkBuddyAI.exe",
  [string]$Listen  = "127.0.0.1:8877",
  [string]$Upstream = "https://www.workbuddy.ai",
  [string]$OutDir  = "D:\workbuddy api2\tools\wb-capture\captures",
  [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$port = ($Listen -split ":")[1]

# --- 0. 关掉已在运行的客户端（单实例，不关新进程会复用旧 env） ---
Get-Process -Name ([IO.Path]::GetFileNameWithoutExtension($ExeName)) -ErrorAction SilentlyContinue |
  ForEach-Object { Write-Host "killing pid=$($_.Id)"; $_ | Stop-Process -Force }
Start-Sleep -Milliseconds 800

# --- 1. 生成注入用 product config（只改 endpoint / updateUrl） ---
$srcCfg = Join-Path $AppDir "resources\app.asar.unpacked\cli\product.json"
if (-not (Test-Path -LiteralPath $srcCfg)) { throw "找不到 product.json: $srcCfg" }

$patchPath = Join-Path $here "product.capture.json"
$cfg = Get-Content -LiteralPath $srcCfg -Raw -Encoding UTF8 | ConvertFrom-Json
$origEndpoint = $cfg.endpoint
$cfg.endpoint = "http://$Listen"
if ($cfg.PSObject.Properties.Name -contains "updateUrl") { $cfg.updateUrl = "http://$Listen" }
# 必须写成 UTF-8 无 BOM：Set-Content -Encoding UTF8 在 PowerShell 5.1 下会加 BOM，
# 客户端 JSON.parse 遇到 BOM 会直接抛错。
$json = $cfg | ConvertTo-Json -Depth 100 -Compress
[System.IO.File]::WriteAllText($patchPath, $json, (New-Object System.Text.UTF8Encoding($false)))

Write-Host "product config 注入文件: $patchPath"
Write-Host "  endpoint: $origEndpoint  ->  $($cfg.endpoint)"

# --- 2. 起抓包代理 ---
$proxyLog = Join-Path $here "proxy.log"
$py = $PythonPath
if (-not $py) {
  $py = "python"
  # 注意：Windows 上 `python` 常指向 WindowsApps 下的 Store 占位 stub（version 0.0.0.0），
  # 它不会报错也不会执行，只会静默退出——必须跳过。
  $cmd = Get-Command $py -ErrorAction SilentlyContinue
  if (-not $cmd -or $cmd.Source -like "*WindowsApps*") {
    $cand = "C:\Users\$env:USERNAME\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
    if (Test-Path -LiteralPath $cand) { $py = $cand }
    else { throw "找不到可用的 python：请用 -PythonPath 指定" }
  }
}
Write-Host "python: $py"
# 注意：路径含空格，PowerShell 的 -ArgumentList 会按空格拆分，必须显式加引号
$pyArgs = @(
  "`"$(Join-Path $here 'wb_capture_proxy.py')`"",
  "--listen", $Listen,
  "--upstream", $Upstream,
  "--out", "`"$OutDir`""
)
$proxy = Start-Process -FilePath $py -ArgumentList $pyArgs -PassThru `
  -RedirectStandardOutput $proxyLog -RedirectStandardError "$proxyLog.err" -WindowStyle Hidden
Start-Sleep -Seconds 2
if ($proxy.HasExited) {
  Write-Host "代理启动失败，看日志: $proxyLog.err" -ForegroundColor Red
  Get-Content -LiteralPath "$proxyLog.err" -Tail 20
  throw "capture proxy failed"
}
Write-Host "抓包代理已启动 pid=$($proxy.Id)  ->  http://$Listen  (上游 $Upstream)"

# --- 3. 带 env 启动客户端 ---
$env:ACC_PRODUCT_CONFIG_PATH = $patchPath
Write-Host "ACC_PRODUCT_CONFIG_PATH = $patchPath"
$exe = Join-Path $AppDir $ExeName
if (-not (Test-Path -LiteralPath $exe)) { throw "找不到客户端: $exe" }
Start-Process -FilePath $exe -WorkingDirectory $AppDir
Write-Host ""
Write-Host "客户端已启动。让它发几条消息，然后在 $OutDir 里看抓到的请求。" -ForegroundColor Green
Write-Host "结束时：Stop-Process -Id $($proxy.Id)" -ForegroundColor Yellow
