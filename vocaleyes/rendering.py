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

