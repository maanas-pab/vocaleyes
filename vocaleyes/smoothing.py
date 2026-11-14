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

