import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import awareness_log
import ownership


def _set_trust_file(monkeypatch, tmp_path, data):
    path = tmp_path / "trusted_devices.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(ownership, "TRUSTED_DEVICES_PATH", str(path))
    ownership.reload_trusted_devices()
    return path


def test_trusted_name_pattern_marks_signal_safe(monkeypatch, tmp_path):
    _set_trust_file(monkeypatch, tmp_path, {
        "owner_label": "Home trusted device",
        "trusted_name_patterns": [r"\bhomecam\b"],
    })
    signal = {
        "name": "HomeCam driveway",
        "type": "WIFI",
        "deviceClass": "Likely surveillance camera",
        "threatLevel": "ALERT",
    }

    match = ownership.apply_trust(signal)

    assert match.trusted is True
    assert signal["threatLevel"] == "SAFE"
    assert "Trusted owner: Home trusted device" in signal["notes"]


def test_trusted_profile_bypasses_dashboard_alert(monkeypatch, tmp_path):
    _set_trust_file(monkeypatch, tmp_path, {
        "trusted_profiles": ["WIFI|AA:BB:CC:DD:EE:FF"],
    })
    profile = {
        "id": "WIFI|AA:BB:CC:DD:EE:FF",
        "type": "WIFI",
        "name": "driveway camera",
        "device_class": "Likely surveillance camera",
        "threat_level": "ALERT",
        "seen_count": 1,
    }

    assert awareness_log._profile_class(profile) == "Normal"
