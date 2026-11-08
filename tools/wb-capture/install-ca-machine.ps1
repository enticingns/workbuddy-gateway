# install-ca-machine.ps1 — 把抓包 CA 装进「本地计算机 / 受信任的根证书颁发机构」
# 需要用管理员权限运行：Start-Process powershell -Verb RunAs
$ErrorActionPreference = 'Stop'
$caPath = 'D:\workbuddy api2\tools\wb-capture\ca\ca.crt.pem'
$log    = 'D:\workbuddy api2\tools\wb-capture\ca\install-machine.log'

function Log($m) {
  $line = "$(Get-Date -Format 'HH:mm:ss') $m"
  Add-Content -LiteralPath $log -Value $line -Encoding UTF8
  Write-Host $line
}

try {
  $cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2 $caPath
  $store = New-Object System.Security.Cryptography.X509Certificates.X509Store 'Root','LocalMachine'
  $store.Open('ReadWrite')
  $store.Add($cert)
  $store.Close()
  Log "OK added to LocalMachine\Root: $($cert.Subject) $($cert.Thumbprint)"
} catch {
  Log "FAILED: $($_.Exception.Message)"
  exit 1
}

$chk = New-Object System.Security.Cryptography.X509Certificates.X509Store 'Root','LocalMachine'
$chk.Open('ReadOnly')
$n = ($chk.Certificates | Where-Object { $_.Subject -like '*WB Capture*' } | Measure-Object).Count
$chk.Close()
Log "verify: found $n matching cert(s) in LocalMachine\Root"
