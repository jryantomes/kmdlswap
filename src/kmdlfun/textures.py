"""Finding the actual pixels behind a texture name.

A trimesh header carries a 32-byte texture *name*, not an image, and the same
name resolves differently depending on where you look. The engine's own search
order is what matters, because a preview that reads a different file from the
one the game will read is worse than no preview:

1. **Loose files first.** Override wins over everything packed, which is the
   whole reason a custom head's `.tga` works at all.
2. **Then the texture packs** - head textures live in `swpc_tex_tpa`, not in
   `chitin.key`.

Anything the caller passes in `extra` is searched before both, so a head pack
that has not been installed yet can still be previewed from its own folder.

TPC decoding is PyKotor's, and unlike its MDL reader it is trustworthy here: the
format is a header and a pixel block, the round-trip that failed for models does
not arise, and the output is checked against the dimensions in the header.
Failures are reported rather than swallowed - a silently missing texture would
show as untextured grey, which looks exactly like a model that has no texture.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

LOOSE_SUFFIXES = (".tga", ".tpc")


class TextureCache:
    """Resolves texture names to (H, W, 3) uint8 arrays, once each.

    Holds a PyKotor `Installation` lazily, because building one reads every
    key file in the game and costs a second or two.
    """

    def __init__(self, install: str | Path | None = None, extra: list[Path] | None = None):
        self.install = Path(install) if install else None
        self.extra = [Path(p) for p in (extra or [])]
        self._cache: dict[str, np.ndarray | None] = {}
        self._inst = None
        self._loose: dict[str, Path] | None = None
        self.problems: list[str] = []

    # ---- lookup ------------------------------------------------------------

    def get(self, resref: str) -> np.ndarray | None:
        key = resref.lower()
        if key not in self._cache:
            try:
                self._cache[key] = self._load(resref)
            except Exception as exc:  # noqa: BLE001
                self.problems.append(f"{resref}: {type(exc).__name__}: {exc}")
                self._cache[key] = None
        return self._cache[key]

    def _load(self, resref: str) -> np.ndarray | None:
        path = self._find_loose(resref)
        if path is not None:
            if path.suffix.lower() == ".tpc":
                return _decode_tpc(path.read_bytes())
            return _decode_image(path)
        return self._from_packs(resref)

    def _find_loose(self, resref: str) -> Path | None:
        if self._loose is None:
            self._loose = {}
            roots = list(self.extra)
            if self.install:
                roots.append(self.install / "Override")
            # Later roots must not shadow earlier ones: `extra` is most specific.
            for root in roots:
                if not root.is_dir():
                    continue
                for p in root.iterdir():
                    if p.is_file() and p.suffix.lower() in LOOSE_SUFFIXES:
                        self._loose.setdefault(p.stem.lower(), p)
        return self._loose.get(resref.lower())

    def _from_packs(self, resref: str) -> np.ndarray | None:
        if not self.install:
            return None
        if self._inst is None:
            from pykotor.extract.installation import Installation

            self._inst = Installation(str(self.install))
        tpc = self._inst.texture(resref)
        if tpc is None:
            return None
        return _from_tpc_object(tpc)


# ---- decoders --------------------------------------------------------------


def _from_tpc_object(tpc) -> np.ndarray:
    from pykotor.resource.formats.tpc import TPCTextureFormat

    tpc.convert(TPCTextureFormat.RGB)
    mm = tpc.get()
    expected = mm.width * mm.height * 3
    if len(mm.data) != expected:
        raise ValueError(
            f"decoded {len(mm.data)} bytes for a {mm.width}x{mm.height} RGB image, "
            f"expected {expected}"
        )
    return np.frombuffer(mm.data, dtype=np.uint8).reshape(mm.height, mm.width, 3)


def _decode_tpc(raw: bytes) -> np.ndarray:
    from pykotor.resource.formats.tpc import read_tpc

    return _from_tpc_object(read_tpc(raw))


def _decode_image(path: Path) -> np.ndarray:
    from PIL import Image

    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"), dtype=np.uint8)
