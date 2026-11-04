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

