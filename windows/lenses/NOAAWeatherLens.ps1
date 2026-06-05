# NOAA Weather Radio: NFM, 162.400-162.550 MHz. Preset band only.
function New-NOAAWeatherLens {
    New-LensObject -Name 'NOAAWeather' -Kind 'voice' -Implemented $true `
        -DisplayName 'Listen - NOAA Weather (NFM)' `
        -CanHandle {
            param($signal)
            $mhz = Get-SignalFrequencyMHz -Signal $signal
            if ($null -eq $mhz) { return $false }
            return ($mhz -ge 162.400 -and $mhz -le 162.550)
        } `
        -Activate {
            param($signal)
            [pscustomobject][ordered]@{
                Kind             = 'listen'
                Mode             = 'nfm'
                AllowModeOverride = $false
                Frequency        = [long]$signal.FrequencyHz
                Title            = $this.DisplayName
            }
        }
}
