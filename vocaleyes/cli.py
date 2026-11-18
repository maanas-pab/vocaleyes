"""Command-line interface — wires config -> camera -> tracker -> detector -> renderer.

``parse_args`` turns flags into an ``argparse.Namespace`` for
:class:`Config`. ``main`` runs VocalEyes until the user quits: it wires
config -> camera -> tracker -> detector -> renderer, then loops on frames
— calibration, key handling, FPS smoothing, and a clean window-close
check — returning a process exit code.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from typing import Callable, Optional, Sequence

from .calibration import EarCalibrator, ThresholdDrift
from .camera import CameraStream, FramePump
from .config import Config
from .deps import cv2, check_dependencies
from .detection import BlinkDetector, BlinkEvent
from .diagnostics import doctor as run_doctor
from .errors import CameraError, DependencyError
from .hooks import on_long_blink
from .logging_setup import configure as configure_logging
from .models import FaceReading, extract_eye_readings
from .profiles import describe as describe_profiles, find as find_profile
from .rendering import Visualizer
from .smoothing import StageTimer
from .stats import SessionStats
from .tracking import FaceMeshTracker
from ._version import __version__

logger = logging.getLogger("vocaleyes")


# ---------------------------------------------------------------------------
# Command-line interface
# ---------------------------------------------------------------------------
def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="vocaleyes",
        description=(
            "Project VocalEyes: select with a long blink. "
            "Hold both eyes closed to trigger a Select action."
        ),
        epilog=(
            "Controls: Q / Esc quit  |  C recalibrate  |  "
            "M toggle face mesh  |  R reset detector."
        ),
    )
    parser.add_argument("command", nargs="?", default="run",
                        choices=("run", "doctor", "profiles"),
                        help="run (default) start tracking; doctor check "
                             "that this machine is ready; profiles list "
                             "the saved profiles and shipped presets.")
