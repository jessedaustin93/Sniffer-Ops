"""Authenticated ingest support for fixed Ethrox mmWave presence nodes."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

MAX_BODY_BYTES = 16_384
MAX_CLOCK_SKEW_MS = 60_000
_VALID_KINDS = {"zone_entry", "alarm_triggered", "tamper"}


class PresenceIngressError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class PresenceIngress:
    def __init__(self) -> None:
        self._registry_path: Path | None = None
        self._seen_events: OrderedDict[str, float] = OrderedDict()

    def configure(self, registry_path: str) -> None:
        self._registry_path = Path(registry_path)

    @property
    def registry_path(self) -> Path:
        if self._registry_path is None:
            raise RuntimeError("mmWave presence registry is not configured")
        return self._registry_path

    def register_node(self, node_id: str, node_name: str) -> str:
        node_id = _clean_identifier(node_id, "nodeId")
        node_name = str(node_name).strip()[:96]
        if not node_name:
            raise PresenceIngressError("nodeName is required")
        registry = self._load_registry(create=True)
        if node_id in registry["nodes"]:
            raise PresenceIngressError(f"node already registered: {node_id}", 409)
        secret = secrets.token_urlsafe(32)
        registry["nodes"][node_id] = {"name": node_name, "secret": secret, "enabled": True}
        self._write_registry(registry)
        return secret

    def verify_and_normalize(self, headers: Any, body: bytes) -> dict[str, Any]:
        if len(body) > MAX_BODY_BYTES:
            raise PresenceIngressError("payload exceeds 16 KiB limit", 413)
        try:
            event = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PresenceIngressError("invalid JSON payload") from exc
        if not isinstance(event, dict):
            raise PresenceIngressError("payload must be a JSON object")
        node_id = _clean_identifier(headers.get("X-Ethrox-Node", ""), "X-Ethrox-Node")
        if event.get("nodeId") != node_id:
            raise PresenceIngressError("nodeId does not match X-Ethrox-Node", 403)
        node = self._load_registry().get("nodes", {}).get(node_id)
        if not node or not node.get("enabled", False):
            raise PresenceIngressError("unregistered or disabled node", 403)
        try:
            timestamp = int(headers.get("X-Ethrox-Timestamp", ""))
        except (TypeError, ValueError) as exc:
            raise PresenceIngressError("invalid X-Ethrox-Timestamp", 401) from exc
        if abs(int(time.time() * 1000) - timestamp) > MAX_CLOCK_SKEW_MS:
            raise PresenceIngressError("request timestamp outside allowed clock skew", 401)
        digest = hashlib.sha256(body).hexdigest()
        expected = hmac.new(str(node["secret"]).encode(), f"{timestamp}\n{digest}".encode(), hashlib.sha256).hexdigest()
        supplied = str(headers.get("X-Ethrox-Signature", "")).lower()
        if not supplied or not hmac.compare_digest(expected, supplied):
            raise PresenceIngressError("invalid request signature", 401)
        if event.get("schema") != 1:
            raise PresenceIngressError("unsupported presence-event schema")
        event_id = _clean_identifier(event.get("eventId", ""), "eventId")
        kind = str(event.get("kind", "")).strip().lower()
        if kind not in _VALID_KINDS:
            raise PresenceIngressError("unsupported presence event kind")
        occurred_at = event.get("occurredAtMs")
        if not isinstance(occurred_at, int) or occurred_at <= 0:
            raise PresenceIngressError("occurredAtMs must be an epoch-millisecond integer")
        zone = event.get("zone")
        if not isinstance(zone, dict):
            raise PresenceIngressError("zone object is required")
        zone_id = _clean_identifier(zone.get("id", ""), "zone.id")
        zone_label = str(zone.get("label", zone_id)).strip()[:96] or zone_id
        targets = event.get("targets", [])
        target_count = event.get("targetCount")
        if not isinstance(targets, list) or len(targets) > 3 or not isinstance(target_count, int) or not 0 <= target_count <= 3:
            raise PresenceIngressError("invalid targets or targetCount")
        normalized = {
            "eventId": event_id, "nodeId": node_id,
            "nodeName": str(node.get("name") or event.get("nodeName") or node_id)[:96],
            "occurredAtMs": occurred_at, "kind": kind, "zoneId": zone_id,
            "zoneLabel": zone_label, "targetCount": target_count,
            "targets": [_normalize_target(target) for target in targets],
            "evidence": event.get("evidence") if isinstance(event.get("evidence"), dict) else {},
        }
        if self._is_duplicate(event_id):
            return {"duplicate": True, "event": normalized, "node": node}
        return {"duplicate": False, "node": node, "event": normalized}

    @staticmethod
    def event_signal(event: dict[str, Any]) -> dict[str, Any]:
        kind = event["kind"]
        is_alert = kind in {"alarm_triggered", "tamper"}
        classification = {"zone_entry": "mmWave protected-zone presence", "alarm_triggered": "mmWave protected-zone alarm", "tamper": "mmWave sensor tamper"}[kind]
        notes = json.dumps({"event": kind, "zone": {"id": event["zoneId"], "label": event["zoneLabel"]}, "targetCount": event["targetCount"], "targets": event["targets"], "evidence": event["evidence"]}, separators=(",", ":"))
        resolution = max((target.get("resolution", 0) for target in event["targets"]), default=0)
        return {"id": f"MMWAVE|{event['nodeId']}|{event['zoneId']}", "name": f"{event['nodeName']} — {event['zoneLabel']}", "address": f"{event['nodeId']}/{event['zoneId']}", "type": "MMWAVE", "signalStrength": resolution, "manufacturer": "Hi-Link HLK-LD2450", "deviceClass": classification, "threatLevel": "ALERT" if is_alert else "SUSPICIOUS", "notes": notes[:2048], "firstSeen": event["occurredAtMs"], "lastSeen": event["occurredAtMs"], "seenCount": 1}

    def _is_duplicate(self, event_id: str) -> bool:
        now, expiry = time.monotonic(), time.monotonic() - 900
        while self._seen_events and next(iter(self._seen_events.values())) < expiry:
            self._seen_events.popitem(last=False)
        if event_id in self._seen_events:
            return True
        self._seen_events[event_id] = now
        return False

    def _load_registry(self, create: bool = False) -> dict[str, Any]:
        path = self.registry_path
        if not path.exists():
            return {"schema": 1, "nodes": {}}
        try:
            registry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PresenceIngressError("unable to load node registry", 500) from exc
        if not isinstance(registry, dict) or not isinstance(registry.get("nodes"), dict):
            raise PresenceIngressError("invalid node registry", 500)
        return registry

    def _write_registry(self, registry: dict[str, Any]) -> None:
        path = self.registry_path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(registry, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp, path)
        os.chmod(path, 0o600)


def _clean_identifier(value: Any, field: str) -> str:
    clean = str(value).strip()
    if not clean or len(clean) > 96 or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-" for ch in clean):
        raise PresenceIngressError(f"invalid {field}")
    return clean


def _normalize_target(target: Any) -> dict[str, int | str]:
    if not isinstance(target, dict):
        raise PresenceIngressError("target must be an object")
    out: dict[str, int | str] = {}
    for field in ("trackId", "xMm", "yMm", "speedCmS", "resolution", "dwellMs"):
        value = target.get(field)
        if not isinstance(value, int):
            raise PresenceIngressError(f"target.{field} must be an integer")
        out[field] = value
    motion = str(target.get("motion", "UNKNOWN")).upper()
    # The sensor core uses NONE before it has enough samples to classify
    # movement. It carries no distinct wire meaning, so retain the event as
    # UNKNOWN rather than rejecting an otherwise valid presence alert.
    if motion == "NONE":
        motion = "UNKNOWN"
    if motion not in {"STANDING", "WALKING", "RUNNING", "UNKNOWN"}:
        raise PresenceIngressError("invalid target.motion")
    out["motion"] = motion
    return out


presence_ingress = PresenceIngress()
