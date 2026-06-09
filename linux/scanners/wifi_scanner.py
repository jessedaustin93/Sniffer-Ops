"""
WiFi scanner for Linux using nmcli or iwlist fallback.
Produces signal dicts compatible with the awareness log schema.
"""

import re
import subprocess
import threading
import time
from typing import Callable


class WifiScanner:
    SCAN_INTERVAL = 15

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
        results = self._nmcli_scan()
        if results is None:
            results = self._iwlist_scan()
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

    def _nmcli_scan(self) -> list[dict] | None:
        try:
            out = subprocess.check_output(
                ["nmcli", "-t", "-f", "SSID,BSSID,SIGNAL,CHAN,FREQ,SECURITY", "dev", "wifi", "list"],
                stderr=subprocess.DEVNULL, timeout=10,
            ).decode("utf-8", errors="replace")
        except (FileNotFoundError, subprocess.SubprocessError):
            return None

        results = []
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) < 6:
                continue
            ssid = parts[0].strip() or "<hidden>"
            bssid = ":".join(parts[1:7]).strip()
            try:
                signal_pct = int(parts[7])
                dbm = (signal_pct / 2) - 100
            except (ValueError, IndexError):
                dbm = 0
                signal_pct = 0

            # re-split properly: nmcli -t uses : but BSSID has colons too
            # safer: use field-based output
            results.append({
                "name": ssid,
                "address": bssid,
                "type": "WIFI",
                "signalStrength": dbm,
                "channel": _safe_int(parts[8] if len(parts) > 8 else ""),
                "frequencyHz": _mhz_to_hz(parts[9] if len(parts) > 9 else ""),
                "security": parts[10] if len(parts) > 10 else "",
                "manufacturer": "",
                "deviceClass": "",
                "threatLevel": "UNKNOWN",
                "isEncrypted": bool(parts[10].strip()) if len(parts) > 10 else False,
            })
        return results if results else None

    def _nmcli_scan_fields(self) -> list[dict] | None:
        try:
            out = subprocess.check_output(
                ["nmcli", "--get-values",
                 "SSID,BSSID,SIGNAL,CHAN,FREQ,SECURITY",
                 "dev", "wifi", "list"],
                stderr=subprocess.DEVNULL, timeout=10,
            ).decode("utf-8", errors="replace")
        except (FileNotFoundError, subprocess.SubprocessError):
            return None
        results = []
        lines = [l for l in out.splitlines() if l.strip()]
        # output has one value per line, grouped in blocks of 6
        block = []
        for line in lines:
            block.append(line.strip())
            if len(block) == 6:
                ssid, bssid, signal, chan, freq, sec = block
                block = []
                try:
                    sig_pct = int(signal)
                    dbm = (sig_pct / 2) - 100
                except ValueError:
                    dbm = 0
                results.append({
                    "name": ssid or "<hidden>",
                    "address": bssid,
                    "type": "WIFI",
                    "signalStrength": int(dbm),
                    "channel": _safe_int(chan),
                    "frequencyHz": _mhz_to_hz(freq),
                    "security": sec,
                    "manufacturer": "",
                    "deviceClass": "",
                    "threatLevel": "UNKNOWN",
                    "isEncrypted": bool(sec.strip()),
                })
        return results if results else None

    def _iwlist_scan(self) -> list[dict] | None:
        try:
            out = subprocess.check_output(
                ["sudo", "iwlist", "scanning"],
                stderr=subprocess.DEVNULL, timeout=15,
            ).decode("utf-8", errors="replace")
        except (FileNotFoundError, subprocess.SubprocessError):
            return None

        results = []
        current: dict = {}
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("Cell "):
                if current.get("name") or current.get("address"):
                    results.append(current)
                current = {"type": "WIFI", "manufacturer": "", "deviceClass": "",
                           "threatLevel": "UNKNOWN"}
                m = re.search(r"Address:\s*([0-9A-Fa-f:]+)", line)
                if m:
                    current["address"] = m.group(1)
            elif line.startswith("ESSID:"):
                current["name"] = line.split(":", 1)[1].strip('"') or "<hidden>"
            elif "Signal level=" in line:
                m = re.search(r"Signal level=(-?\d+)", line)
                if m:
                    current["signalStrength"] = int(m.group(1))
            elif line.startswith("Channel:"):
                current["channel"] = _safe_int(line.split(":", 1)[1])
            elif line.startswith("Frequency:"):
                m = re.search(r"([\d.]+)\s*GHz", line)
                if m:
                    current["frequencyHz"] = int(float(m.group(1)) * 1e9)
            elif "Encryption key:" in line:
                current["isEncrypted"] = "on" in line.lower()
                current["security"] = "WPA" if "on" in line.lower() else "open"

        if current.get("name") or current.get("address"):
            results.append(current)
        return results if results else None


def scan_once() -> list[dict]:
    scanner = WifiScanner(lambda _: None)
    result = scanner._nmcli_scan_fields()
    if not result:
        result = scanner._nmcli_scan()
    if not result:
        result = scanner._iwlist_scan()
    return result or []


def _safe_int(val: str) -> int:
    try:
        return int(str(val).strip())
    except ValueError:
        return 0


def _mhz_to_hz(val: str) -> int:
    val = str(val).strip().upper().replace("MHZ", "").replace("GHZ", "000").strip()
    try:
        return int(float(val) * 1_000_000)
    except ValueError:
        return 0
