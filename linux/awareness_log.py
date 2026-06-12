"""
Durable signal awareness log and LAN sync endpoint.
Wire-compatible with the Windows AwarenessLog.ps1 — same JSON schema,
same HTTP endpoints (port 8765), same merge logic.
"""

import json
import math
import os
import re
import socket
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import signal_classifier as _sc

_log_path: str | None = None
_state_lock = threading.Lock()
_server: HTTPServer | None = None
_server_thread: threading.Thread | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def initialize(path: str) -> None:
    global _log_path
    _log_path = path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        _save_state({
            "Schema": 1,
            "CreatedAt": _now_iso(),
            "UpdatedAt": _now_iso(),
            "Signals": {},
        })


def _read_state() -> dict:
    if not _log_path:
        raise RuntimeError("Awareness log not initialized")
    try:
        with open(_log_path, "r", encoding="utf-8") as f:
            raw = f.read()
        return json.loads(raw) if raw.strip() else _empty_state()
    except (FileNotFoundError, json.JSONDecodeError):
        return _empty_state()


def _empty_state() -> dict:
    return {"Schema": 1, "CreatedAt": _now_iso(), "UpdatedAt": _now_iso(), "Signals": {}}


def _save_state(state: dict) -> None:
    state["UpdatedAt"] = _now_iso()
    tmp = _log_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, _log_path)


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
    p_lat, p_lon = _to_number(prev.get("Latitude")), _to_number(prev.get("Longitude"))
    c_lat, c_lon = _to_number(cur.get("Latitude")), _to_number(cur.get("Longitude"))
    if c_lat is None or c_lon is None:
        return False
    if p_lat is None or p_lon is None:
        return True
    return _distance_meters(p_lat, p_lon, c_lat, c_lon) >= 25.0


def _sdr_class_group(signal: dict) -> str:
    parts = " ".join(filter(None, [
        signal.get("deviceClass", ""),
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
        "broadcast-fm": 200_000.0,
        "cellular": 1_000_000.0,
        "broadcast-tv": 1_000_000.0,
        "adsb": 250_000.0,
        "ism": 500_000.0,
    }
    return buckets.get(class_group, 250_000.0)


def _signal_key(signal: dict) -> str:
    sig_type = (signal.get("type") or signal.get("signalType") or "UNKNOWN").strip().upper()
    if sig_type == "RTL_SDR":
        freq = _to_number(signal.get("frequencyHz"))
        if freq is not None:
            cg = _sdr_class_group(signal)
            bucket_hz = _sdr_bucket_hz(cg)
            bucket = int(round(freq / bucket_hz) * bucket_hz)
            return f"RTL_SDR|{cg}|{bucket}"
    ident = (signal.get("address") or signal.get("id") or
             str(signal.get("frequencyHz") or "") or signal.get("name") or "")
    ident = ident.strip()
    if not ident:
        import uuid
        ident = uuid.uuid4().hex
    return f"{sig_type}|{ident.upper()}"


def _add_timeline_event(profile: dict, at: str, kind: str, summary: str, data: dict | None = None) -> None:
    timeline = profile.setdefault("Timeline", [])
    if timeline and timeline[-1]["Kind"] == kind and timeline[-1]["Summary"] == summary:
        timeline[-1]["LastAt"] = at
        timeline[-1]["Count"] = timeline[-1].get("Count", 1) + 1
        return
    timeline.append({"At": at, "LastAt": at, "Kind": kind, "Summary": summary, "Count": 1, "Data": data})
    if len(timeline) > 120:
        profile["Timeline"] = timeline[-120:]


def _add_sighting(profile: dict, sighting: dict) -> None:
    sightings = profile.setdefault("Sightings", [])
    last = sightings[-1] if sightings else None
    same_node = last and last.get("NodeId") == sighting.get("NodeId")
    last_sig = _to_number(last.get("SignalStrengthNumeric")) if last else None
    new_sig = _to_number(sighting.get("SignalStrengthNumeric"))
    sig_changed = (last_sig is not None and new_sig is not None and
                   abs(new_sig - last_sig) >= 3.0)
    loc_changed = _location_changed(last, sighting)
    if not last or not same_node or sig_changed or loc_changed:
        sightings.append(sighting)
        if len(sightings) > 24:
            profile["Sightings"] = sightings[-24:]


def merge_snapshot(snapshot: dict) -> dict:
    with _state_lock:
        state = _read_state()
        now = _now_iso()
        node_id = (snapshot.get("nodeId") or "unknown-node").strip()
        node_name = (snapshot.get("nodeName") or node_id).strip()
        location = snapshot.get("location") or {}
        node_lat = _to_number(location.get("latitude"))
        node_lon = _to_number(location.get("longitude"))
        node_acc = _to_number(location.get("accuracyMeters"))
        signals = snapshot.get("signals") or []
        complete_types = {str(t).upper() for t in (snapshot.get("completeTypes") or [])}
        current_keys: set[str] = set()
        merged = 0

        for signal in signals:
            key = _signal_key(signal)
            current_keys.add(key)
            sig_lat = _to_number(signal.get("latitude")) or node_lat
            sig_lon = _to_number(signal.get("longitude")) or node_lon
            sig_acc = _to_number(signal.get("accuracyMeters")) or node_acc
            strength = signal.get("signalStrength")
            strength_num = _to_number(strength)
            existing = state["Signals"].get(key)
            created = False

            if not existing:
                existing = {
                    "Key": key,
                    "Name": signal.get("name", ""),
                    "Address": signal.get("address", ""),
                    "Type": signal.get("type", ""),
                    "SpecificType": signal.get("deviceClass", ""),
                    "Manufacturer": signal.get("manufacturer", ""),
                    "ThreatLevel": signal.get("threatLevel", ""),
                    "Notes": signal.get("notes", ""),
                    "Channel": signal.get("channel"),
                    "FrequencyHz": signal.get("frequencyHz"),
                    "FirstSeen": now,
                    "LastSeen": now,
                    "SeenCount": 0,
                    "StrongestSignal": strength,
                    "StrongestSignalNumeric": strength_num,
                    "LastSignal": strength,
                    "LastSignalNumeric": strength_num,
                    "PresenceState": "seen",
                    "LastPresentAt": now,
                    "LastMissingAt": "",
                    "NodeIds": [],
                    "Sightings": [],
                    "Timeline": [],
                    "EstimatedLatitude": None,
                    "EstimatedLongitude": None,
                }
                state["Signals"][key] = existing
                created = True
                _add_timeline_event(existing, now, "first_seen", f"First seen by {node_name}",
                                    {"nodeId": node_id, "nodeName": node_name, "signal": strength,
                                     "latitude": sig_lat, "longitude": sig_lon,
                                     "type": signal.get("deviceClass", "")})

            if not created and existing.get("PresenceState") == "not_seen":
                _add_timeline_event(existing, now, "reappeared", f"Seen again by {node_name}",
                                    {"nodeId": node_id, "nodeName": node_name, "signal": strength})
            existing["PresenceState"] = "seen"
            existing["LastPresentAt"] = now

            new_name = signal.get("name") or existing["Name"]
            new_type = signal.get("deviceClass") or existing["SpecificType"]
            new_mfr = signal.get("manufacturer") or existing["Manufacturer"]
            new_threat = signal.get("threatLevel") or existing["ThreatLevel"]

            if not created:
                if new_name and new_name != existing["Name"]:
                    _add_timeline_event(existing, now, "name_changed",
                                        f"Name changed from '{existing['Name']}' to '{new_name}'",
                                        {"old": existing["Name"], "new": new_name})
                if new_type and new_type != existing["SpecificType"]:
                    _add_timeline_event(existing, now, "type_changed",
                                        f"Type changed from '{existing['SpecificType']}' to '{new_type}'",
                                        {"old": existing["SpecificType"], "new": new_type})
                if new_mfr and new_mfr != existing["Manufacturer"]:
                    _add_timeline_event(existing, now, "vendor_changed",
                                        f"Vendor changed from '{existing['Manufacturer']}' to '{new_mfr}'",
                                        {"old": existing["Manufacturer"], "new": new_mfr})
                if new_threat and new_threat != existing["ThreatLevel"]:
                    _add_timeline_event(existing, now, "alert_changed",
                                        f"Alert level changed from '{existing['ThreatLevel']}' to '{new_threat}'",
                                        {"old": existing["ThreatLevel"], "new": new_threat})

            existing["Name"] = new_name
            existing["Address"] = signal.get("address") or existing["Address"]
            existing["Type"] = signal.get("type") or existing["Type"]
            existing["SpecificType"] = new_type
            existing["Manufacturer"] = new_mfr
            existing["ThreatLevel"] = new_threat
            existing["Notes"] = signal.get("notes") or existing["Notes"]
            existing["Channel"] = signal.get("channel") or existing["Channel"]
            existing["FrequencyHz"] = signal.get("frequencyHz") or existing["FrequencyHz"]
            existing["LastSeen"] = now
            existing["SeenCount"] = existing["SeenCount"] + 1
            existing["LastSignal"] = strength
            existing["LastSignalNumeric"] = strength_num

            strongest_num = _to_number(existing.get("StrongestSignalNumeric"))
            if strength_num is not None and (strongest_num is None or strength_num > strongest_num):
                if not created and strongest_num is not None and (strength_num - strongest_num) >= 10.0:
                    _add_timeline_event(existing, now, "signal_jump",
                                        f"Signal jumped from '{existing['StrongestSignal']}' to '{strength}'",
                                        {"old": existing["StrongestSignal"], "new": strength,
                                         "nodeId": node_id, "nodeName": node_name})
                existing["StrongestSignal"] = strength
                existing["StrongestSignalNumeric"] = strength_num
            elif not existing.get("StrongestSignal"):
                existing["StrongestSignal"] = strength
                existing["StrongestSignalNumeric"] = strength_num

            if node_id not in existing["NodeIds"]:
                existing["NodeIds"].append(node_id)
                if not created:
                    _add_timeline_event(existing, now, "new_node", f"Also seen by {node_name}",
                                        {"nodeId": node_id, "nodeName": node_name})

            sighting = {
                "At": now, "NodeId": node_id, "NodeName": node_name,
                "Latitude": sig_lat, "Longitude": sig_lon, "AccuracyMeters": sig_acc,
                "NodeLatitude": node_lat, "NodeLongitude": node_lon,
                "SignalStrength": strength, "SignalStrengthNumeric": strength_num,
            }
            prev_count = len(existing["Sightings"])
            _add_sighting(existing, sighting)
            if not created and len(existing["Sightings"]) > prev_count:
                prev_last = existing["Sightings"][-2] if len(existing["Sightings"]) >= 2 else None
                if _location_changed(prev_last, sighting):
                    _add_timeline_event(existing, now, "location_changed",
                                        f"Seen from a new scan location by {node_name}",
                                        {"latitude": sig_lat, "longitude": sig_lon,
                                         "accuracyMeters": sig_acc, "nodeId": node_id})

            geo = [s for s in existing["Sightings"]
                   if s.get("Latitude") is not None and s.get("Longitude") is not None]
            if geo:
                existing["EstimatedLatitude"] = sum(s["Latitude"] for s in geo) / len(geo)
                existing["EstimatedLongitude"] = sum(s["Longitude"] for s in geo) / len(geo)
            merged += 1

        if complete_types:
            for key, profile in state["Signals"].items():
                if profile.get("Type", "").upper() not in complete_types:
                    continue
                if key in current_keys:
                    continue
                if node_id not in profile.get("NodeIds", []):
                    continue
                if profile.get("PresenceState") != "not_seen":
                    profile["PresenceState"] = "not_seen"
                    profile["LastMissingAt"] = now
                    _add_timeline_event(profile, now, "not_seen",
                                        f"Not seen by {node_name} in this complete scan",
                                        {"nodeId": node_id, "nodeName": node_name,
                                         "scanTypes": list(complete_types)})

        _save_state(state)
        return {"Merged": merged, "TotalSignals": len(state["Signals"]), "UpdatedAt": state["UpdatedAt"]}


def get_sync_payload() -> dict:
    with _state_lock:
        state = _read_state()
    signals = []
    for profile in state["Signals"].values():
        timeline = profile.get("Timeline", [])
        signals.append({
            "key": profile.get("Key"),
            "name": profile.get("Name"),
            "address": profile.get("Address"),
            "type": profile.get("Type"),
            "deviceClass": profile.get("SpecificType"),
            "manufacturer": profile.get("Manufacturer"),
            "threatLevel": profile.get("ThreatLevel"),
            "signalStrength": profile.get("LastSignal"),
            "strongestSignal": profile.get("StrongestSignal"),
            "channel": profile.get("Channel"),
            "frequencyHz": profile.get("FrequencyHz"),
            "firstSeen": profile.get("FirstSeen"),
            "lastSeen": profile.get("LastSeen"),
            "seenCount": profile.get("SeenCount", 0),
            "estimatedLatitude": profile.get("EstimatedLatitude"),
            "estimatedLongitude": profile.get("EstimatedLongitude"),
            "nodeCount": len(profile.get("NodeIds", [])),
            "latestEvent": timeline[-1]["Summary"] if timeline else "",
            "timelineCount": len(timeline),
            "timeline": timeline[-12:],
        })
    return {
        "schema": 1,
        "updatedAt": state.get("UpdatedAt", _now_iso()),
        "totalSignals": len(signals),
        "signals": signals,
    }


_NORMAL_BASELINE = 5  # seenCount threshold for "Normal" status


def _display_name(profile: dict) -> str:
    """Strip BT service protocol suffixes (AVRCP, A2DP, etc.) from device names."""
    name = (profile.get("Name") or "").strip()
    if (profile.get("Type") or "").upper() == "BLUETOOTH" and name:
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
    sig_type = (profile.get("Type") or "UNKNOWN").upper()
    name = re.sub(r"\s+", " ", _display_name(profile).upper()).strip()
    generic = {
        "", "UNKNOWN", "UNCLASSIFIED",
        "UNCLASSIFIED BLUETOOTH DEVICE OR SERVICE",
        "UNCLASSIFIED RF SIGNAL",
    }
    if sig_type not in ("SDR", "RTL_SDR") and name and name not in generic:
        return f"NAME|{sig_type}|{name}"
    if profile.get("Key"):
        return f"KEY|{profile['Key']}"
    return (f"RAW|{sig_type}|{name}"
            f"|{profile.get('Address','')}"
            f"|{profile.get('FrequencyHz','')}")


def _class_rank(class_name: str) -> int:
    return {"Alert": 5, "Watch": 4, "Noticed": 3,
            "One-off": 2, "Learning": 1, "Normal": 0}.get(class_name, 0)


def _profile_class(profile: dict) -> str:
    """Compute the display class (Alert/Watch/Noticed/One-off/Learning/Normal)."""
    timeline = profile.get("Timeline") or []
    last_event = timeline[-1]["Summary"] if timeline else ""
    notes_text = " ".join(filter(None, [last_event, profile.get("Notes") or ""]))
    alert = _sc.classify_alert(
        profile.get("Name") or "",
        profile.get("Type") or "",
        profile.get("SpecificType") or "",
        profile.get("ThreatLevel") or "",
        notes_text,
    )
    seen = int(profile.get("SeenCount") or 0)
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


def get_display_profiles() -> list[dict]:
    """
    Grouped, classified profiles ready for the awareness strip and timeline view.
    Mirrors Get-AwarenessDisplayProfiles from SnifferOps.Windows.ps1.
    """
    with _state_lock:
        state = _read_state()

    raw: list[dict] = []
    for profile in state["Signals"].values():
        cls = _profile_class(profile)
        timeline = profile.get("Timeline") or []
        raw.append({
            "Key":               profile.get("Key"),
            "Name":              _display_name(profile),
            "RawName":           profile.get("Name") or "",
            "Address":           profile.get("Address"),
            "FrequencyHz":       profile.get("FrequencyHz"),
            "Type":              profile.get("Type"),
            "SpecificType":      profile.get("SpecificType"),
            "ThreatLevel":       profile.get("ThreatLevel"),
            "SeenCount":         int(profile.get("SeenCount") or 0),
            "NodeCount":         len(profile.get("NodeIds") or []),
            "LastSeen":          profile.get("LastSeen") or "",
            "LastSignal":        profile.get("LastSignal"),
            "Class":             cls,
            "LastEvent":         timeline[-1]["Summary"] if timeline else "",
            "Sightings":         profile.get("Sightings") or [],
            "Timeline":          timeline,
            "EstimatedLatitude": profile.get("EstimatedLatitude"),
            "EstimatedLongitude": profile.get("EstimatedLongitude"),
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
        latest  = max(members, key=lambda m: m["LastSeen"])
        types   = ", ".join(dict.fromkeys(
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
    Each location key is a "lat,lon" string rounded to 4 decimal places (~11 m).
    """
    with _state_lock:
        state = _read_state()

    points: dict[str, dict] = {}
    for profile in state["Signals"].values():
        seen_keys: set[str] = set()
        cls = _profile_class(profile)
        for sighting in (profile.get("Sightings") or []):
            lat = _to_number(sighting.get("Latitude"))
            lon = _to_number(sighting.get("Longitude"))
            if lat is None or lon is None:
                continue
            loc_key = f"{lat:.4f},{lon:.4f}"
            if loc_key in seen_keys:
                continue
            seen_keys.add(loc_key)
            if loc_key not in points:
                points[loc_key] = {"key": loc_key, "signal_count": 0, "interesting_count": 0}
            points[loc_key]["signal_count"] += 1
            if cls in ("Alert", "Watch", "Noticed", "One-off"):
                points[loc_key]["interesting_count"] += 1

    return sorted(points.values(), key=lambda p: p["signal_count"], reverse=True)


def get_rows() -> list[dict]:
    with _state_lock:
        state = _read_state()
    rows = []
    for profile in state["Signals"].values():
        timeline = profile.get("Timeline", [])
        latest = timeline[-1]["Summary"] if timeline else "profile updated"
        cls = _profile_class(profile)
        rows.append({
            "Type":             profile.get("Type"),
            "Signal":           _display_name(profile),
            "AddressOrFrequency": profile.get("Address") or profile.get("FrequencyHz"),
            "StrengthOrPower":  profile.get("LastSignal"),
            "Classification":   profile.get("SpecificType"),
            "Confidence":       cls,
            "Details": (f"Seen {profile.get('SeenCount', 0)}x from "
                        f"{len(profile.get('NodeIds', []))} node(s); {latest}"),
            "LastSeen":         profile.get("LastSeen", ""),
        })
    rows.sort(key=lambda r: r.get("LastSeen", ""), reverse=True)
    return rows


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
                payload["merged"] = result["Merged"]
                self._send_json(payload)
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)
        else:
            self._send_json({"error": "not found"}, 404)


def start_server(bind: str = "0.0.0.0", port: int = 8765) -> None:
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


def push_to_node(host: str, port: int, snapshot: dict) -> dict | None:
    """Push a local snapshot to another node (Windows, Linux, or Android bridge)."""
    import urllib.request
    url = f"http://{host}:{port}/snifferops/sync"
    data = json.dumps(snapshot).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def pull_from_node(host: str, port: int) -> dict | None:
    """Pull the full awareness state from another node."""
    import urllib.request
    url = f"http://{host}:{port}/snifferops/awareness"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
