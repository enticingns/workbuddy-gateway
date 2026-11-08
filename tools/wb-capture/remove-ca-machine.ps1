# remove-ca-machine.ps1 — 删除抓包用的 LocalMachine\Root 证书（需管理员）
$ErrorActionPreference = 'Stop'
$log = 'D:\workbuddy api2\tools\wb-capture\ca\remove-machine.log'
function Log($m) { $l = "$(Get-Date -Format 'HH:mm:ss') $m"; Add-Content -LiteralPath $log -Value $l -Encoding UTF8; Write-Host $l }

$store = New-Object System.Security.Cryptography.X509Certificates.X509Store 'Root','LocalMachine'
$store.Open('ReadWrite')
$hits = @($store.Certificates | Where-Object { $_.Subject -like '*WB Capture*' })
foreach ($c in $hits) {
  $store.Remove($c)
  Log "removed: $($c.Subject) $($c.Thumbprint)"
}
$store.Close()
Log "remaining: $((($store.Certificates | Where-Object { $_.Subject -like '*WB Capture*' }) | Measure-Object).Count)"
