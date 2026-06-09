"""
Multi-node sync manager.
Handles push/pull between this Linux node and Windows, other Linux nodes,
and serves as the HTTP backend that Android syncs to.

Configured via a peers list: [{"host": "192.168.1.10", "port": 8765, "name": "windows-pc"}]
"""

import json
import socket
import threading
import time
import urllib.request
from typing import Any


class NodeSyncManager:
    SYNC_INTERVAL = 30   # seconds between peer syncs

    def __init__(self, awareness_log_module, node_id: str, node_name: str,
                 peers: list[dict] | None = None):
        self._log = awareness_log_module
        self._node_id = node_id
        self._node_name = node_name
        self._peers: list[dict] = peers or []
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_sync: dict[str, float] = {}

    def add_peer(self, host: str, port: int = 8765, name: str = "") -> None:
        for p in self._peers:
            if p["host"] == host and p["port"] == port:
                return
        self._peers.append({"host": host, "port": port, "name": name or host})

    def remove_peer(self, host: str, port: int = 8765) -> None:
        self._peers = [p for p in self._peers
                       if not (p["host"] == host and p["port"] == port)]

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def sync_all_now(self) -> dict[str, str]:
        """Immediately sync with all peers. Returns {peer_name: status}."""
        results = {}
        for peer in list(self._peers):
            key = f"{peer['host']}:{peer['port']}"
            try:
                status = self._sync_peer(peer)
                results[peer.get("name", key)] = status
            except Exception as exc:
                results[peer.get("name", key)] = f"error: {exc}"
        return results

    def _loop(self) -> None:
        while self._running:
            now = time.time()
            for peer in list(self._peers):
                key = f"{peer['host']}:{peer['port']}"
                if now - self._last_sync.get(key, 0) >= self.SYNC_INTERVAL:
                    try:
                        self._sync_peer(peer)
                        self._last_sync[key] = now
                    except Exception:
                        pass
            time.sleep(5)

    def _sync_peer(self, peer: dict) -> str:
        host, port = peer["host"], peer.get("port", 8765)
        payload = self._log.get_sync_payload()
        # Wrap as a snapshot so the remote node can merge it
        snapshot = {
            "schema": 1,
            "nodeId": self._node_id,
            "nodeName": self._node_name,
            "capturedAt": int(time.time() * 1000),
            "location": {},
            "completeTypes": list({s.get("type", "") for s in payload.get("signals", [])}),
            "signals": _awareness_signals_to_snapshot(payload.get("signals", [])),
        }
        result = _http_post(host, port, "/snifferops/sync", snapshot)
        if result:
            # Merge whatever the remote returned into our own log
            remote_signals = result.get("signals", [])
            remote_snapshot = {
                "schema": 1,
                "nodeId": f"{host}:{port}",
                "nodeName": peer.get("name", host),
                "capturedAt": int(time.time() * 1000),
                "location": {},
                "completeTypes": [],
                "signals": _awareness_signals_to_snapshot(remote_signals),
            }
            self._log.merge_snapshot(remote_snapshot)
            return f"ok ({result.get('totalSignals', 0)} remote signals)"
        return "no response"


def _awareness_signals_to_snapshot(signals: list[dict]) -> list[dict]:
    """Convert awareness payload signals to snapshot signal format."""
    out = []
    for s in signals:
        out.append({
            "name": s.get("name", ""),
            "address": s.get("address", ""),
            "type": s.get("type", "UNKNOWN"),
            "signalStrength": s.get("signalStrength") or s.get("strongestSignal"),
            "frequencyHz": s.get("frequencyHz"),
            "manufacturer": s.get("manufacturer", ""),
            "deviceClass": s.get("deviceClass", ""),
            "threatLevel": s.get("threatLevel", "UNKNOWN"),
            "channel": s.get("channel"),
            "notes": f"synced; seen {s.get('seenCount', 0)}x from {s.get('nodeCount', 0)} node(s)",
        })
    return out


def _http_post(host: str, port: int, path: str, body: dict) -> dict | None:
    url = f"http://{host}:{port}{path}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def check_peer_health(host: str, port: int = 8765) -> bool:
    url = f"http://{host}:{port}/snifferops/health"
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("ok") is True
    except Exception:
        return False
