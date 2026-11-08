# make_ca_bundle.ps1 - 预生成 <configDir>\system-ca-bundle.pem（系统根 + 抓包 CA）
#
# 为什么要预生成：客户端只有在 bundle **已存在** 时才会把它写进 CLI/daemon 的
# NODE_EXTRA_CA_CERTS（app.asar: system_ca_bundle.n(configDir) 为真才注入）；
# 缺失时它只是异步补生成，赶不上本次 spawn，CLI 就退回 Node 自带 CA → 握手失败。
param(
  [string[]]$ConfigDir = @('D:\wbcfg', 'D:\wbcfg-ai'),
  [string]$CaptureCa = 'D:\workbuddy api2\tools\wb-capture\ca\ca.crt.pem'
)

$ErrorActionPreference = 'Stop'
$pems = New-Object System.Collections.Generic.List[string]

foreach ($store in @('Cert:\LocalMachine\Root', 'Cert:\CurrentUser\Root')) {
  foreach ($c in Get-ChildItem $store -ErrorAction SilentlyContinue) {
    $b64 = [Convert]::ToBase64String($c.RawData, 'InsertLineBreaks')
    $pems.Add("-----BEGIN CERTIFICATE-----`n$b64`n-----END CERTIFICATE-----")
  }
}
if (Test-Path $CaptureCa) {
  $pems.Add((Get-Content $CaptureCa -Raw).Trim())
}

$out = ($pems -join "`n") + "`n"
foreach ($d in $ConfigDir) {
  if (-not (Test-Path $d)) { Write-Host "skip (missing): $d"; continue }
  $f = Join-Path $d 'system-ca-bundle.pem'
  [IO.File]::WriteAllText($f, $out, (New-Object Text.UTF8Encoding($false)))
  $txt = Get-Content $f -Raw
  Write-Host ("wrote {0}  size={1} certs={2} hasWB={3}" -f $f, (Get-Item $f).Length,
    ([regex]::Matches($txt, 'BEGIN CERTIFICATE')).Count, ($txt -match 'WB Capture'))
}
