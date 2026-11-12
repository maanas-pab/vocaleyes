"""Logging setup — one console handler for the whole VocalEyes tree.

VocalEyes is an accessibility tool: a carer or a developer needs to
watch a session live while it runs. The privacy stance is "nothing is
saved or uploaded", so logging here is deliberately minimal — a single
stream handler on the local console, a verbosity choice, and an
optional JSON-lines format for machines. This module never writes logs
to disk itself: no file handlers, no rotation, no network.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Optional, TextIO

# Verbosity choices, keyed by the flag value the caller passes in.
# "quiet" still shows warnings and errors: with a tracker on someone's
# face, a silent failure is worse than a chatty one.
LEVELS = {
    "quiet": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
}

# Sentinel attribute stamped on handlers installed by configure(), so a
# repeated call can find and remove the previous one instead of
# stacking a second handler (which would print every line twice).
_HANDLER_MARKER = "_vocaleyes_installed"

# Human-readable default: time, level, which VocalEyes subsystem spoke.
# The short datefmt keeps the console dense during a live session.
_TEXT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


