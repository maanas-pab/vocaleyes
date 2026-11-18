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

    Truncated rather than rounded: the counters printed beside it
    cover exactly the time that ran, and "5m 00s" next to numbers
    gathered in 4m 59s would round the report away from the truth.
    """
    total = int(max(0.0, seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


# ---------------------------------------------------------------------------
# Session accounting
# ---------------------------------------------------------------------------
class SessionStats:
    """Counters for one run of the camera loop, held in memory.

    Constructed at startup and read once at quit, this object is the
    whole of what the app remembers about a session: selections,
    ignored blinks, loop speed, threshold drift, tracking gaps and
    dropped frames. It stores numbers only — never a frame, a
    landmark or a face — so the report it produces cannot identify
    the person on camera, and nothing reaches disk unless the caller
    explicitly asks with :meth:`save`.

    Each ``note_*`` method is called from inside the loop, so each one
    tolerates junk input: counters are bumped only by values they can
    make sense of, and nothing here raises.
    """

    def __init__(self) -> None:
        # Two clocks, deliberately: monotonic measures how long the
        # session ran (immune to clock steps), while time.time gives
        # the absolute instants a reader can compare afterwards.
        self._started_monotonic = time.monotonic()
        self._started_epoch = time.time()

        self._frames = 0
        self._selections = 0
        self._short_blinks = 0
        self._closed_seconds = 0.0
        self._drift_adjustments = 0
        self._drift_first: Optional[float] = None
        self._drift_last: Optional[float] = None
        self._tracking_losses = 0
        self._dropped_frames = 0
        self._max_drop_batch = 0

        # The FPS readout is smoothed exactly like the HUD's: alpha
        # 0.1 keeps one hitch from moving the average while still
        # following a real change in loop speed within a second or two.
        self._fps_ema = Ema(alpha=0.1)
        self._peak_fps = 0.0

    # -- recording --------------------------------------------------------
    def note_frame(self, fps: float) -> None:
        """Record one completed loop iteration and its instantaneous FPS.

