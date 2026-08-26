import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sync import node_sync


class FakeAwarenessLog:
    """Records whether merge_snapshot was ever called -- the thing
    outbound-only mode must never do, regardless of what the peer sends."""

    def __init__(self):
        self.merge_calls: list[dict] = []

    def merge_snapshot(self, snap: dict) -> None:
        self.merge_calls.append(snap)


def _manager(monkeypatch, outbound_only: bool, post_response, get_response=None):
    log = FakeAwarenessLog()
    manager = node_sync.NodeSyncManager(
        log, "node-1", "Test Node", outbound_only=outbound_only,
    )
    monkeypatch.setattr(node_sync.db, "build_sync_payload",
                        lambda node_id, node_name: {"schema": 1, "signals": []})
    monkeypatch.setattr(node_sync.db, "mark_synced", lambda ids: None)
    monkeypatch.setattr(
        node_sync, "_http_post_any",
        lambda host, port, paths, payload, timeout=8: post_response,
    )
    monkeypatch.setattr(
        node_sync, "_http_get_any",
        lambda host, port, paths, timeout=8: get_response,
    )
    return manager, log


def test_outbound_only_does_not_merge_signals_from_post_response(monkeypatch):
    manager, log = _manager(
        monkeypatch, outbound_only=True,
        post_response={
            "signals": [{"id": "s1", "name": "should-not-be-merged"}],
            "acknowledgedSightingIds": ["a1", "a2"],
            "totalSignals": 999,
        },
    )
    status = manager._sync_peer({"host": "10.0.0.1", "port": 8766, "name": "hub"})
    assert log.merge_calls == []
    assert "outbound only" in status
    assert "2 sightings acked" in status


def test_outbound_only_does_not_pull_when_post_response_has_no_signals(monkeypatch):
    manager, log = _manager(
        monkeypatch, outbound_only=True,
        post_response={"signals": [], "acknowledgedSightingIds": []},
        get_response={"signals": [{"id": "s1", "name": "should-not-be-pulled"}]},
    )
    pulled = []
    monkeypatch.setattr(
        node_sync, "_http_get_any",
        lambda *a, **k: (pulled.append(1) or {"signals": [{"id": "s1"}]}),
    )
    manager._sync_peer({"host": "10.0.0.1", "port": 8766, "name": "hub"})
    assert pulled == []  # the empty-response GET /awareness fallback never ran
    assert log.merge_calls == []


def test_outbound_only_does_not_pull_on_post_failure(monkeypatch):
    manager, log = _manager(
        monkeypatch, outbound_only=True,
        post_response=None,
    )
    pulled = []
    monkeypatch.setattr(
        node_sync, "_http_get_any",
        lambda *a, **k: (pulled.append(1) or {"signals": [{"id": "s1"}]}),
    )
    try:
        manager._sync_peer({"host": "10.0.0.1", "port": 8766, "name": "hub"})
        assert False, "expected ConnectionError"
    except ConnectionError:
        pass
    assert pulled == []  # the POST-failure GET pull never ran
    assert log.merge_calls == []


def test_outbound_only_still_acknowledges_and_marks_synced(monkeypatch):
    marked = []
    manager, log = _manager(
        monkeypatch, outbound_only=True,
        post_response={"signals": [], "acknowledgedSightingIds": ["a1", "a2", "a3"]},
    )
    monkeypatch.setattr(node_sync.db, "mark_synced", lambda ids: marked.extend(ids))
    status = manager._sync_peer({"host": "10.0.0.1", "port": 8766, "name": "hub"})
    assert marked == ["a1", "a2", "a3"]
    assert "3 sightings acked" in status


def test_bidirectional_default_still_merges_signals_from_post_response(monkeypatch):
    # Regression guard: outbound_only must be opt-in -- existing peers
    # (Windows/Android/other Linux nodes) still get the full pull/merge
    # behavior by default.
    manager, log = _manager(
        monkeypatch, outbound_only=False,
        post_response={
            "signals": [{"id": "s1", "name": "should-be-merged"}],
            "acknowledgedSightingIds": [],
            "totalSignals": 1,
        },
    )
    manager._sync_peer({"host": "10.0.0.1", "port": 8766, "name": "hub"})
    assert len(log.merge_calls) == 1
    assert log.merge_calls[0]["signals"][0]["id"] == "s1"
