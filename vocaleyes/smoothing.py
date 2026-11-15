"""Signal conditioning for the EAR stream: smoothing, medians, budgets.

The raw Eye Aspect Ratio is noisy — landmark jitter, one bad frame, a
cloud passing the window. Everything here turns a jittery per-frame
number into something a state machine can trust, and keeps an honest
account of where a frame's time went.

Nothing in this module knows about cameras, windows or blinks: it is
pure signal processing, so it can be reasoned about (and exercised)
without a webcam attached.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Dict, Iterator, Optional


class Ema:
    """Exponentially weighted moving average of a scalar stream.

    ``alpha`` is the weight given to the newest sample: 1.0 follows the
    signal exactly, smaller values trade responsiveness for stability.
    VocalEyes uses one for the EAR (in the detector) and one for the FPS
    readout (in the HUD) — in both cases a single unlucky frame must not
    be allowed to move the whole display.
    """

    def __init__(self, alpha: float, initial: Optional[float] = None) -> None:
        if not 0.0 < alpha <= 1.0:
            raise ValueError(
                f"alpha must be in (0.0, 1.0], got {alpha}: "
                "a value outside that range is not a weighted average."
            )
        self._alpha = alpha
        self._value = initial

    @property
    def alpha(self) -> float:
        return self._alpha

    @property
    def value(self) -> Optional[float]:
        """The smoothed value, or ``None`` before the first sample."""
        return self._value

    def push(self, value: float) -> float:
        """Fold one sample in and return the smoothed value."""
        if self._value is None:
            # First sample seeds the filter rather than being blended with
            # a made-up starting point: starting at 0.0 would drag the
            # first second of a real session towards "eyes shut".
            self._value = value
        else:
            self._value = self._alpha * value + (1.0 - self._alpha) * self._value
        return self._value

    def reset(self, initial: Optional[float] = None) -> None:
        """Forget history (recalibration, detector reset, new session)."""
        self._value = initial

    def __repr__(self) -> str:
        return f"Ema(alpha={self._alpha}, value={self._value!r})"


class MedianFilter:
    """Rolling median of the last ``window`` samples.

    Where the EMA *averages*, the median *rejects*: with a window of 5,
    a single frame whose landmarks landed wildly off cannot move the
    output at all, because it is not the middle value. The blink state
    machine is deliberately conservative — one bad sample must never be
    able to start or finish a hold — so the median is the right shape of
    protection for a signal that is otherwise very well behaved.

    The cost is latency: the output lags by up to half a window. At
    webcam rates a window of 5 is a few tens of milliseconds, which is
    far below the one-second hold the detector is timing.
    """

    def __init__(self, window: int = 5) -> None:
        if window < 1:
            raise ValueError(
                f"window must be at least 1, got {window}: "
                "a median over zero samples is undefined."
            )
        self._window = window
        self._samples: list[float] = []

    @property
    def window(self) -> int:
        return self._window

    @property
    def value(self) -> Optional[float]:
        """The current median, or ``None`` with no samples yet."""
        if not self._samples:
            return None
        ordered = sorted(self._samples)
        mid = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[mid]
        # Even window: average the two middles. Hand-rolled rather than
        # statistics.median so the ordering and the tie-break are visible.
        return 0.5 * (ordered[mid - 1] + ordered[mid])

    def push(self, value: float) -> Optional[float]:
        """Add a sample, drop the oldest if the window is full, return the median."""
        self._samples.append(value)
        if len(self._samples) > self._window:
            del self._samples[0]
        return self.value

    def reset(self) -> None:
        """Forget all samples."""
        self._samples.clear()

    def __repr__(self) -> str:
        return f"MedianFilter(window={self._window}, n={len(self._samples)})"


class StageTimer:
    """Wall-clock accounting for where a frame's time goes.

    Capture, inference and rendering are timed separately so a slow
    machine can say *which* stage is the problem — "inference takes
    80 ms, try a smaller frame" is advice someone can act on; "it is
    slow" is not. Totals accumulate for the whole session, ``last``
    describes only the frame just finished, and a per-frame budget makes
    "too slow" a measurable condition rather than a feeling.

    Timing uses :func:`time.monotonic`, the same clock the blink
    detector uses, so a stalled clock cannot make stages disagree.
    """

    def __init__(self, budget_seconds: float = 0.0) -> None:
        self._budget = budget_seconds
        self._stack: list = []
        self._last: Dict[str, float] = {}
        self._totals: Dict[str, float] = {}
        self._counts: Dict[str, int] = {}

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        """Time the enclosed block under ``name``.

        Nesting is allowed: an inner stage's time is also counted in the
        outer one, which is what makes ``summary`` able to show both the
        whole frame and the part of it that mattered.
        """
        started = time.monotonic()
        self._stack.append(started)
        try:
            yield
        finally:
            elapsed = time.monotonic() - self._stack.pop()
            self.record(name, elapsed)

    def record(self, name: str, seconds: float) -> None:
        """Fold one measurement in directly (for stages timed elsewhere)."""
        self._last[name] = seconds
        self._totals[name] = self._totals.get(name, 0.0) + seconds
        self._counts[name] = self._counts.get(name, 0) + 1

    @property
    def last(self) -> Dict[str, float]:
        """Stage durations of the most recent frame, in seconds."""
        return dict(self._last)

    @property
    def totals(self) -> Dict[str, float]:
        """Cumulative stage durations for the session, in seconds."""
        return dict(self._totals)

    @property
    def counts(self) -> Dict[str, int]:
        """How many samples have been recorded for each stage."""
        return dict(self._counts)

    def average(self, name: str) -> Optional[float]:
        """Mean duration of one stage in seconds, or ``None`` if untimed.

        The mean (not the last value) is what a "this machine is slow"
        decision should rest on: one frame hitching must not condemn a
        session that is otherwise comfortably inside budget.
        """
        count = self._counts.get(name, 0)
        if count == 0:
            return None
        return self._totals[name] / count

    @property
    def last_total(self) -> float:
        """Total time spent in the stages of the last frame."""
        return sum(self._last.values())

    @property
    def over_budget(self) -> bool:
        """True when the last frame's timed stages exceeded the budget.

        A budget of 0.0 means "no budget configured", which is never
        over: the timer measures, it does not nag.
        """
        if self._budget <= 0.0:
            return False
        return self.last_total > self._budget

    @property
    def budget(self) -> float:
        return self._budget

    def summary(self) -> str:
        """One line, e.g. ``capture 3.9ms | infer 24.1ms | render 1.8ms``."""
        if not self._last:
            return "no timings yet"
        return "  |  ".join(
            f"{name} {seconds * 1000.0:.1f}ms"
            for name, seconds in self._last.items()
        )

