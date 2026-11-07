"""Per-person calibration for Project VocalEyes.

Measures open-eye EAR with the user simply looking at the screen, then
sets a threshold well below their typical open value — no button press
or gaze target required.
"""
from __future__ import annotations

import time
from typing import Optional


# ---------------------------------------------------------------------------
# Per-person calibration
# ---------------------------------------------------------------------------
class EarCalibrator:
    """Measure open-eye EAR, then set a threshold from the person.

    The user simply looks at the screen with eyes open and relaxed.
    The threshold is set well below their typical open EAR, so normal
    variation never starts a hold, while a real closure still crosses
    it quickly. No button press or gaze target is required.
    """

    def __init__(self, duration_seconds: float = 3.0) -> None:
        self.duration_seconds = duration_seconds
        self._samples: list[float] = []
        self._started_at: Optional[float] = None

    def start(self, now: float) -> None:
        """Begin (or restart) a calibration window."""
        self._samples.clear()
        self._started_at = now

    @property
    def active(self) -> bool:
        return self._started_at is not None

    @property
    def progress(self) -> float:
        """0.0–1.0 through the calibration window."""
        if self._started_at is None:
            return 0.0
        return min(1.0, (time.monotonic() - self._started_at)
                   / self.duration_seconds)

    def add_sample(self, ear: float) -> None:
        """Record one open-eye EAR sample."""
        self._samples.append(ear)

