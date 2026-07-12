import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("version_tool", ROOT / "tools" / "version.py")
version_tool = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(version_tool)


def test_version_json_is_valid():
    data = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
    version_tool.validate(data)
    assert data["product"] == "Ethrox Detect"
    assert data["slug"] == "ethrox-detect"


def test_bump_minor_resets_patch_and_increments_build():
    data = {
        "product": "Ethrox Detect",
        "slug": "ethrox-detect",
        "major": 1,
        "minor": 2,
        "patch": 9,
        "build": 41,
        "version": "1.2.9",
        "full_version": "1.2.9+41",
        "channel": "development",
    }
    bumped = version_tool.bump(data, "minor")
    assert bumped["major"] == 1
    assert bumped["minor"] == 3
    assert bumped["patch"] == 0
    assert bumped["build"] == 42
    assert bumped["version"] == "1.3.0"
    assert bumped["full_version"] == "1.3.0+42"


def test_bump_major_resets_minor_patch_and_increments_build():
    data = {
        "product": "Ethrox Detect",
        "slug": "ethrox-detect",
        "major": 1,
        "minor": 2,
        "patch": 9,
        "build": 41,
        "version": "1.2.9",
        "full_version": "1.2.9+41",
        "channel": "development",
    }
    bumped = version_tool.bump(data, "major")
    assert bumped["major"] == 2
    assert bumped["minor"] == 0
    assert bumped["patch"] == 0
    assert bumped["build"] == 42


def test_prerelease_full_version_is_valid():
    data = {
        "product": "Ethrox Detect",
        "slug": "ethrox-detect",
        "major": 0,
        "minor": 2,
        "patch": 0,
        "prerelease": "rc.1",
        "build": 1,
        "version": "0.2.0-rc.1",
        "full_version": "0.2.0-rc.1+1",
        "channel": "release-candidate",
    }
    version_tool.validate(data)
