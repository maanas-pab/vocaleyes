"""Project VocalEyes — select with a long blink.

An on-device accessibility tool for people with advanced ALS: a webcam
watches the eyes, measures the Eye Aspect Ratio, and turns one
deliberate action — closing both eyes and holding them shut — into a
Select. Ordinary blinks are ignored. Nothing is recorded or uploaded.

The package is layered so each piece can be read, tested and replaced
on its own:

    geometry, landmarks     pure maths and the index table
    models                  per-frame eye measurements
    detection               the blink state machine
    calibration             per-person thresholds
    tracking, camera        MediaPipe and the webcam
    rendering               every pixel the user sees
    config, profiles        tunables and per-person presets
    diagnostics, stats      doctor command and session reporting
    cli                     the command line

Importing this package is deliberately cheap: OpenCV and MediaPipe are
only touched when something actually needs them, so ``import vocaleyes``
and ``vocaleyes --help`` work on a machine that has not installed them
yet.
"""

from __future__ import annotations

from ._version import __version__
from .calibration import EarCalibrator
from .config import Config
from .detection import BlinkDetector, BlinkEvent, BlinkState
from .errors import CameraError, DependencyError
from .geometry import Point, calculate_ear
from .hooks import on_long_blink
from .models import EyeReading, FaceReading, extract_eye_readings

__all__ = [
    "BlinkDetector",
    "BlinkEvent",
    "BlinkState",
    "CameraError",
    "Config",
    "DependencyError",
    "EarCalibrator",
    "EyeReading",
    "FaceReading",
    "FaceMeshTracker",
    "__version__",
    "calculate_ear",
    "extract_eye_readings",
    "main",
    "on_long_blink",
]


def __getattr__(name: str):
    """Expose the heavier parts of the API lazily (PEP 562).

    ``FaceMeshTracker`` pulls MediaPipe into memory and ``main`` pulls in
    the renderer and NumPy; neither belongs in a plain
    ``import vocaleyes`` used by docs tooling or ``--help``.
    """
    if name == "FaceMeshTracker":
        from .tracking import FaceMeshTracker
        return FaceMeshTracker
    if name == "main":
        from .cli import main
        return main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
