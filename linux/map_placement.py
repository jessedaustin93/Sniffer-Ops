"""
map_placement.py — Pure, testable placement engine for Sniffer-Ops.

Converts raw sighting + profile records into map markers with tiered
confidence: gps → linked → anchor → unplaced.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LINK_WINDOW_MINUTES: int = 20
COLLAPSE_METERS: float = 25.0

SIGNAL_COLORS: dict[str, str] = {
    "WIFI": "#39FF14",
    "BLUETOOTH": "#00BFFF",
    "BLE": "#38BDF8",
    "CELLULAR": "#F59E0B",
    "RTL_SDR": "#8B5CF6",
}

DEFAULT_COLOR: str = "#9CA3AF"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class MapMarker:
    profile_id: str
    name: str
    signal_type: str
    lat: float
    lon: float
    tier: str                          # "gps" | "linked" | "anchor" | "unplaced"
    color: str
    signal_strength: Optional[float] = None
    count: int = 1                     # collapsed point count


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------

def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in metres between two WGS-84 points."""
    R = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return R * 2.0 * math.asin(math.sqrt(a))


def _collapse_points(
    points: list[tuple[float, float]]
) -> list[tuple[float, float, int]]:
    """
    Merge nearby GPS fixes into representative points.

    For each input (lat, lon), if it falls within COLLAPSE_METERS of an
    existing output point the two are merged via a running weighted average
    and the count is incremented.  Otherwise a new output point is appended
    with count=1.

    Returns a list of (lat, lon, count) tuples.
    """
    output: list[list] = []   # each element: [lat, lon, count]

    for lat, lon in points:
        merged = False
        for existing in output:
            elat, elon, ecnt = existing
            if haversine_meters(lat, lon, elat, elon) <= COLLAPSE_METERS:
                # Weighted running average
                new_cnt = ecnt + 1
                existing[0] = (elat * ecnt + lat) / new_cnt
                existing[1] = (elon * ecnt + lon) / new_cnt
                existing[2] = new_cnt
                merged = True
                break
        if not merged:
            output.append([lat, lon, 1])

    return [(row[0], row[1], row[2]) for row in output]


def _weighted_position(
    fixes: list[dict], target_ms: int
) -> Optional[tuple[float, float]]:
    """
    Compute a time-weighted centroid from a list of GPS fixes.

    Each fix dict must have keys: latitude, longitude, captured_at (ms epoch).
    weight = 1.0 / (1.0 + diff_minutes)

    Returns (lat, lon) or None when *fixes* is empty.
    """
    if not fixes:
        return None

    total_weight = 0.0
    wlat = 0.0
    wlon = 0.0

    for fix in fixes:
        diff_ms = abs(fix["captured_at"] - target_ms)
        diff_minutes = diff_ms / 60_000.0
        w = 1.0 / (1.0 + diff_minutes)
        wlat += fix["latitude"] * w
        wlon += fix["longitude"] * w
        total_weight += w

    if total_weight == 0.0:
        return None

    return wlat / total_weight, wlon / total_weight


# ---------------------------------------------------------------------------
# Main placement engine
# ---------------------------------------------------------------------------

def compute_placements(
    profiles: list[dict],
    sightings: list[dict],
) -> tuple[list[MapMarker], int]:
    """
    Convert raw profile + sighting records into a list of MapMarkers.

    Parameters
    ----------
    profiles:
        Each dict: { id, name, type, last_signal,
                     estimated_latitude (nullable),
                     estimated_longitude (nullable) }
    sightings:
        Each dict: { device_id, node_id, captured_at (ms epoch),
                     latitude (nullable), longitude (nullable),
                     signal_strength }

    Returns
    -------
    (markers, unplaced_count)
    """
    markers: list[MapMarker] = []
    unplaced_count: int = 0

    # Index sightings by device_id for quick lookup.
    sightings_by_device: dict[str, list[dict]] = {}
    for s in sightings:
        sightings_by_device.setdefault(s["device_id"], []).append(s)

    # All GPS sightings indexed by node_id (used for the anchor tier).
    all_gps_sightings: list[dict] = [
        s for s in sightings
        if s.get("latitude") is not None and s.get("longitude") is not None
    ]
    gps_by_node: dict[str, list[dict]] = {}
    for s in all_gps_sightings:
        gps_by_node.setdefault(s["node_id"], []).append(s)

    for profile in profiles:
        pid = profile["id"]
        pname = profile.get("name", pid)
        ptype = profile.get("type", "")
        color = SIGNAL_COLORS.get(ptype.upper(), DEFAULT_COLOR)

        profile_sightings = sightings_by_device.get(pid, [])

        # ------------------------------------------------------------------
        # Tier GPS
        # ------------------------------------------------------------------
        gps_sightings = [
            s for s in profile_sightings
            if s.get("latitude") is not None and s.get("longitude") is not None
        ]

        if gps_sightings:
            raw_points = [(s["latitude"], s["longitude"]) for s in gps_sightings]
            collapsed = _collapse_points(raw_points)

            # Attach a representative signal_strength (strongest in group) per
            # collapsed point.  We do a simple nearest-fix assignment.
            for clat, clon, cnt in collapsed:
                # Pick the sighting closest to the collapsed centre.
                closest = min(
                    gps_sightings,
                    key=lambda s: haversine_meters(
                        s["latitude"], s["longitude"], clat, clon
                    ),
                )
                markers.append(
                    MapMarker(
                        profile_id=pid,
                        name=pname,
                        signal_type=ptype,
                        lat=clat,
                        lon=clon,
                        tier="gps",
                        color=color,
                        signal_strength=closest.get("signal_strength"),
                        count=cnt,
                    )
                )
            continue  # GPS tier satisfied; move to next profile.

        # ------------------------------------------------------------------
        # Tier Linked  (no GPS sightings for this profile)
        # ------------------------------------------------------------------
        non_gps_sightings = [
            s for s in profile_sightings
            if s.get("latitude") is None or s.get("longitude") is None
        ]

        linked_marker: Optional[MapMarker] = None

        for s in non_gps_sightings:
            node_id = s["node_id"]
            captured_at = s["captured_at"]
            window_ms = LINK_WINDOW_MINUTES * 60_000

            # GPS fixes from the same node within the time window.
            candidate_fixes = [
                g for g in gps_by_node.get(node_id, [])
                if abs(g["captured_at"] - captured_at) <= window_ms
            ]

            if not candidate_fixes:
                continue

            # Build weighted-position using per-fix weights.
            total_weight = 0.0
            wlat = 0.0
            wlon = 0.0
            for g in candidate_fixes:
                diff_minutes = abs(g["captured_at"] - captured_at) / 60_000.0
                w = 1.0 / (1.0 + diff_minutes)
                wlat += g["latitude"] * w
                wlon += g["longitude"] * w
                total_weight += w

            if total_weight == 0.0:
                continue

            plat = wlat / total_weight
            plon = wlon / total_weight

            linked_marker = MapMarker(
                profile_id=pid,
                name=pname,
                signal_type=ptype,
                lat=plat,
                lon=plon,
                tier="linked",
                color=color,
                signal_strength=s.get("signal_strength"),
                count=1,
            )
            break  # Only one linked marker per profile is needed.

        if linked_marker is not None:
            markers.append(linked_marker)
            continue

        # ------------------------------------------------------------------
        # Tier Anchor  (no linked placement possible)
        # ------------------------------------------------------------------
        # Collect nodes that observed this profile, then average all GPS
        # sightings from those nodes.
        observed_nodes = {s["node_id"] for s in profile_sightings}
        anchor_fixes = [
            g for g in all_gps_sightings if g["node_id"] in observed_nodes
        ]

        if anchor_fixes:
            alat = sum(g["latitude"] for g in anchor_fixes) / len(anchor_fixes)
            alon = sum(g["longitude"] for g in anchor_fixes) / len(anchor_fixes)
            markers.append(
                MapMarker(
                    profile_id=pid,
                    name=pname,
                    signal_type=ptype,
                    lat=alat,
                    lon=alon,
                    tier="anchor",
                    color=color,
                    signal_strength=None,
                    count=1,
                )
            )
            continue

        # ------------------------------------------------------------------
        # Fallback: use estimated position stored on the profile, if present.
        # ------------------------------------------------------------------
        est_lat = profile.get("estimated_latitude")
        est_lon = profile.get("estimated_longitude")

        if est_lat is not None and est_lon is not None:
            markers.append(
                MapMarker(
                    profile_id=pid,
                    name=pname,
                    signal_type=ptype,
                    lat=float(est_lat),
                    lon=float(est_lon),
                    tier="anchor",
                    color=color,
                    signal_strength=None,
                    count=1,
                )
            )
            continue

        # ------------------------------------------------------------------
        # Tier Unplaced
        # ------------------------------------------------------------------
        unplaced_count += 1

    return markers, unplaced_count
