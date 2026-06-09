"""
Bluetooth scanner for Linux using bluetoothctl and hcitool.
Supports classic BT discovery and BLE (requires bluetoothctl >= 5.50).
"""

import re
import subprocess
import threading
import time
from typing import Callable


class BluetoothScanner:
    SCAN_DURATION = 10   # seconds for each BT scan pass
    SCAN_INTERVAL = 20

    def __init__(self, on_results: Callable[[list[dict]], None]):
        self._callback = on_results
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def scan_once(self) -> list[dict]:
        results = self._bluetoothctl_scan()
        if not results:
            results = self._hcitool_scan()
        return results or []

    def _loop(self) -> None:
        while self._running:
            try:
                results = self.scan_once()
                if results:
                    self._callback(results)
            except Exception:
                pass
            time.sleep(self.SCAN_INTERVAL)

    def _bluetoothctl_scan(self) -> list[dict] | None:
        try:
            # Start scan then grab devices list
            subprocess.run(
                ["bluetoothctl", "--timeout", str(self.SCAN_DURATION), "scan", "on"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=self.SCAN_DURATION + 3,
            )
            out = subprocess.check_output(
                ["bluetoothctl", "devices"],
                stderr=subprocess.DEVNULL, timeout=5,
            ).decode("utf-8", errors="replace")
        except (FileNotFoundError, subprocess.SubprocessError):
            return None

        results = []
        for line in out.splitlines():
            m = re.match(r"Device\s+([0-9A-Fa-f:]{17})\s+(.*)", line.strip())
            if not m:
                continue
            mac, name = m.group(1), m.group(2).strip()
            rssi = self._get_rssi(mac)
            results.append({
                "name": name or mac,
                "address": mac,
                "type": "BLUETOOTH",
                "signalStrength": rssi,
                "manufacturer": "",
                "deviceClass": "",
                "threatLevel": "UNKNOWN",
                "isEncrypted": False,
                "channel": 0,
                "frequencyHz": 2_402_000_000,
            })
        return results if results else None

    def _get_rssi(self, mac: str) -> int:
        try:
            out = subprocess.check_output(
                ["bluetoothctl", "info", mac],
                stderr=subprocess.DEVNULL, timeout=3,
            ).decode("utf-8", errors="replace")
            m = re.search(r"RSSI:\s*(-?\d+)", out)
            if m:
                return int(m.group(1))
        except Exception:
            pass
        return -80

    def _hcitool_scan(self) -> list[dict] | None:
        try:
            out = subprocess.check_output(
                ["hcitool", "scan", "--flush"],
                stderr=subprocess.DEVNULL, timeout=15,
            ).decode("utf-8", errors="replace")
        except (FileNotFoundError, subprocess.SubprocessError):
            return None

        results = []
        for line in out.splitlines():
            m = re.match(r"\s*([0-9A-Fa-f:]{17})\s+(.*)", line)
            if not m:
                continue
            mac, name = m.group(1), m.group(2).strip()
            results.append({
                "name": name or mac,
                "address": mac,
                "type": "BLUETOOTH",
                "signalStrength": -80,
                "manufacturer": "",
                "deviceClass": "",
                "threatLevel": "UNKNOWN",
                "isEncrypted": False,
                "channel": 0,
                "frequencyHz": 2_402_000_000,
            })
        return results if results else None


def scan_once() -> list[dict]:
    scanner = BluetoothScanner(lambda _: None)
    return scanner.scan_once()
