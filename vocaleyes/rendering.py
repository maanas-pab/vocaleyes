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

    def _draw_mesh(
        self, frame: np.ndarray, landmarks, width: int, height: int,
    ) -> None:
        """Optional faint full-face mesh (debug / setup aid)."""
        assert cv2 is not None and mp is not None
        connections = mp.solutions.face_mesh.FACEMESH_TESSELLATION
        for start_idx, end_idx in connections:
            a = to_pixel(landmarks[start_idx], width, height)
            b = to_pixel(landmarks[end_idx], width, height)
            cv2.line(frame, a, b, (70, 70, 78), 1, cv2.LINE_AA)

    # -- chrome -----------------------------------------------------------
    def _draw_top_bar(
        self, frame: np.ndarray, width: int, fps: float, face_found: bool,
    ) -> None:
        _draw_filled_rounded_rect(
            frame, (0, 0), (width, 54), 0, Palette.PANEL, alpha=0.62)
        dot_colour = Palette.TEAL if face_found else Palette.RED
        cv2.circle(frame, (26, 27), 7, dot_colour, -1, cv2.LINE_AA)
        _draw_text(frame, "VOCALEYES", (44, 35), scale=0.75,
                   colour=Palette.WHITE, thickness=2)
        _draw_text(frame, "Long-blink select", (190, 34), scale=0.55,
                   colour=Palette.MUTED, thickness=1)
        status = "Face locked" if face_found else "Searching for face..."
        status_colour = Palette.TEAL if face_found else Palette.AMBER
        sw, _ = _text_size(status, 0.55, 1)
        _draw_text(frame, status, (width - sw - 118, 34), scale=0.55,
                   colour=status_colour, thickness=1)
        fps_text = f"{fps:.0f} fps"
        fw, _ = _text_size(fps_text, 0.55, 1)
        _draw_text(frame, fps_text, (width - fw - 18, 34), scale=0.55,
                   colour=Palette.MUTED, thickness=1)

    def _draw_bottom_panel(
        self, frame: np.ndarray, width: int, height: int,
        reading: Optional[FaceReading], detector: BlinkDetector,
        selection_count: int,
    ) -> None:
        panel_h = 128
        y0 = height - panel_h
        _draw_filled_rounded_rect(
            frame, (0, y0), (width, height), 0, Palette.PANEL, alpha=0.78)
        cv2.line(frame, (0, y0), (width, y0), (60, 60, 66), 1, cv2.LINE_AA)

        # Left: per-eye EAR bars with the threshold marker.
        _draw_text(frame, "EYE ASPECT RATIO  (open ~0.30  /  closed ~0.05)",
                   (20, y0 + 26), scale=0.5, colour=Palette.MUTED, thickness=1)
        if reading is not None:
            self._draw_ear_bar(frame, 20, y0 + 40, "L", reading.left.ear,
                               detector.close_threshold)
            self._draw_ear_bar(frame, 20, y0 + 74, "R", reading.right.ear,
                               detector.close_threshold)
            combined = detector.smoothed_ear
            if combined is not None:
                _draw_text(frame, f"Combined  {combined:.2f}",
                           (20, y0 + 108), scale=0.55,
                           colour=Palette.SOFT_WHITE, thickness=1)
        else:
            _draw_text(frame, "No eye data — position your face in frame.",
                       (20, y0 + 62), scale=0.55, colour=Palette.AMBER,
                       thickness=1)

        # Centre: EAR history trace.
        trace_x0, trace_x1 = 330, width - 300
        trace_y0, trace_y1 = y0 + 30, y0 + 104
        self._draw_ear_trace(frame, trace_x0, trace_y0, trace_x1, trace_y1,
                             detector.close_threshold)

        # Right: status + counts, in large type.
        if detector.state is BlinkState.TRIGGERED:
            status, colour = "SELECTED", Palette.GREEN
        elif detector.is_closed:
            status, colour = "HOLDING...", Palette.AMBER
        elif detector.state is BlinkState.COOLDOWN:
            status, colour = "READY SOON", Palette.MUTED
        else:
            status, colour = "READY", Palette.TEAL
        _draw_text(frame, status, (width - 280, y0 + 48), scale=0.9,
                   colour=colour, thickness=2)
        _draw_text(
            frame,
            f"Selections: {selection_count}   "
            f"Hold: {detector.long_blink_seconds:.1f}s   "
            f"Threshold: {detector.close_threshold:.2f}",
            (width - 280, y0 + 78), scale=0.5, colour=Palette.MUTED,
            thickness=1)
        _draw_text(frame, "Q quit  |  C calibrate  |  M mesh  |  R reset",
                   (width - 280, y0 + 106), scale=0.5, colour=Palette.MUTED,
                   thickness=1)

    def _draw_ear_bar(
        self, frame: np.ndarray, x: int, y: int, label: str,
        ear: float, threshold: float,
    ) -> None:
        bar_w, bar_h = 240, 14
        _draw_text(frame, label, (x, y + 12), scale=0.55,
                   colour=Palette.SOFT_WHITE, thickness=1)
        bx = x + 22
        _draw_filled_rounded_rect(frame, (bx, y), (bx + bar_w, y + bar_h),
                                  7, Palette.GREY_TRACK, alpha=0.9)
        fill_w = int(bar_w * min(1.0, max(0.0, ear / 0.45)))
        fill_colour = (Palette.TEAL if ear >= threshold else Palette.AMBER)
        if fill_w > 0:
            _draw_filled_rounded_rect(
                frame, (bx, y), (bx + fill_w, y + bar_h), 7,
                fill_colour, alpha=0.95)
        # Threshold tick.
        tick_x = bx + int(bar_w * (threshold / 0.45))
        cv2.line(frame, (tick_x, y - 3), (tick_x, y + bar_h + 3),
                 Palette.WHITE, 2, cv2.LINE_AA)
        _draw_text(frame, f"{ear:.2f}", (bx + bar_w + 10, y + 12),
                   scale=0.55, colour=Palette.SOFT_WHITE, thickness=1)

    def _draw_ear_trace(
        self, frame: np.ndarray, x0: int, y0: int, x1: int, y1: int,
        threshold: float,
    ) -> None:
        """Sparkline of recent EAR, with the close threshold as a line."""
        assert cv2 is not None
        _draw_text(frame, "EAR HISTORY", (x0, y0 - 6), scale=0.5,
                   colour=Palette.MUTED, thickness=1)
        cv2.rectangle(frame, (x0, y0), (x1, y1), (60, 60, 66), 1, cv2.LINE_AA)
        # Threshold line: EAR below this line means "closed".
        thresh_y = y1 - int((threshold / 0.45) * (y1 - y0))
        cv2.line(frame, (x0, thresh_y), (x1, thresh_y), Palette.AMBER, 1,
                 cv2.LINE_AA)
        if len(self._ear_history) < 2:
            return
        span = max(1, x1 - x0)
        step = span / 89.0
        points = []
        for i, ear in enumerate(self._ear_history):
            px = int(x0 + i * step)
            py = y1 - int(min(1.0, max(0.0, ear / 0.45)) * (y1 - y0))
            points.append((px, py))
        cv2.polylines(frame, [np.array(points, dtype=np.int32)], False,
                      Palette.TEAL, 2, cv2.LINE_AA)

    def _draw_hold_ring(
        self, frame: np.ndarray, reading: FaceReading, detector: BlinkDetector,
    ) -> None:
        """Large progress ring between the eyes: the hold, made visible."""
        assert cv2 is not None
        centre = (
            (reading.left.centre[0] + reading.right.centre[0]) // 2,
            (reading.left.centre[1] + reading.right.centre[1]) // 2,
        )
        radius, thickness = 62, 10
        progress = detector.hold_progress
        cv2.circle(frame, centre, radius, Palette.GREY_TRACK, thickness,
                   cv2.LINE_AA)
        if progress > 0.0:
            end_angle = -90 + int(360 * progress)
            colour = Palette.AMBER if progress < 1.0 else Palette.GREEN
            cv2.ellipse(frame, centre, (radius, radius), 0, -90, end_angle,
                        colour, thickness, cv2.LINE_AA)
        percent = f"{int(progress * 100)}%"
        pw, _ = _text_size(percent, 0.7, 2)
        _draw_text(frame, percent, (centre[0] - pw // 2, centre[1] + 8),
                   scale=0.7, colour=Palette.WHITE, thickness=2)
        label = "HOLD TO SELECT" if progress < 1.0 else "SELECTED"
        lw, _ = _text_size(label, 0.45, 1)
        _draw_text(frame, label, (centre[0] - lw // 2, centre[1] + radius + 26),
                   scale=0.45, colour=Palette.SOFT_WHITE, thickness=1)

    def _draw_selection_banner(
        self, frame: np.ndarray, width: int, height: int,
        now: float, banner_until: float,
    ) -> None:
        """Full-width confirmation banner. Drawn, not flashed."""
        assert cv2 is not None
        remaining = max(0.0, banner_until - now)
        alpha = min(0.92, 0.35 + remaining * 0.4)
        bw, bh = 560, 96
        x0, y0 = (width - bw) // 2, (height - bh) // 2 - 110
        _draw_filled_rounded_rect(frame, (x0, y0), (x0 + bw, y0 + bh), 20,
                                  (24, 88, 38), alpha=alpha)
        cv2.rectangle(frame, (x0, y0), (x0 + bw, y0 + bh), Palette.GREEN, 2,
                      cv2.LINE_AA)
        # Checkmark, drawn as two strokes (Hershey fonts have no tick).
        cx, cy = x0 + 52, y0 + bh // 2
        cv2.line(frame, (cx - 16, cy + 2), (cx - 4, cy + 14), Palette.WHITE,
                 4, cv2.LINE_AA)
        cv2.line(frame, (cx - 4, cy + 14), (cx + 20, cy - 14), Palette.WHITE,
                 4, cv2.LINE_AA)
        _draw_text(frame, "SELECTED", (x0 + 88, y0 + 44), scale=1.0,
                   colour=Palette.WHITE, thickness=2)
        _draw_text(frame, "Long blink confirmed", (x0 + 88, y0 + 74),
                   scale=0.55, colour=Palette.SOFT_WHITE, thickness=1)

    def _draw_no_face_overlay(
        self, frame: np.ndarray, width: int, height: int,
    ) -> None:
        """Calm, large guidance when no face is tracked. Never a guess."""
        _draw_filled_rounded_rect(
            frame, (0, 60), (width, 130), 0, Palette.DARK, alpha=0.45)
        message = "No face detected — please move into frame"
        mw, _ = _text_size(message, 0.8, 2)
        _draw_text(frame, message, ((width - mw) // 2, 108), scale=0.8,
                   colour=Palette.WHITE, thickness=2)

    def _draw_calibration_overlay(
        self, frame: np.ndarray, width: int, height: int,
        calibrator: EarCalibrator,
    ) -> None:
        """Large calibration prompt: eyes open, nothing else to do."""
        _draw_filled_rounded_rect(
            frame, (0, 60), (width, 150), 0, Palette.DARK, alpha=0.55)
        message = "Calibrating — keep your eyes open and relaxed"
        mw, _ = _text_size(message, 0.8, 2)
        _draw_text(frame, message, ((width - mw) // 2, 104), scale=0.8,
                   colour=Palette.WHITE, thickness=2)
        bar_w, bar_h = 420, 12
        bx, by = (width - bar_w) // 2, 122
        _draw_filled_rounded_rect(frame, (bx, by), (bx + bar_w, by + bar_h),
                                  6, Palette.GREY_TRACK, alpha=0.9)
        fill_w = int(bar_w * calibrator.progress)
        if fill_w > 0:
            _draw_filled_rounded_rect(
                frame, (bx, by), (bx + fill_w, by + bar_h), 6,
                Palette.TEAL, alpha=0.95)
