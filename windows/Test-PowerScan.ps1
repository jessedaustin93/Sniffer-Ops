# Headless unit test for the rtl_power CSV parser + peak detector.
# Run:  powershell.exe -NoProfile -ExecutionPolicy Bypass -File windows\Test-PowerScan.ps1
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "spectrum\PowerScan.ps1")

$failures = 0
function Assert($desc, $cond) {
    if ($cond) { "PASS  $desc" } else { "FAIL  $desc"; $script:failures++ }
}

Write-Host "== rtl_power scan tests ==" -ForegroundColor Cyan

# One CSV line: 100..109 MHz, 1 MHz step, 10 bins. Noise ~-60, a peak at index 5
# (105 MHz, -20) and another at index 8 (108 MHz, -22).
$line = "2024-01-01, 12:00:00, 100000000, 110000000, 1000000.00, 100, -60, -61, -59, -60, -62, -20, -58, -61, -22, -60"
$bins = ConvertFrom-RtlPowerCsv -Lines @($line)
Assert "parsed 10 bins"                 ($bins.Count -eq 10)
Assert "first bin at 100 MHz"           ($bins[0].Hz -eq 100000000)
Assert "bin 5 at 105 MHz"               ($bins[5].Hz -eq 105000000)
Assert "bin 5 db = -20"                 ([double]$bins[5].Db -eq -20)

$peaks = @(Find-SpectrumPeaks -Bins $bins -ThresholdDb 6.0)
Assert "found 2 peaks"                  ($peaks.Count -eq 2)
Assert "strongest peak is 105 MHz"      ($peaks[0].FrequencyHz -eq 105000000)
Assert "second peak is 108 MHz"         ((@($peaks | Where-Object { $_.FrequencyHz -eq 108000000 })).Count -eq 1)

# Two adjacent hot bins should collapse into a single peak at the stronger bin.
$line2 = "2024-01-01, 12:00:00, 100000000, 110000000, 1000000.00, 100, -60, -60, -60, -19, -18, -60, -60, -60, -60, -60"
$peaks2 = @(Find-SpectrumPeaks -Bins (ConvertFrom-RtlPowerCsv -Lines @($line2)) -ThresholdDb 6.0)
Assert "adjacent hot bins -> 1 peak"    ($peaks2.Count -eq 1)
Assert "merged peak at stronger bin"    ($peaks2[0].FrequencyHz -eq 104000000)

# Flat noise -> no peaks.
$flat = "2024-01-01, 12:00:00, 100000000, 110000000, 1000000.00, 100, -60, -61, -59, -60, -62, -60, -58, -61, -60, -60"
$peaks3 = @(Find-SpectrumPeaks -Bins (ConvertFrom-RtlPowerCsv -Lines @($flat)) -ThresholdDb 6.0)
Assert "flat noise -> no peaks"         ($peaks3.Count -eq 0)

# Nearby peaks from one wide emitter should collapse to the stronger bucket.
$near = @(
    [pscustomobject]@{ FrequencyHz = 740309000; PowerDb = -2.9; FloorDb = -15.0; ProminenceDb = 12.1 },
    [pscustomobject]@{ FrequencyHz = 740440000; PowerDb = -2.4; FloorDb = -15.0; ProminenceDb = 12.6 },
    [pscustomobject]@{ FrequencyHz = 744000000; PowerDb = 1.0; FloorDb = -15.0; ProminenceDb = 16.0 }
)
$mergedNear = @(Merge-NearbySpectrumPeaks -Peaks $near -CoalesceHz 250000)
Assert "nearby peaks coalesce"          ($mergedNear.Count -eq 2)
Assert "coalesced peak keeps stronger"  ((@($mergedNear | Where-Object { $_.FrequencyHz -eq 740440000 })).Count -eq 1)

# Comment/blank lines are skipped.
$bins4 = ConvertFrom-RtlPowerCsv -Lines @("# header", "", $line)
Assert "comment/blank lines skipped"    ($bins4.Count -eq 10)

Write-Host ""
if ($failures -eq 0) {
    Write-Host "ALL POWER-SCAN TESTS PASSED" -ForegroundColor Green
    exit 0
} else {
    Write-Host "$failures POWER-SCAN TEST(S) FAILED" -ForegroundColor Red
    exit 1
}
