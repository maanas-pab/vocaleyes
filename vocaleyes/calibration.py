"""Per-person calibration for Project VocalEyes.

Measures open-eye EAR with the user simply looking at the screen, then
sets a threshold well below their typical open value — no button press
or gaze target required.
"""
from __future__ import annotations

import time
from collections import deque
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

    def finish(self) -> Optional[float]:
        """Return the recommended threshold, or None if too few samples."""
        self._started_at = None
        if len(self._samples) < 10:
            return None
        samples = sorted(self._samples)
        # Use the median: robust to a blink or two during calibration.
        median = samples[len(samples) // 2]
        # 70% of open EAR, clamped to a sane, safe band.
        return min(0.28, max(0.12, median * 0.70))


# ---------------------------------------------------------------------------
# Slow drift compensation
# ---------------------------------------------------------------------------
class ThresholdDrift:
    """Nudge the startup threshold as a session's eyes slowly drift.

    A startup calibration is a snapshot of one moment: eyelid tone,
    fatigue, settling into a chair, fading light, glasses wiped — all
    move over a long session, so a threshold perfect at minute 1 can be
    wrong by minute 30. This monitor watches the open-eye EAR and makes
    slow, conservative corrections. Safety rests on three limits acting
    together:

    * adjustments are rate-limited (``min_gap_seconds``) and tiny
      (``max_step``), so noise can never cause a jump;
    * every threshold stays within ``baseline ± max_total``, so drift
      compensation can never on its own reach a threshold that would
      fire on open eyes;
    * returning ``None`` almost always means the overlay shows no
      visible change — this monitor is deliberately quiet.
    """

    def __init__(
        self,
        baseline: float,
        *,
        window_seconds: float = 5.0,
        min_gap_seconds: float = 45.0,
        max_step: float = 0.008,
        max_total: float = 0.05,
        min_ear_gap: float = 0.005,
    ) -> None:
        if max_step <= 0:
            raise ValueError(
                f"max_step must be > 0, got {max_step!r}: a non-positive "
                "step could never move the threshold."
            )
        if max_total <= 0:
            raise ValueError(
                f"max_total must be > 0, got {max_total!r}: the band "
                "around the baseline must admit movement."
            )
        if window_seconds <= 0:
            raise ValueError(
                f"window_seconds must be > 0, got {window_seconds!r}."
            )
        if min_gap_seconds <= 0:
            raise ValueError(
                f"min_gap_seconds must be > 0, got {min_gap_seconds!r}: "
                "adjustments must be rate-limited."
            )
        if min_ear_gap < 0:
            raise ValueError(
                f"min_ear_gap must be >= 0, got {min_ear_gap!r}."
            )
        self._baseline = baseline
        self._window_seconds = window_seconds
        self._min_gap_seconds = min_gap_seconds
        self._max_step = max_step
        self._max_total = max_total
        self._min_ear_gap = min_ear_gap

        self._current = baseline
        # (timestamp, ear), oldest first; pruned to the window each call.
        self._samples: deque[tuple[float, float]] = deque()
        self._adjustments = 0
        self._last_adjustment: Optional[float] = None
        # Earliest monotonic time the next look may happen; None until
        # the first frame, so the quiet period starts when monitoring
        # starts and a freshly reset monitor stays quiet again.
        self._next_look: Optional[float] = None

    def observe(self, ear: float, *, closed: bool,
                now: float) -> Optional[float]:
        """Consider one frame; return a new threshold only if it moved.
