"""Overlay rendering — the part the user actually looks at.

This module owns every pixel drawn on screen: the eye contours, the
EAR bars and history trace, the hold-to-select ring, the confirmation
banner, and the calm guidance overlays. It contains no tracking logic;
it only draws what the detection and calibration layers hand to it.

Feedback here is deliberately large, calm, and unambiguous — no
flashing, no tiny text, and no reliance on sound.
"""
from __future__ import annotations

from collections import deque
from typing import Deque, Optional, Tuple

import numpy as np

from .calibration import EarCalibrator
from .config import Config
from .deps import cv2, mp
from .detection import BlinkDetector, BlinkState
from .geometry import Point, to_pixel
from .models import EyeReading, FaceReading
from .palette import Palette


# ---------------------------------------------------------------------------
# Overlay rendering — the part the user actually looks at
# ---------------------------------------------------------------------------
def _draw_filled_rounded_rect(
    frame: np.ndarray,
    top_left: Point,
    bottom_right: Point,
    radius: int,
    colour: Tuple[int, int, int],
    alpha: float = 0.72,
) -> None:
    """Draw a translucent filled panel with rounded corners, in place."""
    assert cv2 is not None
    overlay = frame.copy()
    x1, y1 = top_left
    x2, y2 = bottom_right
    radius = min(radius, (x2 - x1) // 2, (y2 - y1) // 2)
    cv2.rectangle(overlay, (x1 + radius, y1), (x2 - radius, y2), colour, -1)
    cv2.rectangle(overlay, (x1, y1 + radius), (x2, y2 - radius), colour, -1)
    for cx, cy in ((x1 + radius, y1 + radius), (x2 - radius, y1 + radius),
                   (x1 + radius, y2 - radius), (x2 - radius, y2 - radius)):
        cv2.circle(overlay, (cx, cy), radius, colour, -1)
    cv2.addWeighted(overlay, alpha, frame, 1.0 - alpha, 0, frame)


def _draw_rounded_outline(
    frame: np.ndarray,
    top_left: Point,
    bottom_right: Point,
    radius: int,
    colour: Tuple[int, int, int],
    thickness: int = 2,
) -> None:
    """Draw a rounded-corner outline (used for the eye boxes)."""
    assert cv2 is not None
    x1, y1 = top_left
    x2, y2 = bottom_right
    radius = min(radius, (x2 - x1) // 2, (y2 - y1) // 2)
    cv2.line(frame, (x1 + radius, y1), (x2 - radius, y1), colour, thickness,
             cv2.LINE_AA)
    cv2.line(frame, (x1 + radius, y2), (x2 - radius, y2), colour, thickness,
             cv2.LINE_AA)
    cv2.line(frame, (x1, y1 + radius), (x1, y2 - radius), colour, thickness,
             cv2.LINE_AA)
    cv2.line(frame, (x2, y1 + radius), (x2, y2 - radius), colour, thickness,
             cv2.LINE_AA)
    for centre, start, end in (
        ((x1 + radius, y1 + radius), 180, 270),
        ((x2 - radius, y1 + radius), 270, 360),
        ((x1 + radius, y2 - radius), 90, 180),
        ((x2 - radius, y2 - radius), 0, 90),
    ):
        cv2.ellipse(frame, centre, (radius, radius), 0, start, end,
                    colour, thickness, cv2.LINE_AA)


def _text_size(text: str, scale: float, thickness: int) -> Tuple[int, int]:
    assert cv2 is not None
    (w, h), _ = cv2.getTextSize(
        text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
    return w, h


def _draw_text(
    frame: np.ndarray,
    text: str,
    origin: Point,
    scale: float = 0.7,
    colour: Tuple[int, int, int] = Palette.WHITE,
    thickness: int = 2,
) -> None:
    """Anti-aliased text with a soft shadow, so it reads over any background."""
    assert cv2 is not None
    x, y = origin
    cv2.putText(frame, text, (x + 1, y + 1), cv2.FONT_HERSHEY_SIMPLEX,
                scale, (0, 0, 0), thickness + 1, cv2.LINE_AA)
    cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                scale, colour, thickness, cv2.LINE_AA)


class Visualizer:
    """Draws every on-screen element. No tracking logic lives here."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._ear_history: Deque[float] = deque(maxlen=90)

    def note_ear(self, ear: float) -> None:
        """Record an EAR sample for the history trace."""
        self._ear_history.append(ear)

    # -- main entry -------------------------------------------------------
    def draw(
        self,
        frame: np.ndarray,
        reading: Optional[FaceReading],
        detector: BlinkDetector,
        fps: float,
        face_found: bool,
        calibrator: EarCalibrator,
        selection_count: int,
        banner_until: float,
        now: float,
        show_mesh: bool,
        mesh_landmarks=None,
    ) -> np.ndarray:
        """Draw the full overlay onto ``frame`` and return it."""
        height, width = frame.shape[:2]
        if reading is not None:
            self._draw_eye(frame, reading.left, detector.is_closed, "LEFT")
            self._draw_eye(frame, reading.right, detector.is_closed, "RIGHT")
        if show_mesh and mesh_landmarks is not None:
            self._draw_mesh(frame, mesh_landmarks, width, height)
        self._draw_top_bar(frame, width, fps, face_found)
        self._draw_bottom_panel(frame, width, height, reading, detector,
                                selection_count)
        if reading is not None and detector.hold_progress > 0.0:
            self._draw_hold_ring(frame, reading, detector)
        if now < banner_until:
            self._draw_selection_banner(frame, width, height, now, banner_until)
        if calibrator.active:
            self._draw_calibration_overlay(frame, width, height, calibrator)
        elif not face_found:
            self._draw_no_face_overlay(frame, width, height)
        return frame

    # -- eyes -------------------------------------------------------------
    def _draw_eye(
        self, frame: np.ndarray, eye: EyeReading, closed: bool, label: str,
    ) -> None:
        assert cv2 is not None
        colour = Palette.EYE_CLOSED if closed else Palette.EYE_OPEN
        # Eyelid contour — a closed loop so closure is visible at a glance.
        pts = np.array(eye.contour, dtype=np.int32).reshape((-1, 1, 2))
        cv2.polylines(frame, [pts], isClosed=True, color=colour,
                      thickness=2, lineType=cv2.LINE_AA)
        # Landmark dots on the contour.
        for point in eye.contour:
            cv2.circle(frame, point, 2, Palette.WHITE, -1, cv2.LINE_AA)
        # Iris: soft glow ring + centre dot. The ring makes gaze/iris
        # position readable even on a small preview.
        cv2.circle(frame, eye.iris_centre, 9, colour, 1, cv2.LINE_AA)
        cv2.circle(frame, eye.iris_centre, 3, Palette.WHITE, -1, cv2.LINE_AA)
        for point in eye.iris_ring:
            cv2.circle(frame, point, 2, colour, -1, cv2.LINE_AA)
        # Rounded bounding box around the whole eye.
        x, y, w, h = eye.bbox
        _draw_rounded_outline(frame, (x, y), (x + w, y + h), 10, colour, 2)
        # Small label pill above the box with the live EAR.
        pill_w, pill_h = 118, 26
        pill_x = max(4, min(frame.shape[1] - pill_w - 4, x))
        pill_y = max(4, y - pill_h - 6)
        _draw_filled_rounded_rect(
            frame, (pill_x, pill_y), (pill_x + pill_w, pill_y + pill_h),
            13, Palette.DARK, alpha=0.78)
        _draw_text(frame, f"{label}  {eye.ear:.2f}", (pill_x + 10, pill_y + 18),
                   scale=0.5, colour=Palette.SOFT_WHITE, thickness=1)

