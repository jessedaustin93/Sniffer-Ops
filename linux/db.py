"""
SnifferOps Linux — SQLite persistence layer.

Provides durable storage for signal profiles and sightings with
WAL-mode SQLite, optional GPS position averaging, sync-state tracking,
and a JSON-legacy migration path from awareness.json.
"""

import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Optional

# ── Module-level state ────────────────────────────────────────────────────────

_DB_PATH: Optional[str] = None
_write_lock = threading.Lock()

# ── Internal helpers ──────────────────────────────────────────────────────────


def _now_ms() -> int:
    return int(time.time() * 1000)


@contextmanager
def _connect():
    """Yield a WAL-mode, foreign-key-enabled sqlite3 connection."""
    if _DB_PATH is None:
        raise RuntimeError("db not initialized — call db.initialize() first")
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS signal_profiles (
            id                TEXT PRIMARY KEY,
            name              TEXT,
            address           TEXT,
            type              TEXT,
            manufacturer      TEXT,
            device_class      TEXT,
            is_encrypted      INTEGER DEFAULT 0,
            channel           TEXT,
            frequency_hz      REAL,
            threat_level      TEXT DEFAULT 'NORMAL',
            notes             TEXT,
            first_seen        INTEGER,
            last_seen         INTEGER,
            seen_count        INTEGER DEFAULT 0,
            strongest_signal  REAL,
            last_signal       REAL,
            presence_state    TEXT DEFAULT 'seen',
            last_present_at   INTEGER,
            last_missing_at   INTEGER,
            node_ids          TEXT DEFAULT '[]',
            estimated_latitude  REAL,
            estimated_longitude REAL,
            timeline          TEXT DEFAULT '[]'
        );

        CREATE TABLE IF NOT EXISTS signal_sightings (
            id              TEXT PRIMARY KEY,
            device_id       TEXT NOT NULL REFERENCES signal_profiles(id) ON DELETE CASCADE,
            node_id         TEXT NOT NULL,
            captured_at     INTEGER NOT NULL,
            signal_strength REAL,
            latitude        REAL,
            longitude       REAL,
            accuracy_meters REAL,
            synced_at       INTEGER
        );

        CREATE INDEX IF NOT EXISTS idx_sightings_device   ON signal_sightings(device_id);
        CREATE INDEX IF NOT EXISTS idx_sightings_captured ON signal_sightings(captured_at);
        CREATE INDEX IF NOT EXISTS idx_sightings_node     ON signal_sightings(node_id);
        CREATE INDEX IF NOT EXISTS idx_sightings_synced   ON signal_sightings(synced_at);
        CREATE INDEX IF NOT EXISTS idx_profiles_type      ON signal_profiles(type);
        CREATE INDEX IF NOT EXISTS idx_profiles_last_seen ON signal_profiles(last_seen);
    """)
    conn.commit()


# ── SDR helpers (mirrored from awareness_log.py) ───────────────────────────────


def _to_number(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(str(value).strip().rstrip("%"))
    except (ValueError, TypeError):
        return None


def _sdr_class_group(signal: dict) -> str:
    parts = " ".join(filter(None, [
        signal.get("deviceClass", ""),
        signal.get("device_class", ""),
        signal.get("name", ""),
        signal.get("notes", ""),
        signal.get("modulation", ""),
        signal.get("label", ""),
    ])).lower()
    if "broadcast fm" in parts or "fm/rbds" in parts:
        return "broadcast-fm"
    if "military aviation" in parts or "uhf air" in parts:
        return "mil-airband"
    if any(x in parts for x in ("aviation airband", "airband", "am aviation", "am/vor", "nav beacon")):
        return "airband"
    if "noaa weather" in parts:
        return "noaa-weather"
    if any(x in parts for x in ("vhf land mobile", "business", "railroad", "marine", "public service")):
        return "vhf-land-mobile"
    if "amateur radio 70cm" in parts or "amateur 70cm" in parts:
        return "amateur-70cm"
    if "amateur radio 2m" in parts or "amateur 2m" in parts:
        return "amateur-2m"
    if any(x in parts for x in ("lte", "cellular", "gsm", "aws", "pcs")):
        return "cellular"
    if any(x in parts for x in ("ads-b", "mode s", "uat")):
        return "adsb"
    if any(x in parts for x in ("ism", "lora", "fsk", "ook")):
        return "ism"
    if any(x in parts for x in ("tv", "broadcast auxiliary")):
        return "broadcast-tv"
    if any(x in parts for x in ("p25", "trunked", "public safety")):
        return "trunked-radio"
    return "rf"


def _sdr_bucket_hz(class_group: str) -> float:
    buckets = {
        "broadcast-fm":  200_000.0,
        "cellular":    1_000_000.0,
        "broadcast-tv": 1_000_000.0,
        "adsb":          250_000.0,
        "ism":           500_000.0,
    }
    return buckets.get(class_group, 250_000.0)


# ── Public API ────────────────────────────────────────────────────────────────


def initialize(path: str) -> None:
    """
    Set the module-level DB path, create the data directory, create the
    schema (WAL mode, foreign_keys ON), and migrate legacy awareness.json
    if it exists alongside the database file.
    """
    global _DB_PATH
    _DB_PATH = path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with _connect() as conn:
        _create_schema(conn)

    json_path = os.path.join(os.path.dirname(path), "awareness.json")
    if os.path.exists(json_path):
        node_id = "legacy-migration"
        migrate_json(json_path, node_id)


def signal_profile_id(signal: dict) -> str:
    """
    Compute a stable, cross-platform profile key for a signal dict.

    - WiFi / BT / generic: "{TYPE}|{IDENT.upper()}"
      where IDENT is the first non-empty of: address, id, frequencyHz, name
    - RTL_SDR: "RTL_SDR|{class_group}|{freq_bucket}"
    - If no identifier at all: a fresh uuid4 hex string
    """
    sig_type = (
        signal.get("type") or signal.get("signalType") or "UNKNOWN"
    ).strip().upper()

    if sig_type == "RTL_SDR":
        freq = _to_number(signal.get("frequencyHz"))
        if freq is not None:
            cg = _sdr_class_group(signal)
            bucket_hz = _sdr_bucket_hz(cg)
            bucket = int(round(freq / bucket_hz) * bucket_hz)
            return f"RTL_SDR|{cg}|{bucket}"

    ident = (
        signal.get("address")
        or signal.get("id")
        or str(signal.get("frequencyHz") or "")
        or signal.get("name")
        or ""
    ).strip()

    if not ident:
        return uuid.uuid4().hex

    return f"{sig_type}|{ident.upper()}"


def write_detection(
    signal: dict,
    node_id: str,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    accuracy: Optional[float] = None,
    now_ms: Optional[int] = None,
) -> str:
    """
    Persist one signal detection.

    1. Generate a new sighting UUID.
    2. UPSERT signal_profiles (INSERT first time, UPDATE on conflict).
    3. INSERT OR IGNORE into signal_sightings.
    4. Recompute estimated_latitude/longitude as the mean of GPS sightings.
    5. Return the sighting UUID.
    """
    if now_ms is None:
        now_ms = _now_ms()

    profile_id = signal_profile_id(signal)
    sighting_id = uuid.uuid4().hex

    sig_lat = _to_number(signal.get("latitude")) if lat is None else lat
    sig_lon = _to_number(signal.get("longitude")) if lon is None else lon
    sig_acc = _to_number(signal.get("accuracyMeters")) if accuracy is None else accuracy
    strength = _to_number(signal.get("signalStrength"))

    name = signal.get("name") or ""
    address = signal.get("address") or ""
    sig_type = (signal.get("type") or signal.get("signalType") or "UNKNOWN").upper()
    manufacturer = signal.get("manufacturer") or ""
    device_class = signal.get("deviceClass") or signal.get("device_class") or ""
    is_encrypted = 1 if signal.get("isEncrypted") or signal.get("is_encrypted") else 0
    channel = signal.get("channel") or None
    frequency_hz = _to_number(signal.get("frequencyHz"))
    threat_level = signal.get("threatLevel") or signal.get("threat_level") or "NORMAL"
    notes = signal.get("notes") or ""

    with _write_lock:
        with _connect() as conn:
            # UPSERT profile
            conn.execute(
                """
                INSERT INTO signal_profiles (
                    id, name, address, type, manufacturer, device_class,
                    is_encrypted, channel, frequency_hz, threat_level, notes,
                    first_seen, last_seen, seen_count, strongest_signal, last_signal,
                    presence_state, last_present_at, node_ids, timeline
                ) VALUES (
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, 1, ?, ?,
                    'seen', ?, '[]', '[]'
                )
                ON CONFLICT(id) DO UPDATE SET
                    name             = COALESCE(NULLIF(excluded.name, ''), signal_profiles.name),
                    address          = COALESCE(NULLIF(excluded.address, ''), signal_profiles.address),
                    manufacturer     = COALESCE(NULLIF(excluded.manufacturer, ''), signal_profiles.manufacturer),
                    device_class     = COALESCE(NULLIF(excluded.device_class, ''), signal_profiles.device_class),
                    is_encrypted     = CASE WHEN excluded.is_encrypted = 1 THEN 1 ELSE signal_profiles.is_encrypted END,
                    channel          = COALESCE(excluded.channel, signal_profiles.channel),
                    frequency_hz     = COALESCE(excluded.frequency_hz, signal_profiles.frequency_hz),
                    threat_level     = COALESCE(NULLIF(excluded.threat_level, ''), signal_profiles.threat_level),
                    notes            = COALESCE(NULLIF(excluded.notes, ''), signal_profiles.notes),
                    last_seen        = excluded.last_seen,
                    seen_count       = signal_profiles.seen_count + 1,
                    strongest_signal = CASE
                        WHEN excluded.strongest_signal IS NOT NULL
                         AND (signal_profiles.strongest_signal IS NULL
                              OR excluded.strongest_signal > signal_profiles.strongest_signal)
                        THEN excluded.strongest_signal
                        ELSE signal_profiles.strongest_signal
                    END,
                    last_signal      = excluded.last_signal,
                    presence_state   = 'seen',
                    last_present_at  = excluded.last_present_at
                """,
                (
                    profile_id, name, address, sig_type, manufacturer, device_class,
                    is_encrypted, channel, frequency_hz, threat_level, notes,
                    now_ms, now_ms, strength, strength,
                    now_ms,
                ),
            )

            # Update node_ids JSON array
            row = conn.execute(
                "SELECT node_ids FROM signal_profiles WHERE id=?", (profile_id,)
            ).fetchone()
            if row:
                try:
                    node_ids = json.loads(row["node_ids"] or "[]")
                except (json.JSONDecodeError, TypeError):
                    node_ids = []
                if node_id not in node_ids:
                    node_ids.append(node_id)
                    conn.execute(
                        "UPDATE signal_profiles SET node_ids=? WHERE id=?",
                        (json.dumps(node_ids), profile_id),
                    )

            # Insert sighting
            conn.execute(
                """
                INSERT OR IGNORE INTO signal_sightings (
                    id, device_id, node_id, captured_at,
                    signal_strength, latitude, longitude, accuracy_meters, synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (sighting_id, profile_id, node_id, now_ms,
                 strength, sig_lat, sig_lon, sig_acc),
            )

            # Recompute estimated position from GPS sightings
            geo = conn.execute(
                """
                SELECT AVG(latitude) AS avg_lat, AVG(longitude) AS avg_lon
                FROM signal_sightings
                WHERE device_id=? AND latitude IS NOT NULL AND longitude IS NOT NULL
                """,
                (profile_id,),
            ).fetchone()
            if geo and geo["avg_lat"] is not None:
                conn.execute(
                    """
                    UPDATE signal_profiles
                    SET estimated_latitude=?, estimated_longitude=?
                    WHERE id=?
                    """,
                    (geo["avg_lat"], geo["avg_lon"], profile_id),
                )

            conn.commit()

    return sighting_id


def get_live_profiles(type_: str, window_seconds: float) -> list[dict]:
    """
    Return profiles of the given type seen within the last *window_seconds* seconds,
    ordered by last_seen DESC.
    """
    cutoff_ms = _now_ms() - int(window_seconds * 1000)
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM signal_profiles
            WHERE type=? AND last_seen >= ?
            ORDER BY last_seen DESC
            """,
            (type_.upper(), cutoff_ms),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_profiles() -> list[dict]:
    """Return all signal profiles ordered by last_seen DESC."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM signal_profiles ORDER BY last_seen DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_sightings_for_placement() -> list[dict]:
    """
    Return all sightings joined with their profile type,
    ordered by captured_at DESC. Used for placement / map display.
    """
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT ss.*, sp.type AS signal_type
            FROM signal_sightings ss
            JOIN signal_profiles sp ON ss.device_id = sp.id
            ORDER BY ss.captured_at DESC
            """,
        ).fetchall()
    return [dict(r) for r in rows]


def get_unsynced_sightings(limit: int = 500) -> list[dict]:
    """
    Return up to *limit* unsynced sightings joined with enough profile
    fields to build a full sync payload.
    """
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                ss.id,
                ss.device_id,
                ss.node_id,
                ss.captured_at,
                ss.signal_strength,
                ss.latitude,
                ss.longitude,
                ss.accuracy_meters,
                sp.name,
                sp.address,
                sp.type,
                sp.device_class,
                sp.manufacturer,
                sp.threat_level,
                sp.frequency_hz,
                sp.channel,
                sp.first_seen,
                sp.last_seen,
                sp.seen_count,
                sp.strongest_signal,
                sp.is_encrypted,
                sp.notes
            FROM signal_sightings ss
            JOIN signal_profiles sp ON ss.device_id = sp.id
            WHERE ss.synced_at IS NULL
            ORDER BY ss.captured_at ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def count_unsynced() -> int:
    """Return the total number of sightings that have not yet been synced."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM signal_sightings WHERE synced_at IS NULL"
        ).fetchone()
    return row["n"] if row else 0


def count_syncable_compact() -> int:
    """Return the number of sightings that have been synced (synced_at IS NOT NULL)."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM signal_sightings WHERE synced_at IS NOT NULL"
        ).fetchone()
    return row["n"] if row else 0


def mark_synced(sighting_ids: list[str]) -> None:
    """
    Mark the given sighting IDs as synced (only if not already synced).
    """
    if not sighting_ids:
        return
    now_ms = _now_ms()
    with _write_lock:
        with _connect() as conn:
            placeholders = ",".join("?" * len(sighting_ids))
            conn.execute(
                f"""
                UPDATE signal_sightings
                SET synced_at=?
                WHERE id IN ({placeholders}) AND synced_at IS NULL
                """,
                [now_ms] + list(sighting_ids),
            )
            conn.commit()


def get_synced_sighting_ids() -> list[str]:
    """Return all sighting IDs that have been acknowledged (synced_at IS NOT NULL)."""
    if not _DB_PATH:
        return []
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id FROM signal_sightings WHERE synced_at IS NOT NULL"
        ).fetchall()
        return [r[0] for r in rows]


def compact_acknowledged(sighting_ids: list[str]) -> int:
    """
    Delete synced sightings to reclaim space.  Only rows with
    synced_at IS NOT NULL are deleted.  Returns the number of rows removed.
    """
    if not sighting_ids:
        return 0
    with _write_lock:
        with _connect() as conn:
            placeholders = ",".join("?" * len(sighting_ids))
            cur = conn.execute(
                f"""
                DELETE FROM signal_sightings
                WHERE id IN ({placeholders}) AND synced_at IS NOT NULL
                """,
                list(sighting_ids),
            )
            conn.commit()
    return cur.rowcount


def merge_remote_snapshot(snapshot: dict) -> dict:
    """
    Idempotently merge a remote sync snapshot into the local database.

    - For each signal in snapshot["signals"], UPSERT the profile.
    - For each sighting in signal["sightings"], INSERT OR IGNORE by UUID.
    - Remote sightings are pre-acknowledged (synced_at = now_ms).
    - Recomputes estimated positions after merge.
    - Returns {"merged": N, "total_signals": M}.
    """
    now_ms = _now_ms()
    signals = snapshot.get("signals") or []
    merged = 0

    with _write_lock:
        with _connect() as conn:
            for signal in signals:
                profile_id = signal_profile_id(signal)
                name = signal.get("name") or ""
                address = signal.get("address") or ""
                sig_type = (signal.get("type") or "UNKNOWN").upper()
                manufacturer = signal.get("manufacturer") or ""
                device_class = signal.get("deviceClass") or signal.get("device_class") or ""
                is_encrypted = 1 if signal.get("isEncrypted") else 0
                channel = signal.get("channel") or None
                frequency_hz = _to_number(signal.get("frequencyHz"))
                threat_level = signal.get("threatLevel") or "NORMAL"
                notes = signal.get("notes") or ""
                first_seen_val = signal.get("firstSeen") or now_ms
                last_seen_val = signal.get("lastSeen") or now_ms
                seen_count_val = signal.get("seenCount") or 0
                strongest = _to_number(signal.get("strongestSignal") or signal.get("signalStrength"))
                # Accept GPS at the profile level — Windows sends estimatedLatitude/
                # estimatedLongitude (no per-sighting records); _to_snapshot_signals()
                # normalises both names to "latitude"/"longitude".
                profile_lat = _to_number(
                    signal.get("latitude") or signal.get("estimatedLatitude")
                )
                profile_lon = _to_number(
                    signal.get("longitude") or signal.get("estimatedLongitude")
                )

                conn.execute(
                    """
                    INSERT INTO signal_profiles (
                        id, name, address, type, manufacturer, device_class,
                        is_encrypted, channel, frequency_hz, threat_level, notes,
                        first_seen, last_seen, seen_count, strongest_signal, last_signal,
                        presence_state, last_present_at, node_ids, timeline,
                        estimated_latitude, estimated_longitude
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        'seen', ?, '[]', '[]',
                        ?, ?
                    )
                    ON CONFLICT(id) DO UPDATE SET
                        name             = COALESCE(NULLIF(excluded.name, ''), signal_profiles.name),
                        address          = COALESCE(NULLIF(excluded.address, ''), signal_profiles.address),
                        manufacturer     = COALESCE(NULLIF(excluded.manufacturer, ''), signal_profiles.manufacturer),
                        device_class     = COALESCE(NULLIF(excluded.device_class, ''), signal_profiles.device_class),
                        frequency_hz     = COALESCE(excluded.frequency_hz, signal_profiles.frequency_hz),
                        threat_level     = COALESCE(NULLIF(excluded.threat_level, ''), signal_profiles.threat_level),
                        notes            = COALESCE(NULLIF(excluded.notes, ''), signal_profiles.notes),
                        last_seen        = MAX(signal_profiles.last_seen, excluded.last_seen),
                        seen_count       = MAX(signal_profiles.seen_count, excluded.seen_count),
                        strongest_signal = CASE
                            WHEN excluded.strongest_signal IS NOT NULL
                             AND (signal_profiles.strongest_signal IS NULL
                                  OR excluded.strongest_signal > signal_profiles.strongest_signal)
                            THEN excluded.strongest_signal
                            ELSE signal_profiles.strongest_signal
                        END,
                        estimated_latitude  = COALESCE(excluded.estimated_latitude,
                                                        signal_profiles.estimated_latitude),
                        estimated_longitude = COALESCE(excluded.estimated_longitude,
                                                        signal_profiles.estimated_longitude)
                    """,
                    (
                        profile_id, name, address, sig_type, manufacturer, device_class,
                        is_encrypted, channel, frequency_hz, threat_level, notes,
                        first_seen_val, last_seen_val, seen_count_val, strongest, strongest,
                        now_ms,
                        profile_lat, profile_lon,
                    ),
                )

                # Insert remote sightings as pre-acknowledged
                for sighting in (signal.get("sightings") or []):
                    s_id = sighting.get("id") or uuid.uuid4().hex
                    s_node = sighting.get("nodeId") or snapshot.get("nodeId") or "remote"
                    s_at = sighting.get("capturedAt") or now_ms
                    s_sig = _to_number(sighting.get("signalStrength"))
                    s_lat = _to_number(sighting.get("latitude"))
                    s_lon = _to_number(sighting.get("longitude"))
                    s_acc = _to_number(sighting.get("accuracyMeters"))

                    conn.execute(
                        """
                        INSERT OR IGNORE INTO signal_sightings (
                            id, device_id, node_id, captured_at,
                            signal_strength, latitude, longitude, accuracy_meters,
                            synced_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (s_id, profile_id, s_node, s_at,
                         s_sig, s_lat, s_lon, s_acc, now_ms),
                    )

                # Recompute estimated position
                geo = conn.execute(
                    """
                    SELECT AVG(latitude) AS avg_lat, AVG(longitude) AS avg_lon
                    FROM signal_sightings
                    WHERE device_id=? AND latitude IS NOT NULL AND longitude IS NOT NULL
                    """,
                    (profile_id,),
                ).fetchone()
                if geo and geo["avg_lat"] is not None:
                    conn.execute(
                        """
                        UPDATE signal_profiles
                        SET estimated_latitude=?, estimated_longitude=?
                        WHERE id=?
                        """,
                        (geo["avg_lat"], geo["avg_lon"], profile_id),
                    )

                merged += 1

            conn.commit()

    total = len(get_all_profiles())
    return {"merged": merged, "total_signals": total}


def build_sync_payload(
    node_id: str,
    node_name: str,
    complete_types: Optional[list] = None,
) -> dict:
    """
    Build a schema-1 sync payload from the current DB state.

    For each profile, includes up to 20 unsynced sightings. The payload
    shape matches the SnifferOps wire format exactly.
    """
    now_ms = _now_ms()
    profiles = get_all_profiles()

    with _connect() as conn:
        signals_out = []
        for p in profiles:
            pid = p["id"]

            # Up to 20 unsynced sightings for this profile
            sighting_rows = conn.execute(
                """
                SELECT id, captured_at, signal_strength, latitude, longitude, accuracy_meters
                FROM signal_sightings
                WHERE device_id=? AND synced_at IS NULL
                ORDER BY captured_at DESC
                LIMIT 20
                """,
                (pid,),
            ).fetchall()

            sightings_out = [
                {
                    "id":             s["id"],
                    "capturedAt":     s["captured_at"],
                    "signalStrength": s["signal_strength"],
                    "latitude":       s["latitude"],
                    "longitude":      s["longitude"],
                    "accuracyMeters": s["accuracy_meters"],
                }
                for s in sighting_rows
            ]

            signals_out.append({
                "id":           pid,
                "name":         p.get("name") or "",
                "address":      p.get("address") or "",
                "type":         p.get("type") or "",
                "signalStrength":  p.get("last_signal"),
                "frequencyHz":  p.get("frequency_hz"),
                "manufacturer": p.get("manufacturer") or "",
                "deviceClass":  p.get("device_class") or "",
                "isEncrypted":  bool(p.get("is_encrypted")),
                "channel":      p.get("channel"),
                "latitude":     p.get("estimated_latitude"),
                "longitude":    p.get("estimated_longitude"),
                "threatLevel":  p.get("threat_level") or "NORMAL",
                "notes":        p.get("notes") or "",
                "firstSeen":    p.get("first_seen"),
                "lastSeen":     p.get("last_seen"),
                "seenCount":    p.get("seen_count") or 0,
                "sightings":    sightings_out,
            })

    payload: dict = {
        "schema":       1,
        "nodeId":       node_id,
        "nodeName":     node_name,
        "capturedAt":   now_ms,
        "totalSignals": len(signals_out),
        "signals":      signals_out,
    }
    if complete_types is not None:
        payload["completeTypes"] = complete_types

    return payload


def migrate_json(json_path: str, node_id: str) -> int:
    """
    Import legacy awareness.json into the SQLite database.

    Reads the top-level "Signals" dict (keys → signal profiles) and
    INSERTs each as a profile. Uses INSERT OR IGNORE so it is idempotent.
    Returns the number of profiles migrated.
    """
    try:
        with open(json_path, "r", encoding="utf-8") as fh:
            raw = fh.read()
        state = json.loads(raw) if raw.strip() else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return 0

    signals_dict = state.get("Signals") or {}
    if not signals_dict:
        return 0

    now_ms = _now_ms()
    count = 0

    with _write_lock:
        with _connect() as conn:
            for key, profile in signals_dict.items():
                # Build a canonical signal dict from the JSON profile shape
                signal = {
                    "type":         profile.get("Type") or "UNKNOWN",
                    "name":         profile.get("Name") or "",
                    "address":      profile.get("Address") or "",
                    "manufacturer": profile.get("Manufacturer") or "",
                    "deviceClass":  profile.get("SpecificType") or "",
                    "frequencyHz":  profile.get("FrequencyHz"),
                    "channel":      profile.get("Channel"),
                    "threatLevel":  profile.get("ThreatLevel") or "NORMAL",
                    "notes":        profile.get("Notes") or "",
                    "isEncrypted":  profile.get("IsEncrypted") or False,
                }
                profile_id = key  # use the canonical key as stored

                # Parse firstSeen / lastSeen (ISO strings) to epoch-ms
                def _iso_to_ms(iso_str: Optional[str]) -> Optional[int]:
                    if not iso_str:
                        return None
                    try:
                        from datetime import datetime, timezone
                        s = iso_str.replace("Z", "+00:00")
                        dt = datetime.fromisoformat(s)
                        return int(dt.timestamp() * 1000)
                    except Exception:
                        return None

                first_seen_ms = _iso_to_ms(profile.get("FirstSeen")) or now_ms
                last_seen_ms  = _iso_to_ms(profile.get("LastSeen"))  or now_ms
                seen_count    = int(profile.get("SeenCount") or 0)
                strongest     = _to_number(profile.get("StrongestSignalNumeric")
                                           or profile.get("StrongestSignal"))
                last_sig      = _to_number(profile.get("LastSignalNumeric")
                                           or profile.get("LastSignal"))
                is_encrypted  = 1 if signal.get("isEncrypted") else 0
                frequency_hz  = _to_number(signal.get("frequencyHz"))
                node_ids_list = profile.get("NodeIds") or [node_id]

                # Estimated position from sightings in the JSON
                sightings_json = profile.get("Sightings") or []
                geo = [
                    (float(s["Latitude"]), float(s["Longitude"]))
                    for s in sightings_json
                    if s.get("Latitude") is not None and s.get("Longitude") is not None
                ]
                est_lat = sum(g[0] for g in geo) / len(geo) if geo else None
                est_lon = sum(g[1] for g in geo) / len(geo) if geo else None

                conn.execute(
                    """
                    INSERT OR IGNORE INTO signal_profiles (
                        id, name, address, type, manufacturer, device_class,
                        is_encrypted, channel, frequency_hz, threat_level, notes,
                        first_seen, last_seen, seen_count,
                        strongest_signal, last_signal,
                        presence_state, last_present_at,
                        node_ids, estimated_latitude, estimated_longitude, timeline
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?, ?,
                        ?, ?,
                        ?, ?,
                        ?, ?, ?, '[]'
                    )
                    """,
                    (
                        profile_id,
                        signal["name"], signal["address"],
                        signal["type"].upper(),
                        signal["manufacturer"], signal["deviceClass"],
                        is_encrypted, signal["channel"], frequency_hz,
                        signal["threatLevel"], signal["notes"],
                        first_seen_ms, last_seen_ms, seen_count,
                        strongest, last_sig,
                        profile.get("PresenceState") or "seen",
                        _iso_to_ms(profile.get("LastPresentAt")) or last_seen_ms,
                        json.dumps(node_ids_list),
                        est_lat, est_lon,
                    ),
                )

                # Migrate individual sightings
                for s in sightings_json:
                    s_id = uuid.uuid4().hex
                    s_node = s.get("NodeId") or node_id
                    s_at = _iso_to_ms(s.get("At")) or now_ms
                    s_sig = _to_number(s.get("SignalStrengthNumeric") or s.get("SignalStrength"))
                    s_lat = _to_number(s.get("Latitude"))
                    s_lon = _to_number(s.get("Longitude"))
                    s_acc = _to_number(s.get("AccuracyMeters"))
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO signal_sightings (
                            id, device_id, node_id, captured_at,
                            signal_strength, latitude, longitude, accuracy_meters,
                            synced_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
                        """,
                        (s_id, profile_id, s_node, s_at,
                         s_sig, s_lat, s_lon, s_acc),
                    )

                count += 1

            conn.commit()

    return count
