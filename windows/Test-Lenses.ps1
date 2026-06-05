# Independent unit test for the SignalLens system. Dot-sources only the lens
# files (no WPF / Add-Type / audio) and asserts routing + dot color.
# Run:  powershell.exe -NoProfile -ExecutionPolicy Bypass -File windows\Test-Lenses.ps1
$ErrorActionPreference = "Stop"

$LensDir = Join-Path $PSScriptRoot "lenses"
. (Join-Path $LensDir "_LensContract.ps1")
. (Join-Path $LensDir "BroadcastFMLens.ps1")
. (Join-Path $LensDir "AviationVoiceLens.ps1")
. (Join-Path $LensDir "NOAAWeatherLens.ps1")
. (Join-Path $LensDir "AnalogVoiceLens.ps1")
. (Join-Path $LensDir "ADSBLens.ps1")
. (Join-Path $LensDir "P25Phase1Lens.ps1")
. (Join-Path $LensDir "POCSAGLens.ps1")
. (Join-Path $LensDir "ACARSLens.ps1")

$lenses = @(
    New-BroadcastFMLens
    New-AviationVoiceLens
    New-NOAAWeatherLens
    New-AnalogVoiceLens
    New-ADSBLens
    New-P25Phase1Lens
    New-POCSAGLens
    New-ACARSLens
)
foreach ($l in $lenses) { [void] (Test-SignalLens -Lens $l) }

function Signal([double] $mhz) { [pscustomobject]@{ FrequencyHz = [long]($mhz * 1000000); Label = ""; Modulation = "" } }

function Status($sig) {
    $matches = @($lenses | Where-Object { $_.CanHandle($sig) })
    $impl = @($matches | Where-Object { $_.Implemented })
    $dot = if ($matches.Count -eq 0) { "Red" } elseif ($impl.Count -gt 0) { "Green" } else { "Yellow" }
    [pscustomobject]@{ Dot = $dot; Count = $matches.Count; Names = @($matches | ForEach-Object { $_.Name }) }
}

$failures = 0
function Check($desc, $mhz, $expectedDot, $expectedNames) {
    $s = Status (Signal $mhz)
    $gotNames = ($s.Names | Sort-Object) -join ","
    $wantNames = ($expectedNames | Sort-Object) -join ","
    $ok = ($s.Dot -eq $expectedDot) -and ($gotNames -eq $wantNames)
    $mark = if ($ok) { "PASS" } else { "FAIL"; $script:failures++ }
    "{0}  {1,-34} {2,8} MHz  dot={3,-6} lenses=[{4}]" -f $mark, $desc, $mhz, $s.Dot, $gotNames
    if (-not $ok) {
        "       expected dot=$expectedDot lenses=[$wantNames]"
    }
}

Write-Host "== SignalLens routing tests ==" -ForegroundColor Cyan
Check "Broadcast FM -> WFM only"      88.5  "Green"  @("BroadcastFM")
Check "Aviation voice (AM) only"      124.0 "Green"  @("AviationVoice")
Check "ACARS band -> voice+data"      131.55 "Green" @("AviationVoice", "ACARS")
Check "Nav band 108-118 -> fallback"  108.5 "Green"  @("AnalogVoice")
Check "VHF gov -> fallback only"      137.5 "Green"  @("AnalogVoice")
Check "NOAA wx -> NOAA only"          162.45 "Green" @("NOAAWeather")
Check "ISM 433 -> no decoder"         433.92 "Red"   @()
Check "GMRS/FRS -> fallback"          462.5625 "Green" @("AnalogVoice")
Check "P25 800 -> stub only"          851.0 "Yellow" @("P25Phase1")
Check "ISM 915 -> no decoder"         915.0 "Red"    @()
Check "ADS-B UAT 978 -> map"          978.0 "Green"  @("ADSB")
Check "ADS-B 1090 -> map"             1090.0 "Green"  @("ADSB")

Write-Host ""
if ($failures -eq 0) {
    Write-Host "ALL TESTS PASSED" -ForegroundColor Green
    exit 0
} else {
    Write-Host "$failures TEST(S) FAILED" -ForegroundColor Red
    exit 1
}
