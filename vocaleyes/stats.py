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

        The frame count advances even when the FPS value is unusable —
        the loop really did finish, and a first frame dividing by a
        zero-length interval must not vanish from the report. The
        sample feeds the average and the peak only when it is finite
        and positive, so a single ``nan`` cannot poison every readout
        that follows it.
        """
        self._frames += 1
        sample = _finite(fps)
        if sample is None or sample <= 0.0:
            return
        self._fps_ema.push(sample)
        if sample > self._peak_fps:
            self._peak_fps = sample

    def note_event(self, event) -> None:
        """Fold one :class:`vocaleyes.detection.BlinkEvent` into the counts.

        A ``select`` is the user's deliberate action and counts as a
        selection (carrying its hold time with it); every other kind
        is an ordinary blink the detector chose to ignore, and those
        deserve counting too — selections with no context cannot tell
        a patient detector from a broken one. An event with no usable
        ``kind`` is dropped: this runs mid-loop, so it must never
        raise, and guessing at what an event meant would corrupt the
        report it feeds.
        """
        kind = getattr(event, "kind", None)
        if not isinstance(kind, str):
            return
        if kind != "select":
            self._short_blinks += 1
            return
        self._selections += 1
        held = _finite(getattr(event, "closed_seconds", None))
        if held is not None and held > 0.0:
            self._closed_seconds += held

    def note_drift(self, old: float, new: float) -> None:
        """Record one threshold adjustment: ``old`` -> ``new``.

        The count says how often drift compensation fired; keeping the
        first and last values lets the report show where the threshold
        started and where it ended — the part a reader can judge as
        "barely moved" or "climbed all session". A pair containing
        anything but finite numbers is dropped whole: counting an
        adjustment while losing its values would leave a report that
        cannot explain itself.
        """
        before = _finite(old)
        after = _finite(new)
        if before is None or after is None:
            return
        self._drift_adjustments += 1
        if self._drift_first is None:
            self._drift_first = before
        self._drift_last = after

    def note_tracking_loss(self) -> None:
        """Count one streak of frames in which no face was found.

        Call this once per consecutive losing streak, not once per
        lost frame: thirty frames without a face is one event — the
        user looked away, or a hand passed the camera — and a
        per-frame count would read like thirty separate failures,
        burying the numbers that matter beneath inflated ones.
        """
        self._tracking_losses += 1

    def note_camera_drop(self, dropped: int) -> None:
        """Accumulate frames the background capture thread discarded.

        The capture thread keeps the newest frame rather than queueing
        them, so a loop slower than the camera shows up as drops here:
        ordinary back-pressure, not an error. Callers pass the frames
        dropped since the last call (the pump's own counter is
        cumulative, so hand over the delta). The largest single call
        is kept alongside the total because the shape matters — one
        burst is a stall, a steady trickle is merely a slow loop — and
        because non-integer or negative values are ignored rather than
        raised on, for the same reason as every other note here.
        """
        try:
            count = int(dropped)
        except (TypeError, ValueError):
            return
        if count <= 0:
            return
        self._dropped_frames += count
        if count > self._max_drop_batch:
            self._max_drop_batch = count

    # -- read-only report surface -----------------------------------------
    @property
    def frames(self) -> int:
        """Loop iterations completed — the denominator of every rate."""
        return self._frames

    @property
    def selections(self) -> int:
        """Deliberate long holds that became a Select."""
        return self._selections

    @property
    def short_blinks(self) -> int:
        """Ordinary blinks the detector correctly ignored."""
        return self._short_blinks

    @property
    def drift_adjustments(self) -> int:
        """Threshold adjustments made during the session."""
        return self._drift_adjustments

    @property
    def tracking_losses(self) -> int:
        """Losing streaks of frames (one per streak, not per frame)."""
        return self._tracking_losses

    @property
    def dropped_frames(self) -> int:
        """Frames the capture thread overwrote before we read them."""
        return self._dropped_frames

    @property
    def elapsed_seconds(self) -> float:
        """Wall-clock seconds since this object was created."""
        return time.monotonic() - self._started_monotonic

    @property
    def average_fps(self) -> float:
        """Smoothed loop FPS, or 0.0 before a usable sample arrives."""
        value = self._fps_ema.value
        return 0.0 if value is None else value

    @property
    def peak_fps(self) -> float:
        """Fastest single iteration seen, or 0.0 before the first."""
        return self._peak_fps

