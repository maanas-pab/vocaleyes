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
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        config = Config.from_args(args)
    except ValueError as exc:
        print(f"Invalid option: {exc}", file=sys.stderr)
        return 2

    try:
        check_dependencies()
    except DependencyError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    assert cv2 is not None
    detector = BlinkDetector(config)
    visualizer = Visualizer(config)
    calibrator = EarCalibrator(config.calibrate_seconds)
    selection_count = 0
    banner_until = 0.0
    fps = 0.0
    show_mesh = config.show_mesh
    consecutive_failures = 0

    print("Project VocalEyes — long-blink selection")
    print("Hold both eyes closed to select. Press Q to quit.")
    if config.calibrate_seconds > 0:
        print(f"Calibrating for {config.calibrate_seconds:.0f}s: "
              "keep your eyes open and relaxed.")
        calibrator.start(time.monotonic())

    try:
        with CameraStream(config) as camera, FaceMeshTracker(config) as tracker:
            cv2.namedWindow(config.window_name, cv2.WINDOW_NORMAL)
            while True:
                loop_started = time.monotonic()
                try:
                    frame = camera.read()
                except CameraError:
                    consecutive_failures += 1
                    if consecutive_failures >= 30:
                        raise
                    continue
                consecutive_failures = 0

                if config.mirror:
                    frame = cv2.flip(frame, 1)
                height, width = frame.shape[:2]
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                rgb.flags.writeable = False
                landmarks = tracker.process(rgb)
                rgb.flags.writeable = True
                now = time.monotonic()

