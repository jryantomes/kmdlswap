"""What the app remembers about how somebody likes to use it.

Kept apart from `installs.py`, which remembers where the *games* are. That is a
fact about the machine and is re-checked every launch; this is a choice the
person made and should survive being wrong.

One file, one flat dictionary. There is no schema and no migration: an
unreadable file, a missing key or a value that means nothing any more all fall
back to the default, because a preference is never worth failing to start over.
"""

from __future__ import annotations

import json
from pathlib import Path

PREFS = Path.home() / ".kmdlfun" / "prefs.json"

MODE = "mode"
BASIC = "basic"
ADVANCED = "advanced"
MODES = (BASIC, ADVANCED)


def load(path: Path | None = None) -> dict:
    try:
        found = json.loads((path or PREFS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def save(values: dict, path: Path | None = None) -> Path:
    path = path or PREFS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
    return path


def recall(key: str, default=None, path: Path | None = None):
    return load(path).get(key, default)


def remember(key: str, value, path: Path | None = None) -> Path:
    values = load(path)
    values[key] = value
    return save(values, path)


def mode(path: Path | None = None) -> str:
    """Basic unless somebody has said otherwise.

    New is the common case for the setting that exists to help newcomers, and
    the alternative - guessing that an existing config means an expert - is a
    trick that surprises the one person it guesses wrong about.
    """
    found = recall(MODE, BASIC, path)
    return found if found in MODES else BASIC
