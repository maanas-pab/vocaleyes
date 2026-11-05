"""Geometry helpers — pure functions, unit-testable without a camera.

Nothing here touches a camera, a window, or a global clock: points in,
numbers out. The Eye Aspect Ratio is the whole product in one formula,
so it gets its own module and its own guards.
"""

from __future__ import annotations

import math
from typing import Sequence, Tuple

Point = Tuple[int, int]


def distance(a: Point, b: Point) -> float:
    """Euclidean distance between two pixel points."""
    return math.hypot(a[0] - b[0], a[1] - b[1])


def calculate_ear(eye: Sequence[Point]) -> float:
    """Return the Eye Aspect Ratio for one eye from six eyelid points.

    ``eye`` is ordered (outer, upper, upper, inner, lower, lower)
    matching :data:`~vocaleyes.landmarks.LEFT_EYE_EAR` /
    :data:`~vocaleyes.landmarks.RIGHT_EYE_EAR`. Returns 0.0
    for a degenerate (zero-width) eye instead of raising, so one bad
    frame can never crash the tracker.
    """
    if len(eye) != 6:
        raise ValueError(f"EAR needs exactly 6 points, got {len(eye)}")
    horizontal = distance(eye[0], eye[3])
    if horizontal == 0:
        return 0.0
    vertical_a = distance(eye[1], eye[5])
    vertical_b = distance(eye[2], eye[4])
    return (vertical_a + vertical_b) / (2.0 * horizontal)


def to_pixel(landmark, width: int, height: int) -> Point:
    """Convert a normalised MediaPipe landmark to integer pixel coords."""
    return (int(landmark.x * width), int(landmark.y * height))
