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
    GREEN = (94, 197, 34)       # #22C55E — selection confirmed
    AMBER = (11, 158, 245)      # #F59E0B — holding / closing
    RED = (68, 68, 239)         # #EF4444 — eyes closed / no face
    GREY_TRACK = (90, 90, 96)
    EYE_OPEN = (191, 212, 45)
    EYE_CLOSED = (11, 158, 245)
