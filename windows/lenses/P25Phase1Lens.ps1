# P25 Phase 1 digital voice/trunking: 762-775 MHz and 851-869 MHz. STUB.
function New-P25Phase1Lens {
    New-LensObject -Name 'P25Phase1' -Kind 'data' -Implemented $false `
        -DisplayName 'P25 Decoder' `
        -CanHandle {
            param($signal)
            $mhz = Get-SignalFrequencyMHz -Signal $signal
            if ($null -eq $mhz) { return $false }
            return (($mhz -ge 762.0 -and $mhz -le 775.0) -or ($mhz -ge 851.0 -and $mhz -le 869.0))
        } `
        -Activate {
            param($signal)
            [pscustomobject][ordered]@{
                Kind    = 'notimplemented'
                Message = 'P25 Phase 1 decoding is on the roadmap but not yet implemented in SnifferOps Windows.'
            }
        }
}
