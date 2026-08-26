import json
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import awareness_log


def _post(port, path, body):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


@pytest.fixture
def server(tmp_path, monkeypatch):
    """A real awareness_log server against an isolated DB, seeded with one
    signal, with a signal already in it before the test's own POST."""
    awareness_log.set_node_info("test-node", "Test Node")
    awareness_log.initialize(str(tmp_path / "awareness.json"))
    awareness_log.merge_snapshot({
        "schema": 1, "nodeId": "seed", "nodeName": "seed",
        "signals": [{
            "id": "seed-1", "name": "Seed Signal", "type": "WIFI",
            "sightings": [{"id": "sight-1", "capturedAt": 0}],
        }],
    })
    awareness_log.start_server(bind="127.0.0.1", port=0)
    port = awareness_log._server.server_address[1]
    yield port
    awareness_log.stop_server()
    awareness_log.set_bounded_sync_mode(False)  # module-global -- reset for other tests


def test_default_mode_post_sync_includes_signals(server):
    resp = _post(server, "/ethrox-detect/sync", {"schema": 1, "signals": []})
    assert resp["signals"], "expected default (unbounded) mode to include signals"


def test_default_mode_get_awareness_includes_signals(server):
    resp = _get(server, "/ethrox-detect/awareness")
    assert resp["signals"], "expected default (unbounded) mode to include signals"


def test_bounded_mode_post_sync_never_includes_signals(server):
    awareness_log.set_bounded_sync_mode(True)
    resp = _post(server, "/ethrox-detect/sync", {"schema": 1, "signals": []})
    assert resp["signals"] == []
    # Status/ack fields must still work normally.
    assert resp["totalSignals"] >= 1
    assert "merged" in resp
    assert "acknowledgedSightingIds" in resp


def test_bounded_mode_get_awareness_never_includes_signals(server):
    awareness_log.set_bounded_sync_mode(True)
    resp = _get(server, "/ethrox-detect/awareness")
    assert resp["signals"] == []
    assert resp["totalSignals"] >= 1


def test_bounded_mode_post_sync_still_acknowledges_pushed_sightings(server):
    awareness_log.set_bounded_sync_mode(True)
    resp = _post(server, "/ethrox-detect/sync", {
        "schema": 1,
        "signals": [{
            "id": "pushed-1", "name": "Pushed", "type": "WIFI",
            "sightings": [{"id": "pushed-sight-1", "capturedAt": 0}],
        }],
    })
    assert "pushed-sight-1" in resp["acknowledgedSightingIds"]
    assert resp["signals"] == []


def test_export_endpoint_always_returns_full_map_regardless_of_bounded_mode(server):
    awareness_log.set_bounded_sync_mode(True)
    resp = _get(server, "/ethrox-detect/awareness/export")
    assert resp["signals"], "explicit export must return the full map even in bounded mode"


def test_export_endpoint_is_not_on_node_sync_manager_automated_path():
    # NodeSyncManager's periodic loop must never be able to reach the
    # explicit full-map endpoint -- confirms the "not automated" boundary
    # at the client side, independent of the server-side check above.
    from sync import node_sync
    assert "/ethrox-detect/awareness/export" not in node_sync.AWARENESS_PATHS
    assert "/ethrox-detect/awareness/export" not in node_sync.SYNC_PATHS
