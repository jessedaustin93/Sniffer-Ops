# Broadcast FM: 87.5-108.0 MHz. Wideband FM, optimized for music/voice quality.
function New-BroadcastFMLens {
    New-LensObject -Name 'BroadcastFM' -Kind 'voice' -Implemented $true `
        -DisplayName 'Listen - Broadcast FM (WFM)' `
        -CanHandle {
            param($signal)
            $mhz = Get-SignalFrequencyMHz -Signal $signal
            if ($null -eq $mhz) { return $false }
            return ($mhz -ge 87.5 -and $mhz -le 108.0)
        } `
        -Activate {
            param($signal)
            [pscustomobject][ordered]@{
                Kind             = 'listen'
                Mode             = 'wbfm'
                AllowModeOverride = $false
                Frequency        = [long]$signal.FrequencyHz
                Title            = $this.DisplayName
            }
        }
}
