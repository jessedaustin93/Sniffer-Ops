# Analog voice fallback. Reproduces the original "listen" behavior: NFM/WFM/AM
# demod with a manual mode override. As a FALLBACK it yields to the specialized
# voice lenses (Broadcast FM / Aviation / NOAA) and to known digital-only bands,
# so those open their dedicated lens directly instead of a chooser.
function New-AnalogVoiceLens {
    New-LensObject -Name 'AnalogVoice' -Kind 'voice' -Implemented $true `
        -DisplayName 'Listen - Voice (NFM/WFM/AM)' `
        -CanHandle {
            param($signal)
            $mhz = Get-SignalFrequencyMHz -Signal $signal
            if ($null -eq $mhz) { return $false }

            # Plausible analog voice tuning range for the RTL-SDR.
            if ($mhz -lt 24.0 -or $mhz -gt 1000.0) { return $false }

            # Bands owned by a specialized voice lens (let those win).
            $specialized = @(
                @(87.5, 108.0),    # Broadcast FM
                @(118.0, 137.0),   # Aviation civil AM
                @(225.0, 400.0),   # Aviation military AM
                @(162.400, 162.550) # NOAA Weather Radio
            )
            # Known digital-only bands: no useful analog audio here.
            $digitalOnly = @(
                @(977.5, 978.5),   # ADS-B UAT
                @(1089.5, 1090.5), # ADS-B 1090
                @(851.0, 869.0),   # P25 / 800 MHz trunked
                @(433.05, 434.79), # ISM 433 (OOK/FSK telemetry)
                @(902.0, 928.0)    # ISM 915 (LoRa/ZigBee)
            )
            foreach ($band in ($specialized + $digitalOnly)) {
                if ($mhz -ge $band[0] -and $mhz -le $band[1]) { return $false }
            }
            return $true
        } `
        -Activate {
            param($signal)
            $mhz = Get-SignalFrequencyMHz -Signal $signal
            # Auto-pick a sensible default mode; user can override in the UI.
            $mode = if ($null -ne $mhz -and $mhz -ge 108.0 -and $mhz -le 118.0) { 'am' } else { 'nfm' }
            [pscustomobject][ordered]@{
                Kind             = 'listen'
                Mode             = $mode
                AllowModeOverride = $true
                Frequency        = [long]$signal.FrequencyHz
                Title            = $this.DisplayName
            }
        }
}
