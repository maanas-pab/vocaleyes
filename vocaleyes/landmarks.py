"""Landmark indices (MediaPipe Face Mesh, 468 landmarks + refined iris).

Every index VocalEyes depends on lives here, in one table, with the
reason it exists. Changing a webcam or a MediaPipe version never means
touching detection code — it means re-checking these numbers.
"""

from __future__ import annotations

# Six-point EAR landmarks per eye: (outer, upper, upper, inner, lower,
# lower). These are the canonical Soukupova / Cech indices for Face Mesh.
LEFT_EYE_EAR = (33, 160, 158, 133, 153, 144)
RIGHT_EYE_EAR = (362, 385, 387, 263, 373, 380)

