"""Selection action — the one integration hook.

``on_long_blink`` is THE single integration hook for Project VocalEyes:
the one place where a confirmed Long Blink / Select leaves the detection
pipeline and reaches the outside world. Downstream work must stay fast
and non-blocking — the hook runs inside the camera loop, so a slow
callback stalls the frame rate.
"""
from __future__ import annotations

import logging

from .detection import BlinkEvent

logger = logging.getLogger("vocaleyes")


def on_long_blink(event: BlinkEvent, selection_count: int) -> None:
    """Default action for a long blink: confirm loudly on the console.

