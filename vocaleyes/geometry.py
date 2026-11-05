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

