"""Config-level regression coverage for T5810B's actual deployed entry
point. ethrox_detect_gui.py has no argparse -- everything is driven by
config.json (cfg.get("wifi", True), etc.) -- so bounded_sync must be wired
the same way, not as a CLI flag the GUI script would never see."""
import json
import sys
import types
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("gi", reason="GTK not available in this environment")

import awareness_log
import ethrox_detect_gui


def _get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


@pytest.fixture(autouse=True)
def _reset_bounded_mode():
    yield
    awareness_log.set_bounded_sync_mode(False)


def test_bounded_sync_config_key_reaches_the_server(tmp_path):
    awareness_log.set_node_info("t5810b-hub", "T5810B Hub")
    awareness_log.initialize(str(tmp_path / "awareness.json"))
    awareness_log.merge_snapshot({
        "schema": 1, "nodeId": "seed", "nodeName": "seed",
        "signals": [{"id": "seed-1", "name": "Seed", "type": "WIFI",
                     "sightings": [{"id": "sight-1", "capturedAt": 0}]}],
    })

    win = types.SimpleNamespace(_cfg={"port": 0, "bounded_sync": True, "peers": []})
    try:
        ethrox_detect_gui.EthroxDetectApp._start_services(
            types.SimpleNamespace(), win,
        )
        port = awareness_log._server.server_address[1]

        assert _get(port, "/ethrox-detect/awareness")["signals"] == []
        assert _get(port, "/ethrox-detect/awareness/export")["signals"], (
            "explicit export must still return the full map"
        )
    finally:
        awareness_log.stop_server()
        if ethrox_detect_gui._sync_manager:
            ethrox_detect_gui._sync_manager.stop()


def test_bounded_sync_defaults_off_when_config_key_absent(tmp_path):
    awareness_log.set_node_info("t5810b-hub", "T5810B Hub")
    awareness_log.initialize(str(tmp_path / "awareness.json"))
    awareness_log.merge_snapshot({
        "schema": 1, "nodeId": "seed", "nodeName": "seed",
        "signals": [{"id": "seed-1", "name": "Seed", "type": "WIFI",
                     "sightings": [{"id": "sight-1", "capturedAt": 0}]}],
    })

    win = types.SimpleNamespace(_cfg={"port": 0, "peers": []})  # no bounded_sync key
    try:
        ethrox_detect_gui.EthroxDetectApp._start_services(
            types.SimpleNamespace(), win,
        )
        port = awareness_log._server.server_address[1]
        assert _get(port, "/ethrox-detect/awareness")["signals"], (
            "bounded_sync must default off for existing installs without the key"
        )
    finally:
        awareness_log.stop_server()
        if ethrox_detect_gui._sync_manager:
            ethrox_detect_gui._sync_manager.stop()
