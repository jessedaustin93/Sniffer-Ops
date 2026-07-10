import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import signal_classifier
import signal_signatures


def test_flock_wifi_signature_is_high_confidence_surveillance():
    signal = {"name": "FlockSafety-Unit-42", "type": "WIFI", "channel": 6}

    guess = signal_signatures.classify_signal_signature(signal)
    explanation = signal_classifier.classify_wifi(signal)
    alert = signal_classifier.classify_alert(
        signal["name"],
        "WIFI",
        explanation.specific_type,
        "",
        explanation.evidence,
    )

    assert guess.family == "surveillance"
    assert guess.confidence == "High"
    assert "Flock" in explanation.specific_type
    assert alert["level"] == "HIGH"


def test_flock_live_cue_reports_closing():
    signal = {
        "name": "FlockSafety-Unit-42",
        "type": "WIFI",
        "signalStrength": -58,
    }

    cue = signal_signatures.live_cue(signal, previous_strength=-66)

    assert cue["label"] == "ALERT: Flock hostile signal: closing fast"
    assert cue["proximity"]["state"] == "close"


def test_alpr_and_license_plate_terms_are_surveillance_signatures():
    signal = {"name": "north-lot-license-plate-reader", "type": "WIFI", "channel": 149}

    guess = signal_signatures.classify_signal_signature(signal)
    explanation = signal_classifier.classify_wifi(signal)

    assert guess.label == "Possible ALPR / license plate reader"
    assert explanation.confidence == "High"
    assert "plate" in explanation.evidence.lower()


def test_camera_vendor_plus_camera_term_is_high_confidence():
    signal = {
        "name": "Axis-Camera-Setup",
        "manufacturer": "Axis Communications",
        "type": "WIFI",
        "channel": 11,
    }

    guess = signal_signatures.classify_signal_signature(signal)
    annotated = dict(signal)
    signal_signatures.annotate_signal(annotated)

    assert guess.label == "Likely surveillance camera"
    assert guess.confidence == "High"
    assert "Signature:" in annotated["notes"]


def test_ble_tracker_signature_is_not_surveillance_alert():
    signal = {"name": "Tile Tracker", "type": "BLUETOOTH", "status": "BLE"}

    guess = signal_signatures.classify_signal_signature(signal)
    explanation = signal_classifier.classify_bluetooth(signal)
    alert = signal_classifier.classify_alert(
        signal["name"],
        "BLUETOOTH",
        explanation.specific_type,
        "",
        explanation.evidence,
    )

    assert guess.family == "tracker"
    assert "tracker" in explanation.specific_type.lower()
    assert alert["level"] == "LOW"


def test_deauth_signature_is_high_alert_with_explicit_cue():
    signal = {
        "name": "unknown-ap",
        "type": "WIFI",
        "channel": 11,
        "signalStrength": -51,
        "notes": "deauth packets observed",
    }

    guess = signal_signatures.classify_signal_signature(signal)
    explanation = signal_classifier.classify_wifi(signal)
    cue = signal_signatures.live_cue(signal)
    alert = signal_classifier.classify_alert(
        signal["name"],
        "WIFI",
        explanation.specific_type,
        "",
        explanation.evidence,
    )

    assert guess.family == "attack"
    assert "Deauth" in explanation.specific_type
    assert cue["label"] == "ALERT: Deauth detected: close"
    assert alert["level"] == "HIGH"


def test_evil_portal_and_pwnagotchi_are_high_alerts():
    portal = {"name": "Cafe Evil Portal", "type": "WIFI", "channel": 6}
    pwnagotchi = {"name": "pwnagotchi-wardrive", "type": "BLUETOOTH"}

    portal_exp = signal_classifier.classify_wifi(portal)
    portal_alert = signal_classifier.classify_alert(
        portal["name"], "WIFI", portal_exp.specific_type, "", portal_exp.evidence
    )
    pwnagotchi_exp = signal_classifier.classify_bluetooth(pwnagotchi)
    pwnagotchi_alert = signal_classifier.classify_alert(
        pwnagotchi["name"],
        "BLUETOOTH",
        pwnagotchi_exp.specific_type,
        "",
        pwnagotchi_exp.evidence,
    )

    assert "Evil portal" in portal_exp.specific_type
    assert portal_alert["level"] == "HIGH"
    assert "attack tool" in pwnagotchi_exp.specific_type.lower()
    assert pwnagotchi_alert["level"] == "HIGH"


def test_safe_threat_level_suppresses_camera_alert_keywords():
    alert = signal_classifier.classify_alert(
        "Driveway camera",
        "WIFI",
        "Likely surveillance camera",
        "SAFE",
        "trusted home device",
    )

    assert alert["level"] == "NONE"


def test_dji_tello_metadata_is_drone_signature_not_camera():
    signal = {
        "name": "TELLO-EDU-42",
        "type": "WIFI",
        "channel": 6,
        "signalStrength": -61,
        "notes": "Ryze DJI Tello EDU drone",
    }

    guess = signal_signatures.classify_signal_signature(signal)
    explanation = signal_classifier.classify_wifi(signal)
    cue = signal_signatures.live_cue(signal)
    alert = signal_classifier.classify_alert(
        signal["name"], "WIFI", explanation.specific_type, "", explanation.evidence
    )

    assert guess.family == "drone"
    assert "drone" in explanation.specific_type.lower()
    assert cue["label"] == "Drone signal detected: nearby"
    assert alert["level"] == "MEDIUM"


def test_395_mhz_stays_military_airband_not_drone():
    explanation = signal_classifier.classify_sdr(395_400_000)

    assert "Military aviation UHF airband" == explanation.specific_type
    assert "drone" not in explanation.specific_type.lower()
    assert "drone" not in explanation.meaning.lower()


def test_dji_operating_bands_are_drone_candidates_not_confirmed_ids():
    tello_band = signal_classifier.classify_sdr(2_412_000_000)
    dji_51_band = signal_classifier.classify_sdr(5_180_000_000)
    dji_58_band = signal_classifier.classify_sdr(5_800_000_000)

    assert "consumer-drone" in tello_band.specific_type
    assert "candidate" in tello_band.specific_type
    assert "DJI RC 2" in dji_51_band.specific_type
    assert "candidate" in dji_51_band.next_step
    assert "consumer-drone" in dji_58_band.specific_type


def test_new_sdr_transport_bands_have_best_guess_labels():
    cbrs = signal_classifier.classify_sdr(3_600_000_000)
    its = signal_classifier.classify_sdr(5_900_000_000)

    assert "CBRS" in cbrs.specific_type
    assert "ITS" in its.specific_type or "C-V2X" in its.specific_type
