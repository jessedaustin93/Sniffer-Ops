"""
Passive device-signature guesses forEthrox Detect.

These rules do not prove device identity. They turn observed metadata
(SSID/name/address/vendor/notes) into explicit evidence that the UI and alert
classifier can surface and tune over time.
"""

from dataclasses import dataclass, field
import re


@dataclass(frozen=True)
class SignatureGuess:
    family: str
    label: str
    confidence: str
    evidence: tuple[str, ...] = field(default_factory=tuple)
    alert_keyword: str = ""
    alert_label: str = ""

    @property
    def matched(self) -> bool:
        return bool(self.label)

    def evidence_text(self) -> str:
        return "; ".join(self.evidence)


_FLOCK_TERMS = (
    r"\bflock\b",
    r"\bflock\s*safety\b",
    r"\bflocksafety\b",
)

_ALPR_TERMS = (
    r"\balpr\b",
    r"\blpr\b",
    r"\blicen[cs]e[-_\s]*plate\b",
    r"\bplate[-_\s]*reader\b",
    r"\btraffic[-_\s]*reader\b",
    r"\bvehicle[-_\s]*reader\b",
    r"\bhotlist\b",
)

_SURVEILLANCE_PLATFORM_TERMS = (
    r"\baxon\b",
    r"\bbriefcam\b",
    r"\bfusus\b",
    r"\bopenpath\b",
    r"\bavigilon\s*alta\b",
    r"\bvigilant\s*solutions\b",
    r"\blearn\b",
    r"\bgenetec\s*auto[vV]u\b",
)

_SURVEILLANCE_CAMERA_TERMS = (
    r"\bcam\b",
    r"\bcamera\b",
    r"\bipcam\b",
    r"\bcctv\b",
    r"\bnvr\b",
    r"\bdvr\b",
    r"\bsurveillance\b",
    r"\bsecurity[-_\s]*cam",
    r"\bdoorbell\b",
    r"\bred[-_\s]*light\b",
    r"\bspeed[-_\s]*camera\b",
    r"\btraffic[-_\s]*camera\b",
)

_CAMERA_VENDOR_TERMS = (
    r"\baxis\b",
    r"\bavigilon\b",
    r"\bverkada\b",
    r"\bhikvision\b",
    r"\bdahua\b",
    r"\bhanwha\b",
    r"\bwisenet\b",
    r"\bubiquiti\b",
    r"\bunifi\s*protect\b",
    r"\breolink\b",
    r"\bamcrest\b",
    r"\bwyze\b",
    r"\barlo\b",
    r"\bring\b",
    r"\beufy\b",
    r"\bblink\b",
    r"\bnest\s*cam\b",
    r"\btapo\b",
    r"\bvivotek\b",
    r"\bgenetec\b",
    r"\bvigilant\b",
    r"\bmotorola\s*solutions\b",
)

_TRACKER_TERMS = (
    r"\bairtag\b",
    r"\btile\b",
    r"\btracker\b",
    r"\btag\b",
    r"\bbeacon\b",
    r"\bsmarttag\b",
    r"\bchipolo\b",
)

_NETWORK_EXPOSURE_TERMS = (
    r"\brtsp\b",
    r"\bonvif\b",
    r"\bhttp\s*80\b",
    r"\bhttps\s*443\b",
    r"\b554\b",
    r"\b8080\b",
    r"\bopen\s*port\b",
    r"\bcamera\s*port\b",
)

_DEAUTH_TERMS = (
    r"\bdeauth\b",
    r"\bdeauthentication\b",
    r"\bdisassociation\b",
    r"\bdeauther\b",
)

_JAMMING_TERMS = (
    r"\bjam\b",
    r"\bjamming\b",
    r"\bnoise\s*floor\b",
    r"\binterference\s*attack\b",
)

_EVIL_PORTAL_TERMS = (
    r"\bevil[-_\s]*portal\b",
    r"\bevil[-_\s]*twin\b",
    r"\bcaptive[-_\s]*portal\b",
    r"\bcredential[-_\s]*portal\b",
    r"\bphishing[-_\s]*portal\b",
    r"\bwifi\s*pineapple\b",
    r"\bpineapple\b",
)

_ATTACK_TOOL_TERMS = (
    r"\bpwnagotchi\b",
    r"\bmarauder\b",
    r"\bflipper\b",
    r"\bbadusb\b",
)

_DRONE_VENDOR_TERMS = (
    r"\bdji\b",
    r"\bryze\b",
    r"\btello\b",
    r"\btello[-_\s]*edu\b",
    r"\bmavic\b",
    r"\bmini\s*[234]?\b",
    r"\bair\s*[23]?\b",
    r"\bavata\b",
    r"\bphantom\b",
    r"\binspire\b",
    r"\bspark\b",
    r"\bautel\b",
    r"\bevo\s*(lite|nano|max)?\b",
    r"\bparrot\b",
    r"\banafi\b",
    r"\bskydio\b",
    r"\byuneec\b",
)

_DRONE_GENERIC_TERMS = (
    r"\bdrone\b",
    r"\buav\b",
    r"\buas\b",
    r"\bquadcopter\b",
    r"\bfpv\b",
    r"\bremote[-_\s]*id\b",
    r"\bocusync\b",
    r"\bo[234]\s*(video|transmission)?\b",
    r"\bdji[-_\s]*rc\b",
    r"\brc[-_\s]*2\b",
)


def _text(signal: dict) -> str:
    parts = [
        signal.get("name"),
        signal.get("ssid"),
        signal.get("address"),
        signal.get("manufacturer"),
        signal.get("deviceClass"),
        signal.get("device_class"),
        signal.get("security"),
        signal.get("notes"),
    ]
    return " ".join(str(p) for p in parts if p is not None).lower()


def _find_any(patterns: tuple[str, ...], text: str) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(0)
    return ""


def classify_signal_signature(signal: dict) -> SignatureGuess:
    """
    Return the strongest passive signature guess for a Wi-Fi/BLE/network signal.
    """
    text = _text(signal)
    if not text:
        return SignatureGuess("", "", "None")

    match = _find_any(_DEAUTH_TERMS, text)
    if match:
        return SignatureGuess(
            family="attack",
            label="Deauth / disassociation attack indicator",
            confidence="High",
            evidence=(f"Deauth keyword: {match}",),
            alert_keyword="deauth",
            alert_label="ALERT: Deauth detected",
        )

    match = _find_any(_EVIL_PORTAL_TERMS, text)
    if match:
        return SignatureGuess(
            family="attack",
            label="Evil portal / evil twin attack indicator",
            confidence="High",
            evidence=(f"Portal/evil-twin keyword: {match}",),
            alert_keyword="evil portal",
            alert_label="ALERT: Evil portal detected",
        )

    match = _find_any(_ATTACK_TOOL_TERMS, text)
    if match:
        return SignatureGuess(
            family="attack",
            label="Known WiFi/BLE attack tool indicator",
            confidence="High",
            evidence=(f"Attack-tool keyword: {match}",),
            alert_keyword="attack tool",
            alert_label="ALERT: Attack tool detected",
        )

    match = _find_any(_JAMMING_TERMS, text)
    if match:
        return SignatureGuess(
            family="attack",
            label="Possible RF/WiFi jamming indicator",
            confidence="High",
            evidence=(f"Jamming keyword: {match}",),
            alert_keyword="jamming",
            alert_label="ALERT: Jamming indicator detected",
        )

    drone_vendor = _find_any(_DRONE_VENDOR_TERMS, text)
    drone_term = _find_any(_DRONE_GENERIC_TERMS, text)
    if drone_vendor and drone_term:
        return SignatureGuess(
            family="drone",
            label="Likely consumer drone controller or aircraft",
            confidence="High",
            evidence=(f"Drone vendor/model clue: {drone_vendor}", f"drone/control clue: {drone_term}"),
            alert_keyword="drone",
            alert_label="Drone signal detected",
        )
    if drone_vendor:
        return SignatureGuess(
            family="drone",
            label="Possible consumer drone device",
            confidence="Medium",
            evidence=(f"Drone vendor/model clue: {drone_vendor}",),
            alert_keyword="drone",
            alert_label="Drone-capable device detected",
        )
    if drone_term:
        return SignatureGuess(
            family="drone",
            label="Possible drone controller, aircraft, or Remote ID clue",
            confidence="Medium",
            evidence=(f"Drone/control clue: {drone_term}",),
            alert_keyword="drone",
            alert_label="Drone signal detected",
        )

    match = _find_any(_FLOCK_TERMS, text)
    if match:
        return SignatureGuess(
            family="surveillance",
            label="Likely Flock Safety / ALPR camera",
            confidence="High",
            evidence=(f"Flock identifier: {match}",),
            alert_keyword="flock",
            alert_label="ALERT: Flock hostile signal",
        )

    match = _find_any(_ALPR_TERMS, text)
    if match:
        return SignatureGuess(
            family="surveillance",
            label="Possible ALPR / license plate reader",
            confidence="High",
            evidence=(f"ALPR identifier: {match}",),
            alert_keyword="alpr",
            alert_label="ALERT: ALPR/plate reader detected",
        )

    match = _find_any(_SURVEILLANCE_PLATFORM_TERMS, text)
    if match:
        return SignatureGuess(
            family="surveillance",
            label="Possible surveillance platform device",
            confidence="Medium",
            evidence=(f"Surveillance platform clue: {match}",),
            alert_keyword="surveillance",
            alert_label="ALERT: Surveillance platform detected",
        )

    vendor = _find_any(_CAMERA_VENDOR_TERMS, text)
    camera_term = _find_any(_SURVEILLANCE_CAMERA_TERMS, text)
    if vendor and camera_term:
        return SignatureGuess(
            family="surveillance",
            label="Likely surveillance camera",
            confidence="High",
            evidence=(f"Camera vendor: {vendor}", f"camera term: {camera_term}"),
            alert_keyword="surveillance camera",
            alert_label="ALERT: Surveillance camera detected",
        )
    if vendor:
        return SignatureGuess(
            family="surveillance",
            label="Possible security camera or surveillance device",
            confidence="Medium",
            evidence=(f"Surveillance/camera vendor: {vendor}",),
            alert_keyword="surveillance",
            alert_label="ALERT: Surveillance vendor detected",
        )
    if camera_term:
        return SignatureGuess(
            family="camera",
            label="Possible camera, recorder, or video device",
            confidence="Medium",
            evidence=(f"Camera/video term: {camera_term}",),
            alert_keyword="camera",
            alert_label="Camera-like device detected",
        )

    tracker = _find_any(_TRACKER_TERMS, text)
    if tracker:
        return SignatureGuess(
            family="tracker",
            label="Possible BLE tracker, tag, or beacon",
            confidence="Medium",
            evidence=(f"Tracker/beacon term: {tracker}",),
            alert_keyword="tracker",
        )

    exposure = _find_any(_NETWORK_EXPOSURE_TERMS, text)
    if exposure:
        return SignatureGuess(
            family="network-camera",
            label="Possible exposed camera or device service",
            confidence="Medium",
            evidence=(f"Network service clue: {exposure}",),
            alert_keyword="camera service",
            alert_label="ALERT: Camera service exposed",
        )

    return SignatureGuess("", "", "None")


def proximity_from_strength(strength: object, previous_strength: object = None) -> dict:
    """
    Convert signal strength into a practical proximity/trend cue.

    Wi-Fi/BLE RSSI is normally negative dBm where larger is closer. SDR rows may
    use other scales; this remains a best-effort cue, not ranging.
    """
    try:
        current = float(strength)
    except (TypeError, ValueError):
        return {"state": "unknown", "trend": "", "delta": None}

    if current >= -45:
        state = "very close"
    elif current >= -60:
        state = "close"
    elif current >= -72:
        state = "nearby"
    elif current >= -85:
        state = "detected"
    else:
        state = "weak"

    trend = ""
    delta = None
    try:
        previous = float(previous_strength)
    except (TypeError, ValueError):
        previous = None
    if previous is not None:
        delta = round(current - previous, 1)
        if delta >= 6:
            trend = "closing fast"
        elif delta >= 3:
            trend = "closing"
        elif delta <= -6:
            trend = "fading fast"
        elif delta <= -3:
            trend = "fading"
        else:
            trend = "steady"

    return {"state": state, "trend": trend, "delta": delta}


def live_cue(signal: dict, previous_strength: object = None) -> dict:
    """
    Build a short UI cue from passive identity guess plus proximity.
    """
    guess = classify_signal_signature(signal)
    prox = proximity_from_strength(signal.get("signalStrength"), previous_strength)
    if guess.alert_label:
        base = guess.alert_label
    elif guess.alert_keyword == "flock":
        base = "ALERT: Flock hostile signal"
    elif guess.family == "attack":
        base = "ALERT: Attack indicator detected"
    elif guess.family == "drone":
        base = "Drone signal detected"
    elif guess.family == "surveillance":
        base = "ALERT: Surveillance device detected"
    elif guess.family == "camera":
        base = "Camera-like device detected"
    elif guess.family == "tracker":
        base = "Tracker/beacon detected"
    elif guess.family == "network-camera":
        base = "Camera service detected"
    else:
        base = "Signal detected"

    detail = prox["trend"] or prox["state"]
    return {
        "label": base if not detail else f"{base}: {detail}",
        "family": guess.family,
        "confidence": guess.confidence,
        "proximity": prox,
        "evidence": guess.evidence_text(),
    }


def annotate_signal(signal: dict) -> SignatureGuess:
    """
    Add signature evidence into a signal dict without overwriting scanner facts.
    """
    guess = classify_signal_signature(signal)
    if not guess.matched:
        return guess

    if not signal.get("deviceClass"):
        signal["deviceClass"] = guess.label

    notes = str(signal.get("notes") or "").strip()
    evidence = guess.evidence_text()
    note = f"Signature: {guess.label}"
    if evidence:
        note = f"{note} ({evidence})"
    signal["notes"] = "; ".join(part for part in (notes, note) if part)

    return guess
