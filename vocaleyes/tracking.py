"""Face Mesh wrapper for Project VocalEyes.

A thin, safe wrapper around ``mp.solutions.face_mesh``: entered as a
context manager, it returns the first face's landmarks per frame and
always closes the underlying model, even if the camera loop exits on
an error.
"""
from __future__ import annotations

import numpy as np

from .config import Config
from .deps import check_dependencies, mp

