# Headless unit test for the ADS-B decoder using canonical Mode S sample frames.
# Run:  powershell.exe -NoProfile -ExecutionPolicy Bypass -File windows\Test-Adsb.ps1
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "adsb\AdsbDecoder.ps1")

$failures = 0
function Assert($desc, $cond) {
    if ($cond) {
        "PASS  $desc"
    } else {
        "FAIL  $desc"
        $script:failures++
    }
}
function AssertNear($desc, $got, $want, $tol) {
    $ok = ($null -ne $got) -and ([math]::Abs([double]$got - [double]$want) -le $tol)
    if ($ok) { "PASS  $desc (got $got)" } else { "FAIL  $desc (got '$got', want ~$want)"; $script:failures++ }
}

Write-Host "== ADS-B decoder tests ==" -ForegroundColor Cyan

# Callsign: textbook frame -> ICAO 4840D6, callsign KLM1023
$csBytes = Convert-HexToBytes "8D4840D6202CC371C32CE0576098"
Assert "callsign frame is 14 bytes"        ($csBytes.Length -eq 14)
Assert "callsign DF = 17"                   ((Get-AdsbDownlinkFormat -Bytes $csBytes) -eq 17)
Assert "callsign ICAO = 4840D6"             ((Get-AdsbIcao -Bytes $csBytes) -eq "4840D6")
Assert "callsign TC in 1..4"                (((Get-AdsbTypeCode -Bytes $csBytes) -ge 1) -and ((Get-AdsbTypeCode -Bytes $csBytes) -le 4))
Assert "callsign decodes to KLM1023"        ((Get-AdsbCallsign -Bytes $csBytes) -eq "KLM1023")

# Airborne position even/odd pair -> ICAO 40621D, ~lat 52.2572 lon 3.91937, 38000 ft
$even = "8D40621D58C382D690C8AC2863A7"
$odd  = "8D40621D58C386435CC412692AD6"
$evenBytes = Convert-HexToBytes $even
$oddBytes  = Convert-HexToBytes $odd
Assert "position ICAO = 40621D"             ((Get-AdsbIcao -Bytes $evenBytes) -eq "40621D")
AssertNear "altitude ~38000 ft"             (Get-AdsbAltitude -Bytes $evenBytes) 38000 25

$evenCpr = Get-AdsbCprFrame -Bytes $evenBytes
$oddCpr  = Get-AdsbCprFrame -Bytes $oddBytes
Assert "even frame OddFlag=0"               ($evenCpr.OddFlag -eq 0)
Assert "odd frame OddFlag=1"                ($oddCpr.OddFlag -eq 1)

# Even-referenced solution = the canonical junzis worked-example position.
$posEven = Resolve-CprPosition -Even $evenCpr -Odd $oddCpr -MostRecentOdd 0
AssertNear "even-ref latitude ~52.2572"     $posEven.Lat 52.2572 0.001
AssertNear "even-ref longitude ~3.91937"    $posEven.Lon 3.91937 0.001

# Odd-referenced solution = the same pair resolved against the odd frame.
$posOdd = Resolve-CprPosition -Even $evenCpr -Odd $oddCpr -MostRecentOdd 1
AssertNear "odd-ref latitude ~52.26578"     $posOdd.Lat 52.26578 0.001
AssertNear "odd-ref longitude ~3.93891"     $posOdd.Lon 3.93891 0.001

# End-to-end: odd frame is fed last, so the odd-referenced solution is expected.
$acs = Convert-AdsbFrames -Frames @($even, $odd, "8D4840D6202CC371C32CE0576098")
$klm = $acs | Where-Object { $_.Icao -eq "4840D6" }
$pos2 = $acs | Where-Object { $_.Icao -eq "40621D" }
Assert "end-to-end finds KLM callsign"      ($klm.Callsign -eq "KLM1023")
AssertNear "end-to-end position lat"        $pos2.Lat 52.26578 0.001
AssertNear "end-to-end position lon"        $pos2.Lon 3.93891 0.001
AssertNear "end-to-end altitude"            $pos2.Altitude 38000 25

# Junk / short frames are ignored
$acsJunk = Convert-AdsbFrames -Frames @("", "*deadbeef;", "not hex at all")
Assert "junk frames produce no aircraft"    ($acsJunk.Count -eq 0)

Write-Host ""
if ($failures -eq 0) {
    Write-Host "ALL ADS-B TESTS PASSED" -ForegroundColor Green
    exit 0
} else {
    Write-Host "$failures ADS-B TEST(S) FAILED" -ForegroundColor Red
    exit 1
}
