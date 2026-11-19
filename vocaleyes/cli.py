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
    parser.add_argument("--camera", type=int, default=0,
                        help="Webcam index (default: 0; try 1 if no camera).")
    parser.add_argument("--width", type=int, default=1280,
                        help="Requested capture width (default: 1280).")
    parser.add_argument("--height", type=int, default=720,
                        help="Requested capture height (default: 720).")
    parser.add_argument("--no-mirror", action="store_true",
                        help="Do not mirror the preview (default: mirrored).")
    parser.add_argument("--threshold", type=float, default=0.21,
                        help="EAR close threshold (default: 0.21). Lower is "
                        "less sensitive; recalibrate per person with C.")
    parser.add_argument("--long-blink", type=float, default=1.0,
                        help="Hold time in seconds for a Select "
                        "(default: 1.0).")
    parser.add_argument("--cooldown", type=float, default=1.5,
                        help="Quiet period in seconds after a Select "
                        "(default: 1.5).")
    parser.add_argument("--eye-mode", choices=("average", "min"),
                        default="average",
                        help="How to combine the two eyes: average "
                        "(default) or min (more sensitive, for asymmetric "
                        "closure).")
    parser.add_argument("--show-mesh", action="store_true",
                        help="Draw the full face mesh (setup / debugging).")
    parser.add_argument("--calibrate", type=float, default=3.0,
                        help="Seconds of open-eye calibration at startup "
                        "(default: 3.0).")
    parser.add_argument("--no-calibrate", action="store_true",
                        help="Skip startup calibration; use --threshold.")
    parser.add_argument("--no-threaded-capture", action="store_true",
                        help="Capture frames on the main thread instead of "
                             "a background thread (diagnostics only).")
    parser.add_argument("--no-drift", action="store_true",
                        help="Disable slow threshold drift compensation.")
    parser.add_argument("--log-level", choices=("quiet", "info", "debug"),
                        default="info",
                        help="Console verbosity (default: info).")
    parser.add_argument("--log-format", choices=("text", "json"),
                        default="text",
                        help="Console log format: readable text or one JSON "
                             "object per line (default: text).")
    parser.add_argument("--profile", default=None, metavar="NAME",
                        help="Apply a saved profile or a shipped preset "
                             "(see: vocaleyes profiles).")
    parser.add_argument("--stats-json", default=None, metavar="PATH",
                        help="Write the session report to PATH as JSON. "
                             "Nothing is written unless you pass this.")
    parser.add_argument("--verbose", action="store_true",
                        help="Show the details of passing checks "
                             "(vocaleyes doctor only).")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main(
    argv: Optional[Sequence[str]] = None,
    action_callback: Callable[[BlinkEvent, int], None] = on_long_blink,
) -> int:
    """Run VocalEyes until the user quits. Returns a process exit code."""
    args = parse_args(argv)
    configure_logging(level=args.log_level,
                      json_logs=args.log_format == "json")
    try:
        config = Config.from_args(args)
        # A profile is applied after the flags, so `vocaleyes --profile
        # glasses --long-blink 1.5` gives the flag the last word — the
        # person running the session should always win over a saved file.
        profile = find_profile(args.profile)
        if profile is not None:
            config = profile.apply(config)
    except ValueError as exc:
        print(f"Invalid option: {exc}", file=sys.stderr)
        return 2

    if args.command == "doctor":
        # Diagnostics must not need a webcam or the GUI stack, so this
        # returns before any dependency is required to be present.
        return run_doctor(config, verbose=args.verbose)
    if args.command == "profiles":
        print(describe_profiles())
        return 0

    try:
        check_dependencies()
    except DependencyError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    assert cv2 is not None
    detector = BlinkDetector(config)
    visualizer = Visualizer(config)
    calibrator = EarCalibrator(config.calibrate_seconds)
    # Drift compensation starts from whatever calibration ends up with;
    # retune() and reset() below keep it anchored to the live threshold.
    drift = ThresholdDrift(config.ear_threshold) if config.drift_enabled \
        else None
    timer = StageTimer(budget_seconds=0.033)
    stats = SessionStats()
    selection_count = 0
    banner_until = 0.0
    fps = 0.0
    show_mesh = config.show_mesh
    consecutive_failures = 0
    slow_frames = 0
    losing_face = False
