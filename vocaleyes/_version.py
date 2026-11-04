"""Single source of truth for the VocalEyes version.

Kept in its own tiny module so both the package root (``vocaleyes``) and
the command-line entry point can read it without importing each other
and creating an import cycle.
"""

from __future__ import annotations

__version__ = "1.0.0"
