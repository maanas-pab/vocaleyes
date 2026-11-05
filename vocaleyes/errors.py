"""The two failure modes worth naming: no camera, and no dependencies.

An accessibility tool fails at exactly two interesting points: the thing
it watches (the webcam) is not there, or the thing it needs to see with
(OpenCV / MediaPipe) is not installed. Both raise a specific exception
with an actionable message rather than a bare stack trace, because the
person running this may be a carer, not a programmer.
"""

from __future__ import annotations


class CameraError(RuntimeError):
    """Raised when no usable webcam can be opened or frames stop coming."""


class DependencyError(RuntimeError):
    """Raised when OpenCV / MediaPipe are not installed."""
