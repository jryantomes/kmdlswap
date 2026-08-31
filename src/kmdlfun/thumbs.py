"""Small rendered faces for the donor list, cached on disk.

A donor list is a few hundred names, and a name does not tell you what a face
looks like. `n_shaardanh` and `n_lashoweh` are both clean fits on Carth and one
of them is the one you meant.

Rendering is the same software rasteriser the Preview tab uses, so a thumbnail
is drawn by tested code with the corrected camera - the catalogue that existed
before this was every character photographed from behind.

The size is part of the cache key, so changing it redraws rather than showing
a stale face at the wrong scale.

**Cached on disk, keyed by the model's own bytes.** One face takes about a
third of a second, which is nothing on its own and forty-five seconds across a
full list, so they are kept. The key is a hash of the MDL and MDX rather than
the file name, so a model edited in Override redraws itself and a build in
progress never shows a stale face. Nothing here imports Tk: the cache is a
directory of PNGs, and the app turns those into widgets.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

SIZE = 96
CACHE_VERSION = "v1"


def cache_root() -> Path:
    """Somewhere durable that is neither the game nor the project."""
    return Path.home() / ".kmdlfun" / "thumbs" / CACHE_VERSION


def key_for(mdl: bytes, mdx: bytes, size: int = SIZE) -> str:
    """Identify a thumbnail by what it draws, not by what it is called.

    A model swapped into Override keeps its name and changes its bytes, and a
    cache keyed by name would keep showing the face that is gone.
    """
    h = hashlib.md5()
    h.update(mdl)
    h.update(mdx)
    h.update(str(size).encode())
    return h.hexdigest()


def path_for(mdl: bytes, mdx: bytes, size: int = SIZE, root: Path | None = None) -> Path:
    return (root or cache_root()) / f"{key_for(mdl, mdx, size)}.png"


def render(mdl: bytes, mdx: bytes, *, size: int = SIZE, texture_lookup=None,
           root: Path | None = None) -> Path | None:
    """Draw one model's face and cache it. Returns the file, or None.

    None means there was nothing to draw or the model would not parse - both
    real answers about a donor, and neither worth raising over: a list that
    fails to open because one of three hundred models is odd is worse than a
    list with a gap in it.
    """
    from kmdlswap import layout as kl

    from . import render as krender

    out = path_for(mdl, mdx, size, root)
    if out.is_file():
        return out

    try:
        scene = krender.from_layout(kl.parse(mdl, mdx), texture_lookup=texture_lookup)
        if not len(scene.faces):
            return None
        pixels = krender.render(scene, size=size, cull=True)
    except Exception:  # noqa: BLE001
        return None

    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        krender.to_png(pixels, out)
    except Exception:  # noqa: BLE001
        return None
    return out


def cached(mdl: bytes, mdx: bytes, size: int = SIZE, root: Path | None = None):
    """The file if it is already drawn, without drawing it."""
    p = path_for(mdl, mdx, size, root)
    return p if p.is_file() else None


def ensure(library, names, *, size: int = SIZE, texture_lookup=None,
           root: Path | None = None, progress=None, should_stop=None):
    """Draw whatever is missing, yielding `(name, path)` as each one lands.

    A generator so a caller can put faces on screen as they arrive rather than
    waiting for the whole list; `should_stop` lets it be abandoned when the
    user moves on, which matters because the list changes whenever the filter
    does.
    """
    names = list(names)
    for i, name in enumerate(names):
        if should_stop is not None and should_stop():
            return
        if progress is not None:
            progress(i, len(names), name)
        try:
            mdl, mdx = library.read(name)
        except Exception:  # noqa: BLE001
            continue
        path = render(mdl, mdx, size=size, texture_lookup=texture_lookup, root=root)
        if path is not None:
            yield name, path
