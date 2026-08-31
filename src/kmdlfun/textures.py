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

    def packed(self, resref: str) -> np.ndarray | None:
        """Only what the game *ships*, ignoring Override.

        The difference matters when deciding whether a build has to carry a
        texture with it. Override is where this tool puts things, so a plain
        lookup answers "is it there now" - and after installing one Quarren
        build, the next one would decide the host already had that texture and
        ship without it. The question is what the game supplies on its own.
        """
        if not self.install:
            return None
        try:
            from pykotor.extract.installation import Installation, SearchLocation

            if self._inst is None:
                self._inst = Installation(str(self.install))
            # An explicit order without OVERRIDE. The default order includes it,
            # which is the whole thing this method exists to avoid.
            tpc = self._inst.texture(resref, order=[
                SearchLocation.TEXTURES_TPA,
                SearchLocation.TEXTURES_TPB,
                SearchLocation.TEXTURES_TPC,
                SearchLocation.CHITIN,
            ])
            return None if tpc is None else _from_tpc_object(tpc)
        except Exception:  # noqa: BLE001
            return None

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


def raw_texture(install: str | Path, resref: str) -> tuple[bytes, str] | None:
    """The texture's original bytes and extension, straight out of the game.

    Re-encoding a TPC as a TGA is a conversion, and a conversion is a place for
    a mistake to hide - a wrong row order or a lost channel looks like a
    modelling fault, not a file fault. Copying the shipped bytes removes the
    question: whatever the engine did with them in one game, it does in the
    other. Only used when the donor comes from a different install, where the
    host game genuinely lacks the file.
    """
    from pykotor.extract.installation import Installation

    inst = Installation(str(install))
    try:
        found = inst.texture_resource_result(resref)
    except Exception:  # noqa: BLE001
        return None
    if not found:
        return None
    result = found[0] if isinstance(found, tuple) else found
    data = getattr(result, "data", None)
    if data is None:
        return None
    if callable(data):
        data = data()
    if not data:
        return None
    restype = getattr(result, "restype", None)
    ext = getattr(restype, "extension", None) or "tpc"
    return bytes(data), str(ext).lstrip(".")


def export_donor_textures(mdl: bytes, mdx: bytes, donor_install, out_dir,
                          host_install=None) -> list[str]:
    """Write out any texture the built model names that the *host* game lacks.

    A donor from another install brings a texture the host game has never heard
    of, and without it the model loads grey - which reads as a modelling failure
    and is really a missing file. The shipped bytes are copied verbatim where
    they can be, because a re-encode is a place for a mistake to hide: decoding
    a Quarren's RGBA texture to RGB dropped its alpha and cost it its eyes.

    `host_install` is what stops this shipping too much. A built model still
    names the host's own textures on the parts that did not change - Carth keeps
    `P_CarthH01` on his hair and teeth - and both games ship a file by that
    name. Copying the donor game's copy into Override puts a KOTOR 2 asset in
    front of the KOTOR 1 one for every model that uses it, not just this build.
    They happen to be byte-identical for Carth; that is luck, not a reason.
    """
    from pathlib import Path as _Path

    from kmdlswap import layout as kl

    from . import parts as kparts
    from . import render as krender

    out_dir = _Path(out_dir)
    layout = kl.parse(mdl, mdx)
    donor_side = TextureCache(donor_install)
    host_side = TextureCache(host_install) if host_install else None

    notes: list[str] = []
    for name in sorted({krender.node_texture(layout, n)
                        for n in kparts.mesh_nodes(layout)} - {""}):
        if host_side is not None and host_side.packed(name) is not None:
            # The host game ships this one itself, so leave its copy alone.
            # Deliberately not `get`, which would see Override - where this
            # tool's own previous installs live.
            continue
        raw = raw_texture(donor_install, name)
        if raw is not None:
            data, ext = raw
            path = out_dir / f"{name}.{ext}"
            path.write_bytes(data)
            notes.append(f"copied {path.name} ({len(data)} bytes) from the donor's "
                         f"game, unconverted")
            continue

        image = donor_side.get(name)
        if image is None:
            continue                       # the host game supplies this one
        try:
            from PIL import Image
        except ImportError:
            notes.append(f"texture {name!r} needs Pillow to export")
            continue
        path = out_dir / f"{name}.tga"
        Image.fromarray(image, mode="RGB").save(path)
        notes.append(f"exported {path.name} ({image.shape[1]}x{image.shape[0]})")
    return notes


def lookup_across(installs, extra: list[Path] | None = None):
    """A texture lookup that tries several games, in order.

    A cross-game build names a texture the host game has never heard of, so a
    preview built from the host's install alone draws it grey - which is
    exactly what a missing texture looks like, and exactly the wrong thing to
    show someone deciding whether a head is worth building.

    Order matters and matches the engine's: whatever is loose comes first
    (`extra`, then each install's Override), then the packs, host before donor.
    Caches are built once and shared, so turning a model in the viewport does
    not re-read the game.
    """
    caches = [TextureCache(p, extra=extra) for p in installs if p]
    if not caches:
        caches = [TextureCache(None, extra=extra)]

    def get(name: str):
        for cache in caches:
            found = cache.get(name)
            if found is not None:
                return found
        return None

    get.caches = caches           # so a caller can report what went wrong
    return get
