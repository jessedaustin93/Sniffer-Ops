# Headless tests for Windows secondary awareness sync compatibility.
# Run: powershell.exe -NoProfile -ExecutionPolicy Bypass -File windows\Test-AwarenessSync.ps1
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "AwarenessLog.ps1")

$failures = 0
function Assert($desc, $cond) {
    if ($cond) { "PASS  $desc" } else { "FAIL  $desc"; $script:failures++ }
}

$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("snifferops-awareness-" + [guid]::NewGuid().ToString("N") + ".json")
Initialize-AwarenessLog -Path $tmp

$snapshot = [pscustomobject][ordered]@{
    schema = 1
    protocolVersion = 2
    nodeId = "android-synthetic"
    nodeName = "Synthetic Android"
    nodeRole = "mobile_detector"
    capturedAt = 1000
    completeTypes = @("BLUETOOTH")
    location = [pscustomobject]@{
        latitude = 35.0
        longitude = -83.0
        accuracyMeters = 12.0
    }
    signals = @(
        [pscustomobject][ordered]@{
            id = "ble-aa"
            name = "Tile Synthetic"
            address = "AA:BB:CC:00:00:09"
            type = "BLUETOOTH"
            deviceClass = "Tracker"
            manufacturer = "Synthetic"
            threatLevel = "UNKNOWN"
            signalStrength = -62
            sightings = @(
                [pscustomobject][ordered]@{
                    id = "synthetic-sighting-1"
                    capturedAt = 1000
                    signalStrength = -62
                    latitude = 35.0
                    longitude = -83.0
                    accuracyMeters = 12.0
                    movementSessionId = "android-moving-1"
                    speedMetersPerSecond = 8.0
                    bearingDegrees = 90.0
                    locationProvider = "fused"
                    sourceNodeId = "android-synthetic"
                }
            )
        }
    )
}

$merge = Merge-AwarenessSnapshot -Snapshot $snapshot
$payload = Get-AwarenessSyncPayload
$state = Read-AwarenessState
$profile = @($state.Signals.GetEnumerator())[0].Value
$sighting = @($profile.Sightings)[0]

Assert "mobile sighting ID acknowledged" (@($merge.AcknowledgedSightingIds) -contains "synthetic-sighting-1")
Assert "payload advertises secondary companion role" ($payload.nodeRole -eq "secondary_companion")
Assert "payload advertises exact ack capability" (@($payload.capabilities) -contains "exact_sighting_acknowledgement")
Assert "movement session preserved" ($sighting.MovementSessionId -eq "android-moving-1")
Assert "motion fields preserved" ($sighting.SpeedMetersPerSecond -eq 8.0 -and $sighting.BearingDegrees -eq 90.0)

$script:AwarenessMetadataOnlyPayload = $true
$metadataPayload = Get-AwarenessSyncPayload
Assert "metadata-only satellite payload suppresses history" ($metadataPayload.returnedSignals -eq 0 -and @($metadataPayload.signals).Count -eq 0)
Assert "metadata-only satellite payload advertises capability" (@($metadataPayload.capabilities) -contains "metadata_only_companion_awareness_payload")
$script:AwarenessMetadataOnlyPayload = $false

Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue

if ($failures -eq 0) {
    Write-Host "ALL AWARENESS SYNC TESTS PASSED" -ForegroundColor Green
    exit 0
} else {
    Write-Host "$failures AWARENESS SYNC TEST(S) FAILED" -ForegroundColor Red
    exit 1
}
