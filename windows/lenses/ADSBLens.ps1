# ADS-B aircraft positions. Real decoder: rtl_adsb captures 1090 MHz Mode S,
# frames are decoded (ICAO/callsign/altitude/CPR position) and plotted on a map.
# Note: 978 MHz UAT is in range for routing, but rtl_adsb only demodulates 1090;
# a UAT-band tap still runs the same capture (which will simply find no frames).
function New-ADSBLens {
    New-LensObject -Name 'ADSB' -Kind 'data' -Implemented $true `
        -DisplayName 'ADS-B Map' `
        -CanHandle {
            param($signal)
            $mhz = Get-SignalFrequencyMHz -Signal $signal
            if ($null -eq $mhz) { return $false }
            return (($mhz -ge 1089.5 -and $mhz -le 1090.5) -or ($mhz -ge 977.5 -and $mhz -le 978.5))
        } `
        -Activate {
            param($signal)
            [pscustomobject][ordered]@{
                Kind  = 'adsb'
                Title = 'ADS-B Aircraft Map'
            }
        }
}
