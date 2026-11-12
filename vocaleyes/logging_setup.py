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
