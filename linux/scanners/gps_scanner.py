"""
GPS scanner for Linux. Polls a local gpsd instance and exposes the most
recent fix. Talks gpsd's line-delimited JSON protocol directly over a
socket (127.0.0.1:2947) so no extra pip dependency is needed.
"""

import json
import socket
import threading
import time
from typing import Optional


class GpsScanner:
    GPSD_HOST = "127.0.0.1"
    GPSD_PORT = 2947
    SOCKET_TIMEOUT = 10
    RECONNECT_DELAY = 5
    MAX_FIX_AGE = 15  # seconds; older fixes are treated as stale/unavailable

    def __init__(self):
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._fix: Optional[dict] = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="ethrox-detect-gps"
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def get_fix(self, max_age: float = MAX_FIX_AGE) -> Optional[dict]:
        """Return the latest fix (without internal bookkeeping keys), or
        None if there is no fix yet or it's older than max_age seconds."""
        with self._lock:
            fix = self._fix
        if fix is None or time.time() - fix["_received_at"] > max_age:
            return None
        return {k: v for k, v in fix.items() if not k.startswith("_")}

    def _loop(self) -> None:
        while self._running:
            try:
                self._stream_once()
            except (OSError, socket.timeout):
                pass
            if self._running:
                time.sleep(self.RECONNECT_DELAY)

    def _stream_once(self) -> None:
        with socket.create_connection(
            (self.GPSD_HOST, self.GPSD_PORT), timeout=self.SOCKET_TIMEOUT
        ) as sock:
            sock.settimeout(self.SOCKET_TIMEOUT)
            sock.sendall(b'?WATCH={"enable":true,"json":true}\n')
            reader = sock.makefile("r", encoding="utf-8", newline="\n")
            while self._running:
                line = reader.readline()
                if not line:
                    return  # gpsd closed the connection
                self._handle_line(line.strip())

    def _handle_line(self, line: str) -> None:
        if not line:
            return
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return
        if msg.get("class") != "TPV":
            return
        # mode: 0/1 = no fix, 2 = 2D fix, 3 = 3D fix
        if msg.get("mode", 0) < 2 or "lat" not in msg or "lon" not in msg:
            return

        fix = {
            "latitude": msg["lat"],
            "longitude": msg["lon"],
            "accuracyMeters": msg.get("eph") or msg.get("epx") or msg.get("epy"),
            "speedMetersPerSecond": msg.get("speed"),
            "bearingDegrees": msg.get("track"),
            "locationProvider": "gpsd:vk162",
            "_received_at": time.time(),
        }
        with self._lock:
            self._fix = fix
