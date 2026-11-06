"""Blink detection — the core accessibility state machine.

``BlinkDetector`` smooths the combined EAR, applies hysteresis, times
closures with a monotonic clock, fires at most once per closure, and
ignores short blinks entirely. Only a deliberate long hold selects.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from .config import Config


# ---------------------------------------------------------------------------
# Blink detection — the core accessibility state machine
# ---------------------------------------------------------------------------
