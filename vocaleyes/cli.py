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

from .calibration import EarCalibrator
from .camera import CameraStream
from .config import Config
from .deps import cv2, check_dependencies
from .detection import BlinkDetector, BlinkEvent
from .errors import CameraError, DependencyError
from .hooks import on_long_blink
from .models import FaceReading, extract_eye_readings
from .rendering import Visualizer
from .tracking import FaceMeshTracker
from ._version import __version__

logger = logging.getLogger("vocaleyes")


# ---------------------------------------------------------------------------
# Command-line interface
# ---------------------------------------------------------------------------
def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="vocal_eyes",
        description=(
            "Project VocalEyes: select with a long blink. "
            "Hold both eyes closed to trigger a Select action."
        ),
        epilog=(
            "Controls: Q / Esc quit  |  C recalibrate  |  "
            "M toggle face mesh  |  R reset detector."
        ),
    )
    parser.add_argument("--camera", type=int, default=0,
                        help="Webcam index (default: 0; try 1 if no camera).")
    parser.add_argument("--width", type=int, default=1280,
                        help="Requested capture width (default: 1280).")
    parser.add_argument("--height", type=int, default=720,
                        help="Requested capture height (default: 720).")
    parser.add_argument("--no-mirror", action="store_true",
