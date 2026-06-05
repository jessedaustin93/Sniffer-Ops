param(
    [string] $BindAddress = "0.0.0.0",
    [int] $Port = 1234
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$toolRoot = @(
    (Join-Path $root "tools\rtl-sdr-blog\x64"),
    (Join-Path $root "tools\rtl-sdr-blog\x86"),
    (Join-Path $root "tools\rtl-sdr-blog")
) | Where-Object { Test-Path (Join-Path $_ "rtl_tcp.exe") } | Select-Object -First 1

if (-not $toolRoot) {
    $toolRoot = Join-Path $root "tools\rtl-sdr-blog\x64"
}

$rtlTcp = Join-Path $toolRoot "rtl_tcp.exe"

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
Set-Location -LiteralPath $toolRoot
& $rtlTcp -a $BindAddress -p $Port
