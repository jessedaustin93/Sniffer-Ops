"""
Canonical Ethrox Detect version access for Linux components.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


_HERE = Path(__file__).resolve().parent
_VERSION_FILE = _HERE / "version.json"
if not _VERSION_FILE.exists():
    _VERSION_FILE = _HERE.parent / "version.json"


@lru_cache(maxsize=1)
def get_version_info() -> dict[str, Any]:
    with _VERSION_FILE.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def version_text() -> str:
    info = get_version_info()
    return f"{info['product']} {info['version']} (build {info['build']})"
