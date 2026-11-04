#!/usr/bin/env python3
"""Project VocalEyes — long-blink selection for people with advanced ALS.

A single-file, on-device eye-tracking module. A webcam frame is passed
through MediaPipe Face Mesh, the Eye Aspect Ratio (EAR) of each eye is
measured, and a sustained bilateral eye closure is turned into one
deliberate action: a **Long Blink / Select**.

Why this design matters for advanced ALS
----------------------------------------
* **One reliable input, no voice / hands / head movement required.**
  Selection needs only the ability to close both eyes and hold them
  shut. Nothing else on screen has to be looked at, dwelled on, or
  pointed to.
* **Time, not frame count.** Closure is timed with a monotonic clock,
  so a slow laptop and a fast laptop demand the same 1-second hold.
* **Hysteresis + smoothing.** The eye must fall below a close
  threshold to start timing and rise above a slightly higher open
  threshold to end it. A single noisy frame cannot start, stop, or
  fire a selection.
* **Ordinary blinks are ignored.** A normal 0.1–0.4 s blink ends long
  before the hold threshold, so it never selects. Only a deliberate
  hold fires, and only once per closure, followed by a cooldown.
* **Feedback is large, calm, and unambiguous.** A filling progress
  ring shows the hold building, and a full-width banner confirms the
  selection. There is no flashing, no tiny text, and no reliance on
  sound. If the face is lost, tracking pauses instead of guessing.
* **Private by default.** All processing is local. No video, image,
  or landmark is saved, uploaded, or recorded by this module.

How it works
------------
1. ``FaceMeshTracker`` returns 468 facial landmarks per frame
   (``refine_landmarks=True`` also returns the iris landmarks).
2. ``extract_eye_readings`` converts the six eyelid landmarks of each
   eye into an Eye Aspect Ratio (EAR)::

       EAR = (||p2 - p6|| + ||p3 - p5||) / (2 * ||p1 - p4||)

   EAR is ~0.25–0.35 with eyes open and approaches 0 when closed.
   It is scale-invariant, so distance from the camera does not
   change the threshold.
3. ``BlinkDetector`` smooths the combined EAR, runs the
   open -> closed -> triggered -> cooldown state machine, and emits
   a single ``Select`` event per long blink.
4. ``Visualizer`` draws the polished overlay: eye contours, iris
   markers, per-eye EAR bars, an EAR history trace, the hold-to-
   select progress ring, and the selection banner.
5. ``on_long_blink`` is the single integration hook. By default it
   prints a confirmation to the console. Replace it (or pass your
   own callback) to drive a switch, a dwell keyboard, a mouse
   click, or a speech output — this file never assumes what a
   "select" should do downstream.

Usage
-----
Install dependencies, then run::

    pip install -r requirements.txt
    python vocal_eyes.py

    # Tune for one person (recommended for ALS use):
    python vocal_eyes.py --long-blink 1.2 --threshold 0.19 --camera 0

Controls while running: ``Q`` / ``Esc`` quit, ``C`` recalibrate the
EAR threshold from open eyes, ``M`` toggle the full face mesh,
``R`` reset the blink detector.

This module is intentionally dependency-light: OpenCV + MediaPipe
only. It needs a display (``cv2.imshow``) and a working webcam.
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Deque, Optional, Sequence, Tuple

import numpy as np

try:
    import cv2
except ImportError as _cv2_error:  # pragma: no cover - env without cv2
    cv2 = None  # type: ignore[assignment]
    _CV2_IMPORT_ERROR = _cv2_error
else:
    _CV2_IMPORT_ERROR = None

try:
    import mediapipe as mp
except ImportError as _mp_error:  # pragma: no cover - env without mp
    mp = None  # type: ignore[assignment]
    _MP_IMPORT_ERROR = _mp_error
else:
    _MP_IMPORT_ERROR = None


__version__ = "1.0.0"
__all__ = [
    "BlinkDetector",
    "BlinkEvent",
    "CameraError",
    "Config",
    "EyeReading",
    "FaceMeshTracker",
    "calculate_ear",
    "main",
]

logger = logging.getLogger("vocaleyes")


# ---------------------------------------------------------------------------
# Landmark indices (MediaPipe Face Mesh, 468 landmarks + refined iris)
# ---------------------------------------------------------------------------
# Six-point EAR landmarks per eye: (outer, upper, upper, inner, lower,
# lower). These are the canonical Soukupova / Cech indices for Face Mesh.
LEFT_EYE_EAR = (33, 160, 158, 133, 153, 144)
RIGHT_EYE_EAR = (362, 385, 387, 263, 373, 380)

# Full eyelid contours, drawn so the user (and a carer) can see exactly
# what is being tracked. Order follows the eyelid around the eye.
LEFT_EYE_CONTOUR = (
    33, 7, 163, 144, 145, 153, 154, 155, 133,
    173, 157, 158, 159, 160, 161, 246,
)
RIGHT_EYE_CONTOUR = (
    263, 249, 390, 373, 374, 380, 381, 382, 362,
    398, 384, 385, 386, 387, 388, 466,
)

# Iris landmarks (only present with refine_landmarks=True). Index 468 is
# the left iris centre and 473 the right iris centre.
LEFT_IRIS_CENTRE = 468
RIGHT_IRIS_CENTRE = 473
LEFT_IRIS_RING = (469, 470, 471, 472)
RIGHT_IRIS_RING = (474, 475, 476, 477)


# ---------------------------------------------------------------------------
# Visual palette (BGR, as OpenCV expects) — calm, high-contrast, no neon
# ---------------------------------------------------------------------------
class Palette:
    """Named colours for the overlay. One place to restyle the UI."""

    WHITE = (255, 255, 255)
    SOFT_WHITE = (235, 235, 235)
    MUTED = (190, 190, 190)
    DARK = (24, 24, 28)
    PANEL = (18, 18, 22)
    TEAL = (191, 212, 45)       # #2DD4BF — eyes open / ready
    GREEN = (94, 197, 34)       # #22C55E — selection confirmed
    AMBER = (11, 158, 245)      # #F59E0B — holding / closing
    RED = (68, 68, 239)         # #EF4444 — eyes closed / no face
    GREY_TRACK = (90, 90, 96)
    EYE_OPEN = (191, 212, 45)
    EYE_CLOSED = (11, 158, 245)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@dataclass
class Config:
    """All tunable behaviour for VocalEyes. Tune per person, not per run."""

    camera_index: int = 0
    frame_width: int = 1280
    frame_height: int = 720
    mirror: bool = True
    # EAR below this starts the hold timer. Calibrate per person: eyelid
    # laxity, ptosis, glasses, and lighting all move a person's open EAR.
    ear_threshold: float = 0.21
    # Hold time that counts as deliberate. 1.0 s is long enough to
    # exclude ordinary blinks, short enough not to tire the user.
    long_blink_seconds: float = 1.0
    # Quiet period after a selection. Prevents one long closure from
    # firing twice and gives the user time to reopen their eyes.
    cooldown_seconds: float = 1.5
    # How the two eyes combine. "average" is the safe default; use
    # "min" only for markedly asymmetric closure (one eyelid closes
    # much less than the other), as it is more sensitive to winks.
    eye_mode: str = "average"
    # EMA smoothing for EAR (0–1). Higher = smoother but slower.
    ear_smoothing: float = 0.35
    show_mesh: bool = False
    # Seconds of open-eye sampling at startup. 0 disables auto-calibration.
    calibrate_seconds: float = 3.0
    min_detection_confidence: float = 0.5
    min_tracking_confidence: float = 0.5
    window_name: str = "Project VocalEyes"

    def __post_init__(self) -> None:
        if not 0.05 <= self.ear_threshold <= 0.45:
            raise ValueError("ear_threshold must be between 0.05 and 0.45")
        if self.long_blink_seconds <= 0:
            raise ValueError("long_blink_seconds must be positive")
        if self.cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must not be negative")
        if self.eye_mode not in ("average", "min"):
            raise ValueError('eye_mode must be "average" or "min"')

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "Config":
        """Build a Config from parsed command-line arguments."""
        return cls(
            camera_index=args.camera,
            frame_width=args.width,
            frame_height=args.height,
            mirror=not args.no_mirror,
            ear_threshold=args.threshold,
            long_blink_seconds=args.long_blink,
            cooldown_seconds=args.cooldown,
            eye_mode=args.eye_mode,
            show_mesh=args.show_mesh,
            calibrate_seconds=0.0 if args.no_calibrate else args.calibrate,
        )


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class CameraError(RuntimeError):
    """Raised when no usable webcam can be opened or frames stop coming."""


class DependencyError(RuntimeError):
    """Raised when OpenCV / MediaPipe are not installed."""


def _check_dependencies() -> None:
    """Fail fast with an actionable message if a dependency is missing."""
    if cv2 is None:
        raise DependencyError(
            "OpenCV (cv2) is not installed. Install it with:\n"
            "    pip install opencv-python\n"
            f"Original error: {_CV2_IMPORT_ERROR}"
        )
    if mp is None:
        raise DependencyError(
            "MediaPipe is not installed. Install it with:\n"
            "    pip install mediapipe\n"
            f"Original error: {_MP_IMPORT_ERROR}"
        )


# ---------------------------------------------------------------------------
# Geometry helpers — pure functions, unit-testable without a camera
# ---------------------------------------------------------------------------
Point = Tuple[int, int]


def _distance(a: Point, b: Point) -> float:
    """Euclidean distance between two pixel points."""
    return math.hypot(a[0] - b[0], a[1] - b[1])


def calculate_ear(eye: Sequence[Point]) -> float:
    """Return the Eye Aspect Ratio for one eye from six eyelid points.

    ``eye`` is ordered (outer, upper, upper, inner, lower, lower)
    matching :data:`LEFT_EYE_EAR` / :data:`RIGHT_EYE_EAR`. Returns 0.0
    for a degenerate (zero-width) eye instead of raising, so one bad
    frame can never crash the tracker.
    """
    if len(eye) != 6:
        raise ValueError(f"EAR needs exactly 6 points, got {len(eye)}")
    horizontal = _distance(eye[0], eye[3])
    if horizontal == 0:
        return 0.0
    vertical_a = _distance(eye[1], eye[5])
    vertical_b = _distance(eye[2], eye[4])
    return (vertical_a + vertical_b) / (2.0 * horizontal)


def _to_pixel(landmark, width: int, height: int) -> Point:
    """Convert a normalised MediaPipe landmark to integer pixel coords."""
    return (int(landmark.x * width), int(landmark.y * height))


# ---------------------------------------------------------------------------
# Per-frame eye measurements
# ---------------------------------------------------------------------------
@dataclass
class EyeReading:
    """Everything measured for one eye in one frame."""

    ear: float
    contour: list[Point]
    iris_centre: Point
    iris_ring: list[Point]
    bbox: Tuple[int, int, int, int]  # x, y, w, h in pixels

    @classmethod
    def from_landmarks(
        cls,
        landmarks,
        ear_indices: Tuple[int, ...],
        contour_indices: Tuple[int, ...],
        iris_centre_index: int,
        iris_ring_indices: Tuple[int, ...],
        width: int,
        height: int,
        padding: int = 14,
    ) -> "EyeReading":
        """Build a reading from raw landmarks and this eye's indices."""
        points = [_to_pixel(lm, width, height) for lm in landmarks]
        # EAR uses only the six eyelid points, in canonical order.
        ear_points = [points[i] for i in ear_indices]
        ear = calculate_ear(ear_points)
        contour = [points[i] for i in contour_indices]
        iris_ring = [points[i] for i in iris_ring_indices
                     if i < len(points)]
        # Iris landmarks exist only with refine_landmarks=True. Fall
        # back to the eye centre so drawing never fails on a partial
        # result (e.g. 468 landmarks without the refined iris set).
        if iris_centre_index < len(points):
            iris_centre = points[iris_centre_index]
        else:
            xs = [p[0] for p in contour]
            ys = [p[1] for p in contour]
            iris_centre = (sum(xs) // len(xs), sum(ys) // len(ys))
        if not iris_ring:
            iris_ring = [iris_centre]
        xs = [p[0] for p in contour]
        ys = [p[1] for p in contour]
        x = max(0, min(xs) - padding)
        y = max(0, min(ys) - padding)
        bbox = (x, y, min(width - x, max(xs) - x + 2 * padding),
                min(height - y, max(ys) - y + 2 * padding))
        return cls(
            ear=ear, contour=contour, iris_centre=iris_centre,
            iris_ring=iris_ring, bbox=bbox,
        )

    @property
    def centre(self) -> Point:
        """Centre of the eye bounding box (for labels and rings)."""
        x, y, w, h = self.bbox
        return (x + w // 2, y + h // 2)


@dataclass
class FaceReading:
    """Both eyes for one frame, plus the combined EAR used downstream."""

    left: EyeReading
    right: EyeReading
    combined_ear: float


def extract_eye_readings(
    landmarks, width: int, height: int, eye_mode: str = "average",
) -> FaceReading:
    """Extract left/right readings and the combined EAR from landmarks.

    ``landmarks`` is the 468-point (or more, with iris) list from
    MediaPipe. If an iris landmark is missing, the eye centre is used
    as a fallback so drawing never fails on a partial result.
    """
    left = EyeReading.from_landmarks(
        landmarks, LEFT_EYE_EAR, LEFT_EYE_CONTOUR,
        LEFT_IRIS_CENTRE, LEFT_IRIS_RING, width, height,
    )
    right = EyeReading.from_landmarks(
        landmarks, RIGHT_EYE_EAR, RIGHT_EYE_CONTOUR,
        RIGHT_IRIS_CENTRE, RIGHT_IRIS_RING, width, height,
    )
    if eye_mode == "min":
        combined = min(left.ear, right.ear)
    else:
        combined = (left.ear + right.ear) / 2.0
    return FaceReading(left=left, right=right, combined_ear=combined)


# ---------------------------------------------------------------------------
# Face Mesh wrapper
# ---------------------------------------------------------------------------
class FaceMeshTracker:
    """Thin, safe wrapper around ``mp.solutions.face_mesh``.

    Used as a context manager so the underlying model is always closed,
    even if the camera loop exits on an error.
    """

    def __init__(self, config: Config) -> None:
        _check_dependencies()
        self._config = config
        self._mesh = None

    def __enter__(self) -> "FaceMeshTracker":
        assert mp is not None  # checked above; keeps type checkers honest
        self._mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,  # enables the 10 iris landmarks
            min_detection_confidence=self._config.min_detection_confidence,
            min_tracking_confidence=self._config.min_tracking_confidence,
        )
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def close(self) -> None:
        """Release the MediaPipe model. Safe to call more than once."""
        if self._mesh is not None:
            self._mesh.close()
            self._mesh = None

    def process(self, rgb_frame: np.ndarray):
        """Return the first face's landmarks, or ``None`` if no face."""
        if self._mesh is None:
            raise RuntimeError("FaceMeshTracker must be used as a context manager")
        results = self._mesh.process(rgb_frame)
        if not results.multi_face_landmarks:
            return None
        return results.multi_face_landmarks[0].landmark


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


# ---------------------------------------------------------------------------
# Per-person calibration
# ---------------------------------------------------------------------------
class EarCalibrator:
    """Measure open-eye EAR, then set a threshold from the person.

    The user simply looks at the screen with eyes open and relaxed.
    The threshold is set well below their typical open EAR, so normal
    variation never starts a hold, while a real closure still crosses
    it quickly. No button press or gaze target is required.
    """

    def __init__(self, duration_seconds: float = 3.0) -> None:
        self.duration_seconds = duration_seconds
        self._samples: list[float] = []
        self._started_at: Optional[float] = None

    def start(self, now: float) -> None:
        """Begin (or restart) a calibration window."""
        self._samples.clear()
        self._started_at = now

    @property
    def active(self) -> bool:
        return self._started_at is not None

    @property
    def progress(self) -> float:
        """0.0–1.0 through the calibration window."""
        if self._started_at is None:
            return 0.0
        return min(1.0, (time.monotonic() - self._started_at)
                   / self.duration_seconds)

    def add_sample(self, ear: float) -> None:
        """Record one open-eye EAR sample."""
        self._samples.append(ear)

    def finish(self) -> Optional[float]:
        """Return the recommended threshold, or None if too few samples."""
        self._started_at = None
        if len(self._samples) < 10:
            return None
        samples = sorted(self._samples)
        # Use the median: robust to a blink or two during calibration.
        median = samples[len(samples) // 2]
        # 70% of open EAR, clamped to a sane, safe band.
        return min(0.28, max(0.12, median * 0.70))


# ---------------------------------------------------------------------------
# Camera handling
# ---------------------------------------------------------------------------
class CameraStream:
    """Context-managed webcam with clear failure messages.

    A missing or busy camera is the most common first-run failure for
    an accessibility tool, so the error says what to check instead of
    surfacing an OpenCV status code.
    """

    def __init__(self, config: Config) -> None:
        _check_dependencies()
        self._config = config
        self._cap = None

    def __enter__(self) -> "CameraStream":
        assert cv2 is not None
        cap = cv2.VideoCapture(self._config.camera_index)
        if not cap.isOpened():
            raise CameraError(
                f"Could not open webcam (index {self._config.camera_index}).\n"
                "Check that a camera is connected, that no other app is "
                "using it, and that this app has camera permission.\n"
                "Try another index, e.g.  python vocal_eyes.py --camera 1"
            )
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._config.frame_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._config.frame_height)
        self._cap = cap
        return self

    def __exit__(self, *exc_info) -> None:
        self.release()

    def release(self) -> None:
        """Release the camera. Safe to call more than once."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def read(self) -> np.ndarray:
        """Read one frame, or raise CameraError if the stream fails."""
        assert self._cap is not None
        ok, frame = self._cap.read()
        if not ok or frame is None:
            raise CameraError(
                "Webcam stopped returning frames. The camera may have "
                "been unplugged or taken over by another app."
            )
        return frame


# ---------------------------------------------------------------------------
# Overlay rendering — the part the user actually looks at
# ---------------------------------------------------------------------------
def _draw_filled_rounded_rect(
    frame: np.ndarray,
    top_left: Point,
    bottom_right: Point,
    radius: int,
    colour: Tuple[int, int, int],
    alpha: float = 0.72,
) -> None:
    """Draw a translucent filled panel with rounded corners, in place."""
    assert cv2 is not None
    overlay = frame.copy()
    x1, y1 = top_left
    x2, y2 = bottom_right
    radius = min(radius, (x2 - x1) // 2, (y2 - y1) // 2)
    cv2.rectangle(overlay, (x1 + radius, y1), (x2 - radius, y2), colour, -1)
    cv2.rectangle(overlay, (x1, y1 + radius), (x2, y2 - radius), colour, -1)
    for cx, cy in ((x1 + radius, y1 + radius), (x2 - radius, y1 + radius),
                   (x1 + radius, y2 - radius), (x2 - radius, y2 - radius)):
        cv2.circle(overlay, (cx, cy), radius, colour, -1)
    cv2.addWeighted(overlay, alpha, frame, 1.0 - alpha, 0, frame)


def _draw_rounded_outline(
    frame: np.ndarray,
    top_left: Point,
    bottom_right: Point,
    radius: int,
    colour: Tuple[int, int, int],
    thickness: int = 2,
) -> None:
    """Draw a rounded-corner outline (used for the eye boxes)."""
    assert cv2 is not None
    x1, y1 = top_left
    x2, y2 = bottom_right
    radius = min(radius, (x2 - x1) // 2, (y2 - y1) // 2)
    cv2.line(frame, (x1 + radius, y1), (x2 - radius, y1), colour, thickness,
             cv2.LINE_AA)
    cv2.line(frame, (x1 + radius, y2), (x2 - radius, y2), colour, thickness,
             cv2.LINE_AA)
    cv2.line(frame, (x1, y1 + radius), (x1, y2 - radius), colour, thickness,
             cv2.LINE_AA)
    cv2.line(frame, (x2, y1 + radius), (x2, y2 - radius), colour, thickness,
             cv2.LINE_AA)
    for centre, start, end in (
        ((x1 + radius, y1 + radius), 180, 270),
        ((x2 - radius, y1 + radius), 270, 360),
        ((x1 + radius, y2 - radius), 90, 180),
        ((x2 - radius, y2 - radius), 0, 90),
    ):
        cv2.ellipse(frame, centre, (radius, radius), 0, start, end,
                    colour, thickness, cv2.LINE_AA)


def _text_size(text: str, scale: float, thickness: int) -> Tuple[int, int]:
    assert cv2 is not None
    (w, h), _ = cv2.getTextSize(
        text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
    return w, h


def _draw_text(
    frame: np.ndarray,
    text: str,
    origin: Point,
    scale: float = 0.7,
    colour: Tuple[int, int, int] = Palette.WHITE,
    thickness: int = 2,
) -> None:
    """Anti-aliased text with a soft shadow, so it reads over any background."""
    assert cv2 is not None
    x, y = origin
    cv2.putText(frame, text, (x + 1, y + 1), cv2.FONT_HERSHEY_SIMPLEX,
                scale, (0, 0, 0), thickness + 1, cv2.LINE_AA)
    cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                scale, colour, thickness, cv2.LINE_AA)


class Visualizer:
    """Draws every on-screen element. No tracking logic lives here."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._ear_history: Deque[float] = deque(maxlen=90)

    def note_ear(self, ear: float) -> None:
        """Record an EAR sample for the history trace."""
        self._ear_history.append(ear)

    # -- main entry -------------------------------------------------------
    def draw(
        self,
        frame: np.ndarray,
        reading: Optional[FaceReading],
        detector: BlinkDetector,
        fps: float,
        face_found: bool,
        calibrator: EarCalibrator,
        selection_count: int,
        banner_until: float,
        now: float,
        show_mesh: bool,
        mesh_landmarks=None,
    ) -> np.ndarray:
        """Draw the full overlay onto ``frame`` and return it."""
        height, width = frame.shape[:2]
        if reading is not None:
            self._draw_eye(frame, reading.left, detector.is_closed, "LEFT")
            self._draw_eye(frame, reading.right, detector.is_closed, "RIGHT")
        if show_mesh and mesh_landmarks is not None:
            self._draw_mesh(frame, mesh_landmarks, width, height)
        self._draw_top_bar(frame, width, fps, face_found)
        self._draw_bottom_panel(frame, width, height, reading, detector,
                                selection_count)
        if reading is not None and detector.hold_progress > 0.0:
            self._draw_hold_ring(frame, reading, detector)
        if now < banner_until:
            self._draw_selection_banner(frame, width, height, now, banner_until)
        if calibrator.active:
            self._draw_calibration_overlay(frame, width, height, calibrator)
        elif not face_found:
            self._draw_no_face_overlay(frame, width, height)
        return frame

    # -- eyes -------------------------------------------------------------
    def _draw_eye(
        self, frame: np.ndarray, eye: EyeReading, closed: bool, label: str,
    ) -> None:
        assert cv2 is not None
        colour = Palette.EYE_CLOSED if closed else Palette.EYE_OPEN
        # Eyelid contour — a closed loop so closure is visible at a glance.
        pts = np.array(eye.contour, dtype=np.int32).reshape((-1, 1, 2))
        cv2.polylines(frame, [pts], isClosed=True, color=colour,
                      thickness=2, lineType=cv2.LINE_AA)
        # Landmark dots on the contour.
        for point in eye.contour:
            cv2.circle(frame, point, 2, Palette.WHITE, -1, cv2.LINE_AA)
        # Iris: soft glow ring + centre dot. The ring makes gaze/iris
        # position readable even on a small preview.
        cv2.circle(frame, eye.iris_centre, 9, colour, 1, cv2.LINE_AA)
        cv2.circle(frame, eye.iris_centre, 3, Palette.WHITE, -1, cv2.LINE_AA)
        for point in eye.iris_ring:
            cv2.circle(frame, point, 2, colour, -1, cv2.LINE_AA)
        # Rounded bounding box around the whole eye.
        x, y, w, h = eye.bbox
        _draw_rounded_outline(frame, (x, y), (x + w, y + h), 10, colour, 2)
        # Small label pill above the box with the live EAR.
        pill_w, pill_h = 118, 26
        pill_x = max(4, min(frame.shape[1] - pill_w - 4, x))
        pill_y = max(4, y - pill_h - 6)
        _draw_filled_rounded_rect(
            frame, (pill_x, pill_y), (pill_x + pill_w, pill_y + pill_h),
            13, Palette.DARK, alpha=0.78)
        _draw_text(frame, f"{label}  {eye.ear:.2f}", (pill_x + 10, pill_y + 18),
                   scale=0.5, colour=Palette.SOFT_WHITE, thickness=1)

    def _draw_mesh(
        self, frame: np.ndarray, landmarks, width: int, height: int,
    ) -> None:
        """Optional faint full-face mesh (debug / setup aid)."""
        assert cv2 is not None and mp is not None
        connections = mp.solutions.face_mesh.FACEMESH_TESSELLATION
        for start_idx, end_idx in connections:
            a = _to_pixel(landmarks[start_idx], width, height)
            b = _to_pixel(landmarks[end_idx], width, height)
            cv2.line(frame, a, b, (70, 70, 78), 1, cv2.LINE_AA)

    # -- chrome -----------------------------------------------------------
    def _draw_top_bar(
        self, frame: np.ndarray, width: int, fps: float, face_found: bool,
    ) -> None:
        _draw_filled_rounded_rect(
            frame, (0, 0), (width, 54), 0, Palette.PANEL, alpha=0.62)
        dot_colour = Palette.TEAL if face_found else Palette.RED
        cv2.circle(frame, (26, 27), 7, dot_colour, -1, cv2.LINE_AA)
        _draw_text(frame, "VOCALEYES", (44, 35), scale=0.75,
                   colour=Palette.WHITE, thickness=2)
        _draw_text(frame, "Long-blink select", (190, 34), scale=0.55,
                   colour=Palette.MUTED, thickness=1)
        status = "Face locked" if face_found else "Searching for face..."
        status_colour = Palette.TEAL if face_found else Palette.AMBER
        sw, _ = _text_size(status, 0.55, 1)
        _draw_text(frame, status, (width - sw - 118, 34), scale=0.55,
                   colour=status_colour, thickness=1)
        fps_text = f"{fps:.0f} fps"
        fw, _ = _text_size(fps_text, 0.55, 1)
        _draw_text(frame, fps_text, (width - fw - 18, 34), scale=0.55,
                   colour=Palette.MUTED, thickness=1)

    def _draw_bottom_panel(
        self, frame: np.ndarray, width: int, height: int,
        reading: Optional[FaceReading], detector: BlinkDetector,
        selection_count: int,
    ) -> None:
        panel_h = 128
        y0 = height - panel_h
        _draw_filled_rounded_rect(
            frame, (0, y0), (width, height), 0, Palette.PANEL, alpha=0.78)
        cv2.line(frame, (0, y0), (width, y0), (60, 60, 66), 1, cv2.LINE_AA)

        # Left: per-eye EAR bars with the threshold marker.
        _draw_text(frame, "EYE ASPECT RATIO  (open ~0.30  /  closed ~0.05)",
                   (20, y0 + 26), scale=0.5, colour=Palette.MUTED, thickness=1)
        if reading is not None:
            self._draw_ear_bar(frame, 20, y0 + 40, "L", reading.left.ear,
                               detector.close_threshold)
            self._draw_ear_bar(frame, 20, y0 + 74, "R", reading.right.ear,
                               detector.close_threshold)
            combined = detector.smoothed_ear
            if combined is not None:
                _draw_text(frame, f"Combined  {combined:.2f}",
                           (20, y0 + 108), scale=0.55,
                           colour=Palette.SOFT_WHITE, thickness=1)
        else:
            _draw_text(frame, "No eye data — position your face in frame.",
                       (20, y0 + 62), scale=0.55, colour=Palette.AMBER,
                       thickness=1)

        # Centre: EAR history trace.
        trace_x0, trace_x1 = 330, width - 300
        trace_y0, trace_y1 = y0 + 30, y0 + 104
        self._draw_ear_trace(frame, trace_x0, trace_y0, trace_x1, trace_y1,
                             detector.close_threshold)

        # Right: status + counts, in large type.
        if detector.state is BlinkState.TRIGGERED:
            status, colour = "SELECTED", Palette.GREEN
        elif detector.is_closed:
            status, colour = "HOLDING...", Palette.AMBER
        elif detector.state is BlinkState.COOLDOWN:
            status, colour = "READY SOON", Palette.MUTED
        else:
            status, colour = "READY", Palette.TEAL
        _draw_text(frame, status, (width - 280, y0 + 48), scale=0.9,
                   colour=colour, thickness=2)
        _draw_text(
            frame,
            f"Selections: {selection_count}   "
            f"Hold: {detector.long_blink_seconds:.1f}s   "
            f"Threshold: {detector.close_threshold:.2f}",
            (width - 280, y0 + 78), scale=0.5, colour=Palette.MUTED,
            thickness=1)
        _draw_text(frame, "Q quit  |  C calibrate  |  M mesh  |  R reset",
                   (width - 280, y0 + 106), scale=0.5, colour=Palette.MUTED,
                   thickness=1)

    def _draw_ear_bar(
        self, frame: np.ndarray, x: int, y: int, label: str,
        ear: float, threshold: float,
    ) -> None:
        bar_w, bar_h = 240, 14
        _draw_text(frame, label, (x, y + 12), scale=0.55,
                   colour=Palette.SOFT_WHITE, thickness=1)
        bx = x + 22
        _draw_filled_rounded_rect(frame, (bx, y), (bx + bar_w, y + bar_h),
                                  7, Palette.GREY_TRACK, alpha=0.9)
        fill_w = int(bar_w * min(1.0, max(0.0, ear / 0.45)))
        fill_colour = (Palette.TEAL if ear >= threshold else Palette.AMBER)
        if fill_w > 0:
            _draw_filled_rounded_rect(
                frame, (bx, y), (bx + fill_w, y + bar_h), 7,
                fill_colour, alpha=0.95)
        # Threshold tick.
        tick_x = bx + int(bar_w * (threshold / 0.45))
        cv2.line(frame, (tick_x, y - 3), (tick_x, y + bar_h + 3),
                 Palette.WHITE, 2, cv2.LINE_AA)
        _draw_text(frame, f"{ear:.2f}", (bx + bar_w + 10, y + 12),
                   scale=0.55, colour=Palette.SOFT_WHITE, thickness=1)

    def _draw_ear_trace(
        self, frame: np.ndarray, x0: int, y0: int, x1: int, y1: int,
        threshold: float,
    ) -> None:
        """Sparkline of recent EAR, with the close threshold as a line."""
        assert cv2 is not None
        _draw_text(frame, "EAR HISTORY", (x0, y0 - 6), scale=0.5,
                   colour=Palette.MUTED, thickness=1)
        cv2.rectangle(frame, (x0, y0), (x1, y1), (60, 60, 66), 1, cv2.LINE_AA)
        # Threshold line: EAR below this line means "closed".
        thresh_y = y1 - int((threshold / 0.45) * (y1 - y0))
        cv2.line(frame, (x0, thresh_y), (x1, thresh_y), Palette.AMBER, 1,
                 cv2.LINE_AA)
        if len(self._ear_history) < 2:
            return
        span = max(1, x1 - x0)
        step = span / 89.0
        points = []
        for i, ear in enumerate(self._ear_history):
            px = int(x0 + i * step)
            py = y1 - int(min(1.0, max(0.0, ear / 0.45)) * (y1 - y0))
            points.append((px, py))
        cv2.polylines(frame, [np.array(points, dtype=np.int32)], False,
                      Palette.TEAL, 2, cv2.LINE_AA)

    def _draw_hold_ring(
        self, frame: np.ndarray, reading: FaceReading, detector: BlinkDetector,
    ) -> None:
        """Large progress ring between the eyes: the hold, made visible."""
        assert cv2 is not None
        centre = (
            (reading.left.centre[0] + reading.right.centre[0]) // 2,
            (reading.left.centre[1] + reading.right.centre[1]) // 2,
        )
        radius, thickness = 62, 10
        progress = detector.hold_progress
        cv2.circle(frame, centre, radius, Palette.GREY_TRACK, thickness,
                   cv2.LINE_AA)
        if progress > 0.0:
            end_angle = -90 + int(360 * progress)
            colour = Palette.AMBER if progress < 1.0 else Palette.GREEN
            cv2.ellipse(frame, centre, (radius, radius), 0, -90, end_angle,
                        colour, thickness, cv2.LINE_AA)
        percent = f"{int(progress * 100)}%"
        pw, _ = _text_size(percent, 0.7, 2)
        _draw_text(frame, percent, (centre[0] - pw // 2, centre[1] + 8),
                   scale=0.7, colour=Palette.WHITE, thickness=2)
        label = "HOLD TO SELECT" if progress < 1.0 else "SELECTED"
        lw, _ = _text_size(label, 0.45, 1)
        _draw_text(frame, label, (centre[0] - lw // 2, centre[1] + radius + 26),
                   scale=0.45, colour=Palette.SOFT_WHITE, thickness=1)

    def _draw_selection_banner(
        self, frame: np.ndarray, width: int, height: int,
        now: float, banner_until: float,
    ) -> None:
        """Full-width confirmation banner. Drawn, not flashed."""
        assert cv2 is not None
        remaining = max(0.0, banner_until - now)
        alpha = min(0.92, 0.35 + remaining * 0.4)
        bw, bh = 560, 96
        x0, y0 = (width - bw) // 2, (height - bh) // 2 - 110
        _draw_filled_rounded_rect(frame, (x0, y0), (x0 + bw, y0 + bh), 20,
                                  (24, 88, 38), alpha=alpha)
        cv2.rectangle(frame, (x0, y0), (x0 + bw, y0 + bh), Palette.GREEN, 2,
                      cv2.LINE_AA)
        # Checkmark, drawn as two strokes (Hershey fonts have no tick).
        cx, cy = x0 + 52, y0 + bh // 2
        cv2.line(frame, (cx - 16, cy + 2), (cx - 4, cy + 14), Palette.WHITE,
                 4, cv2.LINE_AA)
        cv2.line(frame, (cx - 4, cy + 14), (cx + 20, cy - 14), Palette.WHITE,
                 4, cv2.LINE_AA)
        _draw_text(frame, "SELECTED", (x0 + 88, y0 + 44), scale=1.0,
                   colour=Palette.WHITE, thickness=2)
        _draw_text(frame, "Long blink confirmed", (x0 + 88, y0 + 74),
                   scale=0.55, colour=Palette.SOFT_WHITE, thickness=1)

    def _draw_no_face_overlay(
        self, frame: np.ndarray, width: int, height: int,
    ) -> None:
        """Calm, large guidance when no face is tracked. Never a guess."""
        _draw_filled_rounded_rect(
            frame, (0, 60), (width, 130), 0, Palette.DARK, alpha=0.45)
        message = "No face detected — please move into frame"
        mw, _ = _text_size(message, 0.8, 2)
        _draw_text(frame, message, ((width - mw) // 2, 108), scale=0.8,
                   colour=Palette.WHITE, thickness=2)

    def _draw_calibration_overlay(
        self, frame: np.ndarray, width: int, height: int,
        calibrator: EarCalibrator,
    ) -> None:
        """Large calibration prompt: eyes open, nothing else to do."""
        _draw_filled_rounded_rect(
            frame, (0, 60), (width, 150), 0, Palette.DARK, alpha=0.55)
        message = "Calibrating — keep your eyes open and relaxed"
        mw, _ = _text_size(message, 0.8, 2)
        _draw_text(frame, message, ((width - mw) // 2, 104), scale=0.8,
                   colour=Palette.WHITE, thickness=2)
        bar_w, bar_h = 420, 12
        bx, by = (width - bar_w) // 2, 122
        _draw_filled_rounded_rect(frame, (bx, by), (bx + bar_w, by + bar_h),
                                  6, Palette.GREY_TRACK, alpha=0.9)
        fill_w = int(bar_w * calibrator.progress)
        if fill_w > 0:
            _draw_filled_rounded_rect(
                frame, (bx, by), (bx + fill_w, by + bar_h), 6,
                Palette.TEAL, alpha=0.95)


# ---------------------------------------------------------------------------
# Selection action — the one integration hook
# ---------------------------------------------------------------------------
def on_long_blink(event: BlinkEvent, selection_count: int) -> None:
    """Default action for a long blink: confirm loudly on the console.

    Replace this function (or pass your own callback to :func:`main`
    via ``action_callback`` in a future integration) to drive a real
    downstream effect — a mouse click, a switch press, a scanning
    keyboard advance, or speech output. Keep downstream work fast and
    non-blocking: this runs inside the camera loop.
    """
    message = (
        f"[VocalEyes] Long Blink / Select registered "
        f"(#{selection_count}, held {event.closed_seconds:.2f}s, "
        f"EAR at close {event.ear_at_close:.2f})"
    )
    print(message, flush=True)
    logger.info(message)


# ---------------------------------------------------------------------------
# Command-line interface
# ---------------------------------------------------------------------------
def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="vocal_eyes",
        description=(
            "Project VocalEyes: select with a long blink. "
            "Hold both eyes closed to trigger a Select action."
        ),
        epilog=(
            "Controls: Q / Esc quit  |  C recalibrate  |  "
            "M toggle face mesh  |  R reset detector."
        ),
    )
    parser.add_argument("--camera", type=int, default=0,
                        help="Webcam index (default: 0; try 1 if no camera).")
    parser.add_argument("--width", type=int, default=1280,
                        help="Requested capture width (default: 1280).")
    parser.add_argument("--height", type=int, default=720,
                        help="Requested capture height (default: 720).")
    parser.add_argument("--no-mirror", action="store_true",
                        help="Do not mirror the preview (default: mirrored).")
    parser.add_argument("--threshold", type=float, default=0.21,
                        help="EAR close threshold (default: 0.21). Lower is "
                        "less sensitive; recalibrate per person with C.")
    parser.add_argument("--long-blink", type=float, default=1.0,
                        help="Hold time in seconds for a Select "
                        "(default: 1.0).")
    parser.add_argument("--cooldown", type=float, default=1.5,
                        help="Quiet period in seconds after a Select "
                        "(default: 1.5).")
    parser.add_argument("--eye-mode", choices=("average", "min"),
                        default="average",
                        help="How to combine the two eyes: average "
                        "(default) or min (more sensitive, for asymmetric "
                        "closure).")
    parser.add_argument("--show-mesh", action="store_true",
                        help="Draw the full face mesh (setup / debugging).")
    parser.add_argument("--calibrate", type=float, default=3.0,
                        help="Seconds of open-eye calibration at startup "
                        "(default: 3.0).")
    parser.add_argument("--no-calibrate", action="store_true",
                        help="Skip startup calibration; use --threshold.")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


