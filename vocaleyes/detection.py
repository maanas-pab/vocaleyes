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

