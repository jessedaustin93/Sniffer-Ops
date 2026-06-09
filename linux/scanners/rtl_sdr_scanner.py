"""
RTL-SDR scanner for Linux.
Drives rtl_power for spectrum sweeps and rtl_tcp for IQ streaming.
Also supports connecting to a remote rtl_tcp server (Windows or another Linux node).
"""

import csv
import io
import os
import signal
import socket
import struct
import subprocess
import tempfile
import threading
import time
from typing import Callable

from ..spectrum.power_scan import parse_rtl_power_csv, find_peaks


class RtlSdrScanner:
    """Spectrum sweep using rtl_power — no driver binding needed."""

    DEFAULT_FREQ_RANGE = "80M:1800M"
    DEFAULT_BIN_SIZE = "200k"
    DEFAULT_INTERVAL = 60  # seconds between sweeps

    def __init__(self, on_results: Callable[[list[dict]], None],
                 freq_range: str = DEFAULT_FREQ_RANGE,
                 bin_size: str = DEFAULT_BIN_SIZE,
                 interval: int = DEFAULT_INTERVAL,
                 device_index: int = 0):
        self._callback = on_results
        self._freq_range = freq_range
        self._bin_size = bin_size
        self._interval = interval
        self._device_index = device_index
        self._running = False
        self._thread: threading.Thread | None = None
        self._proc: subprocess.Popen | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._proc:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def scan_once(self) -> list[dict]:
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            cmd = [
                "rtl_power",
                "-f", self._freq_range,
                "-i", "1",
                "-1",
                "-g", "40",
                "-d", str(self._device_index),
                tmp_path,
            ]
            result = subprocess.run(
                cmd, timeout=30,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            if result.returncode != 0:
                return []
            with open(tmp_path, "r") as f:
                raw = f.read()
            peaks = find_peaks(parse_rtl_power_csv(raw))
            return [_peak_to_signal(p) for p in peaks]
        except (FileNotFoundError, subprocess.SubprocessError, Exception):
            return []
        finally:
            try:
                os.unlink(tmp_path)
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
            time.sleep(self._interval)


class NetworkRtlSdrScanner:
    """
    Connect to a remote rtl_tcp server (Windows or Linux node).
    Same binary protocol as the Android NetworkRtlSdrScanner.kt.
    """

    SAMPLE_RATE = 1_024_000
    IQ_CHUNK = 16_384
    TUNE_WAIT = 0.12

    DEFAULT_FREQS = [
        88_500_000, 96_900_000, 100_100_000,      # FM
        118_000_000, 121_500_000, 122_800_000,     # Aviation
        144_390_000, 146_520_000,                  # Amateur 2m
        162_400_000, 162_425_000, 162_450_000,     # NOAA WX
        433_920_000, 915_000_000,                  # ISM
        978_000_000, 1_090_000_000,                # ADS-B
    ]

    def __init__(self, host: str, port: int = 1234,
                 on_results: Callable[[list[dict]], None] | None = None,
                 frequencies: list[int] | None = None):
        self._host = host
        self._port = port
        self._callback = on_results
        self._freqs = frequencies or self.DEFAULT_FREQS
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

    def _rtl_cmd(self, sock: socket.socket, cmd: int, param: int) -> None:
        sock.sendall(struct.pack(">BI", cmd, param))

    def scan_once(self) -> list[dict]:
        results = []
        try:
            with socket.create_connection((self._host, self._port), timeout=1.5) as sock:
                sock.settimeout(1.2)
                self._rtl_cmd(sock, 0x02, self.SAMPLE_RATE)
                self._rtl_cmd(sock, 0x03, 0)
                self._rtl_cmd(sock, 0x04, 0)
                for freq in self._freqs:
                    if not self._running:
                        break
                    self._rtl_cmd(sock, 0x01, freq)
                    time.sleep(self.TUNE_WAIT)
                    try:
                        iq = sock.recv(self.IQ_CHUNK)
                    except socket.timeout:
                        iq = b""
                    power = _estimate_power(iq)
                    results.append({
                        "name": f"RF {freq/1e6:.3f} MHz",
                        "address": f"rtl_tcp://{self._host}:{self._port}",
                        "type": "RTL_SDR",
                        "frequencyHz": freq,
                        "signalStrength": power,
                        "manufacturer": "",
                        "deviceClass": "",
                        "threatLevel": "UNKNOWN",
                        "channel": 0,
                        "isEncrypted": False,
                    })
        except (OSError, socket.error):
            pass
        return results

    def _loop(self) -> None:
        while self._running:
            try:
                results = self.scan_once()
                if results and self._callback:
                    self._callback(results)
            except Exception:
                pass
            time.sleep(30)


def _peak_to_signal(peak: dict) -> dict:
    freq_hz = int(peak.get("frequency", 0))
    power_db = peak.get("power", -999)
    return {
        "name": f"RF {freq_hz/1e6:.3f} MHz",
        "address": f"rf:{freq_hz}",
        "type": "RTL_SDR",
        "frequencyHz": freq_hz,
        "signalStrength": int(power_db),
        "manufacturer": "",
        "deviceClass": "",
        "threatLevel": "UNKNOWN",
        "channel": 0,
        "isEncrypted": False,
    }


def _estimate_power(iq_bytes: bytes) -> int:
    if len(iq_bytes) < 2:
        return -999
    total = 0
    for i in range(0, len(iq_bytes) - 1, 2):
        i_sample = (iq_bytes[i] - 127) / 128.0
        q_sample = (iq_bytes[i + 1] - 127) / 128.0
        total += i_sample * i_sample + q_sample * q_sample
    avg = total / (len(iq_bytes) // 2)
    import math
    return int(10 * math.log10(max(avg, 1e-10)))
