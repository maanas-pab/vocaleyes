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
                f"profile {self.name!r}: cooldown_seconds must not be negative"
            )
        if self.eye_mode not in ("average", "min"):
            raise ProfileError(
                f"profile {self.name!r}: eye_mode must be "
                '"average" or "min"'
            )
        if not 0.0 < self.ear_smoothing <= 1.0:
            raise ProfileError(
                f"profile {self.name!r}: ear_smoothing must be in (0, 1]"
            )

    # -- conversion ------------------------------------------------------
    @classmethod
    def from_dict(cls, data: Dict) -> "Profile":
        """Build a profile from parsed JSON, ignoring unknown keys.

        Unknown keys are ignored rather than rejected so that a profile
        written by a newer VocalEyes still loads here, and so a carer can
        add their own notes without breaking anything.
        """
        if not isinstance(data, dict):
            raise ProfileError("a profile must be a JSON object")
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in known}
        try:
            return cls(**kwargs)
        except TypeError as exc:
            raise ProfileError(f"profile has a field of the wrong type: {exc}")
        except ValueError as exc:
            raise ProfileError(str(exc))

    def to_dict(self) -> Dict:
        data = asdict(self)
        data["schema"] = PROFILE_SCHEMA
        return data

    # -- application -----------------------------------------------------
    def apply(self, config: Config) -> Config:
        """Return ``config`` with this profile's fields overlaid."""
        merged = asdict(config)
        for name in PROFILE_FIELDS:
            merged[name] = getattr(self, name)
        return Config(**merged)


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------
def home() -> Path:
    """The directory VocalEyes keeps user data in.

    ``VOCALEYES_HOME`` exists so a carer can point at a USB stick or a
    synced folder without hunting through the home directory.
    """
    override = os.environ.get("VOCALEYES_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".vocaleyes"


def profiles_dir() -> Path:
    """Where user profiles live (created on first save)."""
    return home() / "profiles"


def presets_dir() -> Path:
    """Where the read-only presets shipped with the package live."""
    return Path(__file__).resolve().parent / "presets"


# ---------------------------------------------------------------------------
# Reading and writing
# ---------------------------------------------------------------------------
def _load_path(path: Path) -> Profile:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProfileError(f"cannot read {path}: {exc}")
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ProfileError(f"{path} is not valid JSON: {exc}")
    return Profile.from_dict(data)


def load(name: str, *, preset: bool = False) -> Profile:
    """Load a profile (or preset) by name.

    Raises :class:`ProfileError` naming the places that were looked at,
    because "no such profile" is only useful if it says where it looked.
    """
    directory = presets_dir() if preset else profiles_dir()
    path = directory / f"{name}.json"
    if not path.is_file():
        other = profiles_dir() if preset else presets_dir()
        raise ProfileError(
            f"no {'preset' if preset else 'profile'} named {name!r} "
            f"(looked in {directory}"
            + (f" and {other})" if not preset else ")")
        )
    return _load_path(path)


def save(profile: Profile) -> Path:
    """Write a profile to disk and return its path.

    This is the only function in the module that writes anything, and it
    is only ever reached because the user asked to save a profile.
    """
    directory = profiles_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{profile.name}.json"
    path.write_text(
        json.dumps(profile.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def delete(name: str) -> bool:
    """Remove a user profile. Returns False when it was not there."""
    path = profiles_dir() / f"{name}.json"
    if not path.is_file():
        return False
    path.unlink()
    return True


def snapshot(name: str, config: Config, *, why: str = "",
             preset: str = "") -> Profile:
    """Capture the current settings as a reusable profile."""
    kwargs = {f: getattr(config, f) for f in PROFILE_FIELDS}
    return Profile(name=name, preset=preset, why=why, **kwargs)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
def _names(directory: Path) -> List[str]:
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.json"))


def list_profiles() -> List[str]:
    """Names of the user's saved profiles, alphabetically."""
    return _names(profiles_dir())


