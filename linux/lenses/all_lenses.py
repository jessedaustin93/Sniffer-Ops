"""
All 8 signal lenses — ported from the Windows companion lenses directory.
Each lens matches the frequency range from its PS1 counterpart.
"""

from .lens_contract import Lens, LensDirective


class BroadcastFmLens(Lens):
    name = "BroadcastFM"
    kind = "voice"
    display_name = "Broadcast FM"

    def can_handle(self, frequency_hz: float) -> bool:
        mhz = frequency_hz / 1e6
        return 87.5 <= mhz <= 108.0

    def activate(self, frequency_hz: float) -> LensDirective:
        return LensDirective(kind="listen", mode="wbfm", frequency_hz=int(frequency_hz))


class AdsbLens(Lens):
    name = "ADSB"
    kind = "data"
    display_name = "ADS-B Aircraft Map"

    def can_handle(self, frequency_hz: float) -> bool:
        mhz = frequency_hz / 1e6
        return (1089.5 <= mhz <= 1090.5) or (977.5 <= mhz <= 978.5)

    def activate(self, frequency_hz: float) -> LensDirective:
        return LensDirective(kind="adsb", title="ADS-B Aircraft Map", frequency_hz=int(frequency_hz))


class AviationVoiceLens(Lens):
    name = "AviationVoice"
    kind = "voice"
    display_name = "Aviation Airband"

    def can_handle(self, frequency_hz: float) -> bool:
        mhz = frequency_hz / 1e6
        return 118.0 <= mhz <= 137.0

    def activate(self, frequency_hz: float) -> LensDirective:
        return LensDirective(kind="listen", mode="am", title="Aviation Voice",
                             frequency_hz=int(frequency_hz))


class AnalogVoiceLens(Lens):
    name = "AnalogVoice"
    kind = "voice"
    display_name = "Analog Voice / Amateur"

    def can_handle(self, frequency_hz: float) -> bool:
        mhz = frequency_hz / 1e6
        return ((144.0 <= mhz <= 148.0) or
                (420.0 <= mhz <= 450.0) or
                (148.0 <= mhz <= 174.0) or
                (450.0 <= mhz <= 470.0))

    def activate(self, frequency_hz: float) -> LensDirective:
        return LensDirective(kind="listen", mode="nfm", title="Analog Voice",
                             frequency_hz=int(frequency_hz))


class NoaaWeatherLens(Lens):
    name = "NOAAWeather"
    kind = "voice"
    display_name = "NOAA Weather Radio"

    def can_handle(self, frequency_hz: float) -> bool:
        mhz = frequency_hz / 1e6
        return 162.4 <= mhz <= 162.55

    def activate(self, frequency_hz: float) -> LensDirective:
        return LensDirective(kind="listen", mode="nfm", title="NOAA Weather Radio",
                             frequency_hz=int(frequency_hz))


class P25Phase1Lens(Lens):
    name = "P25Phase1"
    kind = "voice"
    display_name = "P25 Phase 1 Trunked"

    def can_handle(self, frequency_hz: float) -> bool:
        mhz = frequency_hz / 1e6
        return 806.0 <= mhz <= 869.0

    def activate(self, frequency_hz: float) -> LensDirective:
        return LensDirective(kind="listen", mode="p25", title="P25 Phase 1",
                             frequency_hz=int(frequency_hz))


class PocsagLens(Lens):
    name = "POCSAG"
    kind = "data"
    display_name = "POCSAG Paging"

    def can_handle(self, frequency_hz: float) -> bool:
        mhz = frequency_hz / 1e6
        return 138.0 <= mhz <= 174.0  # common POCSAG allocations

    def activate(self, frequency_hz: float) -> LensDirective:
        return LensDirective(kind="data", mode="pocsag", title="POCSAG Paging",
                             frequency_hz=int(frequency_hz))


class AcarsLens(Lens):
    name = "ACARS"
    kind = "data"
    display_name = "ACARS Aviation Data"

    def can_handle(self, frequency_hz: float) -> bool:
        mhz = frequency_hz / 1e6
        return 129.125 <= mhz <= 136.9

    def activate(self, frequency_hz: float) -> LensDirective:
        return LensDirective(kind="data", mode="acars", title="ACARS",
                             frequency_hz=int(frequency_hz))


ALL_LENSES: list[Lens] = [
    BroadcastFmLens(),
    AdsbLens(),
    AviationVoiceLens(),
    AcarsLens(),          # before AnalogVoice — ACARS is within aviation band
    NoaaWeatherLens(),
    P25Phase1Lens(),
    PocsagLens(),
    AnalogVoiceLens(),
]


def route(frequency_hz: float) -> LensDirective | None:
    """Return the first matching lens directive for a frequency, or None."""
    for lens in ALL_LENSES:
        if lens.can_handle(frequency_hz):
            return lens.activate(frequency_hz)
    return None
