"""Copying built models into the game's Override folder, reversibly.

The brief's rule is that the tools never write into the game install; output goes
to a directory and the user installs it. This module is the user doing that,
triggered from the GUI, which is a different thing from a build silently
modifying a game.

Two safeguards, because Override is where a person's other mods live:

* **Nothing we did not put there is overwritten without being told.** Files are
  tracked in a manifest, so a name that already exists and is not ours is
  reported before anything is copied.
* **Removal only removes what we installed.** It reads the manifest rather than
  deleting by pattern, so a hand-installed `p_hkrfk.mdl` sitting next to our
  `p_hk47.mdl` is never touched.

Vanilla models live in the game's BIF archives, so removing an installed file
restores the original - there is nothing to back up.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

MANIFEST = ".kmdlfun_installed.json"
# `.2da` is how the game learns a new model exists. It is also the one
# extension here that a build *shares* with other mods, so installing one is
# the case the foreign-file guard exists for.
#
# `.lip` and `.dlg` come as a pair from the lips job and are no use apart: the
# lips are named after `VO_ResRef`s that only exist in the updated dialogue.
# A `.dlg` is the most likely thing here to already be somebody's, which is
# again what the foreign-file guard is for - it will not be replaced silently.
INSTALLABLE = {".mdl", ".mdx", ".tga", ".tpc", ".txi", ".2da", ".lip", ".dlg"}


@dataclass
class Plan:
    """What installing would do, worked out before anything is copied."""

    override: Path
    new: list[Path] = field(default_factory=list)
    ours: list[Path] = field(default_factory=list)
    foreign: list[Path] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.new) + len(self.ours) + len(self.foreign)

    def describe(self) -> str:
        bits = []
        if self.new:
            bits.append(f"{len(self.new)} new")
        if self.ours:
            bits.append(f"{len(self.ours)} replacing our own")
        if self.foreign:
            bits.append(f"{len(self.foreign)} OVERWRITING FILES WE DID NOT INSTALL")
        return ", ".join(bits) or "nothing to install"


def override_dir(install: str | Path) -> Path:
    return Path(install) / "Override"


def _manifest_path(install: str | Path) -> Path:
    return override_dir(install) / MANIFEST


def read_manifest(install: str | Path) -> set[str]:
    p = _manifest_path(install)
    if not p.is_file():
        return set()
    try:
        return set(json.loads(p.read_text(encoding="utf-8")).get("files", []))
    except (ValueError, OSError):
        return set()


def write_manifest(install: str | Path, names: set[str]) -> None:
    p = _manifest_path(install)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"files": sorted(names)}, indent=1), encoding="utf-8")


def collect(source: str | Path) -> list[Path]:
    """Installable files in a build folder, including one level of subfolders."""
    src = Path(source)
    if not src.is_dir():
        return []
    found = [p for p in src.iterdir() if p.is_file() and p.suffix.lower() in INSTALLABLE]
    if not found:
        for child in sorted(p for p in src.iterdir() if p.is_dir()):
            found.extend(
                p for p in child.iterdir()
                if p.is_file() and p.suffix.lower() in INSTALLABLE
            )
    return sorted(found)


def plan(install: str | Path, source: str | Path) -> Plan:
    out = Plan(override=override_dir(install))
    known = read_manifest(install)
    for f in collect(source):
        target = out.override / f.name
        if not target.exists():
            out.new.append(f)
        elif f.name in known:
            out.ours.append(f)
        else:
            out.foreign.append(f)
    return out


def apply(install: str | Path, source: str | Path, *, allow_foreign: bool = False) -> list[str]:
    """Copy the build into Override. Returns the names installed."""
    p = plan(install, source)
    if p.foreign and not allow_foreign:
        raise PermissionError(
            "would overwrite files this tool did not install: "
            + ", ".join(f.name for f in p.foreign)
        )
    p.override.mkdir(parents=True, exist_ok=True)
    installed = []
    for f in p.new + p.ours + (p.foreign if allow_foreign else []):
        shutil.copy2(f, p.override / f.name)
        installed.append(f.name)
    write_manifest(install, read_manifest(install) | set(installed))
    return installed


def remove(install: str | Path) -> list[str]:
    """Remove only what we installed. Vanilla comes back from the BIFs."""
    override = override_dir(install)
    removed = []
    for name in sorted(read_manifest(install)):
        target = override / name
        if target.is_file():
            target.unlink()
            removed.append(name)
    write_manifest(install, set())
    if not read_manifest(install):
        mp = _manifest_path(install)
        if mp.is_file():
            mp.unlink()
    return removed
