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
