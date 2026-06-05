# ACARS aircraft data link: VHF 129-137 MHz (e.g. 131.550). STUB.
# Note: overlaps the aviation AM voice band on purpose, so an ACARS-range signal
# produces the "Listen as voice / Decode as data" chooser.
function New-ACARSLens {
    New-LensObject -Name 'ACARS' -Kind 'data' -Implemented $false `
        -DisplayName 'ACARS Decoder' `
        -CanHandle {
            param($signal)
            $mhz = Get-SignalFrequencyMHz -Signal $signal
            if ($null -eq $mhz) { return $false }
            return ($mhz -ge 129.0 -and $mhz -le 137.0)
        } `
        -Activate {
            param($signal)
            [pscustomobject][ordered]@{
                Kind    = 'notimplemented'
                Message = 'ACARS data-link decoding is on the roadmap but not yet implemented in SnifferOps Windows.'
            }
        }
}
