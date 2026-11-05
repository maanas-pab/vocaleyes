"""Tunable behaviour for VocalEyes.

``Config`` holds every adjustable value the tracker uses — camera
setup, blink timing, thresholds, smoothing, and on-screen feedback —
in one dataclass whose defaults are safe for a first run. It is meant
to be tuned once per person during setup and then left alone, rather
than adjusted on each run.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass


@dataclass
class Config:
    """All tunable behaviour for VocalEyes. Tune per person, not per run."""

    camera_index: int = 0
    frame_width: int = 1280
    frame_height: int = 720
    mirror: bool = True
    # EAR below this starts the hold timer. Calibrate per person: eyelid
    # laxity, ptosis, glasses, and lighting all move a person's open EAR.
    ear_threshold: float = 0.21
    # Hold time that counts as deliberate. 1.0 s is long enough to
    # exclude ordinary blinks, short enough not to tire the user.
    long_blink_seconds: float = 1.0
    # Quiet period after a selection. Prevents one long closure from
    # firing twice and gives the user time to reopen their eyes.
    cooldown_seconds: float = 1.5
    # How the two eyes combine. "average" is the safe default; use
    # "min" only for markedly asymmetric closure (one eyelid closes
    # much less than the other), as it is more sensitive to winks.
