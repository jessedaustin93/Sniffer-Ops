import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db


def _connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


# ── _to_epoch_ms ────────────────────────────────────────────────────────────


def test_to_epoch_ms_passes_through_epoch_ms_int():
    assert db._to_epoch_ms(1_785_072_388_644) == 1_785_072_388_644


def test_to_epoch_ms_upconverts_epoch_seconds():
    assert db._to_epoch_ms(1_785_072_388) == 1_785_072_388_000


def test_to_epoch_ms_parses_iso_with_z_suffix():
    assert db._to_epoch_ms("2026-07-11T16:04:22Z") == 1_783_785_862_000


def test_to_epoch_ms_parses_iso_with_offset():
    assert db._to_epoch_ms("2026-07-11T16:04:22+00:00") == 1_783_785_862_000


def test_to_epoch_ms_parses_numeric_string():
    assert db._to_epoch_ms("1785072388644") == 1_785_072_388_644


def test_to_epoch_ms_handles_none_and_empty_and_garbage():
    assert db._to_epoch_ms(None) is None
    assert db._to_epoch_ms("") is None
    assert db._to_epoch_ms("not-a-timestamp") is None
    assert db._to_epoch_ms(True) is None


# ── merge_remote_snapshot (the actual peer-sync injection point) ───────────


def test_merge_remote_snapshot_normalizes_iso_timestamps_to_integer(tmp_path):
    db_path = tmp_path / "awareness.db"
    db.initialize(str(db_path))

    snapshot = {
        "nodeId": "windows-peer",
        "signals": [
            {
                "id": "profile-1",
                "name": "Test Device",
                "type": "BLE",
                "firstSeen": "2026-07-11T16:04:22Z",
                "lastSeen": "2026-07-11T16:05:00Z",
                "sightings": [
                    {
                        "nodeId": "windows-peer",
                        "capturedAt": "2026-07-11T16:05:00Z",
                        "signalStrength": -60,
                    }
                ],
            }
        ],
    }
    db.merge_remote_snapshot(snapshot)

    with _connect(db_path) as conn:
        profile = conn.execute(
            "SELECT first_seen, last_seen, typeof(first_seen) AS t1, "
            "typeof(last_seen) AS t2 FROM signal_profiles"
        ).fetchone()
        sighting = conn.execute(
            "SELECT captured_at, typeof(captured_at) AS t FROM signal_sightings"
        ).fetchone()

    assert profile["t1"] == "integer"
    assert profile["t2"] == "integer"
    assert profile["first_seen"] == 1_783_785_862_000
    assert profile["last_seen"] == 1_783_785_900_000
    assert sighting["t"] == "integer"
    assert sighting["captured_at"] == 1_783_785_900_000


def test_merge_remote_snapshot_max_last_seen_survives_mixed_formats(tmp_path):
    """
    Regression for the TEXT-sorts-above-INTEGER bug: once an ISO string
    landed in last_seen, SQLite's MAX(...) comparison in the UPSERT would
    treat it as permanently "greater" than any real epoch-ms value from a
    later, correctly-formatted sync — freezing last_seen forever. With
    normalization at the write boundary this can no longer happen.
    """
    db_path = tmp_path / "awareness.db"
    db.initialize(str(db_path))

    stale_iso_snapshot = {
        "nodeId": "windows-peer",
        "signals": [{
            "id": "profile-2",
            "name": "Test Device",
            "type": "BLE",
            "firstSeen": "2026-07-11T16:04:22Z",
            "lastSeen": "2026-07-11T16:04:22Z",
            "sightings": [],
        }],
    }
    db.merge_remote_snapshot(stale_iso_snapshot)

    fresh_ms = int(time.time() * 1000)
    fresh_snapshot = {
        "nodeId": "linux-peer",
        "signals": [{
            "id": "profile-2",
            "name": "Test Device",
            "type": "BLE",
            "firstSeen": fresh_ms,
            "lastSeen": fresh_ms,
            "sightings": [],
        }],
    }
    db.merge_remote_snapshot(fresh_snapshot)

    with _connect(db_path) as conn:
        profile = conn.execute(
            "SELECT last_seen FROM signal_profiles"
        ).fetchone()

    assert profile["last_seen"] == fresh_ms


# ── upsert_classification ───────────────────────────────────────────────────


def test_upsert_classification_normalizes_iso_timestamps(tmp_path):
    db_path = tmp_path / "awareness.db"
    db.initialize(str(db_path))

    record = {
        "id": "cls-1",
        "family": "public_safety.possible_cruiser",
        "classifier_version": "linux-inference-1.0.0",
        "label": "Possible cruiser",
        "priority": "MEDIUM",
        "confidence": "MEDIUM",
        "first_seen": "2026-07-11T16:04:22Z",
        "last_seen": "2026-07-11T16:05:00Z",
        "recalculated_at": "2026-07-11T16:05:00Z",
    }
    db.upsert_classification(record, evidence=[])

    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT first_seen, last_seen, recalculated_at, "
            "typeof(first_seen) AS t1, typeof(last_seen) AS t2, "
            "typeof(recalculated_at) AS t3 FROM classifications WHERE id='cls-1'"
        ).fetchone()

    assert row["t1"] == row["t2"] == row["t3"] == "integer"
    assert row["first_seen"] == 1_783_785_862_000
    assert row["last_seen"] == 1_783_785_900_000
    assert row["recalculated_at"] == 1_783_785_900_000


# ── Migration 3: repairs data already on disk ───────────────────────────────


def test_migration_normalizes_preexisting_text_timestamps(tmp_path):
    db_path = tmp_path / "awareness.db"
    db.initialize(str(db_path))

    # Simulate corrupted legacy data written before this fix existed, by
    # inserting a raw ISO string directly, bypassing every normalized writer.
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO signal_profiles (id, name, type, first_seen, last_seen, "
            "seen_count, presence_state, node_ids, timeline) "
            "VALUES ('legacy-1', 'Legacy Device', 'BLE', "
            "'2026-07-11T16:04:22Z', '2026-07-11T16:04:22Z', 1, 'seen', '[]', '[]')"
        )
        conn.execute(
            "INSERT INTO signal_sightings (id, device_id, node_id, captured_at) "
            "VALUES ('legacy-sighting-1', 'legacy-1', 'old-node', "
            "'2026-07-11T16:04:22Z')"
        )
        conn.commit()
        # Force the schema back to "pre-migration-3" so re-initializing re-runs it.
        conn.execute("DELETE FROM schema_migrations WHERE version = 3")
        conn.commit()

    # Re-opening the database re-runs pending migrations, including 3.
    db.initialize(str(db_path))

    with _connect(db_path) as conn:
        profile = conn.execute(
            "SELECT first_seen, last_seen, typeof(first_seen) AS t1, "
            "typeof(last_seen) AS t2 FROM signal_profiles WHERE id='legacy-1'"
        ).fetchone()
        sighting = conn.execute(
            "SELECT captured_at, typeof(captured_at) AS t FROM signal_sightings "
            "WHERE id='legacy-sighting-1'"
        ).fetchone()

    assert profile["t1"] == profile["t2"] == "integer"
    assert profile["first_seen"] == 1_783_785_862_000
    assert profile["last_seen"] == 1_783_785_862_000
    assert sighting["t"] == "integer"
    assert sighting["captured_at"] == 1_783_785_862_000


def test_migration_normalizes_last_missing_at(tmp_path):
    """Every column in _TIMESTAMP_COLUMNS actually present in the schema
    must be covered — this one (signal_profiles.last_missing_at) was missed
    in an earlier draft of the column set."""
    db_path = tmp_path / "awareness.db"
    db.initialize(str(db_path))

    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO signal_profiles (id, name, type, first_seen, last_seen, "
            "last_missing_at, seen_count, presence_state, node_ids, timeline) "
            "VALUES ('legacy-2', 'Legacy Device', 'BLE', 1000, 1000, "
            "'2026-07-11T16:04:22Z', 1, 'missing', '[]', '[]')"
        )
        conn.commit()
        conn.execute("DELETE FROM schema_migrations WHERE version = 3")
        conn.commit()

    db.initialize(str(db_path))

    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT last_missing_at, typeof(last_missing_at) AS t "
            "FROM signal_profiles WHERE id='legacy-2'"
        ).fetchone()

    assert row["t"] == "integer"
    assert row["last_missing_at"] == 1_783_785_862_000


def test_recency_query_finds_rows_after_normalization(tmp_path):
    """
    Reproduces the live bug found on t5810b: a naive 'captured_at within the
    last 24h' query returned zero rows because some captured_at values were
    stored as TEXT and compared incorrectly. After migration, comparing
    against an epoch-ms cutoff must work.
    """
    db_path = tmp_path / "awareness.db"
    db.initialize(str(db_path))

    now_ms = int(time.time() * 1000)
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO signal_profiles (id, name, type, first_seen, last_seen, "
            "seen_count, presence_state, node_ids, timeline) "
            "VALUES ('p1', 'Device', 'BLE', ?, ?, 1, 'seen', '[]', '[]')",
            (now_ms, now_ms),
        )
        # A legacy TEXT captured_at that is actually recent.
        recent_iso = "2026-07-26T09:00:00Z"
        conn.execute(
            "INSERT INTO signal_sightings (id, device_id, node_id, captured_at) "
            "VALUES ('s1', 'p1', 'node', ?)",
            (recent_iso,),
        )
        conn.commit()
        conn.execute("DELETE FROM schema_migrations WHERE version = 3")
        conn.commit()

    db.initialize(str(db_path))

    cutoff_ms = db._to_epoch_ms("2026-07-25T09:00:00Z")
    with _connect(db_path) as conn:
        recent = conn.execute(
            "SELECT COUNT(*) AS n FROM signal_sightings WHERE captured_at >= ?",
            (cutoff_ms,),
        ).fetchone()["n"]

    assert recent == 1
