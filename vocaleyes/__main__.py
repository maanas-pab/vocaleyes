"""``python -m vocaleyes`` — the same entry point as the console script.

Kept separate from :mod:`vocaleyes.cli` so that importing the package
never parses arguments or configures logging.
"""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
