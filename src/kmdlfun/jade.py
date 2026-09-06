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
# `TO_KOTOR` turns it upright; a body arrives already standing, already facing
# the way KOTOR faces, and already handed the same way round. It needs nothing
# doing to it at all, and this is here to say so rather than to act.
#
# Getting to identity took two wrong turns, both of them mine, both taken by
# looking at a render. First the node quaternions were being unpacked x, y, z,
# w when Jade stores them w first, which stood every body on its head; I put in
# a flip about X and the render looked right. With the unpacking fixed I
# replaced the flip with a half turn about Z, and the render looked right then
# too - because a half-turned human is very hard to tell from a human.
#
# What settles it is the two skeletons, which agree without any help. KOTOR
# names its left bicep at x -0.164 and its right at +0.176; Jade names its left
# arm at -0.205 and its right at +0.205. In both games the toes sit forward of
# the ball of the foot along +y. A half turn about Z reverses both of those: it
# puts the left arm on the right and points the toes backwards. The render that
# convinced me otherwise was of a body seen from behind, and the one Jade body
# with a face on it - `n_cnsrt_` - shows her face with no turn applied and the
# back of her head with one.
BODY_FACING = np.array([
    [1.0, 0.0, 0.0],
    [0.0, 1.0, 0.0],
    [0.0, 0.0, 1.0],
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


def _parse(mdl_bytes: bytes, mdx_bytes: bytes | None, tmp_dir=None):
    """The vendored reader, given bytes.

    It takes file paths, and these payloads come from inside an archive and have
    nowhere else to be, so they are written out first.
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
        return parse_jade_mdl(mdl_path, mdx_path)
    except Exception as exc:  # noqa: BLE001 - the reader raises many kinds
        raise JadeError(f"could not read the model: {exc}") from exc


def mesh(mdl_bytes: bytes, mdx_bytes: bytes | None, *, scale: float = SCALE,
         orient: bool = True, centre: bool = True, tmp_dir=None,
         kind: str = HEAD, pose: float | None = None) -> Mesh:
    """Every drawn triangle, in KOTOR's axes and at KOTOR's size.

    `pose` swings the arms down to that many degrees below horizontal, which is
    what a body needs before KOTOR's skeleton will fit it - see `repose`.
    """
    model = _parse(mdl_bytes, mdx_bytes, tmp_dir)
    swing = repose(model, pose) if pose is not None else {}

    out = Mesh()
    rotation = np.eye(3)
    if orient:
        rotation = BODY_FACING if kind == BODY else TO_KOTOR

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
            here = v @ r.T + t
            if swing:
                here = _skin(here, found, model.names, swing)
            world = (here @ rotation.T) * scale
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
    """A node's orientation as a matrix. Jade stores it `w` first.

    The order is not cosmetic: read as `x, y, z, w` the whole model comes out
    turned, and on a body that turn is close enough to a half-revolution that a
    corrective flip hid it for a long time. `skeleton` is what settles it - see
    the note on `BODY_FACING`.
    """
    w, x, y, z = (float(v) for v in q)
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
        out.uvs.append(turn_uv(uv))


def turn_uv(uv) -> tuple:
    """One UV pair, with V turned over. The convention lives here alone.

    `partition` used to read the layer straight out of the reader and skip
    this, and the result was a body wearing a plausible outfit off the wrong
    rows of its own atlas - which reads as a slightly wrong model rather than
    as a flipped coordinate, and is exactly the kind of thing that survives
    being looked at.
    """
    return (float(uv[0]), 1.0 - float(uv[1]))


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
            with_texture: bool = True, pose: float | None = None) -> dict:
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
    found = mesh(*read(entry), scale=scale, kind=entry.kind, pose=pose)

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


# What Jade calls the bones KOTOR names differently. Both games descend from
# the same engine and the skeletons correspond limb for limb - `hturn_g` even
# survives under its own name.
#
# Jade is the finer rig of the two. Its spine has four joints to KOTOR's three,
# each arm carries a twist bone and a radius alongside the ulna, and its hands
# have four digits where KOTOR's have five. Where two Jade bones do one KOTOR
# bone's work they land on the same name and merge, which is what keeps a
# ported mesh under `BONE_CAP`.
BONE_NAMES = {
    # spine, neck and head
    "SpinBone0": "pelvis_g", "SpinBone1": "torso_g", "SpinBone2": "torso_g",
    "SpinBone3": "torsoupr_g", "NeckBone0": "neck_g",
    "hturn_g": "hturn_g", "head_bob": "head_g", "HeadBone": "head_g",
    # legs
    "LegUppeL": "lthigh_g", "LegLoweL": "lshin_g",
    "FootBallL": "lfoot_g", "FootToesL": "lfootT_g",
    "LegUppeR": "rthigh_g", "LegLoweR": "rshin_g",
    "FootBallR": "rfoot_g", "FootToesR": "rfootT_g",
    # left arm - Twis0/Twis1 are one twist bone to KOTOR, Radi rides the Ulna
    "BLClavL01": "lcollar_g", "BLArmUppeL01": "lbicep_g",
    "Twis0L01": "LbicepL_g", "Twis1L01": "LbicepL_g",
    "UlnaL01": "lforearm_g", "RadiL01": "lforearm_g", "HandL": "lhand_g",
    "FingIndeL0": "LaFngrB_g", "FingIndeL1": "LaFngrT_g",
    "FingIndeL2": "LaFngrT_g",
    "FingMiddL0": "LbFngrB_g", "FingMiddL1": "LbFngrT_g",
    "FingRingL0": "LcFngrB_g", "FingRingL1": "LcFngrT_g",
    "FingThumL0": "LThumbB_g", "FingThumL1": "LThumbT_g",
    # right arm
    "BLClavR01": "rcollar_g", "BLArmUppeR01": "rbicep_g",
    "Twis0R01": "RbicepL_g", "Twis1R01": "RbicepL_g",
    "UlnaR01": "rforearm_g", "RadiR01": "rforearm_g", "HandR": "rhand_g",
    "FingIndeR0": "RaFngrB_g", "FingIndeR1": "RaFngrT_g",
    "FingIndeR2": "RaFngrT_g",
    "FingMiddR0": "RbFngrB_g", "FingMiddR1": "RbFngrT_g",
    "FingRingR0": "RcFngrB_g", "FingRingR1": "RcFngrT_g",
    "FingThumR0": "RThumbB_g", "FingThumR1": "RThumbT_g",
}

# The bones every Jade body has, and the ones the rest of this module reaches
# for by name. A body missing one of these is not a body.
CORE_BONES = frozenset({
    "SpinBone0", "SpinBone2", "SpinBone3",
    "BLClavL01", "BLArmUppeL01", "UlnaL01", "HandL",
    "BLClavR01", "BLArmUppeR01", "UlnaR01", "HandR",
    "LegUppeL", "LegLoweL", "FootBallL",
    "LegUppeR", "LegLoweR", "FootBallR",
})


def skeleton(entry: Entry) -> dict:
    """Every named bone of one Jade model, in its own model space.

    Jade bodies carry a full skeleton - 73 nodes on `n_bandit_`, named limb by
    limb - and it answers questions the mesh will not. The rest pose of the arms
    is the one that matters: measured off the geometry it came out anywhere
    between -20 and +11 degrees and could not be found at all on a robed figure
    or a child, because a robe's hem is wider than any arm. Measured off the
    bones it is 5.7 degrees below horizontal on every body tried, robe and child
    included. KOTOR's own arms rest at 52 to 55.

    Positions are relative to the parent in the file, so this walks the tree.
    """
    return _tree(_parse(*read(entry)))[0]


def _tree(model) -> tuple[dict, dict]:
    """Every named bone's model-space position, and who its parent is."""
    where: dict[str, np.ndarray] = {}
    parent: dict[str, str | None] = {}

    def walk(node, rotation, offset, above):
        here = offset + rotation @ np.asarray(
            node.position or (0.0, 0.0, 0.0), dtype=float)
        turned = rotation @ _quaternion(node.orientation or (1, 0, 0, 0))
        if node.name:
            where[node.name] = here
            parent[node.name] = above
        for child in node.children or []:
            walk(child, turned, here, node.name or above)

    walk(model.root, np.eye(3), np.zeros(3), None)
    return where, parent


# What KOTOR's own arms do. Measured off the game's bones the same way
# `arm_rest` measures Jade's: 52.3 and 53.2 degrees below horizontal on every
# male player body, 54.6 and 57.0 on every female one. One number for both is
# close enough - the shoulder is a ball joint and two degrees of it is nothing
# beside the forty-seven this has to close.
KOTOR_ARM_REST = 53.0


def _rodrigues(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """The rotation taking unit vector `a` to unit vector `b`."""
    axis = np.cross(a, b)
    sin = float(np.linalg.norm(axis))
    cos = float(np.dot(a, b))
    if sin < 1e-9:
        # Parallel, or exactly opposed - and nothing here ever asks for the
        # second, so the arbitrary axis it would need is not worth choosing.
        return np.eye(3)
    axis = axis / sin
    K = np.array([[0.0, -axis[2], axis[1]],
                  [axis[2], 0.0, -axis[0]],
                  [-axis[1], axis[0], 0.0]])
    return np.eye(3) + sin * K + (1.0 - cos) * (K @ K)


def _below(parent: dict, root: str) -> set:
    """`root` and everything hanging off it."""
    out = {root}
    growing = True
    while growing:
        growing = False
        for name, above in parent.items():
            if above in out and name not in out:
                out.add(name)
                growing = True
    return out


def repose(model, degrees: float = KOTOR_ARM_REST) -> dict:
    """How to swing each arm down, bone by bone: `name -> (pivot, rotation)`.

    Jade stands its people in a T-pose and KOTOR's rest is an A-pose, so a Jade
    body dropped onto KOTOR's skeleton has its arms out sideways while the bones
    driving them point down and forty-seven degrees of the arm is somewhere the
    engine will never put it.

    Each arm turns about its own shoulder, in the plane the arm already lies in,
    so an arm carried a little forward stays carried a little forward. The
    clavicle stays where it is: KOTOR moves the bicep, not the collar.
    """
    where, parent = _tree(model)
    out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for side in ("L", "R"):
        top, hand = f"BLArmUppe{side}01", f"Hand{side}"
        if top not in where or hand not in where:
            continue
        pivot = where[top]
        along = where[hand] - pivot
        length = float(np.linalg.norm(along))
        if length < 1e-6:
            continue
        along = along / length
        flat = np.array([along[0], along[1], 0.0])
        reach = float(np.linalg.norm(flat))
        if reach < 1e-6:                       # already hanging straight down
            continue
        angle = np.radians(degrees)
        target = np.cos(angle) * (flat / reach) + np.sin(angle) * np.array(
            [0.0, 0.0, -1.0])
        turn = _rodrigues(along, target)
        for name in _below(parent, top):
            out[name] = (pivot, turn)
    return out


def _skin(points: np.ndarray, found, names: list, swing: dict) -> np.ndarray:
    """Move vertices with the bones they are weighted to.

    Plain linear blend skinning. A vertex weighted half to the bicep and half to
    the chest travels half the way, which is what keeps the shoulder from
    tearing open when the arm comes down.
    """
    skin = getattr(found, "skin", None)
    if skin is None or not skin.vertex_weights:
        return points
    out = points.copy()
    for i, weights in enumerate(skin.vertex_weights):
        if not weights or i >= len(points):
            continue
        here = points[i]
        moved = np.zeros(3)
        total = 0.0
        for index, weight in weights:
            total += weight
            name = names[index] if 0 <= index < len(names) else None
            turn = swing.get(name)
            if turn is None:
                moved += weight * here
            else:
                pivot, rotation = turn
                moved += weight * (pivot + rotation @ (here - pivot))
        if total > 1e-6:
            out[i] = moved / total
    return out


def arm_rest(entry: Entry) -> float | None:
    """How far below horizontal this model's arms rest, in degrees.

    KOTOR's own bodies rest at 52-55; Jade's at about 6, which is the gap a
    ported body has to close before its arms land where the bones are.
    """
    bones = skeleton(entry)
    shoulder, hand = bones.get("BLArmUppeL01"), bones.get("HandL")
    if shoulder is None or hand is None:
        return None
    v = hand - shoulder
    length = float(np.linalg.norm(v))
    if length < 1e-6:
        return None
    v = v / length
    return float(np.degrees(np.arctan2(-v[2], abs(v[0]))))


# --- into KOTOR's mesh nodes ------------------------------------------------

# KOTOR will not skin one mesh to more than seventeen bones. Every skinned mesh
# in the game obeys it: across all 2832 models in the K1 library the counts run
# 14 (245 meshes), 15 (147), 16 (176), 17 (21), and nothing above. A Jade body
# weights one mesh to 45, so it cannot be a KOTOR mesh until it is cut up.
BONE_CAP = 17

# An influence this far below its vertex's total contributes nothing you can
# see, and each one can drag a whole extra bone into a mesh's map. Dropping
# them is worth about one bone per body.
WEIGHT_FLOOR = 0.02

# Where KOTOR cuts a body up, and so where we do. `P_CarthBB` is the four-way
# version - Torso, LArm, RArm, Legs - and `PMBBM` the three-way, with the legs
# left inside the torso. Four is the safer shape: the torso is the crowded one,
# because every limb's first bone has to be in it for the joint to bend.
#
# The feet are named separately because Jade hangs them off the model root
# rather than off the leg they belong to - walk the tree from `FootBallL` and
# you arrive at the body, not at `LegLoweL`. Left to the tree they would sort
# into the torso and drag the foot bones up with them.
LIMB_ROOTS = {
    "BLArmUppeL01": "LArm", "BLArmUppeR01": "RArm",
    "LegUppeL": "Legs", "LegUppeR": "Legs",
    "FootBallL": "Legs", "FootBallR": "Legs",
}
TORSO = "Torso"


@dataclass
class Part:
    """One KOTOR mesh node: geometry of its own, and a bone map that fits."""

    name: str
    limb: str = TORSO
    source: str = ""                               # the Jade mesh it came from
    positions: list = field(default_factory=list)
    faces: list = field(default_factory=list)
    uvs: list = field(default_factory=list)
    normals: list = field(default_factory=list)
    bones: list = field(default_factory=list)      # KOTOR bone names
    weights: list = field(default_factory=list)    # per vertex: (bone slot, weight)
    material: int | None = None


def _climb(name, parent: dict, table: dict, fallback=None):
    """What `name` maps to, or what its nearest mapped ancestor maps to.

    Jade weights vertices to things that are not joints - collision proxies,
    weapon hooks, dangly hair, the face rig - and every one of them hangs
    directly off a real bone. Walking up is what saves this from being forty
    special cases, and it is also right: a hook sits at its parent.
    """
    walk, seen = name, set()
    while walk is not None and walk not in seen:
        seen.add(walk)
        if walk in table:
            return table[walk]
        walk = parent.get(walk)
    return fallback


def _pack(faces: list, cap: int) -> list:
    """Faces into as few nodes as will hold them, none over the bone cap.

    The limb split gets almost everything under on its own - across all 112
    Jade bodies this opens 24 extra nodes in total - but "almost" is not a
    guarantee, and a mesh one bone over the cap is a mesh the engine drops.

    Faces are offered in order of the bones they touch, so the ones that share
    bones are tried together and a node fills with a region rather than a
    scatter.
    """
    bins: list = []
    for face in sorted(faces, key=lambda f: (sorted(f[1])[0], -len(f[1]))):
        for used, members in bins:
            if len(used | face[1]) <= cap:
                used |= face[1]
                members.append(face)
                break
        else:
            bins.append((set(face[1]), [face]))
    return bins


def partition(model, *, cap: int = BONE_CAP, floor: float = WEIGHT_FLOOR,
              pose: float | None = None, orient: bool = True,
              scale: float = BODY_SCALE) -> list:
    """Cut a Jade body into mesh nodes KOTOR can skin.

    Jade ships a body as one or two meshes weighted to 45 bones. KOTOR wants
    several, none of them touching more than `cap`, so this splits by limb the
    way the game's own bodies are split: a vertex belongs to the limb of the
    bone that pulls hardest on it, and a triangle to the limb most of its
    corners agree on.

    Meshes that are not skinned keep their shape and become rigid parts, bound
    wholly to the one bone they hang from.

    Positions come out where `mesh` puts them - KOTOR's axes, KOTOR's size -
    because that is the space the parts are for.
    """
    names = list(getattr(model, "names", ()) or ())
    into = BODY_FACING if orient else np.eye(3)
    _where, parent = _tree(model)
    swing = repose(model, pose) if pose is not None else {}
    out: list = []

    def bone_of(index: int) -> str:
        raw = names[index] if 0 <= index < len(names) else ""
        return _climb(raw, parent, BONE_NAMES, "torso_g")

    def limb_of(index: int) -> str:
        raw = names[index] if 0 <= index < len(names) else ""
        return _climb(raw, parent, LIMB_ROOTS, TORSO)

    def gather(limb, members, bones, world, weights, uvs, normals, found, source):
        """One part's own vertices, renumbered from zero.

        A vertex on a seam belongs to two parts and is written into both. That
        is how KOTOR's own bodies are built, and because both copies keep the
        same weights the seam still moves as one when the model animates.
        """
        part = Part(name="", limb=limb, source=source, bones=sorted(bones),
                    material=getattr(found, "material_id", None) or None)
        slot = {b: i for i, b in enumerate(part.bones)}
        seen: dict = {}
        for corners, _touched in members:
            face = []
            for v in corners:
                if v not in seen:
                    seen[v] = len(part.positions)
                    placed = (into @ world[v]) * scale
                    part.positions.append(tuple(float(x) for x in placed))
                    part.weights.append([(slot[b], w) for b, w in weights[v]])
                    if uvs is not None and v < len(uvs):
                        part.uvs.append(turn_uv(uvs[v]))
                    if normals is not None and v < len(normals):
                        part.normals.append(tuple(float(x) for x in normals[v][:3]))
                face.append(seen[v])
            part.faces.append(tuple(face))
        return part

    def cut(node, found, rotation, offset):
        raw = np.asarray(found.vertices, dtype=float)[:, :3]
        raw = np.where(np.isfinite(raw), raw, 0.0)
        world = raw @ rotation.T + offset
        if swing:
            world = _skin(world, found, names, swing)

        skin = getattr(found, "skin", None)
        if skin is None or not skin.vertex_weights:
            # Rigid: the whole mesh rides the one bone it hangs from.
            anchor = _climb(node.name, parent, BONE_NAMES, None) or _climb(
                parent.get(node.name), parent, BONE_NAMES, "torso_g")
            weights = [[(anchor, 1.0)] for _ in range(len(world))]
            limbs = [_climb(node.name, parent, LIMB_ROOTS, TORSO)] * len(world)
        else:
            weights, limbs = [], []
            for ws in skin.vertex_weights:
                total = sum(w for _i, w in ws) or 1.0
                kept = [(i, w) for i, w in ws if w / total >= floor] or list(ws)
                merged: dict = {}
                for index, weight in kept:
                    bone = bone_of(index)
                    merged[bone] = merged.get(bone, 0.0) + weight
                share = sum(merged.values()) or 1.0
                weights.append([(b, w / share) for b, w in merged.items()])
                best = max(kept, key=lambda kv: kv[1])[0] if kept else 0
                limbs.append(limb_of(best))
            short = len(world) - len(weights)
            if short > 0:
                weights += [[("torso_g", 1.0)] for _ in range(short)]
                limbs += [TORSO] * short

        grouped: dict = {}
        for tri in (found.triangles or ()):
            corners = tuple(int(v) for v in tri[:3])
            if any(v >= len(world) for v in corners):
                continue
            vote: dict = {}
            for v in corners:
                vote[limbs[v]] = vote.get(limbs[v], 0) + 1
            limb = max(vote.items(), key=lambda kv: (kv[1], kv[0] == TORSO))[0]
            touched = {b for v in corners for b, _w in weights[v]}
            grouped.setdefault(limb, []).append((corners, touched))

        uvs = found.uv_layers[0] if getattr(found, "uv_layers", None) else None
        normals = getattr(found, "normals", None)
        for limb in (TORSO, "LArm", "RArm", "Legs"):
            if limb not in grouped:
                continue
            for bones, members in _pack(grouped[limb], cap):
                out.append(gather(limb, members, bones, world, weights, uvs,
                                  normals, found, node.name or ""))

    def walk(node, rotation, offset):
        turn = rotation @ _quaternion(node.orientation or (1, 0, 0, 0))
        here = offset + rotation @ np.asarray(
            node.position or (0.0, 0.0, 0.0), dtype=float)
        found = node.mesh
        if found is not None and found.render and found.vertices:
            cut(node, found, turn, here)
        for child in node.children or []:
            walk(child, turn, here)

    walk(model.root, np.eye(3), np.zeros(3))

    # A body can arrive as several meshes - a figure, a chestplate, a vein of
    # trim - and each of them has a torso's worth of triangles in it. Naming
    # happens here, once, so two of them cannot both be called `Torso`: MDL
    # nodes are addressed by name and a duplicate is a model the game misreads.
    tally: dict = {}
    for part in out:
        tally[part.limb] = tally.get(part.limb, 0) + 1
        part.name = part.limb if tally[part.limb] == 1 else (
            part.limb + str(tally[part.limb]))
    return out


def scene(entry: Entry, *, install=None, scale: float | None = None,
          pose: float | None = None):
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
    found = mesh(*read(entry), scale=scale, kind=entry.kind, pose=pose)
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
