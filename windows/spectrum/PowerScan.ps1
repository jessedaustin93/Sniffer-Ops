# Pure rtl_power CSV parsing + peak detection. No hardware, no I/O beyond the
# strings handed in, so it can be unit-tested headless.
#
# rtl_power CSV line format:
#   date, time, Hz_low, Hz_high, Hz_step, samples, db, db, db, ...
# The k-th db sample corresponds to frequency  Hz_low + k * Hz_step.

# Parse rtl_power CSV lines into a flat list of frequency bins { Hz, Db }.
function ConvertFrom-RtlPowerCsv {
    param([string[]] $Lines)
    $bins = New-Object System.Collections.Generic.List[object]
    foreach ($line in $Lines) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        if ($line.TrimStart().StartsWith("#")) { continue }
        $parts = $line.Split(',')
        if ($parts.Count -lt 7) { continue }
        $hzLow = [double]($parts[2].Trim())
        $hzStep = [double]($parts[4].Trim())
        for ($k = 6; $k -lt $parts.Count; $k++) {
            $raw = $parts[$k].Trim()
            if ([string]::IsNullOrWhiteSpace($raw)) { continue }
            $db = $raw -as [double]
            if ($null -eq $db) { continue }
            $hz = $hzLow + ($k - 6) * $hzStep
            $bins.Add([pscustomobject]@{ Hz = [long][math]::Round($hz); Db = $db })
        }
    }
    return ,$bins.ToArray()
}

function Get-Median {
    param([double[]] $Values)
    if ($Values.Count -eq 0) { return 0.0 }
    $sorted = $Values | Sort-Object
    $mid = [int][math]::Floor($sorted.Count / 2)
    if ($sorted.Count % 2 -eq 1) { return [double]$sorted[$mid] }
    return ([double]$sorted[$mid - 1] + [double]$sorted[$mid]) / 2.0
}

# Detect peaks: bins that stand above both the whole-sweep median and their
# local neighborhood floor, grouped into runs. This avoids counting a smooth
# receiver/antenna noise ramp as hundreds of "signals."
function Find-SpectrumPeaks {
    param(
        [object[]] $Bins,
        [double]   $ThresholdDb = 10.0,
        [int]      $WindowBins = 24
    )
    if (@($Bins).Count -eq 0) { return @() }

    $sorted = @($Bins | Sort-Object Hz)
    $globalFloor = Get-Median -Values @($sorted | ForEach-Object { [double]$_.Db })

    # Estimate the bin spacing to know what "contiguous" means.
    $step = 1
    if ($sorted.Count -ge 2) {
        $step = [long]($sorted[1].Hz - $sorted[0].Hz)
        if ($step -le 0) { $step = 1 }
    }
    $gapLimit = $step * 5

    $peaks = New-Object System.Collections.Generic.List[object]
    $runBest = $null
    $prevHz = $null
    for ($i = 0; $i -lt $sorted.Count; $i++) {
        $bin = $sorted[$i]
        $start = [Math]::Max(0, $i - $WindowBins)
        $end = [Math]::Min($sorted.Count - 1, $i + $WindowBins)
        $neighbors = New-Object System.Collections.Generic.List[double]
        for ($j = $start; $j -le $end; $j++) {
            if ([Math]::Abs($j - $i) -le 2) { continue }
            $neighbors.Add([double]$sorted[$j].Db) | Out-Null
        }
        $localFloor = if ($neighbors.Count -gt 0) { Get-Median -Values $neighbors.ToArray() } else { $globalFloor }
        $floor = [Math]::Max($globalFloor, $localFloor)
        $above = ([double]$bin.Db -ge ($floor + $ThresholdDb))
        $contiguous = ($null -ne $prevHz) -and (($bin.Hz - $prevHz) -le $gapLimit)
        if ($above) {
            $candidate = [pscustomobject]@{ Hz = [long]$bin.Hz; Db = [double]$bin.Db; FloorDb = [double]$floor; ProminenceDb = ([double]$bin.Db - [double]$floor) }
            if ($runBest -and $contiguous) {
                if ($candidate.Db -gt $runBest.Db) { $runBest = $candidate }
            } else {
                if ($runBest) {
                    $peaks.Add([pscustomobject]@{ FrequencyHz = [long]$runBest.Hz; PowerDb = [double]$runBest.Db; FloorDb = [double]$runBest.FloorDb; ProminenceDb = [double]$runBest.ProminenceDb }) | Out-Null
                }
                $runBest = $candidate
            }
            $prevHz = $bin.Hz
        } else {
            if ($runBest) {
                $peaks.Add([pscustomobject]@{ FrequencyHz = [long]$runBest.Hz; PowerDb = [double]$runBest.Db; FloorDb = [double]$runBest.FloorDb; ProminenceDb = [double]$runBest.ProminenceDb }) | Out-Null
                $runBest = $null
            }
            $prevHz = $bin.Hz
        }
    }
    if ($runBest) {
        $peaks.Add([pscustomobject]@{ FrequencyHz = [long]$runBest.Hz; PowerDb = [double]$runBest.Db; FloorDb = [double]$runBest.FloorDb; ProminenceDb = [double]$runBest.ProminenceDb }) | Out-Null
    }

    return @($peaks.ToArray() | Sort-Object -Property @{ Expression = "PowerDb"; Descending = $true })
}
