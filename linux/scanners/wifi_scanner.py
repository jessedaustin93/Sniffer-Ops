"""
WiFi scanner for Linux using nmcli or iwlist fallback.
Produces signal dicts compatible with the awareness log schema.
"""

import json
import os
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
        interfaces = _wifi_interfaces()
        t0 = time.time()
        if interfaces:
            # Scan every interface concurrently rather than one after another -
            # sequential scanning was measured taking 70-115s end to end during
            # an actual drive (vs. ~15s SCAN_INTERVAL), almost certainly because
            # each interface's own active scan runs slower while constantly
            # passing new APs, and that cost was being paid twice in a row.
            # Threads only wait on the nmcli subprocess call, so this is cheap
            # even on the Pi Zero 2 W - see _log_scan_timing for measurements.
            results_by_if: dict[str, list[dict] | None] = {}
            per_interface_ms: dict[str, int] = {}

            def _run(ifname: str) -> None:
                t_if = time.time()
                results_by_if[ifname] = self._nmcli_scan(ifname)
                per_interface_ms[ifname] = round((time.time() - t_if) * 1000)

            threads = [threading.Thread(target=_run, args=(ifn,), daemon=True) for ifn in interfaces]
            for t in threads:
                t.start()
            for t in threads:
                # Each _nmcli_scan already bounds itself via subprocess timeout=10;
                # this join timeout is just a backstop so one wedged interface
                # can't hold up the whole cycle.
                t.join(timeout=15)

            merged: dict[str, dict] = {}
            saw_any = False
            for ifname in interfaces:
                results = results_by_if.get(ifname)
                if results is None:
                    continue
                saw_any = True
                for r in results:
                    key = r.get("address") or r.get("name")
                    existing = merged.get(key)
                    # Keep whichever interface saw the stronger signal - the
                    # WNDA4100's extra antennas/5GHz support should usually win.
                    if existing is None or (r.get("signalStrength") or -999) > (existing.get("signalStrength") or -999):
                        merged[key] = r
            if saw_any:
                merged_list = list(merged.values())
                self._log_scan_timing(interfaces, per_interface_ms, time.time() - t0, len(merged_list))
                return merged_list

        results = self._nmcli_scan()
        if results is None:
            results = self._iwlist_scan()
        self._log_scan_timing(interfaces or ["default"], {}, time.time() - t0, len(results or []))
        return results or []

    def _log_scan_timing(
        self,
        interfaces: list[str],
        per_interface_ms: dict[str, int],
        total_s: float,
        result_count: int,
    ) -> None:
        """
        Append one JSONL record per scan cycle to the data dir (not journald,
        which doesn't persist across reboots on this appliance) so cadence can
        be checked after the fact instead of guessed at from a stationary test.
        """
        try:
            import paths
            out_dir = os.path.join(paths.ensure_data_dir(), "scan-timing")
            os.makedirs(out_dir, exist_ok=True)
            day = time.strftime("%Y%m%d", time.gmtime())
            record = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "interfaces": interfaces,
                "per_interface_ms": per_interface_ms,
                "total_ms": round(total_s * 1000),
                "result_count": result_count,
            }
            with open(os.path.join(out_dir, f"wifi-{day}.jsonl"), "a") as f:
                f.write(json.dumps(record, separators=(",", ":")) + "\n")
        except Exception:
            pass

    def _loop(self) -> None:
        while self._running:
            try:
                results = self.scan_once()
                if results:
                    self._callback(results)
            except Exception:
                pass
            time.sleep(self.SCAN_INTERVAL)

    def _nmcli_scan(self, ifname: str | None = None) -> list[dict] | None:
        cmd = ["nmcli", "-t", "-f", "SSID,BSSID,SIGNAL,CHAN,FREQ,SECURITY", "dev", "wifi", "list"]
        if ifname:
            cmd += ["ifname", ifname]
        try:
            out = subprocess.check_output(
                cmd, stderr=subprocess.DEVNULL, timeout=10,
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


def _wifi_interfaces() -> list[str]:
    """Return every NetworkManager-managed wifi interface (e.g. the Pi's
    onboard chip plus a USB adapter like the WNDA4100), so scan_once() can
    sweep all of them instead of whichever one NM would pick by default."""
    try:
        out = subprocess.check_output(
            ["nmcli", "-t", "-f", "DEVICE,TYPE", "device", "status"],
            stderr=subprocess.DEVNULL, timeout=5,
        ).decode("utf-8", errors="replace")
    except (FileNotFoundError, subprocess.SubprocessError):
        return []
    interfaces = []
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 2 and parts[1] == "wifi":
            interfaces.append(parts[0])
    return interfaces


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
