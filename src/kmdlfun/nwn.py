"""Neverwinter Nights models, in the conventions the rest of this tool uses.

NWN is the game KOTOR's engine grew out of, and it shows: the file starts with
the same twelve-byte wrapper, the model header holds the same fields in the
same order, the node flags are the same bits, and a face record is the same
thirty-two bytes with the vertex indices at the same place inside it. Reading
it is a matter of knowing where the fields moved to, not of learning a format.

**Where they moved to.** Measured against all 32,832 models in the install,
not taken from documentation:

  model name field    64 bytes, where KOTOR's is 32
  node header        112 bytes, where KOTOR's is 80
  texture name        64 bytes, where KOTOR's is 32

Those three differences push every later structure along, which is why the
splice engine can never edit an NWN model in place and never will - the same
verdict `jade.py` records for Jade Empire, and for the same reason. What NWN
is good for is *geometry*, and geometry has a route in already: it becomes a
head pack, and from there it is the path every sculpt and Blender export
takes.

**The MDX is laid out differently, and more simply.** KOTOR interleaves each
vertex's position, normal and texture coordinates into one record and gives
the stride in the header. NWN keeps three separate blocks and gives the file
offset of each, so there is no stride to get wrong:

    0      positions          12 bytes each
    ...    texture coords      8 bytes each
    ...    normals            12 bytes each
    ...    triangle indices    2 bytes each

The last block repeats what the MDL's own face array already says - checked
across the corpus and they agree - so this reads the faces from the MDL, the
way it does for KOTOR.

**MDL and MDX arrive in one file.** KOTOR ships them as two resources. NWN
concatenates them behind the wrapper, which is what `split` is for.

**Scale is not a problem; proportion is.** Both games measure in the same
units and an NWN head arrives exactly the right height. It also arrives a
third too wide, because NWN heads carry their hair and are drawn chunkier -
see `HEAD_SCALE`, which is a compromise rather than a conversion. A placeable
needs no correction at all.

**About a third of the models are text.** 7,234 of 32,832 are ASCII MDL rather
than binary - almost all of them tileset pieces. They are recognised and
reported rather than parsed, because nothing in the chosen scope needs them:
every player head and every placeable in the base game is binary.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

# --- the resource types this needs, in Aurora's numbering -------------------

MDL_TYPE = 2002
TGA_TYPE = 3
PLT_TYPE = 6

KEY_NAMES = ("nwn_base.key", "nwn_retail.key")
DATA_DIR = "data"

# --- where the fields are ---------------------------------------------------

FILE_HEADER_SIZE = 12
# Model header: two function pointers, then a 64-byte name.
MODEL_NAME_AT = 8
MODEL_NAME_SIZE = 64
ROOT_NODE_AT = 72
NODE_COUNT_AT = 76

NODE_HEADER_SIZE = 112
NODE_NAME_AT = 32          # inside the node header
NODE_NAME_SIZE = 32
NODE_CHILDREN_AT = 72      # offset, count, allocated
NODE_FLAGS_AT = 108

# Offsets inside the trimesh subheader, which follows the node header.
MESH_FACES_AT = 8          # offset, count, allocated
MESH_BOUND_MIN_AT = 20
MESH_BOUND_MAX_AT = 32
MESH_TEXTURE_AT = 120
MESH_TEXTURE_SIZE = 64
MESH_VERTEX_COUNT_AT = 448   # a u16; the u16 after it counts textures
MESH_MDX_POSITIONS_AT = 444
MESH_MDX_UVS_AT = 452
MESH_MDX_NORMALS_AT = 468

FACE_SIZE = 32
FACE_INDICES_AT = 26       # inside a face record

# The same bits KOTOR uses, which is the whole reason this was worth trying.
HAS_MESH = 0x0020
HAS_SKIN = 0x0040
HAS_AABB = 0x0200

NO_OFFSET = -1

# --- what a model is --------------------------------------------------------

HEAD = "head"
PLACEABLE = "placeable"
OTHER = "other"

# Heads are named `p<gender><race><phenotype>_head<nnn>`: two genders, six
# races and two body builds. Phenotype 2 is the heavy build's head and is a
# near-duplicate of phenotype 0's, so both are offered but 0 comes first.
HEAD_RACES = "adegho"      # halfling, dwarf, elf, gnome, human, half-orc
PLACEABLE_PREFIX = "plc_"

# Both games measure in the same units, so nothing here is a unit conversion.
# A placeable is carried across at its own size and looks right.
SCALE = 1.0

# A head is not, and the reason is proportion rather than scale. Measured
# across 429 NWN heads against 105 of KOTOR's:
#
#     height   0.271 against 0.271   the same
#     depth    0.283 against 0.235   NWN is 20% deeper
#     width    0.219 against 0.164   NWN is 34% wider
#
# NWN heads carry their hair as part of the head and are drawn chunkier, so
# one arrives the right height and far too wide. Width is what binds on 328
# of the 429; depth on 99; height on two.
#
# A uniform scale cannot fix a difference in proportion - it can only trade
# one axis against another - and squashing the width instead would distort
# the face, which `headspec` says plainly it will not do.
#
# So this is the smallest correction that brings the median head under
# `headspec.OVERSIZE_LIMIT`, the point past which a head clips the body:
#
#     scale   median worst-axis overshoot   heads passing the size check
#     1.00                1.50                          16%
#     0.85                1.27                          46%
#     0.80                1.20                          55%
#     0.70                1.12                          62%
#
# 0.70 gets a few more through and looks visibly shrunken beside the body;
# 1.00 looks right and mostly fails. 0.80 is the compromise, and it is a
# number rather than a constant because "fits without clipping" and "looks
# the right size next to a KOTOR head" are genuinely different wants and
# nothing here can serve both. A head that still fails wants a lower one.
HEAD_SCALE = 0.80

# Which way a head looks, in KOTOR's terms. Both engines are Z-up, so this is
# the only axis question left, and it is settled by looking at a render
# rather than by reading a bounding box - a nose and the back of a skull both
# stick out.
FACING = "+y"

# A texture filename becomes a resref, and that field is sixteen characters
# with two spent on the `01` suffix.
RESREF_STEM = 14

# PLT layer numbering, in the order the format stores it. A head uses skin,
# hair and occasionally tattoo; the rest are for clothing and armour.
PLT_LAYERS = ("skin", "hair", "metal1", "metal2", "cloth1",
              "cloth2", "leather1", "leather2", "tattoo1", "tattoo2")
PLT_PALETTES = {
    "skin": "pal_skin01", "hair": "pal_hair01",
    "metal1": "pal_armor01", "metal2": "pal_armor02",
    "cloth1": "pal_cloth01", "cloth2": "pal_cloth01",
    "leather1": "pal_leath01", "leather2": "pal_leath01",
    "tattoo1": "pal_tattoo01", "tattoo2": "pal_tattoo01",
}
PLT_MAGIC = b"PLT V1  "
PLT_SIZE_AT = 16
PLT_DATA_AT = 24
# Row 0 of every palette is the ordinary choice, so a head asked for without
# an opinion comes out looking like a person rather than like a swatch.
DEFAULT_COLOURS = {name: 0 for name in PLT_LAYERS}
# What a pixel gets when its layer has no palette. Grey, and obviously wrong,
# because a silently plausible colour is harder to notice than a bad one.
MISSING_COLOUR = 200

TGA_HEADER_SIZE = 18
TGA_TRUECOLOUR = 2         # uncompressed RGB; the only kind read or written
TGA_TOP_ROW_FIRST = 0x20   # the descriptor bit saying which way up it is


class NwnError(RuntimeError):
    """The file is not what this understands it to be. Never guess."""


# --- finding resources ------------------------------------------------------


@dataclass(frozen=True)
class Source:
    """Where one resource sits: which archive, and where inside it."""

    archive: Path
    offset: int
    size: int

    def read(self) -> bytes:
        with self.archive.open("rb") as f:
            f.seek(self.offset)
            return f.read(self.size)


@dataclass(frozen=True)
class Entry:
    """One model in the game's archives."""

    resref: str
    kind: str
    source: Source

    @property
    def archive(self) -> Path:
        return self.source.archive

    @property
    def label(self) -> str:
        return self.resref


def key_path(install) -> Path:
    """The KEY file that indexes the game, wherever this build keeps it.

    NWN:EE puts it under `data/`; older builds put it beside the executable.
    Both are checked rather than one being assumed, because the folder a
    person picks is the game folder either way.
    """
    root = Path(install)
    for where in (root / DATA_DIR, root):
        for name in KEY_NAMES:
            if (where / name).is_file():
                return where / name
    raise NwnError(f"no {' or '.join(KEY_NAMES)} under {root}")


def index_of(install) -> dict[tuple[str, int], Source]:
    """Every resource in the install, by name and type.

    Aurora's KEY/BIF, read here rather than through PyKotor: PyKotor assumes
    KOTOR's packing of the resource id and raises on NWN's, and the format is
    two tables and a header.
    """
    key = key_path(install)
    raw = key.read_bytes()
    if raw[:4] != b"KEY ":
        raise NwnError(f"{key.name} does not start with KEY")
    bif_count, key_count, files_at, keys_at = struct.unpack_from("<4I", raw, 8)

    root = key.parent.parent if key.parent.name.lower() == DATA_DIR else key.parent
    archives: list[Path] = []
    for i in range(bif_count):
        _size, name_at, name_len, _drives = struct.unpack_from(
            "<IIHH", raw, files_at + i * 12)
        name = raw[name_at:name_at + name_len].split(b"\0")[0].decode("ascii")
        archives.append(root / name.replace("\\", "/"))

    # The key table names 113,489 resources across 60 archives, and each row
    # says only which archive and which row of *its* table to look in. Read
    # every archive's table once, up front: doing it a row at a time is
    # 113,489 file opens and eleven seconds, against a fifth of a second here.
    tables: dict[int, bytes] = {}
    found: dict[tuple[str, int], Source] = {}
    for i in range(key_count):
        at = keys_at + i * 22
        resref = raw[at:at + 16].split(b"\0")[0].decode("ascii", "replace").lower()
        restype, resid = struct.unpack_from("<HI", raw, at + 16)
        bif, within = resid >> 20, resid & 0xFFFFF
        if bif >= len(archives):
            continue                # a key row pointing at no archive
        if bif not in tables:
            tables[bif] = _resource_table(archives[bif])
        row = within * 16
        table = tables[bif]
        if row + 16 > len(table):
            continue                # an archive this build does not ship
        _id, offset, size, _restype = struct.unpack_from("<4I", table, row)
        found[(resref, restype)] = Source(
            archive=archives[bif], offset=offset, size=size)
    return found


def _resource_table(archive: Path) -> bytes:
    """One BIF's resource table, without any of the payloads behind it."""
    try:
        with archive.open("rb") as f:
            head = f.read(20)
            if len(head) < 20:
                return b""
            count, _fixed, table_at = struct.unpack_from("<3I", head, 8)
            f.seek(table_at)
            return f.read(count * 16)
    except OSError:
        return b""                  # an archive this build does not ship



def kind_of(resref: str) -> str:
    """What a model is, by the naming the game is consistent about.

    NWN's resrefs are as reliable as Jade's: 434 heads match one pattern and
    569 placeables share one prefix, with nothing else in the install using
    either.
    """
    name = resref.lower()
    if name.startswith(PLACEABLE_PREFIX):
        return PLACEABLE
    if _is_head_name(name):
        return HEAD
    return OTHER


def _is_head_name(name: str) -> bool:
    stem, _, tail = name.partition("_")
    if not tail.startswith("head") or not tail[4:].isdigit():
        return False
    if len(stem) != 4 or stem[0] != "p":
        return False
    return stem[1] in "fm" and stem[2] in HEAD_RACES and stem[3].isdigit()


def catalogue(install, *, kinds=(HEAD, PLACEABLE), index=None) -> list[Entry]:
    """The models worth offering, best kind first.

    `index` is accepted so a caller that already read the KEY does not read it
    again - it lists 113,489 resources and costs about a second.
    """
    found = index if index is not None else index_of(install)
    out = []
    for (resref, restype), source in found.items():
        if restype != MDL_TYPE:
            continue
        kind = kind_of(resref)
        if kind in kinds:
            out.append(Entry(resref=resref, kind=kind, source=source))
    return sorted(out, key=lambda e: (e.kind != HEAD, e.resref))


# --- reading a model --------------------------------------------------------


@dataclass
class Node:
    """One node of a model, with only what geometry needs read out of it."""

    offset: int
    name: str
    flags: int
    parent: int | None = None

    @property
    def is_mesh(self) -> bool:
        # A walkmesh is a mesh by the flag and scenery by intent: it is the
        # invisible box the engine collides against, and putting it in a head
        # pack would weld a cube to somebody's face.
        return bool(self.flags & HAS_MESH) and not (self.flags & HAS_AABB)


@dataclass
class Model:
    name: str = ""
    node_count: int = 0
    nodes: list[Node] = field(default_factory=list)
    mdl: bytes = b""
    mdx: bytes = b""


@dataclass
class Mesh:
    """Geometry in KOTOR's conventions, ready for a head pack.

    The same shape `jade.Mesh` has, because both feed the same head-pack
    writer. They are separate declarations rather than a shared one so that
    neither game's reader has to import the other's.
    """

    positions: list[tuple[float, float, float]] = field(default_factory=list)
    faces: list[tuple[int, int, int]] = field(default_factory=list)
    uvs: list[tuple[float, float]] = field(default_factory=list)
    normals: list[tuple[float, float, float]] = field(default_factory=list)
    textures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def bounds(self):
        if not self.positions:
            return None, None
        lo = tuple(min(p[i] for p in self.positions) for i in range(3))
        hi = tuple(max(p[i] for p in self.positions) for i in range(3))
        return lo, hi


def is_ascii_model(raw: bytes) -> bool:
    """Whether this is a text MDL rather than a compiled one.

    The wrapper's first word is zero in every binary model and is the first
    four characters of a comment in every text one.
    """
    return len(raw) >= 4 and raw[:4] != b"\0\0\0\0"


def split(raw: bytes) -> tuple[bytes, bytes]:
    """The MDL body and the MDX block, which NWN keeps in one file."""
    if len(raw) < FILE_HEADER_SIZE:
        raise NwnError("shorter than the 12-byte wrapper")
    if is_ascii_model(raw):
        raise NwnError("this is a text MDL, which this reader does not parse")
    zero, mdl_size, mdx_size = struct.unpack_from("<3I", raw, 0)
    if zero != 0:
        raise NwnError(f"wrapper word 0 is {zero}, expected 0")
    if FILE_HEADER_SIZE + mdl_size + mdx_size != len(raw):
        raise NwnError(
            f"wrapper says 12+{mdl_size}+{mdx_size}, file is {len(raw)}")
    at = FILE_HEADER_SIZE + mdl_size
    return raw[FILE_HEADER_SIZE:at], raw[at:]


def _text(buf: bytes, at: int, size: int) -> str:
    """A fixed-width name, stopping at the first NUL.

    The bytes after it are whatever the compiler last had in that buffer -
    floats, other model names - so reading the whole field would hand back
    garbage. Every name in the format is written this way.
    """
    return buf[at:at + size].split(b"\0")[0].decode("ascii", "replace")


def parse(raw: bytes) -> Model:
    """The node tree of one binary model."""
    mdl, mdx = split(raw)
    if len(mdl) < NODE_COUNT_AT + 4:
        raise NwnError("no room for a model header")
    root, count = struct.unpack_from("<2I", mdl, ROOT_NODE_AT)
    model = Model(name=_text(mdl, MODEL_NAME_AT, MODEL_NAME_SIZE),
                  node_count=count, mdl=mdl, mdx=mdx)
    _walk(model, root, None, set())
    return model


def _walk(model: Model, at: int, parent: int | None, seen: set) -> None:
    if at in seen:
        raise NwnError(f"the node at {at} is its own ancestor")
    if at + NODE_HEADER_SIZE > len(model.mdl):
        raise NwnError(f"the node at {at} runs past the end of the file")
    seen.add(at)
    mdl = model.mdl
    model.nodes.append(Node(
        offset=at,
        name=_text(mdl, at + NODE_NAME_AT, NODE_NAME_SIZE),
        flags=struct.unpack_from("<I", mdl, at + NODE_FLAGS_AT)[0],
        parent=parent))
    child_at, child_count, _alloc = struct.unpack_from(
        "<3I", mdl, at + NODE_CHILDREN_AT)
    if not child_count:
        return
    if child_at + child_count * 4 > len(mdl):
        raise NwnError(f"the child list of the node at {at} runs past the end")
    for k in range(child_count):
        _walk(model, struct.unpack_from("<I", mdl, child_at + k * 4)[0], at, seen)


def mesh(raw: bytes, *, scale: float = SCALE, kind: str = OTHER) -> Mesh:
    """Every visible triangle of a model, welded into one mesh.

    One mesh rather than one per node, because a head pack holds one and
    because an NWN head is a single node anyway. A placeable is not - the
    four-mesh crates are the normal case - so the nodes are concatenated with
    their face indices shifted, which is what the head-pack writer expects.
    """
    if kind == HEAD and scale == SCALE:
        scale = HEAD_SCALE
    model = parse(raw)
    out = Mesh()
    for node in model.nodes:
        if not node.is_mesh:
            continue
        _add_node(model, node, out, scale)
    if not out.positions:
        out.notes.append("no visible geometry - every node is a dummy or a "
                         "walkmesh")
    return out


def _add_node(model: Model, node: Node, out: Mesh, scale: float) -> None:
    mdl, mdx = model.mdl, model.mdx
    t = node.offset + NODE_HEADER_SIZE
    if t + MESH_MDX_NORMALS_AT + 4 > len(mdl):
        out.notes.append(f"{node.name}: the mesh header is cut short")
        return
    count = struct.unpack_from("<H", mdl, t + MESH_VERTEX_COUNT_AT)[0]
    positions_at, uvs_at, normals_at = (
        struct.unpack_from("<i", mdl, t + o)[0]
        for o in (MESH_MDX_POSITIONS_AT, MESH_MDX_UVS_AT, MESH_MDX_NORMALS_AT))
    faces_at, face_count, _alloc = struct.unpack_from("<3I", mdl, t + MESH_FACES_AT)
    if not count or positions_at == NO_OFFSET:
        return

    first = len(out.positions)
    if not _block_fits(mdx, positions_at, count, 12):
        out.notes.append(f"{node.name}: its vertices are not in the file")
        return
    for k in range(count):
        x, y, z = struct.unpack_from("<3f", mdx, positions_at + k * 12)
        out.positions.append((x * scale, y * scale, z * scale))

    if uvs_at != NO_OFFSET and _block_fits(mdx, uvs_at, count, 8):
        for k in range(count):
            out.uvs.append(struct.unpack_from("<2f", mdx, uvs_at + k * 8))
    elif out.uvs:
        # Every node has to contribute the same lists or the indices stop
        # lining up, so a node with no texture coordinates gets placeholders
        # rather than being left out of the array.
        out.uvs.extend([(0.0, 0.0)] * count)

    if normals_at != NO_OFFSET and _block_fits(mdx, normals_at, count, 12):
        for k in range(count):
            out.normals.append(struct.unpack_from("<3f", mdx, normals_at + k * 12))
    elif out.normals:
        out.normals.extend([(0.0, 0.0, 1.0)] * count)

    if face_count and faces_at + face_count * FACE_SIZE <= len(mdl):
        for k in range(face_count):
            a, b, c = struct.unpack_from(
                "<3H", mdl, faces_at + k * FACE_SIZE + FACE_INDICES_AT)
            if max(a, b, c) >= count:
                continue        # a face pointing outside its own node
            out.faces.append((first + a, first + b, first + c))

    texture = _text(mdl, t + MESH_TEXTURE_AT, MESH_TEXTURE_SIZE).lower()
    if texture and texture not in out.textures and texture != "null":
        out.textures.append(texture)


def _block_fits(buf: bytes, at: int, count: int, stride: int) -> bool:
    return at >= 0 and at + count * stride <= len(buf)


# --- textures ---------------------------------------------------------------
#
# A head has no picture of itself anywhere in the game. Its skin is a `.plt`:
# two bytes per pixel, one saying which layer this pixel belongs to - skin,
# hair, tattoo - and one saying how light it is. The colours live in seven
# palette images shared by every model in the game, and that is how NWN lets
# one face be any of 176 skin tones.
#
# A palette is a 256 x 176 ramp. Across is the value the PLT stored, down is
# which of the 176 colours somebody picked, so flattening a PLT is a lookup
# and not a multiplication - the ramp already knows what dark skin does to a
# highlight. Row 0 of every palette is the ordinary choice, which is what a
# head asked for without an opinion gets.


def palette_image(install, name: str, *, index=None):
    """One palette as an array of shape (colours, values, 3)."""
    import numpy as np

    found = index if index is not None else index_of(install)
    source = found.get((name.lower(), TGA_TYPE))
    if source is None:
        return None
    pixels, width, height = read_tga(source.read())
    if not width:
        return None
    return np.frombuffer(pixels, dtype=np.uint8).reshape(height, width, 3)


def palettes(install, *, index=None) -> dict[str, object]:
    """Every palette a PLT can refer to, read once and shared."""
    found = index if index is not None else index_of(install)
    out = {}
    for layer in PLT_LAYERS:
        out[layer] = palette_image(install, PLT_PALETTES[layer], index=found)
    return out


def plt_to_tga(raw: bytes, ramps: dict, *, colours=None) -> bytes:
    """A paletted texture flattened into an ordinary picture.

    `colours` picks a row per layer - a skin tone, a hair colour - by the same
    numbering the character creator uses. Anything not named takes row 0.
    """
    import numpy as np

    if raw[:8] != PLT_MAGIC:
        raise NwnError("not a PLT texture")
    width, height = struct.unpack_from("<2I", raw, PLT_SIZE_AT)
    need = PLT_DATA_AT + width * height * 2
    if len(raw) < need:
        raise NwnError(f"PLT says {width}x{height} but the file is too short")
    pairs = np.frombuffer(raw, dtype=np.uint8, count=width * height * 2,
                          offset=PLT_DATA_AT).reshape(-1, 2)
    values, layers = pairs[:, 0], pairs[:, 1]
    wanted = dict(DEFAULT_COLOURS)
    wanted.update(colours or {})

    out = np.full((width * height, 3), MISSING_COLOUR, dtype=np.uint8)
    for i, layer in enumerate(PLT_LAYERS):
        ramp = ramps.get(layer)
        here = layers == i
        if ramp is None or not here.any():
            continue
        row = min(max(int(wanted.get(layer, 0)), 0), ramp.shape[0] - 1)
        out[here] = ramp[row][np.minimum(values[here], ramp.shape[1] - 1)]
    return write_tga(out.tobytes(), width, height)


def read_texture(install, name: str, *, index=None, colours=None
                 ) -> tuple[str, bytes] | None:
    """One texture by resref, as TGA bytes, whichever way the game stores it.

    The PLT is tried first. A head often ships a `.tga` under the same name
    as well, but it is a 64x64 greyscale the engine uses for something else -
    taking it because it was found first put a grey smudge on every face.
    """
    found = index if index is not None else index_of(install)
    key = name.lower()
    paletted = found.get((key, PLT_TYPE))
    if paletted is not None:
        return name, plt_to_tga(paletted.read(),
                                palettes(install, index=found),
                                colours=colours)
    plain = found.get((key, TGA_TYPE))
    if plain is not None:
        raw = plain.read()
        pixels, width, height = read_tga(raw)
        # Handed back as it is when it is already an ordinary picture, and
        # re-encoded when it is not, so the caller always gets a TGA it can
        # write into a head pack.
        return (name, raw) if width and raw[2] == TGA_TRUECOLOUR else (
            (name, write_tga(pixels, width, height)) if width else None)
    return None


def texture_for(install, found: Mesh, *, index=None, colours=None
                ) -> tuple[str, bytes] | None:
    """The picture for a mesh, by the first texture any of its nodes names."""
    for name in found.textures:
        got = read_texture(install, name, index=index, colours=colours)
        if got is not None:
            return got
    return None


def read_tga(raw: bytes) -> tuple[bytes, int, int]:
    """RGB pixels out of an uncompressed TGA, top row first.

    Only what the game's own palettes are: uncompressed truecolour, 24 or 32
    bit. Anything else returns nothing rather than a plausible wrong answer.
    """
    import numpy as np

    if len(raw) < TGA_HEADER_SIZE:
        return b"", 0, 0
    id_len, colour_map, image_type = raw[0], raw[1], raw[2]
    width, height = struct.unpack_from("<2H", raw, 12)
    depth, descriptor = raw[16], raw[17]
    if image_type != TGA_TRUECOLOUR or colour_map or depth not in (24, 32):
        return b"", 0, 0
    step = depth // 8
    at = TGA_HEADER_SIZE + id_len
    if len(raw) < at + width * height * step:
        return b"", 0, 0
    flat = np.frombuffer(raw, dtype=np.uint8, count=width * height * step,
                         offset=at).reshape(height, width, step)
    rgb = flat[:, :, 2::-1] if step == 3 else flat[:, :, 2::-1]
    if not descriptor & TGA_TOP_ROW_FIRST:
        rgb = rgb[::-1]
    return np.ascontiguousarray(rgb).tobytes(), width, height


def write_tga(rgb: bytes, width: int, height: int) -> bytes:
    """An uncompressed 24-bit TGA, which is what a head pack takes."""
    import numpy as np

    header = bytes([0, 0, TGA_TRUECOLOUR, 0, 0, 0, 0, 0]) + struct.pack(
        "<4H", 0, 0, width, height) + bytes([24, TGA_TOP_ROW_FIRST])
    flat = np.frombuffer(rgb, dtype=np.uint8).reshape(height, width, 3)
    return header + np.ascontiguousarray(flat[:, :, ::-1]).tobytes()


# --- writing a model out ----------------------------------------------------


def to_pack(entry: Entry, out_dir, *, install=None, scale: float | None = None,
            name: str | None = None, with_texture: bool = True,
            colours=None, index=None, facing: str = FACING) -> dict:
    """Write an NWN model out as a head pack the Custom head tab can build.

    The pack is the same shape a `.glb` import produces, so everything
    downstream - decimation, fitting, winding repair, the solidity check -
    applies unchanged. What is NWN-specific ends here.

    A placeable goes through the same door. It is not a head and nothing will
    fit it to a neck, but the pack is also how a mesh reaches the tool at all,
    and `target` in the manifest says which node it is meant for.
    """
    import json

    from kmdlswap import obj as kobj

    from . import headpack

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if scale is None:
        scale = HEAD_SCALE if entry.kind == HEAD else SCALE
    found = mesh(entry.source.read(), scale=scale, kind=entry.kind)

    kobj.write_obj(out_dir / "head.obj", found.positions, found.faces,
                   uvs=found.uvs or None, normals=found.normals or None,
                   name=out_dir.name)

    texture_file = None
    if with_texture and found.textures:
        root = install if install is not None else _install_of(entry)
        got = texture_for(root, found, index=index,
                          colours=colours) if root else None
        if got:
            source_name, data = got
            # Named from the model rather than the folder: the folder is the
            # caller's choice, and a resref field is sixteen characters, so
            # truncating the folder name lands in the wrong place and two
            # heads installed together end up sharing one face.
            texture_file = (entry.resref.strip("_").lower()
                            or out_dir.name.lower())[:RESREF_STEM] + "01"
            (out_dir / f"{texture_file}.tga").write_bytes(data)
            found.notes.append(f"texture {source_name} decoded from .plt"
                               if source_name != texture_file
                               else f"texture {source_name}")
        else:
            found.notes.append("no texture found - it will wear the host's")

    headpack.write_template(out_dir, name=name or entry.resref)
    manifest = out_dir / headpack.MANIFEST_NAME
    data = json.loads(manifest.read_text(encoding="utf-8"))
    # Both games are Z-up and measure in the same units, so the geometry is
    # already in KOTOR's conventions and needs no correction on the way in.
    data["up"] = "z"
    data["facing"] = facing
    data["target"] = "head" if entry.kind == HEAD else entry.resref
    data["notes"] = (f"imported from Neverwinter Nights {entry.resref}"
                     + (f" (x{scale:.3f})" if abs(scale - 1.0) > 1e-6 else ""))
    manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    return {
        "pack": out_dir,
        "resref": entry.resref,
        "kind": entry.kind,
        "vertices": len(found.positions),
        "triangles": len(found.faces),
        "uvs": len(found.uvs),
        "texture": texture_file,
        "notes": found.notes,
    }


def _install_of(entry: Entry):
    """The game folder an entry came out of, worked back from its archive.

    An `Entry` carries the archive it lives in, and the archive is either in
    the install root or one level down in `data/`, so the folder above the one
    holding a KEY is the answer.
    """
    for folder in entry.archive.parents:
        try:
            key_path(folder)
        except NwnError:
            continue
        return folder
    return None


# --- drawing one, to pick it by ---------------------------------------------


def scene(entry: Entry, *, install=None, index=None, scale: float | None = None,
          colours=None):
    """A drawable, *textured* scene for one model.

    `render.from_mesh` draws flat colour, which is enough to tell a crate from
    a barrel and nowhere near enough to choose a face: an NWN head is 160-odd
    triangles and carries its eyes, brows and mouth entirely in the texture,
    so untextured they are all the same grey mask. Building that texture means
    reaching back into the install for the palettes, which is why this is the
    one drawing function that needs the game folder.
    """
    import io

    import numpy as np
    from PIL import Image

    from . import render as krender

    if scale is None:
        scale = HEAD_SCALE if entry.kind == HEAD else SCALE
    found = mesh(entry.source.read(), scale=scale, kind=entry.kind)
    built = krender.from_mesh(found.positions, found.faces)
    if not len(built.faces) or not found.uvs:
        return built

    root = install if install is not None else _install_of(entry)
    got = texture_for(root, found, index=index, colours=colours) if root else None
    if not got:
        return built
    _name, data = got
    try:
        with Image.open(io.BytesIO(data)) as im:
            image = np.asarray(im.convert("RGB"), dtype=np.uint8)
    except Exception:  # noqa: BLE001 - an unreadable texture is not worth raising
        return built

    uvs = np.asarray(found.uvs, dtype=np.float64)
    if len(uvs) != len(built.positions):
        return built
    built.uvs = uvs
    built.textures = [image]
    built.face_texture = np.zeros(len(built.faces), dtype=np.int32)
    return built


def thumbnail(entry: Entry, *, size: int = 96, install=None, index=None,
              colours=None, root=None):
    """Draw one model's face and cache it, or None.

    `thumbs.render` cannot be reused: it parses its bytes as a KOTOR model.
    The caching rule is the same though - keyed on the bytes, so a redraw only
    happens when the model does. The chosen colours go into the key as well,
    because two skin tones are two different pictures of the same bytes.
    """
    import hashlib

    from . import render as krender
    from . import thumbs as kthumbs

    picked = "-".join(f"{k}{v}" for k, v in sorted((colours or {}).items()))
    digest = hashlib.md5(  # noqa: S324 - naming a cache file, not a secret
        entry.source.read() + picked.encode("utf-8")).hexdigest()
    folder = Path(root) if root else kthumbs.cache_dir("thumbs") / "nwn-v1"
    out = folder / f"{digest}-{size}.png"
    if out.is_file():
        return out

    try:
        built = scene(entry, install=install, index=index, colours=colours)
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
