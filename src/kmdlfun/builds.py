"""Builds as named, kept folders rather than files overwriting each other.

Everything used to land in one output directory as `p_carthh.mdl`, so each
build destroyed the last. You could not keep two heads side by side, go back to
one that worked, or answer "what is this file?" a day later - which came up
constantly, because the interesting comparison is almost always between two
builds rather than between a build and vanilla.

A build is a folder with its models, its textures, and a `build.json` saying
what it is:

    out_fun/
      p_carthh-n_quarren/
        p_carthh.mdl
        p_carthh.mdx
        N_QuarrenH01.tpc
        build.json

The manifest exists so a good result can be reproduced or handed to somebody
else. It records what went in - host, donor, which game each came from, every
option - and what came out, with a hash per file so a folder can be checked
against its own description.

Installing points at one of these folders, so "install the Quarren one" is a
thing you can actually say.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

MANIFEST = "build.json"


@dataclass
class Build:
    """One folder on disk, and what it says about itself."""

    path: Path
    manifest: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return str(self.manifest.get("name") or self.path.name)

    @property
    def created(self) -> str:
        return str(self.manifest.get("created", ""))

    @property
    def models(self) -> list[str]:
        return sorted(p.name for p in self.path.glob("*.mdl"))

    @property
    def summary(self) -> str:
        m = self.manifest
        host = (m.get("host") or {}).get("model", "?")
        donor = (m.get("donor") or {}).get("model")
        what = f"{host} <- {donor}" if donor else host
        games = {(m.get("host") or {}).get("game"), (m.get("donor") or {}).get("game")}
        games.discard(None)
        cross = "  (K2 donor)" if len(games) > 1 else ""
        when = self.created[:16].replace("T", " ")
        return f"{self.name:<34} {what:<26}{cross}  {when}"

    def check(self) -> list[str]:
        """Has anything in the folder changed since it was written?"""
        out = []
        for entry in self.manifest.get("files", []):
            p = self.path / entry["name"]
            if not p.is_file():
                out.append(f"{entry['name']} is missing")
            elif _digest(p.read_bytes()) != entry.get("md5"):
                out.append(f"{entry['name']} has changed since the build")
        return out


def _digest(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def slug(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(text)).strip("-")
    return cleaned[:60] or "build"


def unique_name(root: str | Path, wanted: str) -> str:
    """A folder name not already taken, without silently clobbering one.

    Overwriting is the behaviour being replaced, so a repeated build gets a
    numbered sibling rather than eating its predecessor.
    """
    root = Path(root)
    base = slug(wanted)
    if not (root / base).exists():
        return base
    n = 2
    while (root / f"{base}-{n}").exists():
        n += 1
    return f"{base}-{n}"


def save(root: str | Path, name: str, files: dict[str, bytes], manifest: dict) -> Build:
    """Write a build folder. `files` maps filename to bytes."""
    root = Path(root)
    folder = root / slug(name)
    folder.mkdir(parents=True, exist_ok=True)

    written = []
    for filename, data in sorted(files.items()):
        (folder / filename).write_bytes(data)
        written.append({"name": filename, "bytes": len(data), "md5": _digest(data)})

    full = dict(manifest)
    full.setdefault("name", folder.name)
    full.setdefault("created", datetime.now().isoformat(timespec="seconds"))
    full["files"] = written
    (folder / MANIFEST).write_text(json.dumps(full, indent=2) + "\n", encoding="utf-8")
    return Build(folder, full)


def adopt(folder: str | Path, manifest: dict) -> Build:
    """Describe a folder whose files are already written."""
    folder = Path(folder)
    written = [
        {"name": p.name, "bytes": p.stat().st_size, "md5": _digest(p.read_bytes())}
        for p in sorted(folder.iterdir())
        if p.is_file() and p.name != MANIFEST
    ]
    full = dict(manifest)
    full.setdefault("name", folder.name)
    full.setdefault("created", datetime.now().isoformat(timespec="seconds"))
    full["files"] = written
    (folder / MANIFEST).write_text(json.dumps(full, indent=2) + "\n", encoding="utf-8")
    return Build(folder, full)


def load(folder: str | Path) -> Build | None:
    """Read one build folder, or None if it is not one."""
    folder = Path(folder)
    if not folder.is_dir():
        return None
    path = folder / MANIFEST
    if path.is_file():
        try:
            return Build(folder, json.loads(path.read_text(encoding="utf-8")))
        except ValueError:
            pass
    # A folder of models without a manifest is still a build - output from
    # before this existed, or something dropped in by hand. Refusing to list it
    # would hide files the user can plainly see.
    if any(folder.glob("*.mdl")):
        return Build(folder, {"name": folder.name, "unmanaged": True})
    return None


def find(root: str | Path) -> list[Build]:
    """Every build under an output directory, newest first."""
    root = Path(root)
    if not root.is_dir():
        return []
    out = [b for b in (load(p) for p in sorted(root.iterdir())) if b is not None]
    out.sort(key=lambda b: (b.created, b.name), reverse=True)
    return out
