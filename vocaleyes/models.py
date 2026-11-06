"""Per-frame eye measurements for VocalEyes.

``EyeReading`` and ``FaceReading`` record what one eye, and then both
eyes, measured in a single frame; the caller supplies the landmark
indices, so these types stay independent of any particular face-mesh
layout. ``extract_eye_readings`` builds them from a MediaPipe landmark
list and combines the two ears for the detector downstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .geometry import Point, calculate_ear, to_pixel
from .landmarks import (LEFT_EYE_EAR, RIGHT_EYE_EAR, LEFT_EYE_CONTOUR, RIGHT_EYE_CONTOUR, LEFT_IRIS_CENTRE, RIGHT_IRIS_CENTRE, LEFT_IRIS_RING, RIGHT_IRIS_RING)


@dataclass
class EyeReading:
    """Everything measured for one eye in one frame."""

    ear: float
    contour: list[Point]
    iris_centre: Point
    iris_ring: list[Point]
    bbox: Tuple[int, int, int, int]  # x, y, w, h in pixels

