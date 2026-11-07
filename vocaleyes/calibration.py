"""Per-person calibration for Project VocalEyes.

Measures open-eye EAR with the user simply looking at the screen, then
sets a threshold well below their typical open value — no button press
or gaze target required.
"""
from __future__ import annotations

import time
from typing import Optional


# ---------------------------------------------------------------------------
# Per-person calibration
# ---------------------------------------------------------------------------
class EarCalibrator:
    """Measure open-eye EAR, then set a threshold from the person.

    The user simply looks at the screen with eyes open and relaxed.
    The threshold is set well below their typical open EAR, so normal
    variation never starts a hold, while a real closure still crosses
    it quickly. No button press or gaze target is required.
    """

