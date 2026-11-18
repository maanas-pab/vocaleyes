"""Session accounting — an honest report of what a run actually did.

A session with VocalEyes cannot easily be replayed to check it went
well, so when the app quits it says plainly what happened: how many
selections were made, how many ordinary blinks were correctly
ignored, how fast the loop actually ran, and whether the calibration
threshold had to drift. This module computes and formats those
numbers in memory — it never writes a file and never uploads
anything, the privacy stance of a tool that watches someone's eyes.

The single exception is :meth:`SessionStats.save`, the only method
here that touches the filesystem, and only when the user explicitly
asks for it by passing a path on the command line. Nothing in the
camera loop calls it: without that opt-in there is no I/O at all.
"""
from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from typing import Optional

from .smoothing import Ema


def _iso_utc(epoch: float) -> str:
    """UTC ISO-8601 with milliseconds and ``Z``, from epoch ``epoch``.

