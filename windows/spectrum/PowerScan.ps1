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

# Detect peaks: bins more than $ThresholdDb above the median noise floor, grouped
# into contiguous runs. Returns one peak per run at its strongest bin.
function Find-SpectrumPeaks {
    param(
        [object[]] $Bins,
        [double]   $ThresholdDb = 6.0
    )
    if (@($Bins).Count -eq 0) { return @() }

    $sorted = @($Bins | Sort-Object Hz)
    $floor = Get-Median -Values @($sorted | ForEach-Object { [double]$_.Db })
    $cutoff = $floor + $ThresholdDb

    # Estimate the bin spacing to know what "contiguous" means.
    $step = 1
    if ($sorted.Count -ge 2) {
        $step = [long]($sorted[1].Hz - $sorted[0].Hz)
        if ($step -le 0) { $step = 1 }
    }
    $gapLimit = $step * 2

    $peaks = New-Object System.Collections.Generic.List[object]
    $runBest = $null
    $prevHz = $null
    foreach ($bin in $sorted) {
        $above = ($bin.Db -ge $cutoff)
        $contiguous = ($null -ne $prevHz) -and (($bin.Hz - $prevHz) -le $gapLimit)
        if ($above) {
            if ($runBest -and $contiguous) {
                if ($bin.Db -gt $runBest.Db) { $runBest = $bin }
            } else {
                if ($runBest) {
                    $peaks.Add([pscustomobject]@{ FrequencyHz = [long]$runBest.Hz; PowerDb = [double]$runBest.Db }) | Out-Null
                }
                $runBest = $bin
            }
            $prevHz = $bin.Hz
        } else {
            if ($runBest) {
                $peaks.Add([pscustomobject]@{ FrequencyHz = [long]$runBest.Hz; PowerDb = [double]$runBest.Db }) | Out-Null
                $runBest = $null
            }
            $prevHz = $bin.Hz
        }
    }
    if ($runBest) {
        $peaks.Add([pscustomobject]@{ FrequencyHz = [long]$runBest.Hz; PowerDb = [double]$runBest.Db }) | Out-Null
    }

    return @($peaks.ToArray() | Sort-Object -Property @{ Expression = "PowerDb"; Descending = $true })
}
