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
    floor: float = 0.0
    prominence: float = 0.0


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
    window_bins: int = 24,
    coalesce_hz: float = 250_000.0,
    cluster_hz: float | None = None,
) -> list[Peak]:
    """
    Find peaks above the noise floor using the same algorithm as PowerScan.ps1:
    - Compute global median as a whole-sweep floor
    - For each bin, compute a local neighborhood floor
    - Keep bins >= max(global_floor, local_floor) + threshold_db
    - Require a local maximum so smooth receiver ramps do not count as signals
    - Group contiguous hot bins into runs
    - Coalesce nearby peaks and return the strongest bin per cluster
    """
    if not bins:
        return []

    if cluster_hz is not None:
        coalesce_hz = cluster_hz

    sorted_bins = sorted(bins, key=lambda b: b.frequency)
    global_floor = _median(sorted(b.power for b in sorted_bins))

    step_hz = 1.0
    if len(sorted_bins) >= 2:
        step_hz = sorted_bins[1].frequency - sorted_bins[0].frequency
        if step_hz <= 0:
            step_hz = 1.0
    gap_limit_hz = step_hz * 5

    peaks: list[Peak] = []
    run_best: Peak | None = None
    run_start_hz: float | None = None
    run_end_hz: float | None = None
    prev_hz: float | None = None

    for index, bin_ in enumerate(sorted_bins):
        local_floor = _local_floor(sorted_bins, index, window_bins, global_floor)
        floor = max(global_floor, local_floor)
        above = (
            bin_.power >= floor + threshold_db
            and _is_local_peak_candidate(sorted_bins, index)
        )
        contiguous = prev_hz is not None and bin_.frequency - prev_hz <= gap_limit_hz

        if above:
            candidate = Peak(
                frequency=bin_.frequency,
                power=bin_.power,
                bandwidth=step_hz,
                floor=floor,
                prominence=bin_.power - floor,
            )
            if run_best is not None and contiguous:
                if candidate.power > run_best.power:
                    run_best = candidate
                run_end_hz = bin_.frequency
            else:
                if run_best is not None:
                    _finish_run(peaks, run_best, run_start_hz, run_end_hz, step_hz)
                run_best = candidate
                run_start_hz = bin_.frequency
                run_end_hz = bin_.frequency
        elif run_best is not None:
            _finish_run(peaks, run_best, run_start_hz, run_end_hz, step_hz)
            run_best = None
            run_start_hz = None
            run_end_hz = None

        prev_hz = bin_.frequency

    if run_best is not None:
        _finish_run(peaks, run_best, run_start_hz, run_end_hz, step_hz)

    return sorted(_merge_nearby_peaks(peaks, coalesce_hz), key=lambda p: p.power, reverse=True)


def _local_floor(
    bins: list[FreqBin],
    index: int,
    window_bins: int,
    fallback_floor: float,
) -> float:
    start = max(0, index - window_bins)
    end = min(len(bins) - 1, index + window_bins)
    neighbors = [
        bins[i].power
        for i in range(start, end + 1)
        if abs(i - index) > 2
    ]
    if not neighbors:
        return fallback_floor
    return _median(sorted(neighbors))


def _is_local_peak_candidate(bins: list[FreqBin], index: int) -> bool:
    if index <= 0 or index >= len(bins) - 1:
        return False
    return (
        bins[index].power >= bins[index - 1].power
        and bins[index].power >= bins[index + 1].power
    )


def _finish_run(
    peaks: list[Peak],
    run_best: Peak,
    run_start_hz: float | None,
    run_end_hz: float | None,
    step_hz: float,
) -> None:
    start_hz = run_start_hz if run_start_hz is not None else run_best.frequency
    end_hz = run_end_hz if run_end_hz is not None else run_best.frequency
    run_best.bandwidth = max(end_hz - start_hz, step_hz)
    peaks.append(run_best)


def _merge_nearby_peaks(peaks: list[Peak], coalesce_hz: float) -> list[Peak]:
    if not peaks:
        return []

    merged: list[Peak] = []
    cluster: list[Peak] = []
    for peak in sorted(peaks, key=lambda p: p.frequency):
        if not cluster:
            cluster = [peak]
            continue

        if peak.frequency - cluster[-1].frequency <= coalesce_hz:
            cluster.append(peak)
        else:
            merged.append(max(cluster, key=lambda p: p.power))
            cluster = [peak]

    if cluster:
        merged.append(max(cluster, key=lambda p: p.power))

    return merged


def _median(sorted_values: list[float]) -> float:
    n = len(sorted_values)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2 == 1:
        return sorted_values[mid]
    return (sorted_values[mid - 1] + sorted_values[mid]) / 2.0
