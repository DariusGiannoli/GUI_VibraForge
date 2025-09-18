from dataclasses import dataclass
from typing import Optional

@dataclass
class TimelineClip:
    actuator: int
    start_s: float
    end_s: float
    waveform_name: str
    event: Optional['HapticEvent']  # can be None

    @property
    def duration(self) -> float:
        return max(0.0, float(self.end_s) - float(self.start_s))