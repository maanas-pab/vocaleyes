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
        points = [to_pixel(lm, width, height) for lm in landmarks]
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

