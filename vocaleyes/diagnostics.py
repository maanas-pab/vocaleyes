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


def _check_config(config: Optional[Config]) -> Check:
    """Validate the tunables now, not halfway through a session."""
    try:
        cfg = Config() if config is None else config
        # A dataclass can be changed after it was built, so re-run the
        # validator instead of trusting the instance we were handed.
        cfg.__post_init__()
    except ValueError as exc:
        return Check(
            "config", "Settings", False, str(exc),
            hint="reset to the defaults: --threshold 0.21 "
                 "--long-blink 1.0 --cooldown 1.5",
        )
    detail = (f"threshold {cfg.ear_threshold}, "
              f"hold {cfg.long_blink_seconds}s, "
              f"cooldown {cfg.cooldown_seconds}s")
    return Check("config", "Settings", True, detail)


def _check_permissions() -> Check:
    """Whether the OS will let this app see a camera.

    Warn-level: it can explain a failure but never fails the doctor on
    its own. macOS has nothing to inspect — the permission prompt
    appears at first run — so that branch only reports the OS.
    """
    system = platform.system()
    if system == "Windows":
        return Check("permissions", "Camera permissions", True,
                     "camera access is managed by Windows Settings",
                     severity="warn")
    if system == "Darwin":
        return Check("permissions", "Camera permissions", True,
                     "macOS: allow VocalEyes in System Settings > "
                     "Privacy & Security > Camera",
                     severity="warn")
    devices = sorted(glob.glob("/dev/video*"))
    if devices:
        names = ", ".join(os.path.basename(d) for d in devices)
        return Check("permissions", "Camera permissions", True,
                     f"{system}: found {names}", severity="warn")
    return Check(
        "permissions", "Camera permissions", False,
        f"{system}: no camera device under /dev/video*",
        hint="is the webcam plugged in? If it is, ask whoever set up "
             "this computer to add your user to the video group: "
             "sudo usermod -aG video $USER",
        severity="warn",
    )


def _check_display() -> Check:
    """A GUI window is required; a bare ssh session has nowhere to draw."""
    system = platform.system()
    if system in ("Windows", "Darwin"):
        name = "macOS" if system == "Darwin" else system
        return Check("display", "Display", True,
                     f"{name} desktop session")
    display = os.environ.get("DISPLAY")
    if display:
        return Check("display", "Display", True,
                     f"X session (DISPLAY={display})")
    wayland = os.environ.get("WAYLAND_DISPLAY")
    if wayland:
        return Check("display", "Display", True,
                     f"Wayland session (WAYLAND_DISPLAY={wayland})")
    return Check(
        "display", "Display", False,
        "no desktop session (DISPLAY and WAYLAND_DISPLAY are both unset)",
        hint="VocalEyes draws a preview window; run it in a desktop "
             "session, not over bare ssh.",
    )


# ---------------------------------------------------------------------------
# Running the checks
# ---------------------------------------------------------------------------
def run_checks(config: Optional[Config] = None, *,
               probe_camera: bool = True) -> List[Check]:
    """Run every check and return them in :data:`CHECK_ORDER`.

    ``config`` is used as-is when given (and re-validated); otherwise
    defaults are built for the checks that need them. ``probe_camera``
    is the one switch a caller may turn off to skip touching the
    webcam — a probe opens the camera, and some callers (tests, CI)
    have none.
    """
    probes = (
        ("python", "Python version", _check_python),
        ("numpy", "NumPy", _check_numpy),
        ("opencv", "OpenCV", _check_opencv),
        ("mediapipe", "MediaPipe", _check_mediapipe),
        ("camera", "Webcam",
         lambda: _check_camera(config, probe_camera)),
        ("config", "Settings", lambda: _check_config(config)),
        ("permissions", "Camera permissions", _check_permissions),
        ("display", "Display", _check_display),
    )
    return [_safe(name, label, probe) for name, label, probe in probes]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def format_report(results: List[Check], *, verbose: bool = False) -> str:
    """Render checks as one readable block, with no trailing newline.

    A failing check always shows what was observed plus a ``-> `` hint,
    because that is the line the reader came for. A passing check only
    shows its detail under ``verbose``, keeping the default report
    short enough to read at a glance.
    """
    total = len(results)
    passed = sum(1 for c in results if c.ok)
    warned = sum(1 for c in results if not c.ok and c.severity == "warn")
    failed = sum(1 for c in results if not c.ok and c.severity != "warn")
    lines = [
        f"VocalEyes doctor — {total} checks, {passed} ok, "
        f"{warned} warnings, {failed} failed",
    ]
    for check in results:
        # The markers are one width wide so every label starts in the
        # same column regardless of outcome.
        if check.ok:
            marker = "[ ok ]"
        elif check.severity == "warn":
            marker = "[warn]"
        else:
            marker = "[FAIL]"
        line = f"  {marker} {check.label}"
        if check.detail and (verbose or not check.ok):
            line += f" — {check.detail}"
        lines.append(line)
        if not check.ok and check.hint:
            lines.append(f"    -> {check.hint}")
    if failed:
        lines.append(
            "Fix the FAIL items above and run vocaleyes doctor again.")
    else:
        lines.append("All good — VocalEyes should run.")
    return "\n".join(lines)

