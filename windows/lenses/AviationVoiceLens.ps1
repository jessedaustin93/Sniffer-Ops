# Aviation voice: AM. 118-137 MHz civil air band + 225-400 MHz military air band.
function New-AviationVoiceLens {
    New-LensObject -Name 'AviationVoice' -Kind 'voice' -Implemented $true `
        -DisplayName 'Listen - Aviation (AM)' `
        -CanHandle {
            param($signal)
            $mhz = Get-SignalFrequencyMHz -Signal $signal
            if ($null -eq $mhz) { return $false }
            return (($mhz -ge 118.0 -and $mhz -le 137.0) -or ($mhz -ge 225.0 -and $mhz -le 400.0))
        } `
        -Activate {
            param($signal)
            [pscustomobject][ordered]@{
                Kind             = 'listen'
                Mode             = 'am'
                AllowModeOverride = $false
                Frequency        = [long]$signal.FrequencyHz
                Title            = $this.DisplayName
            }
        }
}
