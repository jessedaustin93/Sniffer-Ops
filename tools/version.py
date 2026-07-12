#!/usr/bin/env python3
"""
Manage canonical Ethrox Detect versions.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VERSION_PATH = ROOT / "version.json"
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


class VersionError(ValueError):
    pass


def load_version(path: Path = VERSION_PATH) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError as exc:
        raise VersionError(f"missing version file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise VersionError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise VersionError("version.json must contain an object")
    return data


def save_version(data: dict[str, Any], path: Path = VERSION_PATH) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _int_field(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int) or value < 0:
        raise VersionError(f"{key} must be a non-negative integer")
    return value


def _expected_strings(data: dict[str, Any]) -> tuple[str, str]:
    major = _int_field(data, "major")
    minor = _int_field(data, "minor")
    patch = _int_field(data, "patch")
    build = _int_field(data, "build")
    prerelease = data.get("prerelease", "")
    if prerelease is None:
        prerelease = ""
    if not isinstance(prerelease, str):
        raise VersionError("prerelease must be a string when present")
    base = f"{major}.{minor}.{patch}"
    version = f"{base}-{prerelease}" if prerelease else base
    if not SEMVER_RE.match(version):
        raise VersionError(f"malformed semantic version: {version}")
    return version, f"{version}+{build}"


def validate(data: dict[str, Any]) -> None:
    required = {
        "product": "Ethrox Detect",
        "slug": "ethrox-detect",
    }
    for key, expected in required.items():
        if data.get(key) != expected:
            raise VersionError(f"{key} must be {expected!r}")
    version, full_version = _expected_strings(data)
    if data.get("version") != version:
        raise VersionError(f"version must be {version!r}")
    if data.get("full_version") != full_version:
        raise VersionError(f"full_version must be {full_version!r}")
    channel = data.get("channel")
    if not isinstance(channel, str) or not channel:
        raise VersionError("channel must be a non-empty string")


def normalized(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)
    version, full_version = _expected_strings(out)
    out["version"] = version
    out["full_version"] = full_version
    return out


def bump(data: dict[str, Any], part: str) -> dict[str, Any]:
    out = dict(data)
    validate(normalized(out))
    if part == "major":
        out["major"] = _int_field(out, "major") + 1
        out["minor"] = 0
        out["patch"] = 0
        out["build"] = _int_field(out, "build") + 1
        out.pop("prerelease", None)
        out["channel"] = "development"
    elif part == "minor":
        out["minor"] = _int_field(out, "minor") + 1
        out["patch"] = 0
        out["build"] = _int_field(out, "build") + 1
        out.pop("prerelease", None)
        out["channel"] = "development"
    elif part == "patch":
        out["patch"] = _int_field(out, "patch") + 1
        out["build"] = _int_field(out, "build") + 1
        out.pop("prerelease", None)
        out["channel"] = "development"
    elif part == "build":
        out["build"] = _int_field(out, "build") + 1
    else:
        raise VersionError(f"unknown bump target: {part}")
    return normalized(out)


def platform_files() -> list[Path]:
    return [
        ROOT / "version.json",
        ROOT / "linux" / "version_info.py",
    ]


def sync(data: dict[str, Any]) -> list[Path]:
    validate(data)
    changed: list[Path] = []
    version_info = ROOT / "linux" / "version_info.py"
    if version_info.exists():
        text = version_info.read_text(encoding="utf-8")
        if "version.json" not in text or "version_text" not in text:
            raise VersionError(f"{version_info} must read canonical version.json")
    for path in platform_files():
        if path.exists():
            changed.append(path.relative_to(ROOT))
    return changed


def cmd_show(_args: argparse.Namespace) -> int:
    data = load_version()
    validate(data)
    print(data["full_version"])
    print(json.dumps(data, indent=2))
    return 0


def cmd_verify(_args: argparse.Namespace) -> int:
    data = load_version()
    validate(data)
    files = sync(data)
    print(f"version ok: {data['full_version']}")
    print("checked files:")
    for path in files:
        print(f"  {path}")
    return 0


def cmd_bump(args: argparse.Namespace) -> int:
    data = bump(load_version(), args.part)
    before = load_version()["full_version"]
    save_version(data)
    print(f"updated version.json: {before} -> {data['full_version']}")
    for path in sync(data):
        print(f"checked {path}")
    return 0


def cmd_sync(_args: argparse.Namespace) -> int:
    data = normalized(load_version())
    validate(data)
    before = load_version()
    if before != data:
        save_version(data)
        print("updated version.json")
    else:
        print("version.json already synchronized")
    for path in sync(data):
        print(f"checked {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage Ethrox Detect version metadata")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show").set_defaults(func=cmd_show)
    sub.add_parser("verify").set_defaults(func=cmd_verify)
    bump_parser = sub.add_parser("bump")
    bump_parser.add_argument("part", choices=("patch", "minor", "major", "build"))
    bump_parser.set_defaults(func=cmd_bump)
    sub.add_parser("sync").set_defaults(func=cmd_sync)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except VersionError as exc:
        print(f"version error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
