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

