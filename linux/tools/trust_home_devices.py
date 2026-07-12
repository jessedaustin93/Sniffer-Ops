#!/usr/bin/env python3
"""
Manage the local Ethrox Detect trusted-device file.

This never writes private device names into the repository. It reads the local
SQLite awareness DB and updates ~/.ethrox-detect/trusted_devices.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ownership


DEFAULT_DB = Path("~/.ethrox-detect/awareness.db").expanduser()
DEFAULT_TRUST = Path(ownership.TRUSTED_DEVICES_PATH).expanduser()


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def _connect(path: Path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _matching_profiles(db_path: Path, pattern: str, wifi_only: bool) -> list[sqlite3.Row]:
    type_clause = "AND UPPER(type) = 'WIFI'" if wifi_only else ""
    like = f"%{pattern.lower()}%"
    with _connect(db_path) as conn:
        return conn.execute(
            f"""
            SELECT id, type, name, address, manufacturer, device_class, threat_level, seen_count
            FROM signal_profiles
            WHERE LOWER(COALESCE(name, '') || ' ' || COALESCE(address, '') || ' ' ||
                        COALESCE(manufacturer, '') || ' ' || COALESCE(device_class, ''))
                  LIKE ?
              {type_clause}
            ORDER BY last_seen DESC
            """,
            (like,),
        ).fetchall()


def _add_unique(values: list[str], new_values: list[str]) -> list[str]:
    seen = {v.upper() for v in values}
    for value in new_values:
        if value.upper() not in seen:
            values.append(value)
            seen.add(value.upper())
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--trust-file", default=str(DEFAULT_TRUST))
    parser.add_argument("--pattern", action="append", default=[], help="Name/address/vendor text to match")
    parser.add_argument("--all-wifi", action="store_true", help="Trust every current Wi-Fi profile")
    parser.add_argument("--wifi-only", action="store_true", default=True)
    parser.add_argument("--apply", action="store_true", help="Write matching profile IDs into the trust file")
    args = parser.parse_args()

    db_path = Path(args.db).expanduser()
    trust_path = Path(args.trust_file).expanduser()
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")

    trust = _load_json(trust_path)
    trust.setdefault("owner_label", "Jesse/home trusted device")
    trust.setdefault("trusted_profiles", [])
    trust.setdefault("trusted_name_patterns", [])

    rows: list[sqlite3.Row] = []
    if args.all_wifi:
        with _connect(db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, type, name, address, manufacturer, device_class, threat_level, seen_count
                FROM signal_profiles
                WHERE UPPER(type) = 'WIFI'
                ORDER BY last_seen DESC
                """
            ).fetchall()
    else:
        for pattern in args.pattern:
            rows.extend(_matching_profiles(db_path, pattern, args.wifi_only))

    deduped = {row["id"]: row for row in rows}
    rows = list(deduped.values())

    for row in rows:
        print(
            f"{row['id']}\t{row['type']}\t{row['name'] or ''}\t"
            f"{row['device_class'] or ''}\t{row['threat_level'] or ''}\tseen={row['seen_count'] or 0}"
        )

    if args.apply:
        trust["trusted_profiles"] = _add_unique(
            list(trust.get("trusted_profiles") or []),
            [row["id"] for row in rows],
        )
        _write_json(trust_path, trust)
        print(f"trusted_profiles={len(trust['trusted_profiles'])} written to {trust_path}")
    else:
        print("dry run only; add --apply to write trusted profile IDs")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
