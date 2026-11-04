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


