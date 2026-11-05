"""Geometry helpers — pure functions, unit-testable without a camera.

Nothing here touches a camera, a window, or a global clock: points in,
numbers out. The Eye Aspect Ratio is the whole product in one formula,
so it gets its own module and its own guards.
"""

from __future__ import annotations

import math
from typing import Sequence, Tuple

