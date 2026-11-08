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

    def __init__(self, config: Config) -> None:
        check_dependencies()
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
