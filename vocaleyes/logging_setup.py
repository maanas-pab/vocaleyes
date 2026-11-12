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


# ---------------------------------------------------------------------------
# JSON formatting
# ---------------------------------------------------------------------------
def _iso_utc(created: float) -> str:
    """UTC ISO-8601 with milliseconds and ``Z``, from epoch ``created``.

    Built from the record's own timestamp rather than "now", so the
    line says when the event happened even if it is formatted later.
    """
    instant = datetime.fromtimestamp(created, tz=timezone.utc)
    millis = instant.microsecond // 1000
    return f"{instant.strftime('%Y-%m-%dT%H:%M:%S')}.{millis:03d}Z"


def _safe_message(record: logging.LogRecord) -> str:
    """``record.getMessage()`` with fallbacks: never raise from format().

    A broken %-style argument pair should cost one odd line, never the
    camera loop or the console.
    """
    try:
        return record.getMessage()
    except Exception:
        pass
    try:
        return str(record.msg)
    except Exception:
        return "<unprintable log message>"


class JsonFormatter(logging.Formatter):
    """One compact JSON object per line, for the local console only.

    Project VocalEyes is an accessibility tool whose privacy stance is
    "nothing is saved or uploaded": JSON logging exists so a carer or
    developer can watch a session from the console (``jq``-friendly),
    not so logs get collected somewhere. VocalEyes never writes logs
    to disk itself.

    Each line carries ``ts`` (UTC, from the record's own time),
    ``level``, ``logger`` and ``msg``, plus ``exc`` only when the
    record carries a traceback.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": _iso_utc(record.created),
            "level": record.levelname,
            "logger": record.name,
            "msg": _safe_message(record),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # ensure_ascii=False keeps non-ASCII messages (names, UI text)
        # readable while staying valid JSON.
        return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def configure(level: str = "info", json_logs: bool = False,
              stream: Optional[TextIO] = None) -> None:
    """Configure logging for the ``vocaleyes`` logger tree.

    Only ``logging.getLogger("vocaleyes")`` and its children are
    touched, so third-party noise (cv2, mediapipe) keeps its own
    behaviour and is never doubled up. ``propagate`` is turned off so
    the root handler cannot print our lines a second time.

    Repeated calls replace the handler installed by the previous call;
    they never stack duplicates. An unknown ``level`` raises
    ``ValueError`` naming the valid choices.
    """
    if level not in LEVELS:
        valid = ", ".join(sorted(LEVELS))
        raise ValueError(
            f"unknown log level {level!r}; valid choices: {valid}"
        )

