"""Jade Empire models, in the conventions the rest of this tool uses.

Jade and KOTOR share an engine lineage and almost nothing else about their file
layout: every structure is a different size, so the splice engine cannot touch
a Jade model and never will. What Jade is good for is *geometry* - 158 heads
and 112 bodies that KOTOR does not have - and geometry has a route in already,
the one built for sculpts and Blender exports. A Jade head becomes a head pack,
and from there it is the same path as everything else.

Two corrections have to happen on the way, both measured rather than assumed
(`reports/JADE_FINDINGS.md`):

**Orientation.** A Jade model's height runs along X where KOTOR's runs along Z,
so an uncorrected head arrives lying on its side.

**Scale.** Jade models are larger. Measured across 270 models against 200 of
KOTOR's, height and depth agree on a factor of about 0.83.

The scale is a default, not a fact. It disagrees in direction with what the
format's own author reports, nothing has been tested in game, and heads are
proportioned differently from KOTOR's on top of being bigger - so it is exposed
as a number somebody can change.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# Measured, and held loosely. See the report before trusting it.
SCALE = 0.83

# Jade height runs along X, KOTOR's along Z, and the two also face opposite
# ways: `new = (old_z, -old_y, old_x)`. Determinant +1, so it turns the model
# rather than mirroring it - a reflection would invert every face and hand back
# a head that renders inside out.
#
# Established by rendering, not by reasoning. The first attempt got the axis
# right and left the head facing backwards, which is invisible in the numbers -
# the bounding box of a head is the same whichever way it looks.
TO_KOTOR = np.array([
    [0.0, 0.0, 1.0],
    [0.0, -1.0, 0.0],
    [1.0, 0.0, 0.0],
])

MDL_TYPE = 0x07D2
MDX_TYPE = 0x0BC8
MAB_TYPE = 0x0BC3          # material
TXB_TYPE = 0x0BC9          # texture

# A material names its diffuse texture as a null-terminated string at this
# offset, straight after the fixed float block. Verified against every one of
# the 1607 materials in the game - see `test_jade.py`. Scanning for the first
# printable run instead gets 13% of them wrong, because float bytes are often
# printable ASCII.
TEXTURE_NAME_AT = 0x64
RESREF_STEM = 14           # the field is 16 and the suffix takes two
RIM_MAGIC = b"RIM V1.0"
RIM_KEY_SIZE = 32

HEAD = "head"
BODY = "body"
MASK = "mask"
OTHER = "other"

# `H_` covers more than faces. `H_Mask*` are masks - open shells of 78 to 185
# triangles that cannot pass a check asking whether a surface is closed or
# faces outward, because they are not meant to be either. `H_Decap*` is a
# severed stump. Both are worth offering and neither is a head, and calling
# them one turns nine sensible refusals into nine apparent failures.
NOT_A_FACE = ("mask", "decap")


class JadeError(RuntimeError):
    pass


@dataclass(frozen=True)
class Source:
    """Where one resource sits: which archive, and where inside it.

    The archive travels with the offset because a model's two halves are not
    in the same file - see `catalogue`.
    """

    archive: Path
    offset: int
    size: int

    def read(self) -> bytes:
        return self.archive.read_bytes()[self.offset:self.offset + self.size]


@dataclass(frozen=True)
class Entry:
    """One model in the game's archives."""

    resref: str
    kind: str
    mdl: Source
    mdx: Source | None = None

    @property
    def archive(self) -> Path:
        return self.mdl.archive

    @property
    def label(self) -> str:
        return self.resref


@dataclass
class Mesh:
    """Geometry in KOTOR's conventions, ready for a head pack."""

    positions: list[tuple[float, float, float]] = field(default_factory=list)
    faces: list[tuple[int, int, int]] = field(default_factory=list)
    uvs: list[tuple[float, float]] = field(default_factory=list)
    normals: list[tuple[float, float, float]] = field(default_factory=list)
    materials: list[int] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def bounds(self):
        p = np.asarray(self.positions, dtype=float)
        return (p.min(axis=0), p.max(axis=0)) if len(p) else (None, None)


def kind_of(resref: str) -> str:
    """What a model is, by the naming the game is consistent about.

    Unlike the folder names, Jade's resrefs are reliable: `H_` heads and `N_`
    bodies, 499 and 456 entries respectively. Anything else is scenery,
    effects or a creature.
    """
    upper = resref.upper()
    if upper.startswith("H_"):
        rest = upper[2:].lower()
        return MASK if rest.startswith(NOT_A_FACE) else HEAD
    if upper.startswith("N_"):
        return BODY
    return OTHER


# --- finding models --------------------------------------------------------


def _rim_entries(archive: Path):
    """The key table of a RIM, without reading the payloads.

    Short enough to own rather than vendor, and it keeps the archive layer -
    which this project does understand - out of third-party code.
    """
    try:
        data = archive.read_bytes()
    except OSError:
        return
    if len(data) < 0x20 or data[:8] != RIM_MAGIC:
        return
    count, key_offset = struct.unpack_from("<II", data, 0x0C)
    if key_offset + count * RIM_KEY_SIZE > len(data):
        return
    for i in range(count):
        at = key_offset + i * RIM_KEY_SIZE
        resref = data[at:at + 16].split(b"\0", 1)[0].decode("ascii", "replace")
        restype, _resid, offset, size = struct.unpack_from("<IIII", data, at + 16)
        if offset + size <= len(data):
            yield resref, restype, offset, size


def catalogue(install, *, kinds=(HEAD, BODY, MASK)) -> list[Entry]:
    """Every model in the install, deduplicated.

    The models live in the per-area RIMs under `data/<area>/`, not in the
    top-level ones and not in `artcreatures.bif` - which holds visual effects
    despite the name. The same head appears in every area that uses it, so the
    first sighting wins.
    """
    root = Path(install) / "data"
    if not root.is_dir():
        raise JadeError(f"no data folder in {install}")

    # A model's two halves live in different archives. The MDL is in
    # `<area>.rim` and the MDX in its `-a` companion, `<area>-a.rim`, and every
    # area that uses a model carries its own copy - ten of them for a common
    # head. The copies are byte-identical, so any pair will do; what does not
    # work is taking an offset from one archive and reading it out of another,
    # which yields vertices with no faces and a mesh that looks empty.
    mdl: dict[str, Source] = {}
    mdx: dict[str, Source] = {}
    for archive in sorted(root.rglob("*.rim")):
        for resref, restype, offset, size in _rim_entries(archive):
            if restype == MDL_TYPE:
                mdl.setdefault(resref.lower(),
                               Source(archive, offset, size))
            elif restype == MDX_TYPE:
                mdx.setdefault(resref.lower(),
                               Source(archive, offset, size))

    out = []
    for key, source in mdl.items():
        kind = kind_of(key)
        if kinds and kind not in kinds:
            continue
        out.append(Entry(resref=source.archive and key, kind=kind,
                         mdl=source, mdx=mdx.get(key)))
    return sorted(out, key=lambda e: (e.kind, e.resref.lower()))


def read(entry: Entry) -> tuple[bytes, bytes | None]:
    """The model's bytes, each half out of the archive that holds it."""
    return entry.mdl.read(), entry.mdx.read() if entry.mdx else None


# --- reading one --------------------------------------------------------------


def mesh(mdl_bytes: bytes, mdx_bytes: bytes | None, *, scale: float = SCALE,
         orient: bool = True, centre: bool = True, tmp_dir=None) -> Mesh:
    """Every drawn triangle, in KOTOR's axes and at KOTOR's size.

    The vendored reader takes file paths rather than bytes, so the payloads are
    written out first; they come from inside an archive and have nowhere else
    to be.
    """
    import tempfile

    from .vendor.jade import parse_jade_mdl

    folder = Path(tmp_dir) if tmp_dir else Path(tempfile.mkdtemp())
    folder.mkdir(parents=True, exist_ok=True)
    mdl_path = folder / "model.mdl"
    mdl_path.write_bytes(mdl_bytes)
    mdx_path = None
    if mdx_bytes:
        mdx_path = folder / "model.mdx"
        mdx_path.write_bytes(mdx_bytes)

    try:
        model = parse_jade_mdl(mdl_path, mdx_path)
    except Exception as exc:  # noqa: BLE001 - the reader raises many kinds
        raise JadeError(f"could not read the model: {exc}") from exc

    out = Mesh()
    rotation = TO_KOTOR if orient else np.eye(3)

    def walk(node, parent_r, parent_t):
        r = parent_r @ _quaternion(node.orientation)
        t = parent_t + parent_r @ np.asarray(node.position, dtype=float)
        found = node.mesh
        if found is not None and found.render and found.vertices:
            base = len(out.positions)
            v = np.asarray(found.vertices, dtype=float)[:, :3]
            bad = ~np.isfinite(v).all(axis=1)
            if bad.any():
                # Zeroed rather than dropped: removing a vertex renumbers every
                # face after it, which turns a handful of bad points into a
                # scrambled mesh.
                v = np.where(np.isfinite(v), v, 0.0)
                out.notes.append(f"{int(bad.sum())} non-finite vertices in "
                                 f"{node.name!r}, zeroed")
            world = ((v @ r.T + t) @ rotation.T) * scale
            out.positions.extend(tuple(float(x) for x in row) for row in world)
            material = getattr(found, "material_id", None)
            if material and material not in out.materials:
                out.materials.append(int(material))
            for tri in (found.triangles or ()):
                a, b, c = tri[:3]
                out.faces.append((base + a, base + b, base + c))
            _uvs(found, out)
        for child in (node.children or ()):
            walk(child, r, t)

    walk(model.root, np.eye(3), np.zeros(3))
    if not out.faces:
        raise JadeError("the model has no drawn geometry")

    if centre and out.positions:
        # A Jade head model's node chain places it at the top of a body, so its
        # geometry sits about 1.8 units up. A head pack is expected around its
        # own origin, and without this the build refuses it - "centre is 1.799
        # away from the node's geometry, it would float" - which is correct and
        # not something the modder should have to fix with a fit checkbox.
        p = np.asarray(out.positions, dtype=float)
        middle = (p.min(axis=0) + p.max(axis=0)) / 2.0
        out.positions = [tuple(float(x) for x in row) for row in (p - middle)]
        out.notes.append(f"centred on its own origin (moved {np.linalg.norm(middle):.3f})")
    return out


def _quaternion(q):
    x, y, z, w = (float(v) for v in q)
    n = (x * x + y * y + z * z + w * w) ** 0.5
    if n == 0:
        return np.eye(3)
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def _uvs(found, out: Mesh) -> None:
    """The first UV layer, with V turned over.

    Jade's V axis runs the opposite way to the one this project's `.obj`
    pipeline expects. Left alone, the texture still lands on the head and still
    looks like skin - the eyes end up near the eyes - so it reads as a slightly
    wrong model rather than as a flipped coordinate. Settled by rendering the
    two side by side: one is a scrambled mess, the other is a face with a
    moustache and a goatee exactly where they belong.

    Without UVs a head still builds and renders untextured, which is worth
    saying rather than discovering in game.
    """
    layers = getattr(found, "uv_layers", None) or ()
    if not layers:
        out.notes.append("no UVs - the head will build but render untextured")
        return
    for uv in layers[0]:
        out.uvs.append((float(uv[0]), 1.0 - float(uv[1])))


# --- textures ---------------------------------------------------------------
#
# A mesh does not name its texture; it names a material by number, and the
# material names the texture. Both live in the archives, and both are split the
# way models are: the material sits beside the MDL in `<area>.rim`, the texture
# beside the MDX in `<area>-a.rim`.


_INDEX: dict[tuple[str, int], dict[str, Source]] = {}


def index_of(install, restype: int) -> dict[str, Source]:
    """Every resource of one type, by resref. Cached - the walk is 1028 files."""
    key = (str(install), restype)
    if key in _INDEX:
        return _INDEX[key]

    root = Path(install) / "data"
    found: dict[str, Source] = {}
    if root.is_dir():
        for archive in sorted(root.rglob("*.rim")):
            for resref, kind, offset, size in _rim_entries(archive):
                if kind == restype:
                    found.setdefault(resref.lower(),
                                     Source(archive, offset, size))
    _INDEX[key] = found
    return found


def texture_name(install, material_id: int) -> str | None:
    """The diffuse texture a material names, or None."""
    source = index_of(install, MAB_TYPE).get(str(material_id).lower())
    if source is None:
        return None
    raw = source.read()
    if len(raw) <= TEXTURE_NAME_AT:
        return None
    end = raw.find(b"\0", TEXTURE_NAME_AT)
    if end < 0:
        return None
    name = raw[TEXTURE_NAME_AT:end].decode("ascii", "replace").strip()
    # "NULL" is how the format spells an empty slot.
    return name if name and name.upper() != "NULL" else None


def texture(install, name: str) -> bytes | None:
    """One texture, decoded to TGA bytes, or None if it is not there."""
    source = index_of(install, TXB_TYPE).get(name.lower())
    if source is None:
        return None
    from .vendor.jade import parse_txb_bytes, tga_bytes

    try:
        return tga_bytes(parse_txb_bytes(source.read()))
    except Exception:  # noqa: BLE001 - an undecodable texture is not fatal
        return None


def texture_for(install, found: Mesh) -> tuple[str, bytes] | None:
    """The texture a mesh wears: material number, then material, then image."""
    for material in found.materials:
        name = texture_name(install, material)
        if not name:
            continue
        data = texture(install, name)
        if data:
            return name, data
    return None


# --- into a head pack -------------------------------------------------------


def to_pack(entry: Entry, out_dir, *, scale: float = SCALE,
            name: str | None = None, install=None,
            with_texture: bool = True) -> dict:
    """Write a Jade model out as a head pack the Custom head tab can build.

    The pack is the same shape a `.glb` import produces, so everything
    downstream - decimation, fitting, winding repair, the solidity check -
    applies unchanged. What is Jade-specific ends here.
    """
    import json

    from kmdlswap import obj as kobj

    from . import headpack

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    found = mesh(*read(entry), scale=scale)

    kobj.write_obj(out_dir / "head.obj", found.positions, found.faces,
                   uvs=found.uvs or None, normals=found.normals or None,
                   name=out_dir.name)

    # The install is only needed for the texture: a mesh names a material by
    # number, and both the material and the image it points at live in the
    # archives rather than in the model.
    texture_file = None
    if with_texture:
        root = install or _install_of(entry)
        got = texture_for(root, found) if root else None
        if got:
            source_name, data = got
            # The filename becomes the resref, and that field is 16 characters.
            texture_file = out_dir.name.lower()[:RESREF_STEM] + "01"
            (out_dir / f"{texture_file}.tga").write_bytes(data)
            found.notes.append(f"texture {source_name} decoded from .txb")
        elif found.materials:
            found.notes.append("no texture found - it will wear the host's")

    headpack.write_template(out_dir, name=name or entry.resref)
    manifest = out_dir / headpack.MANIFEST_NAME
    data = json.loads(manifest.read_text(encoding="utf-8"))
    # Already converted on the way out, so the pack is in KOTOR's own
    # conventions and needs no further correction.
    data["up"] = "z"
    data["facing"] = "+y"
    data["notes"] = (f"imported from Jade Empire {entry.resref} "
                     f"(x{scale:.2f}, rotated upright)")
    manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    return {
        "pack": out_dir,
        "resref": entry.resref,
        "vertices": len(found.positions),
        "triangles": len(found.faces),
        "uvs": len(found.uvs),
        "texture": texture_file,
        "notes": found.notes,
    }


def _install_of(entry: Entry):
    """The game folder an entry came out of: `<install>/data/<area>/x.rim`."""
    archive = entry.mdl.archive
    for parent in archive.parents:
        if (parent / "chitin.key").is_file():
            return parent
    return None


# --- pictures ---------------------------------------------------------------


def thumbnail(entry: Entry, *, size: int = 96, root=None):
    """Draw one Jade model's face and cache it, or None.

    `thumbs.render` cannot be reused: it parses its bytes as a KOTOR model.
    The caching rule is the same though - keyed on the bytes, so a redraw only
    happens when the model does.
    """
    import hashlib

    from . import render as krender
    from . import thumbs as kthumbs

    mdl_bytes, mdx_bytes = read(entry)
    digest = hashlib.md5(mdl_bytes + (mdx_bytes or b"")).hexdigest()
    folder = Path(root) if root else Path(kthumbs.cache_root()) / "jade"
    out = folder / f"{digest}-{size}.png"
    if out.is_file():
        return out

    try:
        found = mesh(mdl_bytes, mdx_bytes)
        scene = krender.from_mesh(found.positions, found.faces)
        if not len(scene.faces):
            return None
        pixels = krender.render(scene, size=size, cull=True)
    except Exception:  # noqa: BLE001 - a missing face is not worth raising over
        return None

    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        krender.to_png(pixels, out)
    except Exception:  # noqa: BLE001
        return None
    return out
