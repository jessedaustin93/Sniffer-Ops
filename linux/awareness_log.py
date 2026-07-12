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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from typing import Any

import db
import inference_engine
import ownership
import signal_classifier as _sc
import signal_signatures as _sig
import version_info

# ── Module-level state ────────────────────────────────────────────────────────

_node_id: str = ""
_node_name: str = ""
_log_path: str | None = None

_server: ThreadingHTTPServer | None = None
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
    if ownership.is_trusted(profile):
        return "Normal"

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
    stats = db.merge_remote_snapshot(snapshot)
    try:
        inference_engine.recalculate_all()
    except Exception:
        pass
    return stats


def get_sync_payload() -> dict:
    """Build and return a full wire-format sync payload from the local DB."""
    return db.build_sync_payload(_node_id, _node_name)


def get_version_payload() -> dict:
    """Return structured product version metadata for API clients."""
    info = version_info.get_version_info()
    return {
        "product": info["product"],
        "slug": info["slug"],
        "version": info["version"],
        "build": info["build"],
        "full_version": info["full_version"],
        "channel": info["channel"],
        "commit": "",
        "platform": "linux",
        "service": "ethrox-detect-awareness",
    }


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
    Mirrors Get-AwarenessDisplayProfiles from Ethrox Detect Windows.
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
            "Notes":              p.get("notes") or "",
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
        cue = _sig.live_cue({
            "name": primary["RawName"] or primary["Name"],
            "address": primary["Address"],
            "type": primary["Type"],
            "deviceClass": types or primary["SpecificType"],
            "threatLevel": primary["ThreatLevel"],
            "notes": primary["Notes"],
            "signalStrength": latest["LastSignal"],
        })
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
            "LiveCue":          cue["label"] if cue["family"] else "",
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


def get_priority_findings() -> list[dict]:
    """Return structured Linux-hub findings for alert/evidence lenses."""
    findings = db.get_classifications()
    out = []
    for item in findings:
        evidence = db.get_classification_evidence(item["id"])
        out.append({
            "Id": item["id"],
            "Label": item.get("label", ""),
            "Family": item.get("family", ""),
            "Priority": item.get("priority", ""),
            "Confidence": item.get("confidence", ""),
            "Disposition": item.get("policy_disposition", ""),
            "PolicyReason": item.get("policy_reason", ""),
            "FirstSeen": _ms_to_iso(item.get("first_seen")),
            "LastSeen": _ms_to_iso(item.get("last_seen")),
            "ObservationCount": item.get("observation_count", 0),
            "SourceNodes": ", ".join(item.get("source_nodes") or []),
            "RelatedSignals": item.get("related_signal_ids") or [],
            "RecommendedAction": item.get("recommended_next_step", ""),
            "EvidenceSummary": "; ".join(e.get("summary", "") for e in evidence[:3] if e.get("summary")),
            "Evidence": evidence,
        })
    return out


# ── Web dashboard helpers ────────────────────────────────────────────────────


def get_web_status() -> dict:
    """
    Return a compact read-only dashboard payload for browser clients.
    This intentionally does not expose raw sync payload shape or packet data.
    """
    profiles = get_display_profiles()
    locations = get_scan_locations()

    class_counts = {
        "Alert": 0,
        "Watch": 0,
        "Noticed": 0,
        "One-off": 0,
        "Learning": 0,
        "Normal": 0,
    }
    type_counts: dict[str, int] = {}
    for p in profiles:
        class_counts[p.get("Class", "Normal")] = class_counts.get(p.get("Class", "Normal"), 0) + 1
        sig_type = p.get("SourceType") or "UNKNOWN"
        type_counts[sig_type] = type_counts.get(sig_type, 0) + 1

    recent = []
    for p in profiles[:80]:
        recent.append({
            "class": p.get("Class", ""),
            "name": p.get("DisplayName", ""),
            "type": p.get("SourceType", ""),
            "seen": p.get("Seen", 0),
            "nodes": p.get("Nodes", 0),
            "last": p.get("Last", ""),
            "strength": p.get("Strength"),
            "cue": p.get("LiveCue", ""),
            "event": p.get("LastEvent", ""),
        })

    return {
        "ok": True,
        "nodeId": _node_id,
        "nodeName": _node_name,
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "profileCount": len(profiles),
        "locationCount": len(locations),
        "classCounts": class_counts,
        "typeCounts": dict(sorted(type_counts.items())),
        "recent": recent,
        "locations": locations[:40],
    }


_WEB_APP_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Ethrox Detect</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #020617;
      --panel: #111827;
      --panel-2: #0b1120;
      --surface: #0f172a;
      --border: #255866;
      --border-green: #0b6b57;
      --text: #e5e7eb;
      --muted: #9ca3af;
      --dim: #6b7280;
      --green: #21f982;
      --green-2: #10b981;
      --cyan: #22d3ee;
      --blue: #00bfff;
      --blue-2: #0d84ff;
      --orange: #f59e0b;
      --purple: #8b5cf6;
      --pink: #ec4899;
      --red: #ef4444;
    }
    * { box-sizing: border-box; }
    html, body { min-height: 100%; }
    body {
      margin: 0;
      font-family: "Ubuntu Mono", "DejaVu Sans Mono", "Courier New", monospace;
      background-color: var(--bg);
      background-image:
        linear-gradient(rgba(11,58,53,0.48) 1px, transparent 1px),
        linear-gradient(90deg, rgba(11,58,53,0.48) 1px, transparent 1px);
      background-size: 28px 28px;
      color: var(--text);
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      min-height: 58px;
      padding: 10px 18px;
      border-bottom: 1px solid var(--border-green);
      background: #000;
    }
    h1 {
      margin: 0;
      color: var(--green);
      font-size: clamp(24px, 4vw, 34px);
      font-weight: 900;
      letter-spacing: 3px;
      text-transform: uppercase;
    }
    .sub {
      margin-top: 2px;
      color: #637082;
      font-size: 12px;
      letter-spacing: 1.5px;
      text-transform: uppercase;
    }
    .status {
      min-width: 220px;
      color: var(--green);
      text-align: right;
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 1px;
      text-transform: uppercase;
    }
    main {
      width: min(1480px, calc(100vw - 28px));
      margin: 0 auto;
      padding: 16px 0 76px;
    }
    .panel, .tile, section {
      background: rgba(17,24,39,0.94);
      border: 1px solid var(--border);
      border-radius: 6px;
    }
    .hero {
      display: grid;
      grid-template-columns: 190px minmax(220px, 1fr) 300px;
      gap: 12px;
      align-items: stretch;
      margin-bottom: 12px;
    }
    .radar-panel {
      min-height: 190px;
      display: grid;
      place-items: center;
      background: rgba(2,6,23,0.88);
      border-color: var(--border-green);
    }
    .radar {
      position: relative;
      width: 154px;
      height: 154px;
      border: 2px solid var(--green);
      border-radius: 50%;
      background:
        radial-gradient(circle, transparent 0 22%, rgba(33,249,130,0.16) 23% 24%, transparent 25% 47%, rgba(33,249,130,0.16) 48% 49%, transparent 50%),
        linear-gradient(rgba(33,249,130,0.18), rgba(33,249,130,0.18)) 50% 0 / 1px 100% no-repeat,
        linear-gradient(90deg, rgba(33,249,130,0.18), rgba(33,249,130,0.18)) 0 50% / 100% 1px no-repeat,
        radial-gradient(circle, rgba(33,249,130,0.10), rgba(2,6,23,0.18) 62%, rgba(2,6,23,0.75));
      box-shadow: 0 0 22px rgba(33,249,130,0.18), inset 0 0 18px rgba(33,249,130,0.12);
      overflow: hidden;
    }
    .radar::before {
      content: "";
      position: absolute;
      inset: 50% 50% 0 0;
      transform-origin: 100% 0;
      background: conic-gradient(from -22deg, rgba(33,249,130,0.55), rgba(33,249,130,0.08) 34deg, transparent 46deg);
      animation: sweep 3.6s linear infinite;
    }
    .radar::after {
      content: "SCAN";
      position: absolute;
      left: 50%;
      top: 50%;
      transform: translate(-50%, -50%);
      color: var(--green);
      font-size: 11px;
      font-weight: 900;
      letter-spacing: 1.5px;
      text-shadow: 0 0 8px rgba(33,249,130,0.55);
    }
    @keyframes sweep {
      to { transform: rotate(360deg); }
    }
    .stats-panel {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px 18px;
      padding: 18px;
      align-content: center;
    }
    .stat-row {
      display: grid;
      grid-template-columns: 18px 1fr auto;
      align-items: center;
      gap: 8px;
      min-height: 26px;
    }
    .dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: currentColor;
      box-shadow: 0 0 10px currentColor;
    }
    .stat-label {
      color: var(--muted);
      font-size: 13px;
      text-transform: uppercase;
    }
    .stat-value {
      font-size: 17px;
      font-weight: 900;
    }
    .wifi { color: var(--green); }
    .bt { color: var(--blue); }
    .cell { color: var(--orange); }
    .sdr { color: var(--purple); }
    .pink { color: var(--pink); }
    .alerts { color: var(--red); }
    .watch { color: var(--orange); }
    .awareness-panel {
      padding: 16px;
      display: grid;
      align-content: center;
      gap: 8px;
      background: rgba(2,6,23,0.88);
      border-color: var(--border-green);
    }
    .awareness-title {
      color: var(--cyan);
      font-size: 13px;
      font-weight: 900;
      letter-spacing: 1px;
      text-transform: uppercase;
    }
    .awareness-summary {
      color: var(--text);
      font-size: 24px;
      font-weight: 900;
    }
    .awareness-detail { color: var(--green-2); font-size: 12px; }
    .awareness-odd { color: var(--orange); font-size: 12px; }
    .tiles {
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 8px;
      margin-bottom: 12px;
    }
    .tile {
      min-height: 96px;
      padding: 12px 10px;
      display: grid;
      align-content: center;
      justify-items: center;
      gap: 5px;
    }
    .tile-count {
      font-size: 30px;
      line-height: 1;
      font-weight: 900;
    }
    .tile-label {
      color: var(--muted);
      font-size: 12px;
      letter-spacing: 1px;
      text-transform: uppercase;
    }
    .tile-sub {
      color: var(--dim);
      font-size: 11px;
      text-align: center;
      min-height: 14px;
    }
    .content {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 330px;
      gap: 12px;
      align-items: start;
    }
    section { overflow: hidden; }
    section h2 {
      margin: 0;
      padding: 11px 14px;
      border-bottom: 1px solid var(--border);
      color: var(--muted);
      background: var(--panel);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 2px;
    }
    table { width: 100%; border-collapse: collapse; }
    th, td {
      padding: 9px 11px;
      border-bottom: 1px solid rgba(37,88,102,0.55);
      text-align: left;
      font-size: 12px;
      vertical-align: top;
    }
    th {
      color: var(--muted);
      font-weight: 900;
      background: var(--panel-2);
      text-transform: uppercase;
      letter-spacing: 1px;
      font-size: 11px;
    }
    tbody tr:nth-child(odd) { background: var(--panel-2); }
    tbody tr:nth-child(even) { background: var(--surface); }
    tbody tr:hover { background: rgba(37,88,102,0.40); }
    tr:last-child td { border-bottom: 0; }
    .name { font-weight: 900; color: var(--text); }
    .muted { color: var(--muted); }
    .pill {
      display: inline-flex;
      align-items: center;
      min-width: 68px;
      justify-content: center;
      border-radius: 4px;
      padding: 3px 8px;
      font-size: 11px;
      font-weight: 900;
      color: var(--text);
      border: 1px solid currentColor;
      background: rgba(16,185,129,0.08);
      text-transform: uppercase;
    }
    .Alert { color: var(--red); background: rgba(239,68,68,0.10); }
    .Watch { color: var(--orange); background: rgba(245,158,11,0.10); }
    .Noticed { color: var(--cyan); background: rgba(34,211,238,0.10); }
    .One-off { color: var(--blue); background: rgba(0,191,255,0.10); }
    .Learning { color: var(--muted); background: rgba(156,163,175,0.10); }
    .Normal { color: var(--green-2); background: rgba(16,185,129,0.10); }
    .side { display: grid; gap: 12px; }
    .list { padding: 6px 0; }
    .item {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      padding: 9px 12px;
      border-bottom: 1px solid rgba(37,88,102,0.55);
      font-size: 12px;
    }
    .item:last-child { border-bottom: 0; }
    .count { color: var(--green); font-weight: 900; }
    .bottom-nav {
      position: fixed;
      left: 0;
      right: 0;
      bottom: 0;
      display: grid;
      grid-template-columns: repeat(6, 1fr);
      gap: 0;
      border-top: 1px solid var(--border-green);
      background: #000;
      z-index: 10;
    }
    .nav-item {
      min-height: 44px;
      display: grid;
      place-items: center;
      color: var(--muted);
      font-size: 11px;
      font-weight: 900;
      letter-spacing: 1px;
      line-height: 1.15;
      padding: 4px 2px;
      text-align: center;
      text-transform: uppercase;
      border-right: 1px solid rgba(11,107,87,0.45);
    }
    .nav-item:first-child { color: var(--green); }
    .nav-item:last-child { border-right: 0; }
    @media (max-width: 900px) {
      header { align-items: start; flex-direction: column; }
      .status { text-align: left; }
      main { width: calc(100vw - 18px); padding-top: 10px; }
      .hero, .content { grid-template-columns: 1fr; }
      .stats-panel, .tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .radar-panel { min-height: 174px; }
      .nav-item { font-size: 9px; letter-spacing: 0.4px; }
      th:nth-child(6), td:nth-child(6) { display: none; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Ethrox Detect</h1>
      <div class="sub" id="node">Loading T5810B awareness hub...</div>
    </div>
    <div class="status" id="status">Connecting</div>
  </header>
  <main>
    <div class="hero">
      <div class="panel radar-panel"><div class="radar"></div></div>
      <div class="panel stats-panel">
        <div class="stat-row wifi"><span class="dot"></span><span class="stat-label">WiFi</span><span class="stat-value" id="stat-wifi">-</span></div>
        <div class="stat-row bt"><span class="dot"></span><span class="stat-label">BT/BLE</span><span class="stat-value" id="stat-bt">-</span></div>
        <div class="stat-row cell"><span class="dot"></span><span class="stat-label">CELL</span><span class="stat-value" id="stat-cell">-</span></div>
        <div class="stat-row sdr"><span class="dot"></span><span class="stat-label">SDR</span><span class="stat-value" id="stat-sdr">-</span></div>
        <div class="stat-row alerts"><span class="dot"></span><span class="stat-label">ALERTS</span><span class="stat-value" id="stat-alerts">-</span></div>
        <div class="stat-row watch"><span class="dot"></span><span class="stat-label">WATCH</span><span class="stat-value" id="stat-watch">-</span></div>
      </div>
      <div class="panel awareness-panel">
        <div class="awareness-title">Awareness</div>
        <div class="awareness-summary" id="aw-summary">- known / - locations</div>
        <div class="awareness-detail" id="aw-detail">Normal baseline loading</div>
        <div class="awareness-odd" id="aw-odd">Alerts: - / Watch: - / Noticed: -</div>
      </div>
    </div>
    <div class="tiles">
      <div class="tile"><div class="tile-count wifi" id="tile-wifi">-</div><div class="tile-label">WiFi</div><div class="tile-sub">Linux WLAN scan</div></div>
      <div class="tile"><div class="tile-count bt" id="tile-bt">-</div><div class="tile-label">Bluetooth</div><div class="tile-sub">BT/BLE discovery</div></div>
      <div class="tile"><div class="tile-count pink" id="tile-nfc">0</div><div class="tile-label">NFC</div><div class="tile-sub">Android only</div></div>
      <div class="tile"><div class="tile-count cell" id="tile-cell">-</div><div class="tile-label">Cellular</div><div class="tile-sub">Android feed</div></div>
      <div class="tile"><div class="tile-count sdr" id="tile-sdr">-</div><div class="tile-label">SDR Radio</div><div class="tile-sub">RTL-SDR hub</div></div>
      <div class="tile"><div class="tile-count alerts" id="tile-alerts">-</div><div class="tile-label">Alerts</div><div class="tile-sub">Local app status</div></div>
    </div>
    <div class="content">
      <section>
        <h2>Recent Signal Profiles</h2>
        <table>
          <thead>
            <tr><th>Class</th><th>Signal</th><th>Cue</th><th>Type</th><th>Seen</th><th>Last Event</th></tr>
          </thead>
          <tbody id="rows"><tr><td colspan="6" class="muted">Loading...</td></tr></tbody>
        </table>
      </section>
      <div class="side">
        <section>
          <h2>Signal Types</h2>
          <div class="list" id="types"></div>
        </section>
        <section>
          <h2>Scan Locations</h2>
          <div class="list" id="places"></div>
        </section>
      </div>
    </div>
  </main>
  <div class="bottom-nav">
    <div class="nav-item">Dashboard</div>
    <div class="nav-item">WiFi</div>
    <div class="nav-item">Bluetooth</div>
    <div class="nav-item">SDR Radio</div>
    <div class="nav-item">Peers</div>
    <div class="nav-item">Settings</div>
  </div>
  <script>
    const $ = (id) => document.getElementById(id);
    const setText = (id, value) => { $(id).textContent = value; };
    const fmtTime = (value) => value ? new Date(value).toLocaleString() : "";
    const typeCount = (data, key) => data.typeCounts && data.typeCounts[key] ? data.typeCounts[key] : 0;

    function classPill(name) {
      const span = document.createElement("span");
      span.className = "pill " + String(name || "Normal").replace(/[^A-Za-z-]/g, "");
      span.textContent = name || "Normal";
      return span;
    }

    function renderList(id, items, labelKey, countKey, emptyText) {
      const root = $(id);
      root.textContent = "";
      if (!items.length) {
        const empty = document.createElement("div");
        empty.className = "item muted";
        empty.textContent = emptyText;
        root.appendChild(empty);
        return;
      }
      for (const item of items) {
        const row = document.createElement("div");
        row.className = "item";
        const label = document.createElement("div");
        label.textContent = item[labelKey];
        const count = document.createElement("div");
        count.className = "count";
        count.textContent = item[countKey];
        row.append(label, count);
        root.appendChild(row);
      }
    }

    async function refresh() {
      try {
        const res = await fetch("/ethrox-detect/web/status", {cache: "no-store"});
        if (!res.ok) throw new Error("HTTP " + res.status);
        const data = await res.json();
        const wifi = typeCount(data, "WIFI");
        const bt = typeCount(data, "BLUETOOTH") + typeCount(data, "BLE");
        const cell = typeCount(data, "CELLULAR");
        const sdr = typeCount(data, "RTL_SDR") + typeCount(data, "SDR");
        const alerts = data.classCounts.Alert || 0;
        const watch = data.classCounts.Watch || 0;
        const noticed = data.classCounts.Noticed || 0;
        const normal = data.classCounts.Normal || 0;
        setText("stat-wifi", wifi);
        setText("stat-bt", bt);
        setText("stat-cell", cell);
        setText("stat-sdr", sdr);
        setText("stat-alerts", alerts);
        setText("stat-watch", watch);
        setText("tile-wifi", wifi);
        setText("tile-bt", bt);
        setText("tile-cell", cell);
        setText("tile-sdr", sdr);
        setText("tile-alerts", alerts + watch);
        setText("aw-summary", `${data.profileCount} known / ${data.locationCount} locations`);
        setText("aw-detail", `${normal} normal / ${data.profileCount} total profiles`);
        setText("aw-odd", `Alerts: ${alerts} / Watch: ${watch} / Noticed: ${noticed}`);
        setText("node", `${data.nodeName || "Ethrox Detect node"} - ${data.nodeId || "unknown node"}`);
        setText("status", `Live - ${fmtTime(data.generatedAt)}`);

        const rows = $("rows");
        rows.textContent = "";
        for (const item of data.recent) {
          const tr = document.createElement("tr");
          const cls = document.createElement("td");
          cls.appendChild(classPill(item.class));
          const name = document.createElement("td");
          name.innerHTML = "";
          const title = document.createElement("div");
          title.className = "name";
          title.textContent = item.name || "(unnamed signal)";
          const meta = document.createElement("div");
          meta.className = "muted";
          meta.textContent = fmtTime(item.last);
          name.append(title, meta);
          const cue = document.createElement("td");
          cue.textContent = item.cue || "";
          const type = document.createElement("td");
          type.textContent = item.type || "UNKNOWN";
          const seen = document.createElement("td");
          seen.textContent = item.seen || 0;
          const event = document.createElement("td");
          event.textContent = item.event || "";
          tr.append(cls, name, cue, type, seen, event);
          rows.appendChild(tr);
        }
        if (!data.recent.length) {
          rows.innerHTML = '<tr><td colspan="6" class="muted">No profiles yet.</td></tr>';
        }

        const typeItems = Object.entries(data.typeCounts || {}).map(([name, count]) => ({name, count}));
        renderList("types", typeItems, "name", "count", "No signal types yet.");
        const placeItems = (data.locations || []).map((p) => ({
          key: p.key,
          signal_count: `${p.signal_count} / ${p.interesting_count} interesting`
        }));
        renderList("places", placeItems, "key", "signal_count", "No GPS-tagged scan locations.");
      } catch (err) {
        setText("status", "Offline - " + err.message);
      }
    }

    refresh();
    setInterval(refresh, 10000);
  </script>
</body>
</html>
"""


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

    def _send_html(self, body: str, status: int = 200) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def _send_head(self) -> None:
        path = urlparse(self.path).path.lower()
        if path in ("/", "/ethrox-detect", "/ethrox-detect/", "/ethrox-detect/web"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(_WEB_APP_HTML.encode("utf-8"))))
        elif path in (
            "/ethrox-detect/version",
            "/ethrox-detect/web/status",
            "/ethrox-detect/health",
            "/ethrox-detect/awareness",
            "/ethrox-detect/sdr/deep-scan/status",
        ):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        else:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
        self.send_header("Connection", "close")
        self.end_headers()

    def do_HEAD(self):
        self._send_head()

    def do_GET(self):
        path = urlparse(self.path).path.lower()
        if path in ("/", "/ethrox-detect", "/ethrox-detect/", "/ethrox-detect/web"):
            self._send_html(_WEB_APP_HTML)
        elif path == "/ethrox-detect/version":
            self._send_json(get_version_payload())
        elif path == "/ethrox-detect/health":
            self._send_json({"ok": True, **get_version_payload()})
        elif path == "/ethrox-detect/awareness":
            self._send_json(get_sync_payload())
        elif path == "/ethrox-detect/sdr/deep-scan/status":
            self._send_json({"status": "idle", **get_version_payload()})
        elif path == "/ethrox-detect/web/status":
            self._send_json(get_web_status())
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = self.path.lower().split("?")[0]
        if path == "/ethrox-detect/sync":
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
        elif path == "/ethrox-detect/sdr/deep-scan":
            self._send_json({"accepted": True, "status": "queued", **get_version_payload()})
        else:
            self._send_json({"error": "not found"}, 404)


def start_server(bind: str = "0.0.0.0", port: int = 8766) -> None:
    global _server, _server_thread
    if _server:
        return
    _server = ThreadingHTTPServer((bind, port), _SyncHandler)
    _server_thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _server_thread.start()


def stop_server() -> None:
    global _server, _server_thread
    if _server:
        _server.shutdown()
        _server = None
    _server_thread = None
