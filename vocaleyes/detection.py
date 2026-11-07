"""Blink detection — the core accessibility state machine.

``BlinkDetector`` smooths the combined EAR, applies hysteresis, times
closures with a monotonic clock, fires at most once per closure, and
ignores short blinks entirely. Only a deliberate long hold selects.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from .config import Config


# ---------------------------------------------------------------------------
# Blink detection — the core accessibility state machine
# ---------------------------------------------------------------------------
class BlinkState(Enum):
    """Blink detector states. Only CLOSED can become a selection."""

    OPEN = auto()
    CLOSED = auto()      # eyes shut, hold timer running, not yet fired
    TRIGGERED = auto()   # selection fired, waiting for eyes to reopen
    COOLDOWN = auto()    # eyes reopened, quiet period before re-arming


@dataclass
class BlinkEvent:
    """A single meaningful blink outcome."""

    kind: str  # "select" or "short_blink"
    closed_seconds: float
    ear_at_close: float
    timestamp: float = field(default_factory=time.monotonic)


class BlinkDetector:
    """Detect a deliberate long blink from a stream of EAR values.

    The detector is deliberately boring: it smooths the signal, applies
    hysteresis, times closures with ``time.monotonic()``, fires at most
    once per closure, and ignores short blinks entirely. Call
    :meth:`reset` whenever the face is lost so a tracking gap can never
    be mistaken for a closure.
    """

    def __init__(self, config: Config) -> None:
        self.close_threshold = config.ear_threshold
        # Reopen threshold sits above the close threshold: the eye must
        # clearly reopen before the detector re-arms. This gap is what
        # stops EAR jitter around the threshold from fluttering state.
        self.open_threshold = config.ear_threshold + 0.04
        self.long_blink_seconds = config.long_blink_seconds
        self.cooldown_seconds = config.cooldown_seconds
        self.smoothing = config.ear_smoothing
        self.state = BlinkState.OPEN
        self._smoothed_ear: Optional[float] = None
        self._closed_since: Optional[float] = None
        self._ear_at_close = 0.0
        self._cooldown_until = 0.0

    # -- public API -------------------------------------------------------
    def update(self, combined_ear: float, now: float) -> Optional[BlinkEvent]:
        """Feed one (combined) EAR sample. Returns an event, if any."""
        if self._smoothed_ear is None:
            self._smoothed_ear = combined_ear
        else:
            alpha = self.smoothing
            self._smoothed_ear = (
                alpha * combined_ear + (1.0 - alpha) * self._smoothed_ear
            )
        ear = self._smoothed_ear

        if self.state is BlinkState.OPEN:
            if ear < self.close_threshold:
                self.state = BlinkState.CLOSED
                self._closed_since = now
                self._ear_at_close = ear
            return None

        if self.state is BlinkState.CLOSED:
            assert self._closed_since is not None
            if ear >= self.open_threshold:
                closed_for = now - self._closed_since
                self._reset_to_open(now)
                if closed_for < self.long_blink_seconds:
                    return BlinkEvent("short_blink", closed_for,
                                      self._ear_at_close, now)
                return None
            if now - self._closed_since >= self.long_blink_seconds:
                self.state = BlinkState.TRIGGERED
                return BlinkEvent(
                    "select", now - self._closed_since,
                    self._ear_at_close, now,
                )
            return None

        if self.state is BlinkState.TRIGGERED:
            # Stay triggered until the eyes clearly reopen; the selection
            # has already fired, so this state only guards re-arming.
            if ear >= self.open_threshold:
                self.state = BlinkState.COOLDOWN
                self._cooldown_until = now + self.cooldown_seconds
                self._closed_since = None
            return None

        # COOLDOWN: wait out the quiet period, then re-arm.
        if now >= self._cooldown_until:
            self.state = BlinkState.OPEN
        return None

    def reset(self) -> None:
        """Forget any in-progress closure (face lost / user reset)."""
        self.state = BlinkState.OPEN
        self._closed_since = None
        self._smoothed_ear = None
        self._cooldown_until = 0.0

    def retune(self, ear_threshold: float) -> None:
        """Apply a newly calibrated threshold, preserving hysteresis."""
        self.close_threshold = ear_threshold
        self.open_threshold = ear_threshold + 0.04
        self.reset()

    # -- derived state for the UI ----------------------------------------
    @property
    def smoothed_ear(self) -> Optional[float]:
        """The smoothed EAR most recently seen, or ``None`` before data."""
        return self._smoothed_ear

    @property
    def hold_progress(self) -> float:
        """0.0–1.0: how far through the required hold the user is."""
        if self.state is not BlinkState.CLOSED or self._closed_since is None:
            return 1.0 if self.state is BlinkState.TRIGGERED else 0.0
        elapsed = time.monotonic() - self._closed_since
        return min(1.0, elapsed / self.long_blink_seconds)

    @property
    def is_closed(self) -> bool:
        """True while the eyes are held shut (before or after firing)."""
        return self.state in (BlinkState.CLOSED, BlinkState.TRIGGERED)

    def _reset_to_open(self, now: float) -> None:
        self.state = BlinkState.OPEN
        self._closed_since = None
        self._cooldown_until = now
