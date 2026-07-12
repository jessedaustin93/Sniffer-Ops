"""
Canonical Ethrox Detect version access for Linux components.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


_ROOT = Path(__file__).resolve().parents[1]
_VERSION_FILE = _ROOT / "version.json"


@lru_cache(maxsize=1)
def get_version_info() -> dict[str, Any]:
    with _VERSION_FILE.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def version_text() -> str:
    info = get_version_info()
    return f"{info['product']} {info['version']} (build {info['build']})"
