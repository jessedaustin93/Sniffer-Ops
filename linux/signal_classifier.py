"""
Signal classifier — ported from SignalClassifier.ps1.
Returns structured explanations for WiFi, Bluetooth, and SDR/RF signals.
"""

import re
from dataclasses import dataclass, field

import signal_signatures


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
    signature = signal_signatures.classify_signal_signature(signal)
    if signature.matched and signature.family in ("attack", "drone", "surveillance", "camera", "network-camera"):
        return SignalExplanation(
            category="WiFi",
            specific_type=signature.label,
            confidence=signature.confidence,
            evidence=_join(band, signature.evidence_text()),
            meaning="WiFi metadata matched a passive attack, drone, camera, ALPR, or surveillance-device signature.",
            next_step="Treat high-alert signatures as hostile until ruled out; correlate location, repeated sightings, and signal-strength changes before calling identity confirmed.",
        )

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
    signature = signal_signatures.classify_signal_signature(device)
    if signature.matched:
        return SignalExplanation(
            category="Bluetooth",
            specific_type=signature.label,
            confidence=signature.confidence,
            evidence=_join(evidence, signature.evidence_text()),
            meaning="Bluetooth metadata matched a passive tracker, drone, camera, or surveillance-device signature.",
            next_step="Use repeated sightings and RSSI changes to localize; Bluetooth names alone are not proof of ownership or intent.",
        )

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
    (2400.0, 2483.5, "2.4 GHz WiFi/Bluetooth/ISM or consumer-drone control/video candidate",
     "OFDM/FHSS/digital", "Medium",
     "Very crowded unlicensed band used by WiFi, Bluetooth, ZigBee, cameras, IoT, and many consumer drone control/video links including Tello-class WiFi drones.",
     "Do not call this a drone from SDR power alone; correlate with DJI/Tello/Remote ID WiFi/BLE metadata, motion, and repeated peaks."),
    (2483.5, 2500.0, "2.4 GHz upper ISM-adjacent data", "OFDM/FHSS/digital", "Low",
     "Upper edge of the 2.4 GHz region; wide power alone is only a band-occupancy clue.",
     "Correlate with WiFi/Bluetooth lists before assigning a device class."),
    (3300.0, 3500.0, "3.4 GHz CBRS / private LTE / 5G-adjacent data", "Cellular/OFDM", "Medium",
     "Private LTE, CBRS, and nearby 5G-style systems can show as wide digital energy.",
     "Correlate with cellular/router devices and local infrastructure; SDR power alone cannot identify the operator."),
    (3550.0, 3700.0, "CBRS private LTE / fixed wireless", "Cellular/OFDM", "Medium",
     "Common for private LTE, fixed wireless, and enterprise/municipal data links.",
     "Correlate with cameras, gateways, and outdoor antennas if this repeats at one location."),
    (5150.0, 5250.0, "5.1 GHz WiFi/unlicensed or DJI RC 2 control/video candidate",
     "OFDM/digital", "Medium",
     "This overlaps WiFi UNII-1 and DJI RC 2 5.1 GHz operating ranges where allowed.",
     "Treat as a candidate only; do not call this a drone from SDR power alone; correlate with DJI controller/aircraft WiFi/BLE metadata and movement."),
    (5250.0, 5725.0, "5 GHz WiFi or unlicensed data", "OFDM/digital", "Medium",
     "Common for WiFi APs, mesh nodes, cameras, and high-rate unlicensed devices.",
     "Correlate with WiFi SSIDs and channel details."),
    (5725.0, 5850.0, "5.8 GHz WiFi/unlicensed or DJI/consumer-drone control/video candidate",
     "OFDM/digital", "Medium",
     "This overlaps WiFi UNII-3/ISM and common DJI/consumer-drone 5.8 GHz operating ranges.",
     "Do not call this a drone from SDR power alone; correlate with DJI/Tello/Remote ID WiFi/BLE metadata, movement, and repeated peaks."),
    (5850.0, 5925.0, "5.9 GHz ITS / C-V2X / DSRC or upper unlicensed data", "OFDM/data", "Low",
     "Vehicle-to-infrastructure, transportation, or upper unlicensed data systems may appear here.",
     "Treat as a location clue and compare against traffic infrastructure before labeling it."),
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
    if threat == "SAFE":
        return {
            "level": "NONE",
            "evidence": "Threat level is SAFE",
            "meaning": "Signal is locally trusted and should not trigger hostile-signal alerts.",
            "next_step": "",
            "notes": "",
        }

    high_pat = (r'(imsi|stingray|fake\s*sim|fake\s*cell|rogue\s*cell|'
                r'cell\s*site\s*simulator|evil\s*twin|wifi\s*pineapple|pineapple|'
                r'deauth|deauthentication|disassociation|deauther|'
                r'pwnagotchi|marauder|flipper|badusb|skimmer|'
                r'tap\s*to\s*pay|payment|nfc\s*intercept|credential|password|'
                r'phish|evil\s*portal|credential\s*portal|sniffer|data[- ]?capture|'
                r'hacking|jammer|jamming|interference\s*attack|'
                r'flock|flock\s*safety|alpr|lpr|license\s*plate|plate\s*reader|'
                  r'traffic\s*reader|traffic\s*camera|speed\s*camera|red\s*light|'
                  r'surveillance|cctv|doorbell|verkada|avigilon|hikvision|dahua|'
                  r'axis|vigilant|genetec|motorola|fusus|briefcam|openpath)')
    medium_pat = (r'(drone|uav|uas|quadcopter|remote[- ]?id|dji|tello|ryze|'
                  r'mavic|avata|phantom|inspire|autel|parrot|skydio|'
                  r'camera\s*service|rtsp|onvif|open\s*port|hidden\s*wifi|'
                  r'open\s*wifi|open\s*security|unsecured|rogue|spoof|unexpected)')
    low_pat = (r'(unknown\s*ble|beacon|tracker|airtag|tile|hidden\s*wifi|'
               r'burst|unclassified\s*rf|odd|weird)')
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
                        "tool or hostile surveillance class."),
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
            "evidence": (f"Attention keyword: {medium_m.group(0)}"
                         if medium_m else "Threat level is SUSPICIOUS"),
            "meaning": ("Signal has a warning condition such as an exposed service, "
                        "open network, or spoofing clue."),
            "next_step": ("Correlate with location, ownership, and repeated sightings "
                          "before escalating."),
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
