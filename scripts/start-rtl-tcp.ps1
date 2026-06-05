param(
    [string] $BindAddress = "0.0.0.0",
    [int] $Port = 1234
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$rtlTcp = Join-Path $root "tools\rtl-sdr-blog\x64\rtl_tcp.exe"

if (-not (Test-Path $rtlTcp)) {
    throw "rtl_tcp.exe was not found at $rtlTcp"
}

$existing = Get-Process rtl_tcp -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Stopping existing rtl_tcp process..."
    $existing | Stop-Process -Force
    Start-Sleep -Seconds 1
}

Write-Host "Starting rtl_tcp on ${BindAddress}:$Port"
Write-Host "Use this computer's LAN IP address and port $Port in SnifferOps."
& $rtlTcp -a $BindAddress -p $Port
