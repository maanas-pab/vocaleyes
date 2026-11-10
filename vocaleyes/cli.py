"""Command-line interface — wires config -> camera -> tracker -> detector -> renderer.

``parse_args`` turns flags into an ``argparse.Namespace`` for
:class:`Config`. ``main`` runs VocalEyes until the user quits: it wires
config -> camera -> tracker -> detector -> renderer, then loops on frames
— calibration, key handling, FPS smoothing, and a clean window-close
check — returning a process exit code.
"""
from __future__ import annotations

import argparse
import logging
import sys
