"""Per-frame eye measurements for VocalEyes.

``EyeReading`` and ``FaceReading`` record what one eye, and then both
eyes, measured in a single frame; the caller supplies the landmark
indices, so these types stay independent of any particular face-mesh
layout. ``extract_eye_readings`` builds them from a MediaPipe landmark
list and combines the two ears for the detector downstream.
"""

from __future__ import annotations

from dataclasses import dataclass
