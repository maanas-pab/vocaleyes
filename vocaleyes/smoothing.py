"""Signal conditioning for the EAR stream: smoothing, medians, budgets.

The raw Eye Aspect Ratio is noisy — landmark jitter, one bad frame, a
cloud passing the window. Everything here turns a jittery per-frame
number into something a state machine can trust, and keeps an honest
account of where a frame's time went.

Nothing in this module knows about cameras, windows or blinks: it is
pure signal processing, so it can be reasoned about (and exercised)
without a webcam attached.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Dict, Iterator, Optional

