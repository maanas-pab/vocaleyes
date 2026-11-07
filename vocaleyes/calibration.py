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
