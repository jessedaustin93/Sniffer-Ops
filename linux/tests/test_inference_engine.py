import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db
import inference_engine


def _init(tmp_path):
    path = tmp_path / "awareness.db"
    db.initialize(str(path))
    return path


def _tables(path):
    with sqlite3.connect(path) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows}


def test_migration_adds_schema_version_and_inference_tables(tmp_path):
    path = _init(tmp_path)

    assert db.get_schema_version() == db.CURRENT_SCHEMA_VERSION
    assert {
        "schema_migrations",
        "classifications",
        "classification_evidence",
        "classifier_versions",
        "ownership_records",
        "movement_sessions",
        "trusted_networks",
        "network_integrity_events",
        "cellular_baselines",
        "cellular_anomalies",
        "derived_entities",
        "watch_zones",
        "surveillance_zones",
        "enforcement_locations",
        "policy_profiles",
    }.issubset(_tables(path))


def test_android_mobile_detector_sighting_metadata_is_preserved(tmp_path):
    path = _init(tmp_path)
    payload = {
        "schema": 1,
        "protocolVersion": 2,
        "nodeId": "android-synthetic",
        "nodeName": "Synthetic Android",
        "nodeRole": "mobile_detector",
        "signals": [
            {
                "name": "BLE synthetic",
                "address": "AA:BB:CC:00:00:10",
                "type": "BLE",
                "signalStrength": -63,
                "sightings": [
                    {
                        "id": "android-sighting-1",
                        "capturedAt": 10_000,
                        "signalStrength": -63,
                        "latitude": 35.0,
                        "longitude": -83.0,
                        "accuracyMeters": 10.0,
                        "movementSessionId": "android-moving-1",
                        "speedMetersPerSecond": 7.5,
                        "bearingDegrees": 91.0,
                        "locationProvider": "fused",
                        "sourceNodeId": "android-synthetic",
                    }
                ],
            }
        ],
    }

    db.merge_remote_snapshot(payload)

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM signal_sightings").fetchone()

    assert row["movement_session_id"] == "android-moving-1"
    assert row["speed_mps"] == 7.5
    assert row["bearing_degrees"] == 91.0
    assert row["location_provider"] == "fused"
    assert row["source_node_id"] == "android-synthetic"


def test_flock_identity_confidence_priority_and_disposition_are_separate(tmp_path):
    _init(tmp_path)
    signal = {
        "name": "flock-safety-alpr-test",
        "type": "WIFI",
        "address": "02:00:00:00:00:01",
        "deviceClass": "roadside sensor",
        "signalStrength": -55,
    }
    profile_id = db.signal_profile_id(signal)
    db.write_detection(signal, "synthetic-node", now_ms=1_000)

    findings = inference_engine.recalculate_profile(profile_id)

    assert findings
    flock = next(f for f in findings if f.family.startswith("surveillance.flock"))
    assert flock.confidence == "HIGH"
    assert flock.priority == "HIGH"
    assert flock.policy_disposition == "HOSTILE"
    assert "User policy" in flock.policy_reason
    stored = db.get_classifications()
    assert stored[0]["classifier_version"] == inference_engine.ENGINE_VERSION
    assert db.get_classification_evidence(stored[0]["id"])


def test_public_safety_profile_rule_is_dispatched_and_persisted(tmp_path):
    _init(tmp_path)
    signal = {
        "name": "mobile ALPR vehicle equipment",
        "type": "WIFI",
        "address": "02:00:00:00:00:11",
        "deviceClass": "vehicle-mounted system",
        "signalStrength": -55,
    }
    profile_id = db.signal_profile_id(signal)
    db.write_detection(signal, "synthetic-node", now_ms=1_783_785_900_000)

    findings = inference_engine.recalculate_profile(profile_id)

    alpr = next(f for f in findings if f.family == "public_safety.alpr_vehicle_equipment")
    assert alpr.label == "Vehicle-mounted ALPR equipment clue"
    assert alpr.priority == "WATCH"
    assert alpr.confidence == "MEDIUM"
    assert alpr.policy_disposition == "WATCH"
    assert any(e.raw.get("rule_id") == "vehicle-alpr" for e in alpr.evidence)

    stored = [f for f in db.get_classifications() if f["family"] == alpr.family]
    assert len(stored) == 1
    assert isinstance(stored[0]["first_seen"], int)
    assert isinstance(stored[0]["last_seen"], int)
    assert isinstance(stored[0]["recalculated_at"], int)
    assert db.get_classification_evidence(stored[0]["id"])


def test_new_named_classifier_packs_label_public_vendor_clues(tmp_path):
    _init(tmp_path)
    samples = [
        (
            {
                "name": "Rekor OpenALPR roadside node",
                "type": "WIFI",
                "address": "02:00:00:00:10:01",
                "deviceClass": "roadside camera",
            },
            "surveillance.rekor",
            "Rekor/OpenALPR platform clue",
        ),
        (
            {
                "name": "SoundThinking ShotSpotter acoustic sensor",
                "type": "WIFI",
                "address": "02:00:00:00:10:02",
            },
            "surveillance.soundthinking",
            "SoundThinking/ShotSpotter acoustic sensor clue",
        ),
        (
            {
                "name": "Cradlepoint fleet vehicle router",
                "type": "WIFI",
                "address": "02:00:00:00:10:03",
            },
            "entity.fleet_router",
            "Fleet/vehicle router vendor clue",
        ),
        (
            {
                "name": "Ray-Ban Meta smart glasses",
                "type": "BLUETOOTH",
                "address": "02:00:00:00:10:04",
            },
            "surveillance.smartglasses",
            "Meta/Ray-Ban smartglasses clue",
        ),
    ]

    for signal, family, label in samples:
        profile_id = db.signal_profile_id(signal)
        db.write_detection(signal, "synthetic-node", now_ms=1_783_785_900_000)
        findings = inference_engine.recalculate_profile(profile_id)

        finding = next(f for f in findings if f.family == family)
        assert finding.label == label
        assert finding.policy_disposition in {"INFO", "WATCH"}
        assert any(e.raw.get("rule_id") for e in finding.evidence)


def test_offensive_tool_pack_uses_hostile_disposition_for_explicit_tooling(tmp_path):
    _init(tmp_path)
    signal = {
        "name": "lab eaphammer evil twin",
        "type": "WIFI",
        "address": "02:00:00:00:10:05",
        "notes": "hostapd-wpe credential portal",
    }
    profile_id = db.signal_profile_id(signal)
    db.write_detection(signal, "synthetic-node", now_ms=1_783_785_900_000)

    findings = inference_engine.recalculate_profile(profile_id)

    tool = next(f for f in findings if f.family == "network.wifi_phishing_tool")
    assert tool.priority == "HIGH"
    assert tool.confidence == "MEDIUM"
    assert tool.policy_disposition == "HOSTILE"
    assert any(e.raw.get("rule_id") == "wifi-phishing-tools" for e in tool.evidence)


def test_low_cost_camera_and_drone_packs_label_candidates_cautiously(tmp_path):
    _init(tmp_path)
    camera = {
        "name": "V380 camera setup",
        "type": "WIFI",
        "address": "02:00:00:00:10:06",
        "notes": "onvif rtsp default ipcam",
    }
    drone = {
        "name": "Autel EVO Nano",
        "type": "WIFI",
        "address": "02:00:00:00:10:07",
    }

    camera_id = db.signal_profile_id(camera)
    drone_id = db.signal_profile_id(drone)
    db.write_detection(camera, "synthetic-node", now_ms=1_783_785_900_000)
    db.write_detection(drone, "synthetic-node", now_ms=1_783_785_901_000)

    camera_findings = inference_engine.recalculate_profile(camera_id)
    drone_findings = inference_engine.recalculate_profile(drone_id)

    camera_match = next(f for f in camera_findings if f.family == "surveillance.low_cost_ip_camera")
    drone_match = next(f for f in drone_findings if f.family == "surveillance.mobile_camera")
    assert camera_match.confidence == "LOW"
    assert camera_match.policy_disposition == "WATCH"
    assert "camera" in camera_match.label.lower()
    assert drone_match.confidence == "MEDIUM"
    assert drone_match.policy_disposition == "WATCH"


def test_owned_tracker_is_suppressed_without_deleting_sightings(tmp_path):
    _init(tmp_path)
    signal = {
        "name": "Tile synthetic tracker",
        "type": "BLUETOOTH",
        "address": "AA:BB:CC:00:00:02",
        "signalStrength": -60,
    }
    profile_id = db.signal_profile_id(signal)
    for n in range(1, 6):
        db.write_detection(signal, "synthetic-node", now_ms=n * 1_000)
    db.set_ownership_state(profile_id, "Mine", reason="synthetic owner")

    findings = inference_engine.recalculate_profile(profile_id)

    tracking = [f for f in findings if f.family.startswith("tracking.")]
    assert tracking
    assert all(f.priority == "INFO" for f in tracking)
    assert any(f.policy_disposition == "Mine" for f in tracking)
    with sqlite3.connect(tmp_path / "awareness.db") as conn:
        count = conn.execute("SELECT COUNT(*) FROM signal_sightings").fetchone()[0]
    assert count == 1


def test_single_tracker_sighting_is_not_called_following(tmp_path):
    _init(tmp_path)
    signal = {
        "name": "AirTag one pass",
        "type": "BLUETOOTH",
        "address": "AA:BB:CC:00:00:03",
        "signalStrength": -75,
    }
    profile_id = db.signal_profile_id(signal)
    db.write_detection(signal, "synthetic-node", now_ms=1_000)

    findings = inference_engine.recalculate_profile(profile_id)

    assert all(f.label != "Probable following tracker" for f in findings)
    assert all(f.priority != "HIGH" for f in findings if f.family.startswith("tracking."))


def test_repeated_unknown_tracker_gets_following_risk(tmp_path):
    _init(tmp_path)
    signal = {
        "name": "Chipolo synthetic tag",
        "type": "BLUETOOTH",
        "address": "AA:BB:CC:00:00:04",
        "signalStrength": -58,
        "latitude": 35.0,
        "longitude": -83.0,
    }
    profile_id = db.signal_profile_id(signal)
    for n in range(1, 8):
        db.write_detection(signal, "synthetic-node", now_ms=n * 60_000)

    findings = inference_engine.recalculate_profile(profile_id)

    assert any(f.family == "tracking.following" for f in findings)
    scored = next(f for f in findings if f.family == "tracking.following")
    assert scored.details["following_risk_score"] >= 55
    assert scored.confidence in {"MEDIUM", "HIGH"}


def test_trusted_network_fingerprint_detects_evil_twin_gateway_dns_and_dhcp():
    fingerprint = {
        "ssid": "SyntheticNet",
        "bssid_set": ["aa:bb:cc:dd:ee:01"],
        "gateway_ip": "192.0.2.1",
        "gateway_mac": "aa:bb:cc:dd:ee:ff",
        "dns_servers": ["192.0.2.53"],
        "dhcp_server": "192.0.2.1",
        "normal_encryption": "WPA2",
        "captive_portal_expected": False,
    }
    observation = {
        "ssid": "SyntheticNet",
        "bssid": "aa:bb:cc:dd:ee:99",
        "duplicate_ssid_visible": True,
        "gateway_ip": "192.0.2.2",
        "gateway_mac": "aa:bb:cc:dd:ee:98",
        "dns_servers": ["198.51.100.53"],
        "dhcp_server": "192.0.2.2",
        "encryption": "Open",
        "captive_portal": True,
    }

    findings = inference_engine.compare_trusted_network(fingerprint, observation)
    families = {f.family for f in findings}

    assert "network.evil_twin" in families
    assert "network.gateway_change" in families
    assert "network.dns_hijack" in families
    assert "network.dhcp_change" in families
    assert "network.encryption_downgrade" in families
    assert "network.captive_portal_anomaly" in families


def test_cellular_single_indicator_stays_cautious():
    baseline = {
        "radio_technology": "LTE",
        "serving_cell_id": "cell-a",
        "mcc": "310",
        "mnc": "260",
    }
    observation = {
        "radio_technology": "GSM",
        "serving_cell_id": "cell-a",
        "mcc": "310",
        "mnc": "260",
        "stationary": True,
    }

    finding = inference_engine.score_cellular_anomaly(baseline, observation)

    assert finding is not None
    assert finding.family == "cellular.downgrade"
    assert finding.confidence == "LOW"
    assert "not proof" in finding.recommended_next_step


def test_cellular_multiple_indicators_can_reach_possible_rogue_label():
    baseline = {
        "radio_technology": "LTE",
        "serving_cell_id": "cell-a",
        "mcc": "310",
        "mnc": "260",
    }
    observation = {
        "radio_technology": "GSM",
        "serving_cell_id": "cell-b",
        "mcc": "999",
        "mnc": "001",
        "stationary": True,
        "registration_failures": 3,
    }

    finding = inference_engine.score_cellular_anomaly(baseline, observation)

    assert finding.family == "cellular.possible_rogue_cell"
    assert finding.confidence == "HIGH"
    assert "Possible" in finding.label


def test_route_exposure_scoring_uses_family_confidence_and_distance():
    findings = [
        {
            "family": "surveillance.flock",
            "label": "Synthetic Flock",
            "confidence": "HIGH",
            "details": {"latitude": 35.0, "longitude": -83.0},
        },
        {
            "family": "surveillance.camera",
            "label": "Far camera",
            "confidence": "HIGH",
            "details": {"latitude": 36.0, "longitude": -84.0},
        },
    ]

    score = inference_engine.route_exposure_score([(35.0005, -83.0005)], findings, "Low Exposure")

    assert score["score"] > 0
    assert len(score["contributors"]) == 1
    assert score["contributors"][0]["family"] == "surveillance.flock"


def test_old_android_windows_payload_ingests_and_classifies(tmp_path):
    _init(tmp_path)
    payload = {
        "schema": 1,
        "nodeId": "old-collector",
        "nodeName": "old Android or Windows",
        "signals": [
            {
                "name": "Tile old payload",
                "address": "AA:BB:CC:00:00:05",
                "type": "BLUETOOTH",
                "signalStrength": -70,
                "deviceClass": "",
                "threatLevel": "NORMAL",
                "seenCount": 3,
                "firstSeen": 1_000,
                "lastSeen": 3_000,
                "sightings": [
                    {"capturedAt": 1_000, "signalStrength": -75},
                    {"capturedAt": 3_000, "signalStrength": -70},
                ],
            }
        ],
    }

    stats = db.merge_remote_snapshot(payload)
    findings = inference_engine.recalculate_all()

    assert stats["merged"] == 1
    assert findings
    assert any(f.family.startswith("tracking.") for f in findings)


def test_specific_surveillance_rules_refine_broad_camera_signature(tmp_path):
    _init(tmp_path)
    signal = {
        "name": "intersection red light camera",
        "type": "WIFI",
        "address": "02:00:00:00:00:06",
        "deviceClass": "traffic camera",
        "notes": "red-light camera reference",
    }
    profile_id = db.signal_profile_id(signal)
    db.write_detection(signal, "synthetic-node", now_ms=1_000)

    findings = inference_engine.recalculate_profile(profile_id)

    assert any(f.family == "surveillance.red_light_camera" for f in findings)
    refined = next(f for f in findings if f.family == "surveillance.red_light_camera")
    assert refined.priority == "CAUTION"
    assert refined.policy_disposition == "WATCH"


def test_deflock_osm_reference_metadata_refines_to_hostile_flock(tmp_path):
    _init(tmp_path)
    signal = {
        "name": "OSM ALPR reference",
        "type": "WIFI",
        "address": "02:00:00:00:00:07",
        "deviceClass": "camera",
        "notes": "DeFlock OpenStreetMap surveillance:type=ALPR manufacturer=Flock Safety",
    }
    profile_id = db.signal_profile_id(signal)
    db.write_detection(signal, "synthetic-node", now_ms=1_000)

    findings = inference_engine.recalculate_profile(profile_id)

    assert any(f.family == "surveillance.flock" for f in findings)
    flock = next(f for f in findings if f.family == "surveillance.flock")
    assert flock.policy_disposition == "HOSTILE"
    assert flock.confidence == "HIGH"
    assert any(ev.type == "classifier_rule" for ev in flock.evidence)


def test_specific_tracker_rules_refine_known_tracker_family(tmp_path):
    _init(tmp_path)
    signal = {
        "name": "Samsung SmartTag synthetic",
        "type": "BLUETOOTH",
        "address": "AA:BB:CC:00:00:08",
        "signalStrength": -62,
    }
    profile_id = db.signal_profile_id(signal)
    for n in range(1, 4):
        db.write_detection(signal, "synthetic-node", now_ms=n * 1_000)

    findings = inference_engine.recalculate_profile(profile_id)

    assert any(f.family == "tracking.samsung_smarttag" for f in findings)
    smarttag = next(f for f in findings if f.family == "tracking.samsung_smarttag")
    assert smarttag.priority == "WATCH"
    assert any(ev.type == "classifier_rule" for ev in smarttag.evidence)


def test_hidden_camera_keyword_refines_to_hostile(tmp_path):
    _init(tmp_path)
    signal = {
        "name": "Hidden Camera AP42",
        "type": "WIFI",
        "address": "02:00:00:00:00:07",
        "deviceClass": "unknown",
        "notes": "spy cam listing found nearby",
    }
    profile_id = db.signal_profile_id(signal)
    db.write_detection(signal, "synthetic-node", now_ms=1_000)

    findings = inference_engine.recalculate_profile(profile_id)

    assert any(f.family == "surveillance.hidden_camera" for f in findings)
    hidden = next(f for f in findings if f.family == "surveillance.hidden_camera")
    assert hidden.priority == "HIGH"
    assert hidden.policy_disposition == "HOSTILE"
    assert any(ev.type == "classifier_rule" for ev in hidden.evidence)


def test_generic_ip_camera_ap_refines_to_watch(tmp_path):
    _init(tmp_path)
    signal = {
        "name": "IPCAM-A1B2",
        "type": "WIFI",
        "address": "02:00:00:00:00:08",
        "deviceClass": "unknown",
        "notes": "",
    }
    profile_id = db.signal_profile_id(signal)
    db.write_detection(signal, "synthetic-node", now_ms=1_000)

    findings = inference_engine.recalculate_profile(profile_id)

    assert any(f.family == "surveillance.generic_ip_camera" for f in findings)
    cam = next(f for f in findings if f.family == "surveillance.generic_ip_camera")
    assert cam.priority == "WATCH"
    assert cam.policy_disposition == "WATCH"


def test_audio_listening_device_keyword_refines_to_hostile(tmp_path):
    _init(tmp_path)
    signal = {
        "name": "unknown BLE device",
        "type": "BLE",
        "address": "02:00:00:00:00:09",
        "deviceClass": "unknown",
        "notes": "listed as a spy microphone / audio bug",
    }
    profile_id = db.signal_profile_id(signal)
    db.write_detection(signal, "synthetic-node", now_ms=1_000)

    findings = inference_engine.recalculate_profile(profile_id)

    assert any(f.family == "surveillance.audio_bug" for f in findings)
    bug = next(f for f in findings if f.family == "surveillance.audio_bug")
    assert bug.priority == "HIGH"
    assert bug.policy_disposition == "HOSTILE"


def test_route_exposure_uses_domain_route_weights():
    findings = [
        {
            "family": "surveillance.camera_trailer",
            "label": "Synthetic trailer",
            "confidence": "HIGH",
            "details": {"latitude": 35.0, "longitude": -83.0},
        }
    ]

    score = inference_engine.route_exposure_score([(35.0, -83.0)], findings, "Balanced")

    assert score["score"] == 2.6
    assert score["contributors"][0]["family"] == "surveillance.camera_trailer"
