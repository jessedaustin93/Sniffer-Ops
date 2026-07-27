#!/usr/bin/env python3
"""
Ethrox Detect Linux Companion
- Awareness map consolidation hub (same HTTP API as Windows on port 8766)
- WiFi + Bluetooth scanning
- RTL-SDR spectrum sweeps (if hardware present)
- Android sync (receives POST /ethrox-detect/sync)
- Windows / Linux peer sync (push/pull)
- Terminal UI powered by Rich
"""

import argparse
import json
import os
import platform
import socket
import sys
import threading
import time
import uuid

# Ensure repo root is on path when run directly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import awareness_log
import signal_classifier
import signal_signatures
import ownership
import db
import version_info
from lenses.all_lenses import ALL_LENSES, route
from scanners.wifi_scanner import WifiScanner
from scanners.bluetooth_scanner import BluetoothScanner
from scanners.gps_scanner import GpsScanner
from sync.node_sync import NodeSyncManager, check_peer_health

try:
    from rich.console import Console
    from rich.table import Table
    from rich.live import Live
    from rich.panel import Panel
    from rich.columns import Columns
    from rich.text import Text
    from rich import box
    RICH = True
except ImportError:
    RICH = False

# ── Config ────────────────────────────────────────────────────────────────────

DATA_DIR = os.path.expanduser(os.environ.get("ETHROX_DETECT_DATA_DIR", "~/.ethrox-detect"))
LOG_PATH = os.path.join(DATA_DIR, "awareness.json")
SYNC_PORT = 8766
NODE_ID = str(uuid.uuid4())[:16]
NODE_NAME = f"linux-{platform.node()}"

# ── Globals ───────────────────────────────────────────────────────────────────

_scan_stats = {"wifi": 0, "bt": 0, "sdr": 0, "syncs": 0}
_console = Console() if RICH else None
_gps_scanner: "GpsScanner | None" = None


# ── Scanner callbacks ─────────────────────────────────────────────────────────

def _stamp_gps(signals: list[dict]) -> None:
    """Attach the current GPS fix (if any, and not stale) to each signal in
    a batch. Uses setdefault so a signal that already carries its own
    position (e.g. relayed from a phone) is left alone."""
    if _gps_scanner is None:
        return
    fix = _gps_scanner.get_fix()
    if not fix:
        return
    for s in signals:
        s.setdefault("latitude", fix["latitude"])
        s.setdefault("longitude", fix["longitude"])
        if fix.get("accuracyMeters") is not None:
            s.setdefault("accuracyMeters", fix["accuracyMeters"])
        if fix.get("speedMetersPerSecond") is not None:
            s.setdefault("speedMetersPerSecond", fix["speedMetersPerSecond"])
        if fix.get("bearingDegrees") is not None:
            s.setdefault("bearingDegrees", fix["bearingDegrees"])
        s.setdefault("locationProvider", fix.get("locationProvider"))


def _on_wifi(signals: list[dict]) -> None:
    _stamp_gps(signals)
    for s in signals:
        previous = db.get_profile(db.signal_profile_id(s))
        expl = signal_classifier.classify_wifi(s)
        s["deviceClass"] = expl.specific_type
        signature = signal_signatures.annotate_signal(s)
        cue = signal_signatures.live_cue(s, previous.get("last_signal") if previous else None)
        if signature.matched:
            s["notes"] = "; ".join(part for part in (
                s.get("notes", ""),
                f"Live cue: {cue['label']}",
            ) if part)
        ownership.apply_trust(s)
    _submit_snapshot(signals, "WIFI")
    _scan_stats["wifi"] += len(signals)


def _on_bluetooth(devices: list[dict]) -> None:
    _stamp_gps(devices)
    for d in devices:
        previous = db.get_profile(db.signal_profile_id(d))
        expl = signal_classifier.classify_bluetooth(d)
        d["deviceClass"] = expl.specific_type
        signature = signal_signatures.annotate_signal(d)
        cue = signal_signatures.live_cue(d, previous.get("last_signal") if previous else None)
        if signature.matched:
            d["notes"] = "; ".join(part for part in (
                d.get("notes", ""),
                f"Live cue: {cue['label']}",
            ) if part)
        ownership.apply_trust(d)
    _submit_snapshot(devices, "BLUETOOTH")
    _scan_stats["bt"] += len(devices)


def _on_sdr(signals: list[dict]) -> None:
    _stamp_gps(signals)
    for s in signals:
        freq = s.get("frequencyHz") or 0
        expl = signal_classifier.classify_sdr(freq)
        s["deviceClass"] = expl.specific_type
        directive = route(freq)
        if directive:
            s["notes"] = f"Lens: {directive.kind}/{directive.mode or directive.title}"
    _submit_snapshot(signals, "RTL_SDR")
    _scan_stats["sdr"] += len(signals)


def _submit_snapshot(signals: list[dict], signal_type: str) -> None:
    for signal in signals:
        signal["type"] = signal.get("type") or signal_type
        db.write_detection(signal, NODE_ID)
    _scan_stats["syncs"] += 1


# ── TUI ───────────────────────────────────────────────────────────────────────

def _build_table(rows: list[dict]) -> "Table":
    t = Table(
        title="[bold green]Ethrox Detect Awareness Map[/bold green]",
        box=box.SIMPLE_HEAVY,
        show_lines=False,
        header_style="bold cyan",
    )
    t.add_column("Type", style="cyan", width=10)
    t.add_column("Signal", style="white", width=28)
    t.add_column("Addr / Freq", style="dim white", width=22)
    t.add_column("Strength", style="yellow", width=10)
    t.add_column("Class", style="green", width=28)
    t.add_column("Details", style="dim", width=50)

    for r in rows[:40]:
        t.add_row(
            str(r.get("Type") or ""),
            str(r.get("Signal") or "")[:27],
            str(r.get("AddressOrFrequency") or "")[:21],
            str(r.get("StrengthOrPower") or ""),
            str(r.get("Classification") or "")[:27],
            str(r.get("Details") or "")[:49],
        )
    return t


def _build_status(peers: list[dict]) -> str:
    parts = [
        f"[bold]Node:[/bold] {NODE_NAME}",
        f"[bold]Port:[/bold] {SYNC_PORT}",
        f"WiFi scans: {_scan_stats['wifi']}  "
        f"BT scans: {_scan_stats['bt']}  "
        f"SDR peaks: {_scan_stats['sdr']}  "
        f"Syncs: {_scan_stats['syncs']}",
    ]
    if peers:
        peer_strs = []
        for p in peers:
            alive = check_peer_health(p["host"], p.get("port", 8766))
            icon = "[green]●[/green]" if alive else "[red]●[/red]"
            peer_strs.append(f"{icon} {p.get('name', p['host'])}")
        parts.append("Peers: " + "  ".join(peer_strs))
    return "  |  ".join(parts)


def _run_tui(sync_manager: NodeSyncManager) -> None:
    if not RICH:
        _run_plain(sync_manager)
        return

    with Live(refresh_per_second=1, screen=True) as live:
        while True:
            rows = awareness_log.get_rows()
            table = _build_table(rows)
            status = _build_status(sync_manager._peers)
            panel = Panel(table, title="[bold green]Ethrox Detect Linux[/bold green]",
                          subtitle=status, border_style="green")
            live.update(panel)
            time.sleep(2)


def _run_plain(sync_manager: NodeSyncManager) -> None:
    while True:
        rows = awareness_log.get_rows()
        print(f"\n=== Ethrox Detect Linux ({NODE_NAME}) — port {SYNC_PORT} ===")
        print(f"WiFi:{_scan_stats['wifi']} BT:{_scan_stats['bt']} "
              f"SDR:{_scan_stats['sdr']} Syncs:{_scan_stats['syncs']}")
        print(f"{'Type':<10} {'Signal':<25} {'Addr/Freq':<20} {'Strength':<10} {'Class':<25}")
        print("-" * 95)
        for r in rows[:30]:
            print(f"{str(r.get('Type','')):<10} {str(r.get('Signal',''))[:24]:<25} "
                  f"{str(r.get('AddressOrFrequency',''))[:19]:<20} "
                  f"{str(r.get('StrengthOrPower','')):<10} "
                  f"{str(r.get('Classification',''))[:24]:<25}")
        time.sleep(5)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Ethrox Detect Linux Companion")
    parser.add_argument("--version", action="store_true",
                        help="show version and exit")
    parser.add_argument("--port", type=int, default=SYNC_PORT,
                        help="HTTP sync server port (default 8766)")
    parser.add_argument("--bind", default="0.0.0.0",
                        help="Bind address for sync server")
    parser.add_argument("--peer", action="append", default=[],
                        metavar="HOST[:PORT[:NAME]]",
                        help="Add a peer node to sync with (can repeat)")
    parser.add_argument("--no-wifi", action="store_true",
                        help="Disable WiFi scanning")
    parser.add_argument("--no-bt", action="store_true",
                        help="Disable Bluetooth scanning")
    parser.add_argument("--no-sdr", action="store_true",
                        help="Disable RTL-SDR scanning")
    parser.add_argument("--sdr-remote", metavar="HOST[:PORT]",
                        help="Connect to remote rtl_tcp server instead of local hardware")
    parser.add_argument("--plain", action="store_true",
                        help="Plain text output (no Rich TUI)")
    parser.add_argument("--no-ui", action="store_true",
                        help="Run scanners and API without rendering a terminal UI")
    parser.add_argument("--no-gps", action="store_true",
                        help="Disable GPS tagging via gpsd")
    args = parser.parse_args()

    if args.version:
        print(version_info.version_text())
        return

    # Init awareness log
    os.makedirs(DATA_DIR, exist_ok=True)
    awareness_log.initialize(LOG_PATH)

    # Start HTTP sync server (serves Android, Windows, and other Linux nodes)
    awareness_log.start_server(bind=args.bind, port=args.port)
    print(f"[ethrox-detect] Sync server listening on {args.bind}:{args.port}")

    # Build peer list from --peer args
    peers = []
    for peer_str in args.peer:
        parts = peer_str.split(":")
        host = parts[0]
        port = int(parts[1]) if len(parts) > 1 else 8766
        name = parts[2] if len(parts) > 2 else host
        peers.append({"host": host, "port": port, "name": name})

    # Node sync manager (push/pull with Windows + other Linux nodes)
    sync_manager = NodeSyncManager(awareness_log, NODE_ID, NODE_NAME, peers)
    sync_manager.start()

    # Start scanners
    if not args.no_gps:
        global _gps_scanner
        _gps_scanner = GpsScanner()
        _gps_scanner.start()
        print("[ethrox-detect] GPS scanner started (gpsd @ 127.0.0.1:2947)")

    if not args.no_wifi:
        WifiScanner(_on_wifi).start()
        print("[ethrox-detect] WiFi scanner started")

    if not args.no_bt:
        BluetoothScanner(_on_bluetooth).start()
        print("[ethrox-detect] Bluetooth scanner started")

    if not args.no_sdr:
        if args.sdr_remote:
            from scanners.rtl_sdr_scanner import NetworkRtlSdrScanner
            parts = args.sdr_remote.split(":")
            rhost = parts[0]
            rport = int(parts[1]) if len(parts) > 1 else 1234
            NetworkRtlSdrScanner(rhost, rport, _on_sdr).start()
            print(f"[ethrox-detect] RTL-SDR remote scanner → {rhost}:{rport}")
        else:
            from scanners.rtl_sdr_scanner import RtlSdrScanner
            RtlSdrScanner(_on_sdr).start()
            print("[ethrox-detect] RTL-SDR local scanner started")

    print(f"[ethrox-detect] Node ID: {NODE_ID}")
    print("[ethrox-detect] Press Ctrl+C to stop\n")

    if args.no_ui:
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            pass
        return

    if args.plain or not RICH:
        _run_plain(sync_manager)
    else:
        _run_tui(sync_manager)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[ethrox-detect] Stopped.")
        awareness_log.stop_server()
        sys.exit(0)
