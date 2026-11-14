"""Camera handling for Project VocalEyes.

A context-managed webcam that fails with clear, actionable messages,
because a missing or busy camera is the most common first-run failure
for an accessibility tool. Capture also runs on a background pump, so
slow inference never backs up the camera buffer or ages the image on
screen.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

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
                "Try another index, e.g.  vocaleyes --camera 1"
            )
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._config.frame_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._config.frame_height)
        self._cap = cap
        return self

    def __exit__(self, *exc_info) -> None:
        self.release()

    def release(self) -> None:
        """Release the camera. Safe to call more than once."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def read(self) -> np.ndarray:
        """Read one frame, or raise CameraError if the stream fails."""
        assert self._cap is not None
        ok, frame = self._cap.read()
        if not ok or frame is None:
            raise CameraError(
                "Webcam stopped returning frames. The camera may have "
                "been unplugged or taken over by another app."
            )
        return frame


# ---------------------------------------------------------------------------
# Background capture
# ---------------------------------------------------------------------------
class FramePump:
    """Background capture thread handing the loop one fresh frame.

    Face-mesh inference is slower than a webcam, so ``read()`` runs on a
    daemon thread of its own: the camera buffer is drained as fast as it
    fills, and the image on screen never falls seconds behind reality.

