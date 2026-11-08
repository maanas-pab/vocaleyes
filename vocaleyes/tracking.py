"""Face Mesh wrapper for Project VocalEyes.

A thin, safe wrapper around ``mp.solutions.face_mesh``: entered as a
context manager, it returns the first face's landmarks per frame and
always closes the underlying model, even if the camera loop exits on
an error.
"""
from __future__ import annotations

import numpy as np

from .config import Config
from .deps import check_dependencies, mp


# ---------------------------------------------------------------------------
# Face Mesh wrapper
# ---------------------------------------------------------------------------
class FaceMeshTracker:
    """Thin, safe wrapper around ``mp.solutions.face_mesh``.

    Used as a context manager so the underlying model is always closed,
    even if the camera loop exits on an error.
    """

    def __init__(self, config: Config) -> None:
        check_dependencies()
        self._config = config
        self._mesh = None

    def __enter__(self) -> "FaceMeshTracker":
        assert mp is not None  # checked above; keeps type checkers honest
        self._mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,  # enables the 10 iris landmarks
            min_detection_confidence=self._config.min_detection_confidence,
            min_tracking_confidence=self._config.min_tracking_confidence,
        )
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def close(self) -> None:
        """Release the MediaPipe model. Safe to call more than once."""
        if self._mesh is not None:
            self._mesh.close()
            self._mesh = None

    def process(self, rgb_frame: np.ndarray):
        """Return the first face's landmarks, or ``None`` if no face."""
        if self._mesh is None:
            raise RuntimeError("FaceMeshTracker must be used as a context manager")
        results = self._mesh.process(rgb_frame)
        if not results.multi_face_landmarks:
            return None
        return results.multi_face_landmarks[0].landmark
