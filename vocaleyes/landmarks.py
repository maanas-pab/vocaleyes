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

# Full eyelid contours, drawn so the user (and a carer) can see exactly
# what is being tracked. Order follows the eyelid around the eye.
LEFT_EYE_CONTOUR = (
    33, 7, 163, 144, 145, 153, 154, 155, 133,
    173, 157, 158, 159, 160, 161, 246,
)
RIGHT_EYE_CONTOUR = (
    263, 249, 390, 373, 374, 380, 381, 382, 362,
    398, 384, 385, 386, 387, 388, 466,
)

# Iris landmarks (only present with refine_landmarks=True). Index 468 is
# the left iris centre and 473 the right iris centre.
LEFT_IRIS_CENTRE = 468
RIGHT_IRIS_CENTRE = 473
LEFT_IRIS_RING = (469, 470, 471, 472)
RIGHT_IRIS_RING = (474, 475, 476, 477)
