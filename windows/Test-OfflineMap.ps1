# Headless unit test for the offline map placement engine.
# Run:  powershell.exe -NoProfile -ExecutionPolicy Bypass -File windows\Test-OfflineMap.ps1
$ErrorActionPreference = "Stop"

# AwarenessLog.ps1 provides ConvertTo-AwarenessNumber; OfflineMap.ps1 is the
# unit under test. Neither needs WPF for the placement functions.
. (Join-Path $PSScriptRoot "AwarenessLog.ps1")
. (Join-Path $PSScriptRoot "OfflineMap.ps1")

$failures = 0
function Assert($desc, $cond) {
    if ($cond) { "PASS  $desc" } else { "FAIL  $desc"; $script:failures++ }
}

function New-TestProfile {
    param([string] $Key, [string] $Type, [object[]] $Sightings, [string[]] $NodeIds = @())
    return [pscustomobject][ordered]@{
        Key = $Key
        Name = $Key
        Type = $Type
        SpecificType = ""
        Class = "Normal"
        LastSeen = "2026-06-11T12:00:00Z"
        SeenCount = @($Sightings).Count
        LastSignal = "-50 dBm"
        NodeIds = $NodeIds
        Sightings = @($Sightings)
    }
}

function New-TestSighting {
    param([string] $NodeId, [string] $At, [object] $Lat = $null, [object] $Lon = $null)
    return [pscustomobject][ordered]@{
        At = $At
        NodeId = $NodeId
        NodeName = $NodeId
        Latitude = $Lat
        Longitude = $Lon
        NodeLatitude = $Lat
        NodeLongitude = $Lon
        AccuracyMeters = $null
        SignalStrength = "-50 dBm"
        SignalStrengthNumeric = -50
    }
}

Write-Host "== offline map placement tests ==" -ForegroundColor Cyan

# Scenario:
#  phone  - has GPS; saw AP-GPS at 40.00/-75.00 at 12:00 and the no-GPS device
#           BT-LINKED at 12:05 (no fix recorded for that sighting).
#  pc     - never has GPS; saw AP-GPS too (so the PC node can be anchored) and
#           the PC-only device WIFI-ANCHOR.
#  ghost  - seen once by a node with no GPS and no co-seen GPS: stays unplaced.
$profiles = @(
    New-TestProfile -Key "AP-GPS" -Type "WIFI" -NodeIds @("phone", "pc") -Sightings @(
        (New-TestSighting -NodeId "phone" -At "2026-06-11T12:00:00Z" -Lat 40.00 -Lon -75.00),
        (New-TestSighting -NodeId "phone" -At "2026-06-11T12:10:00Z" -Lat 40.02 -Lon -74.98),
        (New-TestSighting -NodeId "pc" -At "2026-06-11T12:20:00Z")
    )
    New-TestProfile -Key "BT-LINKED" -Type "BLUETOOTH" -NodeIds @("phone") -Sightings @(
        (New-TestSighting -NodeId "phone" -At "2026-06-11T12:05:00Z")
    )
    New-TestProfile -Key "WIFI-ANCHOR" -Type "WIFI" -NodeIds @("pc") -Sightings @(
        (New-TestSighting -NodeId "pc" -At "2026-06-10T09:00:00Z")
    )
    New-TestProfile -Key "GHOST" -Type "BLE" -NodeIds @("lost-node") -Sightings @(
        (New-TestSighting -NodeId "lost-node" -At "2026-06-11T11:00:00Z")
    )
)

$placements = @(Get-OfflineMapPlacements -Profiles $profiles -LinkWindowMinutes 20)
$byKey = @{}
foreach ($p in $placements) { $byKey[$p.Key] = $p }

Assert "all profiles got a placement row"   ($placements.Count -eq 4)

# Tier 1: own GPS -> averaged position.
$gps = $byKey["AP-GPS"]
Assert "GPS signal uses gps tier"           ($gps.PlacementTier -eq "gps")
Assert "GPS latitude is sighting average"   ([Math]::Abs($gps.Latitude - 40.01) -lt 0.0001)
Assert "GPS longitude is sighting average"  ([Math]::Abs($gps.Longitude - (-74.99)) -lt 0.0001)

# Tier 2: no own GPS, placed from the nearest-in-time fix of the same node.
# BT-LINKED at 12:05 sits between phone fixes at 12:00 and 12:10 (both 5 min
# away) - the implementation keeps the first equally-near fix (12:00).
$linked = $byKey["BT-LINKED"]
Assert "co-seen signal uses linked tier"    ($linked.PlacementTier -eq "linked")
Assert "linked position from nearest fix"   ([Math]::Abs($linked.Latitude - 40.00) -lt 0.0001 -and [Math]::Abs($linked.Longitude - (-75.00)) -lt 0.0001)

# Tier 3: PC-only device, PC never had GPS. The PC co-sees AP-GPS (placed), so
# the PC node anchors to AP-GPS's position and WIFI-ANCHOR lands there.
$anchored = $byKey["WIFI-ANCHOR"]
Assert "PC-only signal uses anchor tier"    ($anchored.PlacementTier -eq "anchor")
Assert "anchor borrows co-seen GPS area"    ([Math]::Abs($anchored.Latitude - 40.01) -lt 0.0001 -and [Math]::Abs($anchored.Longitude - (-74.99)) -lt 0.0001)

# Tier 4: nothing GPS-related anywhere near it.
$ghost = $byKey["GHOST"]
Assert "isolated signal stays unplaced"     ($ghost.PlacementTier -eq "unplaced")
Assert "unplaced has no coordinates"        ($null -eq $ghost.Latitude -and $null -eq $ghost.Longitude)

# Link window is respected: a sighting hours away from any fix must not link.
$stale = @(
    New-TestProfile -Key "AP2" -Type "WIFI" -NodeIds @("phone") -Sightings @(
        (New-TestSighting -NodeId "phone" -At "2026-06-11T06:00:00Z" -Lat 40.05 -Lon -74.90)
    )
    New-TestProfile -Key "BT2" -Type "BLUETOOTH" -NodeIds @("phone") -Sightings @(
        (New-TestSighting -NodeId "phone" -At "2026-06-11T12:00:00Z")
    )
)
$stalePlacements = @(Get-OfflineMapPlacements -Profiles $stale -LinkWindowMinutes 20)
$bt2 = @($stalePlacements | Where-Object { $_.Key -eq "BT2" })[0]
Assert "out-of-window sighting not linked"  ($bt2.PlacementTier -ne "linked")
Assert "falls back to node anchor instead"  ($bt2.PlacementTier -eq "anchor")
Assert "anchor at node's own GPS average"   ([Math]::Abs($bt2.Latitude - 40.05) -lt 0.0001)

# Weighting: a closer-in-time fix dominates a farther one.
$weighted = @(
    New-TestProfile -Key "AP3" -Type "WIFI" -NodeIds @("phone") -Sightings @(
        (New-TestSighting -NodeId "phone" -At "2026-06-11T12:00:00Z" -Lat 40.00 -Lon -75.00),
        (New-TestSighting -NodeId "phone" -At "2026-06-11T13:00:00Z" -Lat 41.00 -Lon -76.00)
    )
    New-TestProfile -Key "BT3" -Type "BLUETOOTH" -NodeIds @("phone") -Sightings @(
        (New-TestSighting -NodeId "phone" -At "2026-06-11T12:01:00Z"),
        (New-TestSighting -NodeId "phone" -At "2026-06-11T12:59:00Z")
    )
)
$weightedPlacements = @(Get-OfflineMapPlacements -Profiles $weighted -LinkWindowMinutes 20)
$bt3 = @($weightedPlacements | Where-Object { $_.Key -eq "BT3" })[0]
Assert "two sightings both link"            ($bt3.PlacementTier -eq "linked")
Assert "linked position is between fixes"   ($bt3.Latitude -gt 40.0 -and $bt3.Latitude -lt 41.0)

# Web Mercator helpers used by the tile renderer.
$origin = Get-OfflineMapWorldPixel -Lat 0.0 -Lon 0.0 -Zoom 0.0
Assert "mercator origin centers at z0"      ([Math]::Abs($origin[0] - 128) -lt 0.001 -and [Math]::Abs($origin[1] - 128) -lt 0.001)
$z1 = Get-OfflineMapWorldPixel -Lat 0.0 -Lon 0.0 -Zoom 1.0
Assert "world doubles per zoom level"       ([Math]::Abs($z1[0] - 256) -lt 0.001)
$px = Get-OfflineMapWorldPixel -Lat 40.0 -Lon -75.0 -Zoom 12.0
$rt = Get-OfflineMapLatLon -X $px[0] -Y $px[1] -Zoom 12.0
Assert "mercator roundtrip is stable"       ([Math]::Abs($rt[0] - 40.0) -lt 0.000001 -and [Math]::Abs($rt[1] - (-75.0)) -lt 0.000001)
Assert "meters/pixel at equator z0"         ([Math]::Abs((Get-OfflineMapMetersPerPixel -Lat 0.0 -Zoom 0.0) - 156543.03392) -lt 0.01)
Assert "tile path under data\map-tiles"     ((Get-OfflineMapTilePath -Z 12 -X 5 -Y 7) -like "*data\map-tiles\dark\12\5\7.png")

# Type colors stay distinct for the legend.
Assert "wifi color"                         ((Get-OfflineMapTypeColor -Type "WIFI") -eq "#39FF14")
Assert "unknown type gets default color"    ((Get-OfflineMapTypeColor -Type "MYSTERY") -eq "#E5E7EB")

Write-Host ""
if ($failures -eq 0) {
    Write-Host "ALL OFFLINE-MAP TESTS PASSED" -ForegroundColor Green
    exit 0
} else {
    Write-Host "$failures OFFLINE-MAP TEST(S) FAILED" -ForegroundColor Red
    exit 1
}
