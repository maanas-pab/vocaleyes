"""Session accounting — an honest report of what a run actually did.

A session with VocalEyes cannot easily be replayed to check it went
well, so when the app quits it says plainly what happened: how many
selections were made, how many ordinary blinks were correctly
ignored, how fast the loop actually ran, and whether the calibration
threshold had to drift. This module computes and formats those
numbers in memory — it never writes a file and never uploads
anything, the privacy stance of a tool that watches someone's eyes.

The single exception is :meth:`SessionStats.save`, the only method
here that touches the filesystem, and only when the user explicitly
asks for it by passing a path on the command line. Nothing in the
camera loop calls it: without that opt-in there is no I/O at all.
"""
from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from typing import Optional

from .smoothing import Ema


def _iso_utc(epoch: float) -> str:
    """UTC ISO-8601 with milliseconds and ``Z``, from epoch ``epoch``.

    The same shape as the timestamps in ``logging_setup`` so console
    lines and saved reports read alike, and built from :func:`time.time`
    so the instant is absolute — never the machine's local time, which
    would make a report ambiguous the moment it left this machine.
    """
    instant = datetime.fromtimestamp(epoch, tz=timezone.utc)
    millis = instant.microsecond // 1000
    return f"{instant.strftime('%Y-%m-%dT%H:%M:%S')}.{millis:03d}Z"


def _finite(value) -> Optional[float]:
    """``value`` as a finite float, or ``None`` for anything else.

    Every ``note_*`` method runs inside the camera loop, where a raise
    means someone's session ends over a bookkeeping nicety. Non-numeric
    input, and the ``nan``/``inf`` a division can produce, are dropped
    rather than counted: a bad call must never be able to skew the
    very report it feeds.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _format_duration(seconds: float) -> str:
    """Human session age — ``4m 12s``, ``1h 04m 05s`` — truncated.

