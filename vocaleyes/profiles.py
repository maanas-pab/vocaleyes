"""Per-person profiles — settings that belong to a face, not a run.

Two people sharing one laptop do not share an eyelid. A profile holds
just the tunables that genuinely differ between people — threshold,
hold time, eye mode, smoothing, camera — under a name a carer can
recognise, and leaves everything else to :class:`~vocaleyes.config.Config`.

Profiles are plain JSON in a directory VocalEyes owns
(``~/.vocaleyes/profiles``, overridable with ``VOCALEYES_HOME``) so they
can be copied, backed up or edited by hand. A handful of *presets* ship
inside the package for common situations (ptosis, asymmetric closure,
glasses) and are read-only; anything the user saves lands beside them as
a profile.

Nothing here touches the network, and nothing is written unless the user
explicitly asks for a profile to be saved.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Dict, List, Optional

from .config import Config

PROFILE_SCHEMA = "vocaleyes.profile.v1"

# The subset of Config a person actually differs on. Kept deliberately
# short: every field added here is one more thing to get wrong during a
# setup visit, so new tunables default to the package and only join this
# list when someone genuinely needs them per person.
PROFILE_FIELDS = (
    "camera_index",
    "mirror",
    "ear_threshold",
    "long_blink_seconds",
    "cooldown_seconds",
    "eye_mode",
    "ear_smoothing",
    "calibrate_seconds",
)


class ProfileError(ValueError):
    """Raised for a profile that is missing, unreadable or nonsensical."""


@dataclass
class Profile:
    """A named bundle of per-person settings."""

    name: str = ""
    preset: str = ""
    why: str = ""
    camera_index: int = 0
    mirror: bool = True
    ear_threshold: float = 0.21
    long_blink_seconds: float = 1.0
    cooldown_seconds: float = 1.5
    eye_mode: str = "average"
    ear_smoothing: float = 0.35
    calibrate_seconds: float = 3.0

    def __post_init__(self) -> None:
        # Validate on the way in, not on the way out: a hand-edited JSON
        # file should fail at load time with a message naming the field,
        # not halfway through a session with the camera running.
        if not self.name:
            raise ProfileError("a profile needs a non-empty name")
        if not 0.05 <= self.ear_threshold <= 0.45:
            raise ProfileError(
                f"profile {self.name!r}: ear_threshold must be between "
                "0.05 and 0.45"
            )
        if self.long_blink_seconds <= 0:
            raise ProfileError(
                f"profile {self.name!r}: long_blink_seconds must be positive"
            )
        if self.cooldown_seconds < 0:
            raise ProfileError(
