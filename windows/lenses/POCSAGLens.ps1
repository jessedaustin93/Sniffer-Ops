# POCSAG/FLEX paging: common US pager bands 152-159, 454-460, 929-932 MHz. STUB.
function New-POCSAGLens {
    New-LensObject -Name 'POCSAG' -Kind 'data' -Implemented $false `
        -DisplayName 'Pager Decoder (POCSAG)' `
        -CanHandle {
            param($signal)
            $mhz = Get-SignalFrequencyMHz -Signal $signal
            if ($null -eq $mhz) { return $false }
            return (($mhz -ge 152.0 -and $mhz -le 159.0) -or
                    ($mhz -ge 454.0 -and $mhz -le 460.0) -or
                    ($mhz -ge 929.0 -and $mhz -le 932.0))
        } `
        -Activate {
            param($signal)
            [pscustomobject][ordered]@{
                Kind    = 'notimplemented'
                Message = 'POCSAG pager decoding is on the roadmap but not yet implemented in SnifferOps Windows.'
            }
        }
}
