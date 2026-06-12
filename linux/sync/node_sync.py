"""
Multi-node sync manager — Tailscale-aware, bidirectional.

Sync protocol (wire-compatible across Linux / Windows / Android):
  POST /snifferops/sync  → push our snapshot, receive peer's full payload → merge both
  GET  /snifferops/awareness → pull full state (fallback / initial import)
  GET  /snifferops/health    → liveness check

Tailscale auto-discovery:
  On startup and every DISCOVERY_INTERVAL seconds, query `tailscale status --json`,
  probe each peer's :8766 health endpoint, and add any SnifferOps nodes automatically.
  Discovered peers are tagged {"via": "tailscale"} and persisted to config.json.
"""

import json
import logging
import subprocess
import threading
import time
import urllib.request
from typing import Any

log = logging.getLogger("snifferops.sync")


class NodeSyncManager:
    SYNC_INTERVAL      = 30    # seconds between peer sync cycles
    DISCOVERY_INTERVAL = 60    # seconds between Tailscale rediscovery passes
    PROBE_TIMEOUT      = 3     # seconds for health probe
    SYNC_TIMEOUT       = 8     # seconds for sync POST/GET
    MAX_BACKOFF        = 300   # max seconds before retrying a failing peer

    def __init__(self, awareness_log_module, node_id: str, node_name: str,
                 peers: list[dict] | None = None,
                 on_peer_update: "callable | None" = None):
        self._log        = awareness_log_module
        self._node_id    = node_id
        self._node_name  = node_name
        self._peers: list[dict] = list(peers or [])
        self._on_update  = on_peer_update   # called with updated peer list on discovery
        self._running    = False
        self._lock       = threading.Lock()
        self._thread: threading.Thread | None = None
        self._last_sync:      dict[str, float] = {}  # key → last successful sync epoch
        self._fail_count:     dict[str, int]   = {}  # key → consecutive failure count
        self._last_discovery: float = 0.0

    # ── Public API ─────────────────────────────────────────────────────────────

    def add_peer(self, host: str, port: int = 8766, name: str = "",
                 via: str = "") -> bool:
        """Add a peer. Returns True if it was new."""
        with self._lock:
            for p in self._peers:
                if p["host"] == host and p["port"] == port:
                    return False
            self._peers.append({
                "host": host, "port": port,
                "name": name or host,
                "via": via,
            })
        log.info("Peer added: %s:%s (%s)", host, port, name or host)
        return True

    def remove_peer(self, host: str, port: int = 8766) -> None:
        with self._lock:
            self._peers = [p for p in self._peers
                           if not (p["host"] == host and p["port"] == port)]
        key = f"{host}:{port}"
        self._last_sync.pop(key, None)
        self._fail_count.pop(key, None)

    def peer_list(self) -> list[dict]:
        with self._lock:
            return list(self._peers)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        # Run discovery immediately in background, then start main loop
        threading.Thread(target=self._discover_tailscale, daemon=True).start()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="snifferops-sync")
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def sync_all_now(self) -> dict[str, str]:
        """Force-sync all peers immediately. Returns {name: status}."""
        results = {}
        with self._lock:
            peers = list(self._peers)
        for peer in peers:
            key = f"{peer['host']}:{peer['port']}"
            try:
                status = self._sync_peer(peer)
                results[peer.get("name", key)] = status
                self._last_sync[key] = time.time()
                self._fail_count[key] = 0
            except Exception as exc:
                results[peer.get("name", key)] = f"error: {exc}"
                self._fail_count[key] = self._fail_count.get(key, 0) + 1
        return results

    # ── Main sync loop ─────────────────────────────────────────────────────────

    def _loop(self) -> None:
        while self._running:
            now = time.time()

            # Periodic Tailscale rediscovery
            if now - self._last_discovery >= self.DISCOVERY_INTERVAL:
                threading.Thread(target=self._discover_tailscale, daemon=True).start()

            # Sync each peer if it's due
            with self._lock:
                peers = list(self._peers)

            for peer in peers:
                key = f"{peer['host']}:{peer['port']}"
                fails = self._fail_count.get(key, 0)
                # Exponential back-off: 30s → 60s → 120s → … → MAX_BACKOFF
                backoff = min(self.SYNC_INTERVAL * (2 ** fails), self.MAX_BACKOFF)
                if now - self._last_sync.get(key, 0) < backoff:
                    continue
                try:
                    status = self._sync_peer(peer)
                    self._last_sync[key] = now
                    self._fail_count[key] = 0
                    log.debug("Synced %s: %s", peer.get("name", key), status)
                except Exception as exc:
                    self._fail_count[key] = fails + 1
                    log.debug("Sync failed %s (fail #%d): %s", key, fails + 1, exc)

            time.sleep(5)

    # ── Tailscale auto-discovery ───────────────────────────────────────────────

    def _discover_tailscale(self) -> None:
        self._last_discovery = time.time()
        nodes = _tailscale_nodes()
        if not nodes:
            return

        added = []
        with self._lock:
            existing_hosts = {p["host"] for p in self._peers}

        for node in nodes:
            ip   = node["ip"]
            name = node["name"]
            if ip in existing_hosts:
                continue
            # Probe for SnifferOps
            if check_peer_health(ip, 8766, timeout=self.PROBE_TIMEOUT):
                if self.add_peer(ip, 8766, name, via="tailscale"):
                    added.append({"host": ip, "port": 8766, "name": name, "via": "tailscale"})
                    log.info("Auto-discovered Tailscale peer: %s (%s)", name, ip)

        if added and self._on_update:
            try:
                self._on_update(added)
            except Exception:
                pass

    # ── Per-peer sync ──────────────────────────────────────────────────────────

    def _sync_peer(self, peer: dict) -> str:
        host, port = peer["host"], peer.get("port", 8766)

        # Build our outgoing snapshot
        payload  = self._log.get_sync_payload()
        snapshot = {
            "schema":       1,
            "nodeId":       self._node_id,
            "nodeName":     self._node_name,
            "capturedAt":   int(time.time() * 1000),
            "location":     {},
            "completeTypes": list({s.get("type", "") for s in payload.get("signals", [])}),
            "signals":      _to_snapshot_signals(payload.get("signals", [])),
        }

        # Push our snapshot; the remote returns its own full payload
        remote = _http_post(host, port, "/snifferops/sync", snapshot,
                            timeout=self.SYNC_TIMEOUT)

        if remote:
            remote_snap = {
                "schema":       1,
                "nodeId":       f"{host}:{port}",
                "nodeName":     peer.get("name", host),
                "capturedAt":   int(time.time() * 1000),
                "location":     {},
                "completeTypes": [],
                "signals":      _to_snapshot_signals(remote.get("signals", [])),
            }
            self._log.merge_snapshot(remote_snap)
            n = remote.get("totalSignals", 0)
            return f"ok — {n} signals from peer"

        # POST failed; try a plain GET pull as fallback (older/Windows nodes)
        pulled = _http_get(host, port, "/snifferops/awareness",
                           timeout=self.SYNC_TIMEOUT)
        if pulled:
            pull_snap = {
                "schema":       1,
                "nodeId":       f"{host}:{port}",
                "nodeName":     peer.get("name", host),
                "capturedAt":   int(time.time() * 1000),
                "location":     {},
                "completeTypes": [],
                "signals":      _to_snapshot_signals(pulled.get("signals", [])),
            }
            self._log.merge_snapshot(pull_snap)
            n = pulled.get("totalSignals", 0)
            return f"ok (pull) — {n} signals from peer"

        raise ConnectionError(f"no response from {host}:{port}")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _to_snapshot_signals(signals: list[dict]) -> list[dict]:
    out = []
    for s in signals:
        out.append({
            "name":         s.get("name", ""),
            "address":      s.get("address", ""),
            "type":         s.get("type", "UNKNOWN"),
            "signalStrength": s.get("signalStrength") or s.get("strongestSignal"),
            "frequencyHz":  s.get("frequencyHz"),
            "manufacturer": s.get("manufacturer", ""),
            "deviceClass":  s.get("deviceClass", ""),
            "threatLevel":  s.get("threatLevel", "UNKNOWN"),
            "channel":      s.get("channel"),
            "notes": (f"synced; seen {s.get('seenCount', 0)}x "
                      f"from {s.get('nodeCount', 0)} node(s)"),
        })
    return out


def _tailscale_nodes() -> list[dict]:
    """Return [{name, ip, os}] for all online Tailscale peers."""
    try:
        r = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True, text=True, timeout=6,
        )
        data = json.loads(r.stdout)
        nodes = []
        for v in data.get("Peer", {}).values():
            if not v.get("Online"):
                continue
            ips = v.get("TailscaleIPs", [])
            ip4 = next((x for x in ips if "." in x), None)
            if ip4:
                nodes.append({
                    "name": v.get("HostName", ip4),
                    "ip":   ip4,
                    "os":   v.get("OS", ""),
                })
        return nodes
    except Exception:
        return []


def _http_post(host: str, port: int, path: str, body: dict,
               timeout: int = 8) -> dict | None:
    url  = f"http://{host}:{port}{path}"
    data = json.dumps(body).encode("utf-8")
    req  = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _http_get(host: str, port: int, path: str,
              timeout: int = 8) -> dict | None:
    url = f"http://{host}:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def check_peer_health(host: str, port: int = 8766,
                      timeout: int = 3) -> bool:
    data = _http_get(host, port, "/snifferops/health", timeout=timeout)
    return bool(data and data.get("ok") is True)
