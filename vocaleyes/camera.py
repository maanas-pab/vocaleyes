"""Camera handling for Project VocalEyes.

A context-managed webcam that fails with clear, actionable messages,
because a missing or busy camera is the most common first-run failure
for an accessibility tool. Capture also runs on a background pump, so
slow inference never backs up the camera buffer or ages the image on
screen.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

import numpy as np

from .config import Config
from .deps import check_dependencies, cv2
from .errors import CameraError


# ---------------------------------------------------------------------------
# Camera handling
# ---------------------------------------------------------------------------
class CameraStream:
    """Context-managed webcam with clear failure messages.

    A missing or busy camera is the most common first-run failure for
    an accessibility tool, so the error says what to check instead of
    surfacing an OpenCV status code.
    """

    def __init__(self, config: Config) -> None:
        check_dependencies()
        self._config = config
        self._cap = None

    def __enter__(self) -> "CameraStream":
        assert cv2 is not None
        cap = cv2.VideoCapture(self._config.camera_index)
        if not cap.isOpened():
            raise CameraError(
                f"Could not open webcam (index {self._config.camera_index}).\n"
                "Check that a camera is connected, that no other app is "
                "using it, and that this app has camera permission.\n"
                "Try another index, e.g.  vocaleyes --camera 1"
            )
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._config.frame_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._config.frame_height)
        self._cap = cap
        return self

    def __exit__(self, *exc_info) -> None:
        self.release()

    def release(self) -> None:
        """Release the camera. Safe to call more than once."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def read(self) -> np.ndarray:
        """Read one frame, or raise CameraError if the stream fails."""
        assert self._cap is not None
        ok, frame = self._cap.read()
        if not ok or frame is None:
            raise CameraError(
                "Webcam stopped returning frames. The camera may have "
                "been unplugged or taken over by another app."
            )
        return frame


# ---------------------------------------------------------------------------
# Background capture
# ---------------------------------------------------------------------------
class FramePump:
    """Background capture thread handing the loop one fresh frame.

    Face-mesh inference is slower than a webcam, so ``read()`` runs on a
    daemon thread of its own: the camera buffer is drained as fast as it
    fills, and the image on screen never falls seconds behind reality.

    Only the newest frame is kept. A queue would grow without bound
    whenever inference is slower than the camera, so latency would creep
    up without limit; a single slot bounds end-to-end latency to roughly
    one frame period, and :attr:`dropped` makes that trade-off visible
    instead of silent.
    """

    # How long the worker rests when the stream has nothing to give.
    # Waiting on the stop event (rather than sleeping) means stop() wakes
    # it at once; the timeout stops an idle stream from spinning a core.
    _NO_FRAME_WAIT = 0.01

    def __init__(self, stream: CameraStream,
                 max_age_seconds: float = 1.0) -> None:
        self._stream = stream
        # Withheld by latest(): once a frame is older than this it no
        # longer describes the present, and showing nothing tells the
        # caller more than a stale picture would.
        self._max_age_seconds = max_age_seconds
        # One lock guards the hand-off slot and the counters derived
        # from it, and is never held across stream.read(): capture must
        # not wait on a slow consumer, nor the consumer on a slow read.
        self._lock = threading.Lock()
        # An event rather than a bare flag: the worker waits on it when
        # there is nothing to read, so stop() both signals and wakes it.
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._frame: Optional[np.ndarray] = None
        self._frame_at: Optional[float] = None
        self._dropped = 0
        self._fps = 0.0
        # Set by the worker when read() fails; the main loop reads it to
        # surface the failure instead of hunting for a silent thread.
        self.error: Optional[CameraError] = None

    def start(self) -> None:
        """Start the worker thread; a second call while it runs does nothing."""
        # Idempotency matters: two workers would race on the same camera
        # and double every counter. The pump belongs to one caller (the
        # main loop), so this needs no lock. A pump that has been
        # stopped can be started again — the old thread simply fails the
        # is_alive() check below.
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="vocaleyes-frame-pump",
            daemon=True,  # a wedged camera must not block process exit
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the worker and join it; safe twice or before start()."""
        self._stop.set()
        thread = self._thread
        if thread is None:
            return  # never started (or already torn down): nothing to join
        # 1.5s is ample for one read() to return, yet short enough that
        # a wedged camera cannot hang shutdown; the thread is a daemon,
        # so anything still stuck dies with the process.
        thread.join(timeout=1.5)

    def __enter__(self) -> "FramePump":
        self.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self.stop()

    def latest(self) -> Optional[np.ndarray]:
        """Return the newest frame and consume it; None if none is new.

        Consuming is what keeps the loop honest: the next call returns
        None until a newer frame arrives, so no frame is ever processed
        twice and the work is always done on the freshest image. A frame
        older than ``max_age_seconds`` is withheld as well — past that
        age the picture misleads, and silence says more than it would.
        """
        with self._lock:
            frame, captured_at = self._frame, self._frame_at
            self._frame = None  # consume: the next call sees nothing
            if frame is None or captured_at is None:
                return None
            if time.monotonic() - captured_at > self._max_age_seconds:
                return None  # stale: withheld rather than shown
            # The reference is handed over as-is (the caller flips or
            # converts it): the worker replaces the slot instead of
            # writing into a published frame, so there is nothing to
            # copy against.
            return frame

    @property
    def dropped(self) -> int:
        """Frames discarded because a newer one arrived before they were read."""
        with self._lock:
            return self._dropped

    @property
    def fps(self) -> float:
        """Smoothed capture rate; 0.0 until two frames establish one."""
        with self._lock:
            return self._fps

    def _run(self) -> None:
        """Worker loop: read, publish, rest — until stopped or failing.

        Nothing here may propagate: a failure from ``read()`` is recorded
        on ``error`` and ends the loop, because an exception escaping
        would kill the thread silently and freeze the preview. The rest
        of the body is bookkeeping on the pump's own state.
        """
        while not self._stop.is_set():
            try:
                frame = self._stream.read()
            except CameraError as exc:
                # The expected failure: the camera vanished. Recorded for
                # the main loop instead of raised here, where nobody
                # would see the traceback.
                self.error = exc
