"""
Local ownership/trust overrides for SnifferOps.

The source tree defines the matching behavior; the actual trusted devices live
in ~/.snifferops/trusted_devices.json so private SSIDs, MACs, and local camera
names do not get committed.
"""

from dataclasses import dataclass
import json
import os
import re
from functools import lru_cache
from typing import Any


DATA_DIR = os.path.expanduser("~/.snifferops")
TRUSTED_DEVICES_PATH = os.environ.get(
    "SNIFFEROPS_TRUSTED_DEVICES",
    os.path.join(DATA_DIR, "trusted_devices.json"),
)


@dataclass(frozen=True)
class OwnershipMatch:
    trusted: bool
    label: str = ""
    reason: str = ""


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _profile_id(signal: dict) -> str:
    sig_type = _norm(signal.get("type") or signal.get("signalType") or "UNKNOWN").upper()
    ident = (
        signal.get("id")
        or signal.get("address")
        or str(signal.get("frequencyHz") or "")
        or signal.get("name")
        or ""
    )
    ident = str(ident).strip()
    if not ident:
        return ""
    if "|" in ident and ident.upper().startswith(f"{sig_type}|"):
        return ident.upper()
    return f"{sig_type}|{ident.upper()}"


@lru_cache(maxsize=1)
def load_trusted_devices() -> dict:
    try:
        with open(TRUSTED_DEVICES_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = {}
    return data if isinstance(data, dict) else {}


def reload_trusted_devices() -> None:
    load_trusted_devices.cache_clear()


def _iter_list(data: dict, key: str) -> list[str]:
    values = data.get(key) or []
    if not isinstance(values, list):
        return []
    return [str(v) for v in values if str(v).strip()]


def classify_ownership(signal: dict) -> OwnershipMatch:
    data = load_trusted_devices()
    label = str(data.get("owner_label") or "Jesse/home trusted device")

    profile_id = _profile_id(signal)
    trusted_profiles = {v.upper() for v in _iter_list(data, "trusted_profiles")}
    if profile_id and profile_id in trusted_profiles:
        return OwnershipMatch(True, label, f"profile {profile_id}")

    address = _norm(signal.get("address") or signal.get("Address"))
    trusted_addresses = {_norm(v) for v in _iter_list(data, "trusted_addresses")}
    if address and address in trusted_addresses:
        return OwnershipMatch(True, label, f"address {address}")

    name = _norm(signal.get("name") or signal.get("Name") or signal.get("ssid") or signal.get("SSID"))
    trusted_names = {_norm(v) for v in _iter_list(data, "trusted_names")}
    if name and name in trusted_names:
        return OwnershipMatch(True, label, f"name {name}")

    haystack = " ".join(_norm(signal.get(k)) for k in (
        "name", "Name", "ssid", "SSID", "address", "Address", "manufacturer",
        "Manufacturer", "deviceClass", "device_class", "SpecificType", "notes", "Notes",
    ))
    for pattern in _iter_list(data, "trusted_name_patterns"):
        try:
            if re.search(pattern, haystack, flags=re.IGNORECASE):
                return OwnershipMatch(True, label, f"pattern {pattern}")
        except re.error:
            continue

    return OwnershipMatch(False)


def is_trusted(signal: dict) -> bool:
    return classify_ownership(signal).trusted


def apply_trust(signal: dict) -> OwnershipMatch:
    match = classify_ownership(signal)
    if not match.trusted:
        return match

    signal["threatLevel"] = "SAFE"
    notes = str(signal.get("notes") or "").strip()
    trust_note = f"Trusted owner: {match.label}"
    if match.reason:
        trust_note = f"{trust_note} ({match.reason})"
    if trust_note not in notes:
        signal["notes"] = "; ".join(part for part in (notes, trust_note) if part)
    return match
