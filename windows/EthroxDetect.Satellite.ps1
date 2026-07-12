param(
    [string] $BindAddress = "0.0.0.0",
    [int] $Port = 8766
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$DataRoot = Join-Path $RepoRoot "data"
$AwarenessLog = Join-Path $DataRoot "signal-awareness.json"
$AppLog = Join-Path $RepoRoot "ethrox-detect-windows.log"

. (Join-Path $PSScriptRoot "AwarenessLog.ps1")
Initialize-AwarenessLog -Path $AwarenessLog
$script:AwarenessMetadataOnlyPayload = $true

function Write-SatelliteLog {
    param([string] $Message)
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $AppLog -Value $line -ErrorAction SilentlyContinue
    Write-Host $line
}

try {
    Start-AwarenessSyncServer -BindAddress $BindAddress -Port $Port -LogPath $AppLog
    Write-SatelliteLog "Ethrox Detect Windows satellite sync listening on ${BindAddress}:${Port}."
    Write-SatelliteLog "Role: secondary companion. Linux T5810B remains the classification and SDR hub."

    $waitHandle = [System.Threading.ManualResetEvent]::new($false)
    while ($true) {
        [void](Receive-AwarenessSyncRequests -LogPath $AppLog -MaxRequests 8)
        [void]$waitHandle.WaitOne(500)
    }
} finally {
    if ($waitHandle) { $waitHandle.Dispose() }
    Stop-AwarenessSyncServer
    Write-SatelliteLog "Ethrox Detect Windows satellite sync stopped."
}
