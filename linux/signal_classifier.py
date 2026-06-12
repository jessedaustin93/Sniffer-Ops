"""
Signal classifier — ported from SignalClassifier.ps1.
Returns structured explanations for WiFi, Bluetooth, and SDR/RF signals.
"""

import re
from dataclasses import dataclass, field


@dataclass
class SignalExplanation:
    category: str
    specific_type: str
    confidence: str          # High / Medium / Low
    evidence: str
    meaning: str
    next_step: str
    modulation: str = ""


def _join(*parts) -> str:
    return "; ".join(p for p in parts if p and str(p).strip())


def classify_wifi(signal: dict) -> SignalExplanation:
    name = str(signal.get("name") or signal.get("ssid") or "")
    security = str(signal.get("security") or signal.get("encryption") or "")
    channel = str(signal.get("channel") or "")

    # band from channel
    try:
        ch = int(channel)
        if 1 <= ch <= 14:
            band = "2.4 GHz WiFi"
        elif 32 <= ch <= 177:
            band = "5 GHz WiFi"
        else:
            band = f"WiFi channel {ch}"
    except ValueError:
        band = "Unknown band"

    evidence_parts = [band]

    rules = [
        {
            "type": "Likely Flock camera",
            "confidence": "High",
            "pattern": r"(?i)\b(flock|flocksafety|flock\s*safety)\b",
            "meaning": "Network name contains a Flock/Flock Safety identifier.",
            "next": "Treat as a likely Flock Safety camera or related device near a roadway or parking entrance.",
        },
        {
            "type": "Camera / doorbell WiFi",
            "confidence": "High",
            "pattern": r"(?i)\b(cam|camera|ipcam|doorbell|baby\s*monitor|nanny|surveillance|cctv|nvr|dvr|wyze|arlo|ring|eufy|blink|nestcam|reolink|amcrest|ezviz|tapo)\b",
            "meaning": "Network name contains camera/security wording or a known camera brand.",
            "next": "Inspect SSID owner and look for a nearby camera, doorbell, NVR, or setup hotspot.",
        },
        {
            "type": "WiFi access point",
            "confidence": "High",
            "pattern": r"(?i)\b(router|gateway|mesh|wifi|wi-fi|wlan|ap|eero|orbi|netgear|tp-?link|linksys|asus|ubiquiti|unifi|arris|xfinity|spectrum|verizon|fios|att|comcast)\b",
            "meaning": "Name looks like infrastructure providing WiFi coverage.",
            "next": "Treat as network source or extender unless other clues point to a device hotspot.",
        },
        {
            "type": "TV / media WiFi",
            "confidence": "High",
            "pattern": r"(?i)\b(tv|smart\s*tv|roku|chromecast|fire\s*tv|firetv|apple\s*tv|samsung|lg|sony|vizio|hisense|tcl|xbox|playstation|ps5|nintendo|shield)\b",
            "meaning": "Name contains a media-device or TV/vendor clue.",
            "next": "Check nearby TVs, consoles, streaming boxes, and casting devices.",
        },
        {
            "type": "Phone / hotspot WiFi",
            "confidence": "High",
            "pattern": r"(?i)\b(iphone|ipad|android|galaxy|pixel|hotspot|jetpack|mifi|macbook|surface|laptop)\b",
            "meaning": "Name looks like a personal device or mobile hotspot.",
            "next": "Look for a phone, tablet, laptop, or portable hotspot.",
        },
        {
            "type": "Smart-home WiFi",
            "confidence": "Medium",
            "pattern": r"(?i)\b(iot|smart|bulb|hue|thermostat|plug|switch|alexa|echo|homepod|printer|kasa|tuya|shelly|sonoff)\b",
            "meaning": "Name contains smart-device wording or a common IoT brand.",
            "next": "Check smart plugs, bulbs, speakers, printers, sensors, and setup-mode devices.",
        },
        {
            "type": "Guest or secondary network",
            "confidence": "Medium",
            "pattern": r"(?i)\b(guest|visitor|iot|devices)\b",
            "meaning": "SSID appears to be a separate network profile, often router-created.",
            "next": "Treat as a router-created network unless the SSID also names a specific device.",
        },
    ]

    for rule in rules:
        m = re.search(rule["pattern"], name)
        if m:
            ev = _join(band, f"SSID keyword: {m.group(0)}")
            if re.search(r"(?i)open|none|no authentication", security):
                ev = _join(ev, "open security")
            return SignalExplanation(
                category="WiFi",
                specific_type=rule["type"],
                confidence=rule["confidence"],
                evidence=ev,
                meaning=rule["meaning"],
                next_step=rule["next"],
            )

    if name == "<hidden>" or not name:
        return SignalExplanation(
            category="WiFi", specific_type="Hidden WiFi device", confidence="Medium",
            evidence=_join(band, "SSID is hidden"),
            meaning="Transmitter is advertising a BSSID but hiding the network name.",
            next_step="Compare signal strength while moving; hidden SSIDs are often routers, extenders, cameras, or setup networks.",
        )

    if re.search(r"(?i)open|none|no authentication", security):
        return SignalExplanation(
            category="WiFi", specific_type="Open WiFi device", confidence="Medium",
            evidence=_join(band, "open security"),
            meaning="Open WiFi often means guest access, setup mode, captive portal, or an unsecured AP.",
            next_step="Avoid joining unless trusted; check whether a nearby device is in setup mode.",
        )

    return SignalExplanation(
        category="WiFi", specific_type="WiFi access point", confidence="Low",
        evidence=band,
        meaning="A WiFi network beacon is visible. Without vendor or SSID clues the safest specific class is access point.",
        next_step="Use BSSID/vendor lookup, signal strength changes, or the phone app to narrow down the physical source.",
    )


def classify_bluetooth(device: dict) -> SignalExplanation:
    name = str(device.get("name") or "")
    status = str(device.get("status") or device.get("device_class") or "")
    evidence = f"status: {status}" if status else "no status"

    rules = [
        {
            "type": "Likely headphones, speaker, headset, or audio device",
            "confidence": "High",
            "pattern": r"(?i)\b(headphone|headset|earbud|earbuds|speaker|sound|audio|buds|airpods|beats|jbl|bose|sony|anker|soundcore)\b",
            "next": "Check nearby audio gear and paired speaker/headset lists.",
        },
        {
            "type": "Likely phone, tablet, watch, or wearable",
            "confidence": "High",
            "pattern": r"(?i)\b(phone|iphone|ipad|android|galaxy|pixel|watch|wear|fitbit|garmin)\b",
            "next": "Check nearby personal devices and wearable pairing state.",
        },
        {
            "type": "Likely keyboard, mouse, trackpad, or input device",
            "confidence": "High",
            "pattern": r"(?i)\b(keyboard|mouse|trackpad|touchpad|logitech|razer|controller|gamepad|xbox|dualsense)\b",
            "next": "Check nearby input devices and game controllers.",
        },
        {
            "type": "Likely Bluetooth adapter or radio service",
            "confidence": "Medium",
            "pattern": r"(?i)\b(adapter|radio|intel|realtek|qualcomm|broadcom|mediatek|bluetooth)\b",
            "next": "This may be the local Bluetooth adapter rather than an external device.",
        },
        {
            "type": "Likely tracker, tag, beacon, or sensor",
            "confidence": "Medium",
            "pattern": r"(?i)\b(tile|tag|airtag|tracker|beacon|sensor)\b",
            "next": "Check for small BLE tags, sensors, or beacon devices.",
        },
    ]

    for rule in rules:
        m = re.search(rule["pattern"], name)
        if m:
            return SignalExplanation(
                category="Bluetooth",
                specific_type=rule["type"],
                confidence=rule["confidence"],
                evidence=_join(evidence, f"name keyword: {m.group(0)}"),
                meaning="Bluetooth device names usually reveal class only when the maker exposes a useful name.",
                next_step=rule["next"],
            )

    return SignalExplanation(
        category="Bluetooth", specific_type="Unclassified Bluetooth device or service",
        confidence="Low", evidence=evidence,
        meaning="A Bluetooth device is visible but the name does not reveal the device class.",
        next_step="Use pairing details, manufacturer info, or proximity changes to narrow it down.",
    )


_SDR_RULES = [
    (87.5, 108.0, "Broadcast FM radio station", "WFM/RBDS", "High",
     "Commercial or public FM broadcast audio, often with RDS/RBDS station metadata.",
     "Use the FM lens/tuner to listen and identify the station."),
    (108.0, 118.0, "Aviation navigation beacon (VOR/ILS)", "AM/VOR/ILS", "Medium",
     "Aircraft navigation band; may be tones/data-like audio rather than voice.",
     "Use aviation lens; do not expect normal voice unless near voice channels."),
    (118.0, 137.0, "Aviation airband voice", "AM voice", "High",
     "Aircraft, airport tower, approach, or ground voice traffic when active.",
     "Use aviation AM listening and wait for intermittent transmissions."),
    (137.0, 138.0, "NOAA weather satellite downlink", "APT/data", "Medium",
     "Satellite weather image/data downlinks appear only during overhead passes.",
     "Check satellite pass timing and use a weather-satellite decoder."),
    (144.0, 148.0, "Amateur radio 2m band", "NFM/FM/CW/data", "High",
     "Ham repeaters, simplex voice, packet, APRS, or other amateur traffic.",
     "Use narrowband FM for voice channels; look for APRS near 144.39 MHz in the US."),
    (148.0, 162.0, "VHF land mobile / business / railroad / marine / public service",
     "NFM/data", "Medium",
     "Shared VHF services; exact use depends on local channel allocation.",
     "Use narrowband FM and compare exact frequency against local allocation databases."),
    (162.4, 162.55, "NOAA Weather Radio broadcast", "NFM weather voice", "High",
     "Continuous weather broadcast from NOAA transmitters in the US.",
     "Use the NOAA weather lens/listener."),
    (162.0, 162.4, "VHF public service / NOAA-adjacent", "NFM/data", "Low",
     "Near the NOAA weather allocation but outside the normal NOAA voice channels.",
     "Compare exact channel to 162.400-162.550 MHz before labeling as NOAA."),
    (162.55, 174.0, "VHF land mobile / business / railroad / marine / public service",
     "NFM/data", "Medium",
     "Shared VHF services; exact use depends on local channel allocation.",
     "Use narrowband FM and compare exact frequency against local allocation databases."),
    (174.0, 216.0, "VHF TV / broadcast auxiliary band", "Digital TV/auxiliary", "Medium",
     "Legacy/digital TV or related broadcast services depending on location.",
     "Treat as wide digital/broadcast energy, not a voice channel."),
    (225.0, 400.0, "Military aviation UHF airband", "AM voice/data", "Medium",
     "Military aircraft, air-to-air, air refueling, range, and UHF aviation channels.",
     "Use aviation AM listening and expect intermittent traffic."),
    (433.0, 435.0, "433 MHz ISM short-range device", "OOK/FSK", "High",
     "Common for sensors, remotes, weather stations, car keys, and low-power IoT devices.",
     "Look for bursty transmissions when a remote, sensor, or nearby device activates."),
    (420.0, 450.0, "Amateur radio 70cm band", "NFM/FM/data", "High",
     "Ham repeaters, simplex voice, control links, or digital modes.",
     "Use narrowband FM for voice channels and compare exact frequency to local repeater listings."),
    (450.0, 470.0, "UHF land mobile / GMRS/FRS / business / public service",
     "NFM/data", "Medium",
     "Walkie-talkies, business radios, repeaters, and local services share this region.",
     "Use narrowband FM and compare exact frequency to GMRS/FRS/business allocations."),
    (470.0, 698.0, "UHF TV / broadcast band", "Digital TV", "Medium",
     "Digital TV and broadcast services are common here.",
     "Treat as wide digital energy unless the exact frequency maps to a known narrow service."),
    (698.0, 806.0, "LTE/cellular 700 MHz", "Cellular digital", "Medium",
     "Carrier LTE/cellular downlink/uplink ranges may appear as wide digital signals.",
     "Do not listen for audio; use as a cellular-band presence clue only."),
    (806.0, 869.0, "800 MHz public safety or trunked radio", "P25/trunked/FM", "Medium",
     "Public safety, trunked systems, and specialized mobile radio may be present.",
     "Use P25/trunking tools where legal and available."),
    (869.0, 894.0, "Cellular 850 MHz", "Cellular digital", "Medium",
     "Cellular-band RF energy, usually not human-listenable audio.",
     "Treat as band occupancy, not a decodable voice signal."),
    (902.0, 928.0, "915 MHz ISM device", "LoRa/FSK/FHSS", "High",
     "LoRa, smart meters, sensors, alarms, and other unlicensed short-range devices.",
     "Look for bursts and repeated packets; exact decoding depends on protocol."),
    (978.0, 979.0, "ADS-B UAT aircraft data", "UAT", "High",
     "Aircraft position/weather data on the US 978 MHz UAT channel.",
     "Use the ADS-B lens/map."),
    (1090.0, 1091.0, "ADS-B / Mode S aircraft transponder", "PPM/ADS-B", "High",
     "Aircraft transponder position/identity messages.",
     "Use the ADS-B lens/map."),
    (960.0, 1215.0, "Aviation DME/TACAN/navigation band", "Pulsed aviation data", "Medium",
     "Aircraft navigation systems and pulsed data signals.",
     "Expect pulses/data rather than voice."),
    (1215.0, 1240.0, "GNSS/GPS L2 region", "Spread spectrum", "Medium",
     "Satellite navigation signals are very weak and spread-spectrum.",
     "Usually not useful with a simple wideband power hit alone."),
    (1559.0, 1610.0, "GNSS/GPS L1 / GLONASS region", "Spread spectrum", "Medium",
     "Satellite navigation signals; visible only with suitable antenna/gain/decoder.",
     "Use GNSS-specific tooling if intentionally measuring this band."),
    (1710.0, 1990.0, "AWS/PCS cellular band", "Cellular digital", "Medium",
     "Cellular uplink/downlink energy depending on exact frequency.",
     "Use as a cellular presence clue; not an audio target."),
    (2400.0, 2500.0, "2.4 GHz WiFi, Bluetooth, or ISM device", "OFDM/FHSS/digital", "Medium",
     "Very crowded unlicensed band used by WiFi, Bluetooth, ZigBee, cameras, controllers, and IoT.",
     "Correlate with WiFi/Bluetooth lists and movement."),
    (5150.0, 5850.0, "5 GHz WiFi or unlicensed data", "OFDM/digital", "Medium",
     "Common for WiFi APs, mesh nodes, cameras, and high-rate unlicensed devices.",
     "Correlate with WiFi SSIDs and channel details."),
]


def classify_alert(name: str, type_: str, specific_type: str,
                   threat_level: str, notes: str = "") -> dict:
    """
    Returns {"level": "HIGH"/"MEDIUM"/"LOW"/"NONE", "evidence": ...,
             "meaning": ..., "next_step": ..., "notes": ...}

    Mirrors Get-SignalAlertClassification from SnifferOps.Windows.ps1.
    Movement clue on a surveillance-class signal upgrades it to HIGH.
    """
    text = " ".join(filter(None, [name, type_, specific_type, threat_level, notes])).lower()
    threat = threat_level.strip().upper()

    high_pat = (r'(imsi|stingray|fake\s*sim|fake\s*cell|rogue\s*cell|'
                r'cell\s*site\s*simulator|evil\s*twin|wifi\s*pineapple|pineapple|'
                r'deauther|pwnagotchi|marauder|flipper|badusb|skimmer|'
                r'tap\s*to\s*pay|payment|nfc\s*intercept|credential|password|'
                r'phish|sniffer|data[- ]?capture|hacking)')
    # "camera" removed — too many false positives on SSID names
    medium_pat = (r'(flock|flock\s*safety|alpr|lpr|license\s*plate|plate\s*reader|'
                  r'traffic\s*reader|traffic\s*camera|speed\s*camera|red\s*light|'
                  r'surveillance|cctv|doorbell|verkada|avigilon|hikvision|dahua|'
                  r'axis|vigilant|genetec|motorola)')
    low_pat = (r'(unknown\s*ble|beacon|tracker|airtag|tile|hidden\s*wifi|'
               r'open\s*wifi|open\s*security|unsecured|rogue|spoof|jam|burst|'
               r'unclassified\s*rf|unexpected|odd|weird)')
    move_pat = (r'(new\s+scan\s+location|location_changed|also\s+seen\s+by|'
                r'same\s+reader|following|followed|moved\s+with)')

    high_m   = re.search(high_pat,   text)
    medium_m = re.search(medium_pat, text)
    low_m    = re.search(low_pat,    text)
    move_m   = re.search(move_pat,   text)

    if threat == "ALERT" or high_m:
        return {
            "level": "HIGH",
            "evidence": (f"High-risk keyword: {high_m.group(0)}"
                         if high_m else "Threat level is ALERT"),
            "meaning": ("Signal name, type, or classification matched a known adversarial "
                        "or surveillance tool."),
            "next_step": ("Investigate immediately; this matches patterns associated with "
                          "tracking, interception, or network attack tools."),
            "notes": "High alert: treat as confirmed threat until ruled out.",
        }
    if threat == "SUSPICIOUS" or medium_m:
        if move_m:
            return {
                "level": "HIGH",
                "evidence": f"Surveillance/traffic class with movement clue: {move_m.group(0)}",
                "meaning": ("Possible surveillance or reader system seen across "
                             "scan locations or nodes."),
                "next_step": ("Correlate the timeline and map; repeated movement "
                              "with your route deserves immediate attention."),
                "notes": ("High alert: surveillance-class signal appears to move "
                          "or repeat across scan locations."),
            }
        return {
            "level": "MEDIUM",
            "evidence": (f"Surveillance/traffic keyword: {medium_m.group(0)}"
                         if medium_m else "Threat level is SUSPICIOUS"),
            "meaning": ("Signal matches patterns associated with license plate readers, "
                        "ALPR cameras, or surveillance infrastructure."),
            "next_step": ("Note location and whether it moves; a stationary reader "
                          "is expected, a mobile one is not."),
            "notes": "",
        }
    if low_m:
        return {
            "level": "LOW",
            "evidence": f"Attention keyword: {low_m.group(0)}",
            "meaning": ("Signal has a low-priority attention flag — "
                        "tracker, beacon, or unclassified RF."),
            "next_step": ("Monitor for changes; LOW alone is informational "
                          "unless combined with other clues."),
            "notes": "",
        }
    return {"level": "NONE", "evidence": "", "meaning": "", "next_step": "", "notes": ""}


def classify_sdr(frequency_hz: int | float) -> SignalExplanation:
    mhz = frequency_hz / 1_000_000.0
    for lo, hi, sig_type, mod, conf, meaning, nxt in _SDR_RULES:
        if lo <= mhz <= hi:
            return SignalExplanation(
                category="SDR/RF", specific_type=sig_type, confidence=conf,
                evidence=f"{mhz:.3f} MHz band plan match",
                meaning=meaning, next_step=nxt, modulation=mod,
            )
    return SignalExplanation(
        category="SDR/RF", specific_type="Unclassified RF signal", confidence="Low",
        evidence=f"{mhz:.3f} MHz has no local rule match",
        meaning="The frequency is outside the companion's known band-plan rules.",
        next_step="Run a wider/deeper scan, compare exact frequency to local band plans.",
        modulation="Unknown",
    )
