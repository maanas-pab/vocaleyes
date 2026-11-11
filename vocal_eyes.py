#!/usr/bin/env python3
"""Project VocalEyes — long-blink selection for people with advanced ALS.

Historically this one file held the whole implementation. The code now
lives in the :mod:`vocaleyes` package, split by concern, and this module
remains only as a compatibility surface: the documented
``python vocal_eyes.py`` invocation and any ``from vocal_eyes import
Config, calculate_ear`` style imports keep working unchanged.
"""

from __future__ import annotations

