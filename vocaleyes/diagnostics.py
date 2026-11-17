"""``vocaleyes doctor`` — say what is wrong, and what to do about it.

Project VocalEyes is run by carers, not programmers, and it fails at a
handful of predictable places: too old a Python, a library that was
never installed, a webcam another app has taken, settings out of range,
a session with nowhere to draw. Each becomes one :class:`Check` that
reports what was actually observed and — when it is wrong — the exact
command or setting that fixes it, because a stack trace tells a carer
nothing.

Everything here is standard library plus this package's own modules.
NumPy, OpenCV and MediaPipe are only touched inside the checks that
need them, and every probe is wrapped so an unexpected crash turns into
a FAIL line instead of an exception: the doctor has to keep talking on
the very machines it exists to diagnose.
"""

from __future__ import annotations

import glob
import os
import platform
import sys
from dataclasses import dataclass
from typing import Callable, List, Optional

from .config import Config

# The fixed order checks are run and reported in: what you are running
# (python), what it needs (the libraries), what it watches (the camera
# and the settings it watches with), then the room it draws into.
CHECK_ORDER = (
    "python",
    "numpy",
    "opencv",
    "mediapipe",
    "camera",
    "config",
    "permissions",
    "display",
)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
@dataclass
class Check:
    """One probe: what was checked, what happened, what to do next.

    ``hint`` is read only when ``ok`` is False — it is the instruction
    handed to a carer, so it must be a command or a setting to change,
    never a stack trace. ``severity`` decides whether a failure stops
    the run: ``"warn"`` marks findings worth mentioning that do not
    stop VocalEyes from working (and so never fail ``doctor``).
    """

    name: str
    label: str
    ok: bool
    detail: str
    hint: str = ""
    severity: str = "error"


def _safe(name: str, label: str, probe: Callable[[], Check]) -> Check:
    """Run one probe; a crash inside it becomes a FAIL line, not a traceback.

    No probe may raise out of the doctor: a carer running this on a
    machine that is already misbehaving needs a report, not a crash.
    """
    try:
        return probe()
    except Exception as exc:  # the point of this function is to catch all
        return Check(name, label, False, f"check crashed: {exc!r}",
                     hint="something unexpected happened; run the command "
                          "again, and if it repeats, send this line to "
                          "whoever set up VocalEyes.")


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def _check_python() -> Check:
    """Everything else assumes 3.9+; say which interpreter is running."""
    ok = sys.version_info >= (3, 9)
    version = platform.python_version()
    implementation = platform.python_implementation()
    hint = "" if ok else (
        "VocalEyes needs Python 3.9 or newer; install a newer Python "
        "from python.org, then run pip install -r requirements.txt again."
    )
    return Check("python", "Python version", ok,
                 f"{version} ({implementation})", hint)


def _check_numpy() -> Check:
    """NumPy backs every frame measurement, so it is checked first."""
    try:
        import numpy as np
    except ImportError as exc:
        return Check("numpy", "NumPy", False, f"not installed ({exc})",
                     hint="pip install numpy")
    return Check("numpy", "NumPy", True, np.__version__)


def _check_opencv() -> Check:
    """Read deps' lazily-imported cv2 instead of importing it again."""
    from . import deps

    if deps.cv2 is None:
        return Check("opencv", "OpenCV", False,
                     f"not installed ({deps.CV2_IMPORT_ERROR})",
                     hint="pip install opencv-python")
    return Check("opencv", "OpenCV", True, deps.cv2.__version__)


def _check_mediapipe() -> Check:
    """Same shape as OpenCV: deps already recorded why the import failed."""
    from . import deps

    if deps.mp is None:
        return Check("mediapipe", "MediaPipe", False,
                     f"not installed ({deps.MP_IMPORT_ERROR})",
                     hint="pip install mediapipe")
    return Check("mediapipe", "MediaPipe", True, deps.mp.__version__)


def _check_camera(config: Optional[Config], probe_camera: bool) -> Check:
    """Open the webcam and read one frame — the most common first-run fail.

    Probing briefly holds the camera, so it only runs when asked for
    and when OpenCV (which does the probing) is present; otherwise the
    camera check is skipped rather than passed or failed. The handle is
    always released so the real run that follows finds a free camera.
    """
    from . import deps

    if not probe_camera or deps.cv2 is None:
        return Check("camera", "Webcam", True, "skipped")

    index = 0 if config is None else config.camera_index
    cap = deps.cv2.VideoCapture(index)
    try:
        if not cap.isOpened():
            return Check(
                "camera", "Webcam", False, f"camera {index} did not open",
                hint="check the camera is not in use by another app, "
                     "or try --camera 1",
            )
        got_frame, frame = cap.read()
        if not got_frame or frame is None:
            return Check(
                "camera", "Webcam", False,
                f"camera {index} opened but sent no frame",
                hint="check the camera is not in use by another app, "
                     "or try --camera 1",
            )
        height, width = frame.shape[:2]
        return Check("camera", "Webcam", True,
                     f"camera {index} opened, first frame {width}x{height}")
    finally:
        cap.release()


