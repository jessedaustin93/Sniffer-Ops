"""
ADS-B / Mode S decoder — ported from AdsbDecoder.ps1.
Parses hex frames from rtl_adsb or dump1090, extracts callsign,
position (CPR), altitude, speed, and heading.
"""

import math
import re
from dataclasses import dataclass, field


@dataclass
class Aircraft:
    icao: str
    callsign: str = ""
    altitude_ft: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    speed_kts: int | None = None
    heading_deg: int | None = None
    on_ground: bool = False
    last_msg: str = ""

    # CPR state for position decoding
    cpr_lat_even: float | None = None
    cpr_lon_even: float | None = None
    cpr_lat_odd: float | None = None
    cpr_lon_odd: float | None = None
    cpr_even_time: float = 0.0
    cpr_odd_time: float = 0.0


_CALLSIGN_CHARS = "@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_ !\"#$%&'()*+,-./0123456789"
_fleet: dict[str, Aircraft] = {}


def decode_frame(hex_frame: str, timestamp: float = 0.0) -> Aircraft | None:
    """Decode a single ADS-B hex frame. Returns the updated Aircraft or None."""
    frame = hex_frame.strip().lstrip("*").rstrip(";").upper()
    if not re.fullmatch(r"[0-9A-F]+", frame):
        return None

    data = bytes.fromhex(frame)
    if len(data) < 7:
        return None

    df = (data[0] >> 3) & 0x1F
    if df not in (17, 18, 19):
        return None
    if len(data) < 14:
        return None
    if not _crc_ok(data):
        return None

    icao = frame[2:8]
    aircraft = _fleet.setdefault(icao, Aircraft(icao=icao))
    aircraft.last_msg = hex_frame.strip()

    me = data[4:11]
    tc = (me[0] >> 3) & 0x1F

    if 1 <= tc <= 4:
        _decode_callsign(aircraft, me)
    elif tc in (9, 10, 11, 12, 13, 14, 15, 16, 17, 18):
        _decode_airborne_position(aircraft, me, tc, timestamp)
    elif tc == 19:
        _decode_velocity(aircraft, me)
    elif tc in (5, 6, 7, 8):
        _decode_surface_position(aircraft, me, tc, timestamp)

    return aircraft


def _decode_callsign(aircraft: Aircraft, me: bytes) -> None:
    raw = 0
    for b in me[1:7]:
        raw = (raw << 8) | b
    chars = []
    for i in range(47, -1, -6):
        idx = (raw >> i) & 0x3F
        chars.append(_CALLSIGN_CHARS[idx] if idx < len(_CALLSIGN_CHARS) else "?")
    aircraft.callsign = "".join(chars).strip().rstrip("_").rstrip()


def _decode_airborne_position(aircraft: Aircraft, me: bytes, tc: int, ts: float) -> None:
    ss = (me[0] >> 1) & 0x03
    nicsb = me[0] & 0x01
    alt_raw = ((me[1] << 4) | (me[2] >> 4)) & 0x0FFF
    t_flag = (me[2] >> 2) & 0x01  # 0=odd, 1=even... wait actually:
    # bit F (format): 0=even, 1=odd
    f_flag = (me[2] >> 2) & 0x01
    lat_cpr = ((me[2] & 0x03) << 15) | (me[3] << 7) | (me[4] >> 1)
    lon_cpr = ((me[4] & 0x01) << 16) | (me[5] << 8) | me[6]
    lat_cpr_f = lat_cpr / 131072.0
    lon_cpr_f = lon_cpr / 131072.0

    # Altitude (Gillham/Q-bit decoding)
    q_bit = (alt_raw >> 4) & 0x01
    if q_bit:
        n = ((alt_raw & 0x0FE0) >> 1) | (alt_raw & 0x000F)
        aircraft.altitude_ft = n * 25 - 1000
    else:
        aircraft.altitude_ft = _gillham_decode(alt_raw)

    aircraft.on_ground = False

    if f_flag == 0:
        aircraft.cpr_lat_even = lat_cpr_f
        aircraft.cpr_lon_even = lon_cpr_f
        aircraft.cpr_even_time = ts
    else:
        aircraft.cpr_lat_odd = lat_cpr_f
        aircraft.cpr_lon_odd = lon_cpr_f
        aircraft.cpr_odd_time = ts

    if (aircraft.cpr_lat_even is not None and aircraft.cpr_lat_odd is not None):
        _solve_cpr(aircraft)


def _solve_cpr(aircraft: Aircraft) -> None:
    lat_e, lon_e = aircraft.cpr_lat_even, aircraft.cpr_lon_even
    lat_o, lon_o = aircraft.cpr_lat_odd, aircraft.cpr_lon_odd

    dlat_e = 360.0 / 60
    dlat_o = 360.0 / 59

    j = math.floor(59 * lat_e - 60 * lat_o + 0.5)
    lat_even = dlat_e * (j % 60 + lat_e)
    lat_odd = dlat_o * (j % 59 + lat_o)

    if lat_even >= 270:
        lat_even -= 360
    if lat_odd >= 270:
        lat_odd -= 360

    nl_even = _nl(lat_even)
    nl_odd = _nl(lat_odd)
    if nl_even != nl_odd:
        return

    if aircraft.cpr_even_time >= aircraft.cpr_odd_time:
        lat = lat_even
        nl_lat = nl_even
        lon_f = lon_e
        ni = max(nl_lat, 1)
    else:
        lat = lat_odd
        nl_lat = nl_odd - 1
        lon_f = lon_o
        ni = max(nl_lat, 1)

    dlon = 360.0 / ni
    m = math.floor(lon_e * (nl_lat - 1) - lon_o * nl_lat + 0.5)
    lon = dlon * (m % ni + lon_f)
    if lon >= 180:
        lon -= 360

    aircraft.latitude = round(lat, 5)
    aircraft.longitude = round(lon, 5)


def _nl(lat: float) -> int:
    if abs(lat) >= 87.0:
        return 1
    if abs(lat) < 1e-9:
        return 59
    a = 1 - math.cos(math.pi / (2 * 15)) / math.cos(math.radians(lat)) ** 2
    return math.floor(2 * math.pi / math.acos(1 - a))


def _gillham_decode(raw: int) -> int | None:
    # simplified — return None for unrecognized
    return None


def _decode_velocity(aircraft: Aircraft, me: bytes) -> None:
    subtype = me[0] & 0x07
    if subtype in (1, 2):
        ew_dir = (me[1] >> 2) & 0x01
        ew_vel = ((me[1] & 0x03) << 8) | me[2]
        ns_dir = (me[3] >> 7) & 0x01
        ns_vel = ((me[3] & 0x7F) << 3) | (me[4] >> 5)
        if ew_vel and ns_vel:
            ew = ew_vel - 1 if not ew_dir else -(ew_vel - 1)
            ns = ns_vel - 1 if not ns_dir else -(ns_vel - 1)
            aircraft.speed_kts = int(math.sqrt(ew * ew + ns * ns))
            aircraft.heading_deg = int(math.degrees(math.atan2(ew, ns))) % 360


def _decode_surface_position(aircraft: Aircraft, me: bytes, tc: int, ts: float) -> None:
    aircraft.on_ground = True


def _crc_ok(data: bytes) -> bool:
    crc = 0
    for i in range(len(data) - 3):
        for j in range(7, -1, -1):
            if (crc ^ (data[i] >> j)) & 0x80:
                crc = ((crc << 1) ^ 0xFFF409) & 0xFFFFFF
            else:
                crc = (crc << 1) & 0xFFFFFF
    residual = (data[-3] << 16) | (data[-2] << 8) | data[-1]
    return crc == residual


def get_aircraft() -> list[Aircraft]:
    return list(_fleet.values())


def clear_stale(max_age_sec: float = 60.0) -> None:
    import time
    now = time.time()
    stale = [k for k, v in _fleet.items()
             if now - getattr(v, "_ts", now) > max_age_sec]
    for k in stale:
        del _fleet[k]
