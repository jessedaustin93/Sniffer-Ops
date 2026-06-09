"""Base lens interface — matches _LensContract.ps1."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LensDirective:
    kind: str            # 'listen', 'adsb', 'data', etc.
    mode: str = ""       # demodulation mode e.g. 'wbfm', 'am', 'nfm'
    title: str = ""
    frequency_hz: int = 0
    extra: dict = None

    def __post_init__(self):
        if self.extra is None:
            self.extra = {}


class Lens(ABC):
    name: str = ""
    kind: str = ""       # 'voice' or 'data'
    display_name: str = ""
    implemented: bool = True

    @abstractmethod
    def can_handle(self, frequency_hz: float) -> bool:
        ...

    @abstractmethod
    def activate(self, frequency_hz: float) -> LensDirective:
        ...

    def deactivate(self) -> None:
        pass
