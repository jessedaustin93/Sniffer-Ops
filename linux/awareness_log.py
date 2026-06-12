"""
Durable signal awareness log and LAN sync endpoint.
Wire-compatible with the Windows AwarenessLog.ps1 — same JSON schema,
same HTTP endpoints (port 8766), same merge logic.

Storage is delegated to db.py (SQLite/WAL).  This module owns only the
HTTP server layer, the display-classification helpers, and the public
API consumed by the GUI.
"""

import json
import math
import re
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import db
import signal_classifier as _sc

# ── Module-level state ────────────────────────────────────────────────────────

_node_id: str = ""
_node_name: str = ""
_log_path: str | None = None

_server: HTTPServer | None = None
_server_thread: threading.Thread | None = None

_NORMAL_BASELINE = 5  # seenCount threshold for "Normal" status


# ── Node identity ─────────────────────────────────────────────────────────────


def set_node_info(node_id: str, node_name: str) -> None:
    """Set the module-level node identity used by sync payloads."""
    global _node_id, _node_name
    _node_id = node_id
    _node_name = node_name


# ── Initialization ────────────────────────────────────────────────────────────


def initialize(path: str) -> None:
    """
    Initialize the awareness layer.

    *path* is the legacy JSON path (kept for backward compat / migration
    reference).  The SQLite database is created at the same location with
    the extension replaced by '.db'.
    """
    global _log_path
    _log_path = path
    db_path = path.replace(".json", ".db")
    db.initialize(db_path)
    db.migrate_json(path, _node_id)


# ── Numeric / geo helpers ─────────────────────────────────────────────────────


def _to_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip().rstrip("%"))
    except (ValueError, TypeError):
        return None


def _distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    r_lat1 = math.radians(lat1)
    r_lat2 = math.radians(lat2)
    a = (math.sin(d_lat / 2) ** 2 +
         math.cos(r_lat1) * math.cos(r_lat2) * math.sin(d_lon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _location_changed(prev: dict | None, cur: dict) -> bool:
    if not prev:
        return True
    p_lat = _to_number(prev.get("Latitude") or prev.get("latitude"))
    p_lon = _to_number(prev.get("Longitude") or prev.get("longitude"))
    c_lat = _to_number(cur.get("Latitude") or cur.get("latitude"))
    c_lon = _to_number(cur.get("Longitude") or cur.get("longitude"))
    if c_lat is None or c_lon is None:
        return False
    if p_lat is None or p_lon is None:
        return True
    return _distance_meters(p_lat, p_lon, c_lat, c_lon) >= 25.0


# ── Epoch-ms helpers ──────────────────────────────────────────────────────────


def _ms_to_iso(ms: int | None) -> str:
    """Convert epoch-milliseconds to an ISO-8601 UTC string, or '' if None."""
    if ms is None:
        return ""
    try:
        dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")
    except Exception:
        return ""


# ── Display helpers (operate on db row dicts) ─────────────────────────────────


def _display_name(profile: dict) -> str:
    """Strip BT service protocol suffixes (AVRCP, A2DP, etc.) from device names."""
    name = (profile.get("name") or profile.get("Name") or "").strip()
    sig_type = (profile.get("type") or profile.get("Type") or "").upper()
    if sig_type == "BLUETOOTH" and name:
        for suffix in (
            r"\s+AVRCP\s+TRANSPORT$", r"\s+A2DP\s+(SINK|SOURCE)$",
            r"\s+RFCOMM\s+.*$",       r"\s+HANDS[- ]FREE\s+.*$",
            r"\s+HEADSET\s+.*$",      r"\s+GATT\s+.*$",
            r"\s+HID\s+.*$",
        ):
            trimmed = re.sub(suffix, "", name, flags=re.IGNORECASE).strip()
            if trimmed and trimmed != name:
                return trimmed
    return name


def _display_group_key(profile: dict) -> str:
    """Key used to merge duplicate profiles (same device seen by multiple nodes)."""
    sig_type = (profile.get("type") or profile.get("Type") or "UNKNOWN").upper()
    name = re.sub(r"\s+", " ", _display_name(profile).upper()).strip()
    generic = {
        "", "UNKNOWN", "UNCLASSIFIED",
        "UNCLASSIFIED BLUETOOTH DEVICE OR SERVICE",
        "UNCLASSIFIED RF SIGNAL",
    }
    freq = profile.get("frequency_hz") or profile.get("FrequencyHz")
    addr = profile.get("address") or profile.get("Address") or ""
    key = profile.get("id") or profile.get("Key") or ""
    if sig_type not in ("SDR", "RTL_SDR") and name and name not in generic:
        return f"NAME|{sig_type}|{name}"
    if key:
        return f"KEY|{key}"
    return f"RAW|{sig_type}|{name}|{addr}|{freq or ''}"


def _class_rank(class_name: str) -> int:
    return {"Alert": 5, "Watch": 4, "Noticed": 3,
            "One-off": 2, "Learning": 1, "Normal": 0}.get(class_name, 0)


def _profile_class(profile: dict) -> str:
    """Compute the display class (Alert/Watch/Noticed/One-off/Learning/Normal)."""
    # Timeline is stored as a JSON string in the db row
    raw_timeline = profile.get("timeline") or profile.get("Timeline") or []
    if isinstance(raw_timeline, str):
        try:
            timeline = json.loads(raw_timeline)
        except (json.JSONDecodeError, TypeError):
            timeline = []
    else:
        timeline = raw_timeline

    last_event = timeline[-1]["Summary"] if timeline else ""
    notes_text = " ".join(filter(None, [
        last_event,
        profile.get("notes") or profile.get("Notes") or "",
    ]))
    alert = _sc.classify_alert(
        profile.get("name") or profile.get("Name") or "",
        profile.get("type") or profile.get("Type") or "",
        profile.get("device_class") or profile.get("SpecificType") or "",
        profile.get("threat_level") or profile.get("ThreatLevel") or "",
        notes_text,
    )
    seen = int(profile.get("seen_count") or profile.get("SeenCount") or 0)
    level = alert["level"]
    if level == "HIGH":
        return "Alert"
    if level == "MEDIUM":
        return "Watch"
    if level == "LOW":
        return "Noticed" if seen < _NORMAL_BASELINE else "Normal"
    if seen <= 1:
        return "One-off"
    if seen >= _NORMAL_BASELINE:
        return "Normal"
    return "Learning"


# ── Public API ────────────────────────────────────────────────────────────────


def merge_snapshot(snapshot: dict) -> dict:
    """Merge a remote sync snapshot into the local DB. Returns merge stats."""
    return db.merge_remote_snapshot(snapshot)


def get_sync_payload() -> dict:
    """Build and return a full wire-format sync payload from the local DB."""
    return db.build_sync_payload(_node_id, _node_name)


def get_rows() -> list[dict]:
    """
    Return a flat list of signal rows suitable for table display.
    Each row is keyed for the awareness table columns.
    Sorted by LastSeen descending.
    """
    profiles = db.get_all_profiles()
    rows = []
    for p in profiles:
        cls = _profile_class(p)
        last_seen_ms = p.get("last_seen")
        rows.append({
            "Type":               p.get("type") or "",
            "Signal":             _display_name(p),
            "AddressOrFrequency": p.get("address") or p.get("frequency_hz"),
            "StrengthOrPower":    p.get("last_signal"),
            "Classification":     p.get("device_class") or "",
            "Confidence":         cls,
            "LastSeen":           _ms_to_iso(last_seen_ms),
        })
    rows.sort(key=lambda r: r.get("LastSeen", ""), reverse=True)
    return rows


def get_display_profiles() -> list[dict]:
    """
    Grouped, classified profiles ready for the awareness strip and timeline view.
    Mirrors Get-AwarenessDisplayProfiles from SnifferOps.Windows.ps1.
    """
    profiles = db.get_all_profiles()

    raw: list[dict] = []
    for p in profiles:
        cls = _profile_class(p)

        raw_timeline = p.get("timeline") or "[]"
        if isinstance(raw_timeline, str):
            try:
                timeline = json.loads(raw_timeline)
            except (json.JSONDecodeError, TypeError):
                timeline = []
        else:
            timeline = raw_timeline

        node_ids_raw = p.get("node_ids") or "[]"
        if isinstance(node_ids_raw, str):
            try:
                node_ids = json.loads(node_ids_raw)
            except (json.JSONDecodeError, TypeError):
                node_ids = []
        else:
            node_ids = node_ids_raw

        last_seen_iso = _ms_to_iso(p.get("last_seen"))

        raw.append({
            "Key":                p.get("id") or "",
            "Name":               _display_name(p),
            "RawName":            p.get("name") or "",
            "Address":            p.get("address") or "",
            "FrequencyHz":        p.get("frequency_hz"),
            "Type":               p.get("type") or "",
            "SpecificType":       p.get("device_class") or "",
            "ThreatLevel":        p.get("threat_level") or "",
            "SeenCount":          int(p.get("seen_count") or 0),
            "NodeCount":          len(node_ids),
            "LastSeen":           last_seen_iso,
            "LastSignal":         p.get("last_signal"),
            "Class":              cls,
            "LastEvent":          timeline[-1]["Summary"] if timeline else "",
            "Sightings":          [],   # sightings not bulk-loaded here for perf
            "Timeline":           timeline,
            "EstimatedLatitude":  p.get("estimated_latitude"),
            "EstimatedLongitude": p.get("estimated_longitude"),
        })

    groups: dict[str, list[dict]] = {}
    for p in raw:
        groups.setdefault(_display_group_key(p), []).append(p)

    rows: list[dict] = []
    for members in groups.values():
        if not members:
            continue
        primary = sorted(
            members,
            key=lambda m: (_class_rank(m["Class"]), m["LastSeen"]),
            reverse=True,
        )[0]
        latest = max(members, key=lambda m: m["LastSeen"])
        types = ", ".join(dict.fromkeys(
            m["SpecificType"] for m in members if m["SpecificType"]
        ))
        raw_ids = ", ".join(dict.fromkeys(
            str(m["Address"]) if m["Address"]
            else (str(m["FrequencyHz"]) if m["FrequencyHz"] else (m["Key"] or ""))
            for m in members
        ))
        all_sightings = [s for m in members for s in m["Sightings"]]
        node_count = max(
            primary["NodeCount"],
            len({s.get("NodeId") for s in all_sightings if s.get("NodeId")}),
        )
        last_event = (
            f"Grouped {len(members)} matching IDs; {latest['LastEvent']}"
            if len(members) > 1 else latest["LastEvent"]
        )
        rows.append({
            "Class":            primary["Class"],
            "Signal":           primary["Name"],
            "Type":             types or primary["SpecificType"],
            "SourceType":       primary["Type"],
            "ThreatLevel":      primary["ThreatLevel"],
            "Seen":             sum(m["SeenCount"] for m in members),
            "Nodes":            node_count,
            "Last":             latest["LastSeen"],
            "LastEvent":        last_event,
            "Strength":         latest["LastSignal"],
            "RawIds":           raw_ids,
            "CombinedProfiles": len(members),
            "TimelineCount":    sum(len(m["Timeline"]) for m in members),
            "Sightings":        all_sightings,
        })

    rows.sort(
        key=lambda r: (_class_rank(r["Class"]), r["Seen"], r["Last"]),
        reverse=True,
    )
    return rows


def get_scan_locations() -> list[dict]:
    """
    Returns deduplicated scan locations with signal and interesting-signal counts.
    Each location key is a 'lat,lon' string rounded to 4 decimal places (~11 m).
    Sources data from db.get_sightings_for_placement() joined with profile classes.
    """
    profiles = db.get_all_profiles()
    # Build a map of profile_id -> class for interesting-signal detection
    class_map: dict[str, str] = {p["id"]: _profile_class(p) for p in profiles}

    sightings = db.get_sightings_for_placement()

    points: dict[str, dict] = {}
    # Track which profiles have already been counted at each location
    seen_at: dict[str, set] = {}

    for s in sightings:
        lat = _to_number(s.get("latitude"))
        lon = _to_number(s.get("longitude"))
        if lat is None or lon is None:
            continue
        loc_key = f"{lat:.4f},{lon:.4f}"
        device_id = s.get("device_id") or ""
        pair = (loc_key, device_id)
        if pair in seen_at.get(loc_key, set()):
            continue
        seen_at.setdefault(loc_key, set()).add(device_id)

        if loc_key not in points:
            points[loc_key] = {"key": loc_key, "signal_count": 0, "interesting_count": 0}
        points[loc_key]["signal_count"] += 1
        cls = class_map.get(device_id, "")
        if cls in ("Alert", "Watch", "Noticed", "One-off"):
            points[loc_key]["interesting_count"] += 1

    return sorted(points.values(), key=lambda p: p["signal_count"], reverse=True)


# ── HTTP server ───────────────────────────────────────────────────────────────


class _SyncHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress default access log

    def _send_json(self, body: dict, status: int = 200) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.lower().split("?")[0]
        if path == "/snifferops/health":
            self._send_json({"ok": True, "service": "snifferops-awareness", "platform": "linux"})
        elif path == "/snifferops/awareness":
            self._send_json(get_sync_payload())
        elif path == "/snifferops/sdr/deep-scan/status":
            self._send_json({"status": "idle"})
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = self.path.lower().split("?")[0]
        if path == "/snifferops/sync":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8")
                snapshot = json.loads(body)
                result = merge_snapshot(snapshot)
                payload = get_sync_payload()
                payload["merged"] = result.get("merged", 0)
                # Return the UUIDs of every sighting we successfully assimilated
                # so the sending node (Windows/Android/Linux) can compact its journal
                acked = [
                    s.get("id")
                    for sig in snapshot.get("signals", [])
                    for s in (sig.get("sightings") or [])
                    if s.get("id")
                ]
                payload["acknowledgedSightingIds"] = acked
                self._send_json(payload)
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)
        elif path == "/snifferops/sdr/deep-scan":
            self._send_json({"accepted": True, "status": "queued"})
        else:
            self._send_json({"error": "not found"}, 404)


def start_server(bind: str = "0.0.0.0", port: int = 8766) -> None:
    global _server, _server_thread
    if _server:
        return
    _server = HTTPServer((bind, port), _SyncHandler)
    _server_thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _server_thread.start()


def stop_server() -> None:
    global _server, _server_thread
    if _server:
        _server.shutdown()
        _server = None
    _server_thread = None
