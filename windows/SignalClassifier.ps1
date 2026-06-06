# Reusable signal explanation helpers for the Windows companion.
# These rules score observable clues instead of claiming certainty from thin data.

function Join-NonEmptyText {
    param([object[]] $Values, [string] $Separator = "; ")

    return (($Values | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } | ForEach-Object { [string]$_ }) -join $Separator)
}

function Get-WifiBandDescription {
    param([string] $Channel)

    $channelNumber = 0
    if (-not [int]::TryParse(([string]$Channel).Trim(), [ref]$channelNumber)) {
        return "Unknown band"
    }

    if ($channelNumber -ge 1 -and $channelNumber -le 14) { return "2.4 GHz WiFi" }
    if ($channelNumber -ge 32 -and $channelNumber -le 177) { return "5 GHz WiFi" }
    if ($channelNumber -ge 1 -and $channelNumber -le 233) { return "WiFi channel $channelNumber" }
    return "Unknown band"
}

function New-SignalExplanation {
    param(
        [string] $Category,
        [string] $SpecificType,
        [string] $Confidence,
        [object[]] $Evidence,
        [string] $Meaning,
        [string] $NextStep
    )

    return [pscustomobject][ordered]@{
        Category = $Category
        SpecificType = $SpecificType
        Confidence = $Confidence
        Evidence = Join-NonEmptyText -Values $Evidence
        Meaning = $Meaning
        NextStep = $NextStep
    }
}

function Get-WifiSignalExplanation {
    param([object] $Wifi)

    $name = [string]$Wifi.Name
    $security = [string]$Wifi.Security
    $channel = [string]$Wifi.Channel
    $band = Get-WifiBandDescription -Channel $channel
    $evidence = @($band)

    $patterns = @(
        @{
            Type = "Likely Flock camera"
            Confidence = "High"
            Match = '(?i)\b(flock|flocksafety|flock\s*safety)\b'
            Meaning = "The network name contains a Flock/Flock Safety clue."
            NextStep = "Treat this as a likely Flock Safety camera or related wireless device if the signal is near a roadway or parking entrance."
        },
        @{
            Type = "Camera / doorbell WiFi"
            Confidence = "High"
            Match = '(?i)\b(cam|camera|ipcam|doorbell|baby\s*monitor|nanny|surveillance|cctv|nvr|dvr|wyze|arlo|ring|eufy|blink|nestcam|reolink|amcrest|ezviz|tapo)\b'
            Meaning = "The network name contains camera/security wording or a known camera brand."
            NextStep = "Inspect the SSID owner and look for a nearby camera, doorbell, NVR, or setup hotspot."
        },
        @{
            Type = "WiFi access point"
            Confidence = "High"
            Match = '(?i)\b(router|gateway|mesh|wifi|wi-fi|wlan|ap|eero|orbi|netgear|tp-?link|linksys|asus|ubiquiti|unifi|arris|xfinity|spectrum|verizon|fios|att|comcast)\b'
            Meaning = "The name looks like infrastructure that provides WiFi coverage."
            NextStep = "Treat this as the network source or an extender unless other clues point to a device hotspot."
        },
        @{
            Type = "TV / media WiFi"
            Confidence = "High"
            Match = '(?i)\b(tv|smart\s*tv|roku|chromecast|fire\s*tv|firetv|apple\s*tv|samsung|lg|sony|vizio|hisense|tcl|xbox|playstation|ps5|nintendo|shield)\b'
            Meaning = "The name contains a media-device or TV/vendor clue."
            NextStep = "Check nearby TVs, consoles, streaming boxes, and casting devices."
        },
        @{
            Type = "Phone / hotspot WiFi"
            Confidence = "High"
            Match = '(?i)\b(iphone|ipad|android|galaxy|pixel|hotspot|jetpack|mifi|macbook|surface|laptop)\b'
            Meaning = "The name looks like a personal device or mobile hotspot."
            NextStep = "Look for a phone, tablet, laptop, or portable hotspot broadcasting WiFi."
        },
        @{
            Type = "Smart-home WiFi"
            Confidence = "Medium"
            Match = '(?i)\b(iot|smart|bulb|hue|thermostat|plug|switch|alexa|echo|homepod|printer|kasa|tuya|shelly|sonoff)\b'
            Meaning = "The name contains smart-device wording or a common IoT brand."
            NextStep = "Check smart plugs, bulbs, speakers, printers, sensors, and setup-mode devices."
        },
        @{
            Type = "Guest or secondary network"
            Confidence = "Medium"
            Match = '(?i)\b(guest|visitor|iot|devices)\b'
            Meaning = "The SSID appears to be a separate network profile, often made by a router."
            NextStep = "Treat this as a router-created network unless the SSID also names a specific device."
        }
    )

    foreach ($rule in $patterns) {
        if ($name -match $rule.Match) {
            $evidence += "SSID keyword: $($Matches[0])"
            if ($security -match '(?i)open|none|no authentication') { $evidence += "open security" }
            return New-SignalExplanation -Category "WiFi" -SpecificType $rule.Type -Confidence $rule.Confidence -Evidence $evidence -Meaning $rule.Meaning -NextStep $rule.NextStep
        }
    }

    if ($name -eq "<hidden>") {
        $evidence += "SSID is hidden"
        return New-SignalExplanation -Category "WiFi" -SpecificType "Hidden WiFi device" -Confidence "Medium" -Evidence $evidence -Meaning "The transmitter is advertising a BSSID but hiding the network name." -NextStep "Compare signal strength while moving; hidden SSIDs are often routers, extenders, cameras, or setup networks."
    }

    if ($security -match '(?i)open|none|no authentication') {
        $evidence += "open security"
        return New-SignalExplanation -Category "WiFi" -SpecificType "Open WiFi device" -Confidence "Medium" -Evidence $evidence -Meaning "Open WiFi often means guest access, setup mode, captive portal, or an unsecured AP." -NextStep "Avoid joining unless you trust it; check whether a nearby device is in setup mode."
    }

    return New-SignalExplanation -Category "WiFi" -SpecificType "WiFi access point" -Confidence "Low" -Evidence $evidence -Meaning "Windows can see a WiFi network beacon. Without vendor or SSID clues, the safest specific class is access point/router-style transmitter." -NextStep "Use BSSID/vendor lookup, signal strength changes, or the phone app to narrow down the physical source."
}

function Get-BluetoothSignalExplanation {
    param([object] $Device)

    $name = [string]$Device.Name
    $status = [string]$Device.Status
    $evidence = @("PnP status: $status")

    $patterns = @(
        @{ Type = "Likely headphones, speaker, headset, or audio device"; Confidence = "High"; Match = '(?i)\b(headphone|headset|earbud|earbuds|speaker|sound|audio|buds|airpods|beats|jbl|bose|sony|anker|soundcore)\b'; Next = "Check nearby audio gear and paired speaker/headset lists." },
        @{ Type = "Likely phone, tablet, watch, or wearable"; Confidence = "High"; Match = '(?i)\b(phone|iphone|ipad|android|galaxy|pixel|watch|wear|fitbit|garmin)\b'; Next = "Check nearby personal devices and wearable pairing state." },
        @{ Type = "Likely keyboard, mouse, trackpad, or input device"; Confidence = "High"; Match = '(?i)\b(keyboard|mouse|trackpad|touchpad|logitech|razer|controller|gamepad|xbox|dualsense)\b'; Next = "Check nearby input devices and game controllers." },
        @{ Type = "Likely Bluetooth adapter or radio service"; Confidence = "Medium"; Match = '(?i)\b(adapter|radio|intel|realtek|qualcomm|broadcom|mediatek|bluetooth)\b'; Next = "This may be the PC Bluetooth adapter rather than an external device." },
        @{ Type = "Likely tracker, tag, beacon, or sensor"; Confidence = "Medium"; Match = '(?i)\b(tile|tag|airtag|tracker|beacon|sensor)\b'; Next = "Check for small BLE tags, sensors, or beacon devices." }
    )

    foreach ($rule in $patterns) {
        if ($name -match $rule.Match) {
            $evidence += "name keyword: $($Matches[0])"
            return New-SignalExplanation -Category "Bluetooth" -SpecificType $rule.Type -Confidence $rule.Confidence -Evidence $evidence -Meaning "Bluetooth device names usually reveal class only when the maker exposes a useful name." -NextStep $rule.Next
        }
    }

    return New-SignalExplanation -Category "Bluetooth" -SpecificType "Unclassified Bluetooth device or service" -Confidence "Low" -Evidence $evidence -Meaning "Windows listed a Bluetooth PnP item, but the name does not reveal the device class." -NextStep "Use pairing details, manufacturer info, or proximity changes to narrow it down."
}

function Get-SdrSignalExplanation {
    param([long] $Frequency)

    $mhz = $Frequency / 1000000.0
    $rules = @(
        @{ Min = 87.5; Max = 108.0; Type = "Broadcast FM radio station"; Mod = "WFM/RBDS"; Confidence = "High"; Meaning = "Commercial or public FM broadcast audio, often with RDS/RBDS station metadata."; Next = "Use the FM lens/tuner to listen and identify the station." },
        @{ Min = 108.0; Max = 118.0; Type = "Aviation navigation beacon (VOR/ILS localizer range)"; Mod = "AM/VOR/ILS"; Confidence = "Medium"; Meaning = "Aircraft navigation band; may be tones/data-like audio rather than conversation."; Next = "Use aviation lens; do not expect normal voice unless near voice channels." },
        @{ Min = 118.0; Max = 137.0; Type = "Aviation airband voice"; Mod = "AM voice"; Confidence = "High"; Meaning = "Aircraft, airport tower, approach, or ground voice traffic when active."; Next = "Use aviation AM listening and wait for intermittent transmissions." },
        @{ Min = 137.0; Max = 138.0; Type = "NOAA weather satellite downlink"; Mod = "APT/data"; Confidence = "Medium"; Meaning = "Satellite weather image/data downlinks may appear only during overhead passes."; Next = "Check satellite pass timing and use a weather-satellite decoder." },
        @{ Min = 144.0; Max = 148.0; Type = "Amateur radio 2m band"; Mod = "NFM/FM/CW/data"; Confidence = "High"; Meaning = "Ham repeaters, simplex voice, packet, APRS, or other amateur traffic."; Next = "Use narrowband FM for voice channels; look for APRS near 144.39 MHz in the US." },
        @{ Min = 150.0; Max = 162.0; Type = "VHF land mobile, business, railroad, marine, or public service"; Mod = "NFM/data"; Confidence = "Medium"; Meaning = "Shared VHF services; exact use depends on the local channel allocation."; Next = "Use narrowband FM and compare exact frequency against local allocation databases." },
        @{ Min = 162.4; Max = 162.55; Type = "NOAA Weather Radio broadcast"; Mod = "NFM weather voice"; Confidence = "High"; Meaning = "Continuous weather broadcast from NOAA transmitters in the US."; Next = "Use the NOAA weather lens/listener." },
        @{ Min = 162.0; Max = 162.4; Type = "VHF public service / NOAA-adjacent"; Mod = "NFM/data"; Confidence = "Low"; Meaning = "Near the NOAA weather allocation but outside the normal NOAA voice channels."; Next = "Do not label as NOAA unless the exact channel is 162.400-162.550 MHz; compare against local VHF allocations." },
        @{ Min = 174.0; Max = 216.0; Type = "VHF TV / broadcast auxiliary band"; Mod = "Digital TV/auxiliary"; Confidence = "Medium"; Meaning = "Legacy/digital TV or related broadcast services depending on location."; Next = "Treat as wide digital/broadcast energy, not a voice channel." },
        @{ Min = 225.0; Max = 400.0; Type = "Military aviation UHF airband"; Mod = "AM voice/data"; Confidence = "Medium"; Meaning = "Military aircraft, air-to-air, air refueling, range, and UHF aviation voice/data channels occupy this region."; Next = "Use aviation AM listening and expect intermittent traffic; exact use depends on local military/airspace activity." },
        @{ Min = 433.0; Max = 435.0; Type = "433 MHz ISM short-range device"; Mod = "OOK/FSK"; Confidence = "High"; Meaning = "Common for sensors, remotes, weather stations, car keys, and low-power IoT devices."; Next = "Look for bursty transmissions when a remote, sensor, or nearby device activates." },
        @{ Min = 420.0; Max = 450.0; Type = "Amateur radio 70cm band"; Mod = "NFM/FM/data"; Confidence = "High"; Meaning = "Ham repeaters, simplex voice, control links, or digital modes."; Next = "Use narrowband FM for voice channels and compare exact frequency to local repeater listings." },
        @{ Min = 450.0; Max = 470.0; Type = "UHF land mobile, GMRS/FRS, business, or public service"; Mod = "NFM/data"; Confidence = "Medium"; Meaning = "Walkie-talkies, business radios, repeaters, and local services share this region."; Next = "Use narrowband FM and compare exact frequency to GMRS/FRS/business allocations." },
        @{ Min = 470.0; Max = 698.0; Type = "UHF TV / broadcast band"; Mod = "Digital TV"; Confidence = "Medium"; Meaning = "Digital TV and broadcast services are common here."; Next = "Treat as wide digital energy unless the exact frequency maps to a known narrow service." },
        @{ Min = 698.0; Max = 806.0; Type = "LTE/cellular 700 MHz"; Mod = "Cellular digital"; Confidence = "Medium"; Meaning = "Carrier LTE/cellular downlink/uplink ranges may appear as wide digital signals."; Next = "Do not listen for audio; use as a cellular-band presence clue only." },
        @{ Min = 806.0; Max = 869.0; Type = "800 MHz public safety or trunked radio"; Mod = "P25/trunked/FM"; Confidence = "Medium"; Meaning = "Public safety, trunked systems, and specialized mobile radio may be present."; Next = "Use P25/trunking tools where legal and available; analog audio may be silent or digital noise." },
        @{ Min = 869.0; Max = 894.0; Type = "Cellular 850 MHz"; Mod = "Cellular digital"; Confidence = "Medium"; Meaning = "Cellular-band RF energy, usually not human-listenable audio."; Next = "Treat as band occupancy, not a decodable voice signal." },
        @{ Min = 902.0; Max = 928.0; Type = "915 MHz ISM device"; Mod = "LoRa/FSK/FHSS"; Confidence = "High"; Meaning = "LoRa, smart meters, sensors, alarms, and other unlicensed short-range devices."; Next = "Look for bursts and repeated packets; exact decoding depends on protocol." },
        @{ Min = 978.0; Max = 979.0; Type = "ADS-B UAT aircraft data"; Mod = "UAT"; Confidence = "High"; Meaning = "Aircraft position/weather data on the US 978 MHz UAT channel."; Next = "Use the ADS-B lens/map." },
        @{ Min = 1090.0; Max = 1091.0; Type = "ADS-B / Mode S aircraft transponder"; Mod = "PPM/ADS-B"; Confidence = "High"; Meaning = "Aircraft transponder position/identity messages."; Next = "Use the ADS-B lens/map." },
        @{ Min = 960.0; Max = 1215.0; Type = "Aviation DME/TACAN/navigation band"; Mod = "Pulsed aviation data"; Confidence = "Medium"; Meaning = "Aircraft navigation systems and pulsed data signals."; Next = "Expect pulses/data rather than voice." },
        @{ Min = 1215.0; Max = 1240.0; Type = "GNSS/GPS L2 region"; Mod = "Spread spectrum"; Confidence = "Medium"; Meaning = "Satellite navigation signals are very weak and spread-spectrum."; Next = "Usually not useful with a simple wideband power hit alone." },
        @{ Min = 1559.0; Max = 1610.0; Type = "GNSS/GPS L1 / GLONASS region"; Mod = "Spread spectrum"; Confidence = "Medium"; Meaning = "Satellite navigation signals; visible only with suitable antenna/gain/decoder."; Next = "Use GNSS-specific tooling if you are intentionally measuring this band." },
        @{ Min = 1710.0; Max = 1990.0; Type = "AWS/PCS cellular band"; Mod = "Cellular digital"; Confidence = "Medium"; Meaning = "Cellular uplink/downlink energy depending on exact frequency."; Next = "Use as a cellular presence clue; not an audio target." },
        @{ Min = 2400.0; Max = 2500.0; Type = "2.4 GHz WiFi, Bluetooth, or ISM device"; Mod = "OFDM/FHSS/digital"; Confidence = "Medium"; Meaning = "Very crowded unlicensed band used by WiFi, Bluetooth, ZigBee, cameras, controllers, and IoT."; Next = "Correlate with WiFi/Bluetooth lists and movement; SDR alone cannot separate all device types here." },
        @{ Min = 5150.0; Max = 5850.0; Type = "5 GHz WiFi or unlicensed data"; Mod = "OFDM/digital"; Confidence = "Medium"; Meaning = "Common for WiFi APs, mesh nodes, cameras, and high-rate unlicensed devices."; Next = "Correlate with WiFi SSIDs and channel details." }
    )

    foreach ($rule in $rules) {
        if ($mhz -ge $rule.Min -and $mhz -le $rule.Max) {
            $result = New-SignalExplanation -Category "SDR/RF" -SpecificType $rule.Type -Confidence $rule.Confidence -Evidence @("{0:N3} MHz band plan match" -f $mhz) -Meaning $rule.Meaning -NextStep $rule.Next
            $result | Add-Member -NotePropertyName Modulation -NotePropertyValue $rule.Mod
            return $result
        }
    }

    $fallback = New-SignalExplanation -Category "SDR/RF" -SpecificType "Unclassified RF signal" -Confidence "Low" -Evidence @("{0:N3} MHz has no local rule match" -f $mhz) -Meaning "The frequency is outside the companion's known band-plan rules." -NextStep "Run a wider/deeper scan, compare exact frequency to local band plans, and add a rule if this repeats."
    $fallback | Add-Member -NotePropertyName Modulation -NotePropertyValue "Unknown"
    return $fallback
}
