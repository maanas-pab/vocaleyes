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

    Replace this function (or pass your own callback to :func:`main`
    via ``action_callback`` in a future integration) to drive a real
    downstream effect — a mouse click, a switch press, a scanning
    keyboard advance, or speech output. Keep downstream work fast and
    non-blocking: this runs inside the camera loop.
