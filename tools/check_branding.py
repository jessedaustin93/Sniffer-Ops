#!/usr/bin/env python3
"""
Fail when old product branding appears outside approved compatibility files.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_RE = re.compile(
    r"snifferops|sniffer-ops|sniffer_ops|sniffersales",
    re.IGNORECASE,
)
ALLOWLIST = {
    "docs/migration-from-snifferops.md",
    "linux/deploy/migrate-snifferops-to-ethrox-detect.sh",
    "linux/tests/test_migration_script.py",
    "tools/check_branding.py",
}
ALLOWLIST_PREFIXES = (
    ".git/",
    ".pytest_cache/",
)


def tracked_files() -> list[Path]:
    try:
        output = subprocess.check_output(
            ["git", "ls-files"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return [ROOT / line.strip() for line in output.splitlines() if line.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return [
            path for path in ROOT.rglob("*")
            if path.is_file()
            and ".git" not in path.relative_to(ROOT).parts
            and "__pycache__" not in path.relative_to(ROOT).parts
        ]


def is_allowed(rel: str) -> bool:
    return rel in ALLOWLIST or any(rel.startswith(prefix) for prefix in ALLOWLIST_PREFIXES)


def scan() -> list[tuple[str, int, str]]:
    hits: list[tuple[str, int, str]] = []
    for path in tracked_files():
        rel = path.relative_to(ROOT).as_posix()
        if is_allowed(rel):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if FORBIDDEN_RE.search(line):
                hits.append((rel, lineno, line.strip()))
    return hits


def main(_argv: list[str] | None = None) -> int:
    hits = scan()
    if not hits:
        print("branding ok: no forbidden old product identifiers in tracked active files")
        return 0
    print("forbidden old product identifiers found:", file=sys.stderr)
    for rel, lineno, line in hits:
        print(f"{rel}:{lineno}: {line}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
