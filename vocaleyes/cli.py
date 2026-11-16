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
from .errors import CameraError, DependencyError
from .hooks import on_long_blink
from .logging_setup import configure as configure_logging
from .models import FaceReading, extract_eye_readings
from .rendering import Visualizer
from .smoothing import StageTimer
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
    # Drift compensation starts from whatever calibration ends up with;
    # retune() and reset() below keep it anchored to the live threshold.
    drift = ThresholdDrift(config.ear_threshold) if config.drift_enabled \
        else None
    timer = StageTimer(budget_seconds=0.033)
    selection_count = 0
    banner_until = 0.0
    fps = 0.0
    show_mesh = config.show_mesh
    consecutive_failures = 0
    slow_frames = 0

    print("Project VocalEyes — long-blink selection")
    print("Hold both eyes closed to select. Press Q to quit.")
    if config.calibrate_seconds > 0:
        print(f"Calibrating for {config.calibrate_seconds:.0f}s: "
              "keep your eyes open and relaxed.")
        calibrator.start(time.monotonic())

    try:
        with CameraStream(config) as camera, FaceMeshTracker(config) as tracker:
            cv2.namedWindow(config.window_name, cv2.WINDOW_NORMAL)
            # Background capture keeps the webcam drained while inference
            # runs, so the preview never falls seconds behind reality.
            pump = FramePump(camera) if config.threaded_capture else None
            if pump is not None:
                pump.start()
            try:
                while True:
                    loop_started = time.monotonic()
                    with timer.stage("capture"):
                        if pump is not None:
                            frame = pump.latest()
                            if frame is None:
                                # Not a failure: the pump is simply ahead
                                # of the camera this tick.
                                time.sleep(0.001)
                                continue
                            if pump.error is not None:
                                raise pump.error
                        else:
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
                    with timer.stage("infer"):
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        rgb.flags.writeable = False
                        landmarks = tracker.process(rgb)
                        rgb.flags.writeable = True
                    now = time.monotonic()

                    face_found = landmarks is not None
                    reading: Optional[FaceReading] = None
                    if face_found:
                        reading = extract_eye_readings(
                            landmarks, width, height, config.eye_mode)
                        visualizer.note_ear(reading.combined_ear)

                        if calibrator.active:
                            # Calibration pauses selection: samples must be
                            # open eyes only, and a blink mid-calibration
                            # must never fire.
                            calibrator.add_sample(reading.combined_ear)
                            if calibrator.progress >= 1.0:
                                threshold = calibrator.finish()
                                if threshold is not None:
                                    detector.retune(threshold)
                                    if drift is not None:
                                        # A fresh calibration is the new
                                        # anchor; drift starts from here.
                                        drift.reset(threshold)
                                    print(
                                        "Calibration complete: EAR threshold "
                                        f"set to {threshold:.2f}.",
                                        flush=True,
                                    )
                                else:
                                    print(
                                        "Calibration had too few samples; "
                                        "keeping threshold "
                                        f"{detector.close_threshold:.2f}.",
                                        flush=True,
                                    )
                        else:
                            event = detector.update(reading.combined_ear, now)
                            if drift is not None:
                                # ThresholdDrift samples only open eyes and
                                # moves at most a step at a time, so this
                                # can never turn a blink into a selection.
                                moved = drift.observe(
                                    reading.combined_ear,
                                    closed=detector.is_closed, now=now)
                                if moved is not None:
                                    detector.retune(moved)
                                    logger.info(
                                        "Threshold drift: %.3f -> %.3f",
                                        detector.close_threshold, moved,
                                    )
                            if event is not None and event.kind == "select":
                                selection_count += 1
                                banner_until = now + 1.6
                                action_callback(event, selection_count)
                            elif event is not None:
                                logger.debug(
                                    "Short blink ignored (%.2fs)",
                                    event.closed_seconds,
                                )
                    else:
                        # No face: forget any partial closure. A tracking
                        # gap must never become a selection.
                        detector.reset()

                    with timer.stage("render"):
                        frame = visualizer.draw(
                            frame, reading, detector, fps, face_found,
                            calibrator, selection_count, banner_until, now,
                            show_mesh, mesh_landmarks=landmarks,
                        )
                        cv2.imshow(config.window_name, frame)

                    # Smooth FPS for the HUD (EMA, so one slow frame
                    # does not make the display jump).
