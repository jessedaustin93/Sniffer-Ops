import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spectrum.power_scan import FreqBin, find_peaks, parse_rtl_power_csv


def test_parse_rtl_power_csv():
    raw = (
        "2024-01-01, 12:00:00, 100000000, 110000000, 1000000.00, 100, "
        "-60, -61, -59, -60, -62, -20, -58, -61, -22, -60"
    )

    bins = parse_rtl_power_csv(raw)

    assert len(bins) == 10
    assert bins[0].frequency == 100_000_000
    assert bins[5].frequency == 105_000_000
    assert bins[5].power == -20


def test_find_peaks_uses_local_floor():
    bins = [
        FreqBin(100_000_000 + i * 1_000_000, power)
        for i, power in enumerate([-60, -61, -59, -60, -62, -20, -58, -61, -22, -60])
    ]

    peaks = find_peaks(bins, threshold_db=6.0)

    assert len(peaks) == 2
    assert peaks[0].frequency == 105_000_000
    assert {peak.frequency for peak in peaks} == {105_000_000, 108_000_000}


def test_adjacent_hot_bins_collapse_to_strongest():
    bins = [
        FreqBin(100_000_000 + i * 1_000_000, power)
        for i, power in enumerate([-60, -60, -60, -19, -18, -60, -60, -60, -60, -60])
    ]

    peaks = find_peaks(bins, threshold_db=6.0)

    assert len(peaks) == 1
    assert peaks[0].frequency == 104_000_000


def test_flat_noise_returns_no_peaks():
    bins = [
        FreqBin(100_000_000 + i * 1_000_000, power)
        for i, power in enumerate([-60, -61, -59, -60, -62, -60, -58, -61, -60, -60])
    ]

    assert find_peaks(bins, threshold_db=6.0) == []


def test_smooth_ramp_is_not_a_signal():
    bins = [
        FreqBin(100_000_000 + i * 1_000_000, -80 + i)
        for i in range(40)
    ]

    assert find_peaks(bins, threshold_db=6.0) == []


def test_nearby_peaks_coalesce_to_strongest():
    bins = [
        FreqBin(740_000_000 + i * 100_000, -60)
        for i in range(80)
    ]
    bins[3] = FreqBin(740_300_000, -20)
    bins[4] = FreqBin(740_400_000, -18)
    bins[40] = FreqBin(744_000_000, -15)

    peaks = find_peaks(bins, threshold_db=6.0, coalesce_hz=250_000)

    assert len(peaks) == 2
    assert {peak.frequency for peak in peaks} == {740_400_000, 744_000_000}
