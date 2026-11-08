"""Overlay rendering — the part the user actually looks at.

This module owns every pixel drawn on screen: the eye contours, the
EAR bars and history trace, the hold-to-select ring, the confirmation
banner, and the calm guidance overlays. It contains no tracking logic;
it only draws what the detection and calibration layers hand to it.

Feedback here is deliberately large, calm, and unambiguous — no
flashing, no tiny text, and no reliance on sound.
"""
from __future__ import annotations

from collections import deque
from typing import Deque, Optional, Tuple

import numpy as np

from .calibration import EarCalibrator
from .config import Config
from .deps import cv2, mp
from .detection import BlinkDetector, BlinkState
from .geometry import Point, to_pixel
from .models import EyeReading, FaceReading
from .palette import Palette


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
