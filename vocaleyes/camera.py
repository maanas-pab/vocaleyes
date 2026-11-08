"""Camera handling for Project VocalEyes.

A context-managed webcam that fails with clear, actionable messages,
because a missing or busy camera is the most common first-run failure
for an accessibility tool.
"""
from __future__ import annotations

import numpy as np

from .config import Config
from .deps import check_dependencies, cv2
