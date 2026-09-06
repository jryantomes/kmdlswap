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

# Measured per kind, because heads and bodies do not agree. Across 158 Jade
# heads against 105 of KOTOR's the height factor is 0.858; across 112 bodies
# against 95 it is 0.830, with depth agreeing to 0.4%. Using the body figure
# for heads made them visibly small in game.
#
# Held loosely either way - see reports/JADE_FINDINGS.md before trusting it.
SCALE = 0.97
HEAD_SCALE = 0.86
# Bodies: KOTOR's median body height 1.576 against Jade's 1.618.
#
# It was 0.83, from comparing Jade's X extent of 1.85 against a KOTOR body's
# height. 1.85 is consistent across the corpus and that consistency was read as
# evidence it was the height - it is the *arm span*, which is just as
# consistent. Measuring height against height gives 0.97, so a Jade body is
# about 3% larger than a KOTOR one rather than a sixth.
BODY_SCALE = 0.97


def scale_for(kind: str) -> float:
    """The size correction for one kind of model."""
    return HEAD_SCALE if kind in (HEAD, MASK) else BODY_SCALE

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

# Bodies do not share the heads' convention. A head's height runs along X and
# `TO_KOTOR` turns it upright; a body's runs along Z already, and along it the
# figure is upside down - shoulders at the low end, feet at the high one. Put a
# body through the head's correction and it arrives lying on its side, which is
# what the game would have shown.
#
# So a body only needs turning over: 180 degrees about X, `(x, -y, -z)`.
# Determinant +1, so no face is mirrored - the same care `TO_KOTOR` takes.
#
# Established by rendering twelve of them, after two numeric checks each gave a
# confident wrong answer. A bounding box cannot tell a T-pose from one rotated
# ninety degrees, because arm span and height are nearly equal; and comparing
# the girth of the two ends splits the corpus 41/32, because on a figure whose
# arms sit near mid-height both ends are small and the comparison is noise.
BODY_UPRIGHT = np.array([
    [1.0, 0.0, 0.0],
    [0.0, -1.0, 0.0],
    [0.0, 0.0, -1.0],
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
         orient: bool = True, centre: bool = True, tmp_dir=None,
         kind: str = HEAD) -> Mesh:
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
    rotation = np.eye(3)
    if orient:
        rotation = BODY_UPRIGHT if kind == BODY else TO_KOTOR

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


def to_pack(entry: Entry, out_dir, *, scale: float | None = None,
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
    if scale is None:
        scale = scale_for(entry.kind)
    found = mesh(*read(entry), scale=scale, kind=entry.kind)

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
            #
            # Named from the *model*, not the folder it is being written into.
            # The folder is the caller's choice and the truncation then falls in
            # the wrong place: the window's default is `jade_<resref>`, and
            # fourteen characters of that is spent before the digits that tell
            # two heads apart - all eight `h_bandit0*` heads come out as
            # `jade_h_bandit001`. Across the catalogue that is 42 of 270 models
            # sharing a texture name with another, so installing two of them
            # together means one wears the other's face.
            #
            # From the resref instead, all 270 are distinct and the longest is
            # 15 characters.
            texture_file = (entry.resref.strip("_").lower() or out_dir.name.lower())
            texture_file = texture_file[:RESREF_STEM] + "01"
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


def scene(entry: Entry, *, install=None, scale: float | None = None):
    """A drawable, *textured* scene for one Jade model.

    `render.from_mesh` draws flat colour, which is enough to tell one silhouette
    from another and not enough to choose a face: Jade heads carry their eyes,
    brows and mouth in the texture, and untextured they are all the same grey
    mask. The atlas is not in the model - a mesh names a material by number and
    both the material and its image live in the archives - so this is the one
    place that has to reach back into the install to draw.
    """
    import io

    import numpy as _np
    from PIL import Image

    from . import render as krender

    if scale is None:
        scale = scale_for(entry.kind)
    found = mesh(*read(entry), scale=scale, kind=entry.kind)
    built = krender.from_mesh(found.positions, found.faces)
    if not len(built.faces) or not found.uvs:
        return built

    got = texture_for(install or _install_of(entry), found)
    if not got:
        return built
    _name, data = got
    try:
        with Image.open(io.BytesIO(data)) as im:
            image = _np.asarray(im.convert("RGB"), dtype=_np.uint8)
    except Exception:  # noqa: BLE001 - an unreadable atlas is not worth raising
        return built

    uvs = _np.asarray(found.uvs, dtype=_np.float64)
    if len(uvs) != len(built.positions):
        return built
    built.uvs = uvs
    built.textures = [image]
    built.face_texture = _np.zeros(len(built.faces), dtype=_np.int32)
    return built


# Bump when the build pipeline changes what a converted head looks like, so
# cached ones are redrawn rather than shown stale.
BUILD_VERSION = "v1"


# Jade heads whose geometry carries a collar rather than a neck.
#
# A converted head keeps whatever its own mesh had below the jaw, and on these
# that is clothing - UV-mapped to a garment in the atlas, not to skin. It shows
# as a coloured tube standing out of a KOTOR collar, which no amount of
# weighting or scaling can turn into a neck; fixing one properly means re-UVing
# the neck or trimming it away.
#
# Curated rather than measured, and that is worth being straight about. Three
# colour tests were tried against the atlas and against the render, and none
# separated: `h_common01_` reads as skin at 24 while a genuinely bare neck
# reads 60, because a tan collar and a shadowed neck are the same colour. So
# these are read off renders of all 148, at a size where the answer is obvious.
#
# 18 of 148. The estimate before they were looked at properly was about 35 -
# shoulder plates below the jaw and a creature's mane both read as collars in a
# thumbnail and are neither.
NECK_GARMENT = frozenset({
    "h_assnf01gh_",     # brown and red banded wrap
    "h_bling01_",       # magenta collar
    "h_bling02_",       # green striped necklace
    "h_iguard01_",      # ribbed orange collar under shoulder plates
    "h_isldr03_",       # maroon collar
    "h_isldr04_",       # black banded collar
    "h_isoldr01_",      # gold banded collar
    "h_isoldr01gh_",    # gold banded collar
    "h_jane01_",        # orange collar
    "h_joe05_",         # white ruff
    "h_laf02_",         # ornate gold collar
    "h_lai02_",         # white collar with a clasp
    "h_lai03_",         # layered rope collar
    "h_mercf01_",       # red collar - the one seen in game
    "h_mercf02_",       # black collar
    "h_mercf02gh_",     # black collar
    "h_piratf01_",      # dark red collar
    "h_piratf02_",      # black collar with gold trim
})


def wears_a_collar(resref: str) -> bool:
    """Whether this head brings a garment where a neck should be."""
    return (resref or "").strip().lower() in NECK_GARMENT


def as_head(resref: str, jade_install, install, host: str, *, root=None):
    """Convert one Jade head and build it into `host`, cached on disk.

    A KOTOR II head can be copied into a character as it is; a Jade head cannot
    be loaded by this engine at all, so "using" one means running the whole
    conversion - geometry out, pack in, weights transferred, mouth split, lids
    seated - before there is a model to name. That takes a few seconds, which is
    fine once and not fine every time a picker is clicked, so the result is kept.

    Returns `(mdl_path, mdx_path, texture_path | None)`, or None if the head
    will not build.
    """
    from . import headbuild, thumbs as kthumbs

    folder = Path(root) if root else kthumbs.cache_dir("heads") / BUILD_VERSION
    out = folder / f"{resref.strip('_').lower()}-{host.lower()}"
    mdl, mdx = out / f"{host}.mdl", out / f"{host}.mdx"
    if mdl.is_file() and mdx.is_file():
        textures = [p for p in out.glob("*.tga")]
        return mdl, mdx, (textures[0] if textures else None)

    import tempfile

    entry = next((e for e in catalogue(jade_install, kinds=(HEAD,))
                  if e.resref.lower() == resref.lower()), None)
    if entry is None:
        return None
    pack = Path(tempfile.mkdtemp()) / "pack"
    try:
        to_pack(entry, pack, install=jade_install)
        result = headbuild.run(str(pack), install=str(install), host=host,
                               node="Head", repair=True, hide=[], build=True)
        # Hosts are not all the same size. Carth's head node is
        # 0.161x0.225x0.281 and Bastila's is 0.137x0.187x0.231, so a Jade head
        # that drops straight into his is 1.4x too big for hers and would clip
        # through the body. Fitting scales it onto the node, which is what the
        # spec's own failure message says to do - but only reach for it when
        # the head does not fit, so a host with room keeps its full size.
        if any(f.check == "size" for f in result.failures):
            result = headbuild.run(str(pack), install=str(install), host=host,
                                   node="Head", repair=True, hide=[], fit=True,
                                   build=True)
    except Exception:  # noqa: BLE001
        return None
    if result.error or result.failures or result.mdl is None:
        return None
    out.mkdir(parents=True, exist_ok=True)
    written = headbuild.write(result, out, host)
    textures = [p for p in written if p.suffix.lower() == ".tga"]
    return mdl, mdx, (textures[0] if textures else None)


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
    # The same scale the pack would use, so the picture and the thing it
    # promises are the same size.
    # `jade-v2` because v1 drew these flat: the key is the model's bytes, which
    # have not changed, so a textured redraw needs a new folder to land in.
    folder = Path(root) if root else kthumbs.cache_dir("thumbs") / "jade-v2"
    out = folder / f"{digest}-{size}.png"
    if out.is_file():
        return out

    try:
        built = scene(entry)
        if not len(built.faces):
            return None
        pixels = krender.render(built, size=size, cull=True)
    except Exception:  # noqa: BLE001 - a missing face is not worth raising over
        return None

    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        krender.to_png(pixels, out)
    except Exception:  # noqa: BLE001
        return None
    return out
