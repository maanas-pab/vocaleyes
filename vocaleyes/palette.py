"""Visual palette (BGR, as OpenCV expects) — calm, high-contrast, no neon.

One place to restyle the whole overlay. The colours are deliberately
unexciting: teal means open/ready, amber means holding, green means
confirmed, red means the face is gone. Nothing flashes.
"""

from __future__ import annotations


class Palette:
    """Named colours for the overlay. One place to restyle the UI."""

    WHITE = (255, 255, 255)
    SOFT_WHITE = (235, 235, 235)
    MUTED = (190, 190, 190)
    DARK = (24, 24, 28)
    PANEL = (18, 18, 22)
    TEAL = (191, 212, 45)       # #2DD4BF — eyes open / ready
