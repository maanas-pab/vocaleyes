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

    @property
    def selections_per_minute(self) -> float:
        """Selections per minute, or 0.0 until a second has elapsed.

        Below one second the rate would be nonsense — one selection
        in a quarter second is "240/min" — so 0.0 says "too early to
        tell" rather than something untrue.
        """
        elapsed = self.elapsed_seconds
        if elapsed < 1.0:
            return 0.0
        return self._selections * 60.0 / elapsed

    # -- reporting --------------------------------------------------------
    def to_dict(self) -> dict:
        """A JSON-ready snapshot of the session.

        Floats are rounded to 2 dp so the numbers are stable to read
        and to diff; ``schema`` names and versions the shape so a
        consumer can tell this format from a later one; ``started``
        (captured at construction) and ``ended`` (taken now) are UTC
        ISO-8601 derived from :func:`time.time`, never local time, so
        a report read in another timezone cannot be misread.
        """
        return {
            "schema": "vocaleyes.session.v1",
            "started": _iso_utc(self._started_epoch),
            "ended": _iso_utc(time.time()),
            "frames": self.frames,
            "selections": self.selections,
            "short_blinks": self.short_blinks,
            "drift_adjustments": self.drift_adjustments,
            "tracking_losses": self.tracking_losses,
            "dropped_frames": self.dropped_frames,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "average_fps": round(self.average_fps, 2),
            "peak_fps": round(self.peak_fps, 2),
            "selections_per_minute": round(self.selections_per_minute, 2),
        }

    def summary(self) -> str:
        """A compact human report — one subject per short line.

        A line whose subject is empty or zero is left out: "tracking
        losses: 0" tells nobody anything, and a short report is
        easier to read at the end of a long session. The first line is
        the exception — it always appears, because a report that
        printed nothing would be indistinguishable from one that never
        ran, and "no frames processed" is itself the finding.
        """
        if self._frames == 0:
            return "Session: no frames processed."

        frames_word = "frame" if self._frames == 1 else "frames"
        lines = [
            f"Session: {_format_duration(self.elapsed_seconds)} | "
            f"{self._frames} {frames_word} | "
            f"{self.average_fps:.1f} fps avg (peak {self.peak_fps:.1f})"
        ]

        # Selections and ignored blinks share a line because they are
        # two views of one subject: what the detector did with the
        # user's blinks. Each part still stands alone, so a session of
        # purely ordinary blinks reports that honestly too.
        parts = []
        if self._selections:
            parts.append(
                f"Selections: {self._selections} "
                f"({self.selections_per_minute:.1f}/min)"
            )
        if self._short_blinks:
            parts.append(f"short blinks ignored: {self._short_blinks}")
        if parts:
            lines.append(" | ".join(parts))

        parts = []
        if self._tracking_losses:
            parts.append(f"Tracking losses: {self._tracking_losses}")
        if self._dropped_frames:
            parts.append(
                f"camera frames dropped: {self._dropped_frames}")
        if parts:
            lines.append(" | ".join(parts))

        if (self._drift_adjustments
                and self._drift_first is not None
                and self._drift_last is not None):
            noun = ("adjustment" if self._drift_adjustments == 1
                    else "adjustments")
            lines.append(
                f"Threshold drift: {self._drift_adjustments} {noun}, "
                f"{self._drift_first:.3f} -> {self._drift_last:.3f}"
            )
        return "\n".join(lines)

    def save(self, path: str) -> str:
        """Write :meth:`to_dict` as pretty JSON to ``path``; return ``path``.

        This is the only method in this module that writes anything,
        and it runs only when the user passes an explicit path on the
        command line — without that opt-in VocalEyes computes and
        prints its report in memory and touches no file at all, which
        is the privacy promise in the module docstring. Parent
        directories are created so a fresh path works. Failures
        surface as ``OSError``: a report the user asked for should
        say why it could not be saved, not swallow the reason.
        """
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        payload = json.dumps(self.to_dict(), indent=2,
                             sort_keys=True) + "\n"
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(payload)
        return path


def format_summary(stats: SessionStats) -> str:
    """Render ``stats`` — a free-function alias of ``stats.summary()``.

    Kept so callers can depend on a plain function rather than
    importing the class: the CLI can render a session report without
    coupling itself to the name of the type that produced it, and a
    rename or a swap behind :class:`SessionStats` leaves those callers
    untouched.
    """
    return stats.summary()
