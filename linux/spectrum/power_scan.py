"""
Spectrum peak detection — ported from PowerScan.ps1.
Parses rtl_power CSV output and finds signal peaks above the noise floor.
"""

import csv
import io
import math
from dataclasses import dataclass, field


@dataclass
class FreqBin:
    frequency: float   # Hz
    power: float       # dBm


@dataclass
class Peak:
    frequency: float   # Hz — center of the merged cluster
    power: float       # dBm — strongest bin in the cluster
    bandwidth: float   # Hz — span of bins merged into this peak


def parse_rtl_power_csv(raw: str) -> list[FreqBin]:
    """Parse rtl_power CSV into a list of (frequency, power) bins."""
    bins: list[FreqBin] = []
    reader = csv.reader(io.StringIO(raw))
    for row in reader:
        if len(row) < 7:
            continue
        try:
            # columns: date, time, freq_lo, freq_hi, freq_step, samples, power...
            freq_lo = float(row[2])
            freq_hi = float(row[3])
            freq_step = float(row[4])
            powers = [float(v) for v in row[6:] if v.strip()]
            if not powers:
                continue
            for i, pwr in enumerate(powers):
                freq = freq_lo + i * freq_step
                bins.append(FreqBin(frequency=freq, power=pwr))
        except (ValueError, IndexError):
            continue
    return bins


def find_peaks(
    bins: list[FreqBin],
    threshold_db: float = 10.0,
    cluster_hz: float = 250_000.0,
) -> list[Peak]:
    """
    Find peaks above the noise floor using the same algorithm as PowerScan.ps1:
    - Compute global median as noise floor baseline
    - Keep bins >= (noise_floor + threshold_db)
    - Merge bins within cluster_hz of each other
    - Return strongest bin per cluster
    """
    if not bins:
        return []

    powers = sorted(b.power for b in bins)
    median = _median(powers)

    candidates = [b for b in bins if b.power >= median + threshold_db]
    if not candidates:
        return []

    candidates.sort(key=lambda b: b.frequency)

    clusters: list[list[FreqBin]] = []
    current: list[FreqBin] = [candidates[0]]
    for b in candidates[1:]:
        if b.frequency - current[-1].frequency <= cluster_hz:
            current.append(b)
        else:
            clusters.append(current)
            current = [b]
    clusters.append(current)

    peaks: list[Peak] = []
    for cluster in clusters:
        strongest = max(cluster, key=lambda b: b.power)
        span = cluster[-1].frequency - cluster[0].frequency
        peaks.append(Peak(
            frequency=strongest.frequency,
            power=strongest.power,
            bandwidth=max(span, cluster_hz / 4),
        ))

    return peaks


def _median(sorted_values: list[float]) -> float:
    n = len(sorted_values)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2 == 1:
        return sorted_values[mid]
    return (sorted_values[mid - 1] + sorted_values[mid]) / 2.0
