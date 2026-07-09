import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db


def _connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_repeated_local_detection_updates_one_sighting(tmp_path):
    db_path = tmp_path / "awareness.db"
    db.initialize(str(db_path))
    signal = {
        "name": "RF 100.100 MHz",
        "address": "rf:100100000",
        "type": "RTL_SDR",
        "frequencyHz": 100_100_000,
        "signalStrength": -30,
    }

    first_id = db.write_detection(signal, "linux-node", now_ms=1_000)
    signal["signalStrength"] = -20
    second_id = db.write_detection(signal, "linux-node", now_ms=2_000)

    assert first_id == second_id
    with _connect(db_path) as conn:
        profile = conn.execute("SELECT * FROM signal_profiles").fetchone()
        sightings = conn.execute("SELECT * FROM signal_sightings").fetchall()

    assert profile["seen_count"] == 2
    assert profile["last_seen"] == 2_000
    assert profile["last_signal"] == -20
    assert len(sightings) == 1
    assert sightings[0]["captured_at"] == 2_000
    assert sightings[0]["signal_strength"] == -20
    assert sightings[0]["synced_at"] is None


def test_duplicate_sighting_compaction_keeps_latest_per_profile_node(tmp_path):
    db_path = tmp_path / "awareness.db"
    db.initialize(str(db_path))
    signal = {
        "name": "RF 101.100 MHz",
        "address": "rf:101100000",
        "type": "RTL_SDR",
        "frequencyHz": 101_100_000,
        "signalStrength": -40,
    }
    stable_id = db.write_detection(signal, "linux-node", now_ms=1_000)

    with _connect(db_path) as conn:
        profile_id = conn.execute("SELECT id FROM signal_profiles").fetchone()["id"]
        conn.execute(
            """
            INSERT INTO signal_sightings (
                id, device_id, node_id, captured_at, signal_strength
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("old-random-id", profile_id, "linux-node", 500, -50),
        )
        conn.commit()

    removed = db.compact_duplicate_sightings()

    with _connect(db_path) as conn:
        sightings = conn.execute("SELECT * FROM signal_sightings").fetchall()

    assert removed == 1
    assert len(sightings) == 1
    assert sightings[0]["id"] == stable_id
    assert sightings[0]["captured_at"] == 1_000
