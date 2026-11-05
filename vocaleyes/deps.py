"""Lazy, forgiving imports of the two heavy dependencies.

OpenCV and MediaPipe are imported here inside ``try/except`` so that
``import vocaleyes`` — and therefore ``vocal_eyes --help``,
``--version`` and any documentation tooling — still works on a machine
where they have not been installed yet. Nothing else in the package
imports ``cv2`` or ``mediapipe`` directly; they come from this module,
along with :func:`check_dependencies`, which turns a missing wheel into
an instruction instead of a traceback.
"""

from __future__ import annotations

from .errors import DependencyError

try:
    import cv2
except ImportError as _cv2_error:  # pragma: no cover - env without cv2
    cv2 = None  # type: ignore[assignment]
    CV2_IMPORT_ERROR = _cv2_error
else:
    CV2_IMPORT_ERROR = None

try:
    import mediapipe as mp
except ImportError as _mp_error:  # pragma: no cover - env without mp
    mp = None  # type: ignore[assignment]
    MP_IMPORT_ERROR = _mp_error
else:
    MP_IMPORT_ERROR = None


