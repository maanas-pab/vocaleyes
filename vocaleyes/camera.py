"""Camera handling for Project VocalEyes.

A context-managed webcam that fails with clear, actionable messages,
because a missing or busy camera is the most common first-run failure
for an accessibility tool.
"""
from __future__ import annotations

import numpy as np

from .config import Config
from .deps import check_dependencies, cv2
from .errors import CameraError


# ---------------------------------------------------------------------------
# Camera handling
# ---------------------------------------------------------------------------
class CameraStream:
    """Context-managed webcam with clear failure messages.

    A missing or busy camera is the most common first-run failure for
    an accessibility tool, so the error says what to check instead of
    surfacing an OpenCV status code.
    """

