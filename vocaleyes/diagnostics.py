"""``vocaleyes doctor`` — say what is wrong, and what to do about it.

Project VocalEyes is run by carers, not programmers, and it fails at a
handful of predictable places: too old a Python, a library that was
never installed, a webcam another app has taken, settings out of range,
a session with nowhere to draw. Each becomes one :class:`Check` that
reports what was actually observed and — when it is wrong — the exact
command or setting that fixes it, because a stack trace tells a carer
nothing.

Everything here is standard library plus this package's own modules.
NumPy, OpenCV and MediaPipe are only touched inside the checks that
need them, and every probe is wrapped so an unexpected crash turns into
a FAIL line instead of an exception: the doctor has to keep talking on
the very machines it exists to diagnose.
"""

from __future__ import annotations

import glob
import os
import platform
import sys
from dataclasses import dataclass
