"""Simulated clock with time-compression abstraction.

Allows 1 real minute to count as 1 simulated hour (or any configurable scale factor)
while strictly preserving point-in-time calculation correctness for rolling window
features and step counters.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional


class CompressedClock:
    """Manages simulated time progression with a configurable compression scale factor."""

    def __init__(
        self,
        scale_factor: float = 60.0,
        base_sim_step: int = 700,
        start_wall_time: Optional[float] = None,
        time_provider: Optional[Callable[[], float]] = None,
    ):
        self._time_fn = time_provider or time.time
        self.scale_factor = max(1.0, float(scale_factor))
        self.base_sim_step = int(base_sim_step)
        self.start_wall_time = start_wall_time if start_wall_time is not None else self._time_fn()
        self.is_paused = False
        self._pause_wall_time: Optional[float] = None
        self._accumulated_pause_duration = 0.0

    def pause(self) -> None:
        if not self.is_paused:
            self.is_paused = True
            self._pause_wall_time = self._time_fn()

    def resume(self) -> None:
        if self.is_paused and self._pause_wall_time is not None:
            self._accumulated_pause_duration += self._time_fn() - self._pause_wall_time
            self._pause_wall_time = None
            self.is_paused = False

    @property
    def elapsed_wall_seconds(self) -> float:
        if self.is_paused and self._pause_wall_time is not None:
            current = self._pause_wall_time
        else:
            current = self._time_fn()
        return max(0.0, current - self.start_wall_time - self._accumulated_pause_duration)

    @property
    def simulated_seconds(self) -> float:
        """Simulated seconds elapsed since room start."""
        return self.elapsed_wall_seconds * self.scale_factor

    @property
    def simulated_seconds_elapsed(self) -> float:
        """Alias for simulated_seconds."""
        return self.simulated_seconds

    @property
    def simulated_timestamp(self) -> float:
        """Simulated Unix timestamp."""
        return self.start_wall_time + self.simulated_seconds

    @property
    def current_step(self) -> int:
        """Simulated PaySim/system step (1 step = 1 simulated hour = 3600 sim seconds)."""
        sim_hours = int(self.simulated_seconds // 3600)
        return self.base_sim_step + sim_hours

    @property
    def current_hour_of_day(self) -> int:
        """Simulated hour of day (0-23)."""
        return (self.current_step % 24)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scale_factor": self.scale_factor,
            "base_sim_step": self.base_sim_step,
            "elapsed_wall_seconds": round(self.elapsed_wall_seconds, 2),
            "simulated_hours": round(self.simulated_seconds / 3600.0, 2),
            "current_step": self.current_step,
            "current_hour_of_day": self.current_hour_of_day,
            "is_paused": self.is_paused,
        }
