# wb_launch_capture_cn.ps1 - 国内版抓包启动器（零证书），代理用 WMI 脱离进程树启动
#
# 为什么不用 Start-Process：DSH 一轮结束会连带杀掉工具进程树，
# 代理作为子进程会被一起收掉（上一轮就是这么"terminated"的）。
# 用 Win32_Process.Create 由 WmiPrvSE 拉起，进程父级不是本 shell，跨轮存活。
#
# 用法：
#   pwsh -File tools\wb-capture\wb_launch_capture_cn.ps1            # 起代理 + 重启客户端
#   pwsh -File tools\wb-capture\wb_launch_capture_cn.ps1 -ProxyOnly # 只保证代理在跑

param(
  [string]$AppDir   = "D:\workbuddy cn",
  [string]$ExeName  = "WorkBuddy.exe",
  [string]$Listen   = "127.0.0.1:8878",
  [string]$Upstream = "https://www.workbuddy.cn",
  [string]$OutDir   = "D:\workbuddy api2\tools\wb-capture\captures",
  [string]$PythonPath = "$env:USERPROFILE\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe",
  [switch]$ProxyOnly
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$port = [int]($Listen -split ":")[1]

function Test-Listening([int]$p) {
  try { $c = New-Object Net.Sockets.TcpClient; $c.Connect("127.0.0.1", $p); $c.Close(); return $true }
  catch { return $false }
}

# --- 1. 代理：已在听就复用，否则用 WMI 拉起 ---
if (Test-Listening $port) {
  Write-Host "[=] proxy already listening on $Listen"
} else {
  if (-not (Test-Path -LiteralPath $PythonPath)) { throw "python not found: $PythonPath" }
  $script = Join-Path $here "wb_capture_proxy.py"
  $log    = Join-Path $here "proxy.log"
  $errLog = Join-Path $here "proxy.log.err"
  # cmd /c 负责重定向（WMI Create 没有 shell，不能直接写 >）
  $inner = '"{0}" "{1}" --listen {2} --upstream {3} --out "{4}" >> "{5}" 2>> "{6}"' -f `
    $PythonPath, $script, $Listen, $Upstream, $OutDir, $log, $errLog
  $cmdline = 'cmd /c ' + $inner
  $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $cmdline }
  if ($r.ReturnValue -ne 0) { throw "Win32_Process.Create failed: $($r.ReturnValue)" }
  Write-Host "[+] proxy started pid=$($r.ProcessId) -> $Listen (upstream $Upstream)"
  for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 250
    if (Test-Listening $port) { break }
  }
  if (-not (Test-Listening $port)) { Write-Host "[-] proxy not listening, log:"; Get-Content $errLog -Tail 20; throw "proxy failed" }
  Write-Host "[+] proxy listening on $Listen"
}

if ($ProxyOnly) { return }

# --- 2. 关掉在跑的国内版客户端（单实例会复用旧 env） ---
$base = [IO.Path]::GetFileNameWithoutExtension($ExeName)
Get-Process -Name $base -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "kill pid=$($_.Id)"; $_ | Stop-Process -Force }
Start-Sleep -Milliseconds 1200

# --- 3. 生成注入配置：只改 endpoint / updateUrl ---
$srcCfg = Join-Path $AppDir "resources\app.asar.unpacked\cli\product.json"
if (-not (Test-Path -LiteralPath $srcCfg)) { throw "no product.json: $srcCfg" }
$patchPath = Join-Path $here "product.capture.json"
$cfg = Get-Content -LiteralPath $srcCfg -Raw -Encoding UTF8 | ConvertFrom-Json
$orig = $cfg.endpoint
$cfg.endpoint = "http://$Listen"
if ($cfg.PSObject.Properties.Name -contains "updateUrl") { $cfg.updateUrl = "http://$Listen" }
$json = $cfg | ConvertTo-Json -Depth 100 -Compress
[IO.File]::WriteAllText($patchPath, $json, (New-Object Text.UTF8Encoding($false)))
Write-Host "[i] config: $patchPath"
Write-Host "    endpoint $orig -> $($cfg.endpoint)"

# --- 4. 带 env 启动客户端 ---
$env:ACC_PRODUCT_CONFIG_PATH = $patchPath
$exe = Join-Path $AppDir $ExeName
Start-Process -FilePath $exe -WorkingDirectory $AppDir
Write-Host "[+] client launched: $exe"
Write-Host "[i] 现在在客户端里发消息；captures 会随请求增长。"
