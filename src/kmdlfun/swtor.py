"""Star Wars: The Old Republic models, in the conventions the rest of this tool uses.

The Old Republic is the one game here that shares nothing with KOTOR but its
setting. Jade Empire and Neverwinter Nights are Aurora derivatives and their
model files are recognisably the same twelve-byte wrapper with the fields
moved; this is HeroEngine, and both the archive and the model are formats this
project had never read. So unlike `nwn.py`, none of what follows was worked out
by knowing where a field moved to. It was measured.

Nothing here writes. The Old Republic is a *source* of geometry and every
conversion ends where `headpack` begins, which is the same door a sculpt, a
Jade Empire head and a Blender export come through.

**The archives are MYP, and they are Zstandard now.** `Assets/*.tor` are MYP
version 6 containers: a header, a chain of file tables, and a payload per
entry behind a 36-byte block header. Every published description of this
format says the payloads are zlib, and they were. They are not any more - a
payload now starts with `28 b5 2f fd`, which is Zstandard's magic. That single
change is why an older extractor fails on a current install before it has read
a single model, and it is the reason `zstandard` is a dependency. Both are
accepted, decided per entry by looking at the first four bytes rather than by
trusting the flag.

**The names are hashed, and geometry does not care.** An entry carries two
32-bit values where a filename should be. They are not CRC32 in either
convention, FNV-1 or FNV-1a at 32 bits (two bases) or 64, djb2 in either
variant, sdbm, Jenkins one-at-a-time, or MurmurHash3 - each tried over sixteen
spellings of the path, and three of them over UTF-16 as well as UTF-8, against
176 known path/hash pairs recovered from the archive's own asset catalogue.
None matched, on the whole path or split into folder and filename. A working
implementation exists in the SWTOR extraction community and lifting it is the
obvious way to finish this. It does not block models,
because a `.gr2` carries its own mesh and bone names inside the file, so this
module indexes by *content*: read every entry once, keep the ones that are
models, and take the name from the model. It does block **textures**, which
are DDS with no internal name, and it is the one thing standing between this
and a textured head. See `to_pack`.

**The model format, derived rather than documented.** A `.gr2` starts `GAWB`
and everything in this module's field offsets was found by probing and then
checked against something the file itself asserts:

    the mesh header at 0x58 gives 736 vertices of 32 bytes at 0xf0
    those 736 positions have exactly the bounding box the file states at 0x20
    the index block that follows them ends exactly where the bone table starts

Three independent structures agreeing is the reason these offsets are trusted.
Across the 4,383 models in the head, body-type and creature archives, every
one is version 5, type 3, and holds zero, one or two meshes.

**Where the texture coordinates are.** The vertex layout varies with a flag
word, and six combinations appear across those archives:

    vsize  flags   what it is
    12     0x001   position only
    24     0x02f   position, normal, tangent, one UV set
    32     0x12f   the above plus bone indices and weights - every head
    36     0x13f   0x12f plus one more four-byte channel
    36     0x16f   0x12f plus a second UV set
    40     0x17f   both of those

Rather than guess a layout per flag, the UV offset was found by decoding every
four-byte-aligned position in every mesh of the five layouts that have texture
coordinates as a half float pair, and scoring how much of it lands in [0, 1].
One rule fits all five:
**UV0 sits four bytes before the end of the vertex, or eight when a second UV
set is present.** The winning offsets scored 0.97 to 0.99; the runners-up
scored 0.20 to 0.62, so this is not a close call.

**Units, and the one axis question.** The Old Republic is Y-up and measures in
tens of metres. A head arrives with its own bounding box sitting between 0.163
and 0.193 on Y, which is a head's height on a standing person if - and only if
- a unit is ten metres. So the conversion into KOTOR's Z-up metres is a
rotation about X and a factor of ten, and `(x, y, z)` becomes `(x, -z, y)`.

The sign matters more than it looks. `(x, z, y)` is the same rotation with a
mirror in it, and a mirror reverses every triangle: the first head through here
scored 5% of its surface facing outward, which `headspec` correctly called a
mesh folded inside out. The rotation scores 91%. A head that reads inside out
is a determinant, not a bug in the reader.

**Proportion, and why heads come in at 0.85.** Measured over 205 human heads
against 34 vanilla KOTOR head meshes, in metres after conversion:

    width    0.192 against 0.161    15% wider
    depth    0.218 against 0.235    7% shallower
    height   0.306 against 0.236    30% taller

Height is not a big head. The Old Republic models a head down to the collar,
so a third of that overshoot is neck, and height is what binds on 178 of the
205 - width on the other 27, depth on none.

Cropping the neck is therefore a better fix than shrinking the face, and the
pipeline already has one: `kmdlfun head --crop`, written for busts bought off
asset sites. Measured on a human head, with the render checked at each step
rather than the number alone:

    crop    height   against a vanilla head
    none     0.282            1.19
    0.15     0.258            1.09
    0.20     0.252            1.07
    0.25     0.239            1.01

0.20 is the most that plainly takes neck and not jaw. It is not the default
because `to_pack` writes geometry and cropping is a build-time decision the
caller can see the result of, but it is the first thing to reach for on a head
that reports too tall.

The scale below is the correction that needs no decision:

    scale   median worst axis   human heads inside headspec's 1.25 ceiling
    1.00           1.30                          33%
    0.95           1.23                          56%
    0.90           1.17                          58%
    0.85           1.10                         100%
    0.80           1.04                         100%

0.85 is where every human head passes; below it, size is given away for
nothing. Non-human heads reach 57% at the same scale and no scale fixes the
rest, because a Togruta's montrals and a Twi'lek's lekku are not a head that
is too big - they are geometry KOTOR has no room for.

**What does not come across.** Both engines drive a face with a bone rig,
which is more than could be hoped for, but they are not the same rig. A KOTOR
head is a skinned mesh with 16 bone slots, driven by nodes named `f_jaw_g`,
`f_mdbrw_g`, `f_llweye_g`. A head here carries 33 or so, named `fc_jaw`,
`fc_brow_mid`, `fc_lid_left_top`.

The rig is dropped anyway, and it costs less than it sounds like. `transplant`
already transfers the *host's* weights onto whatever geometry arrives, and on
this one it filled all 16 slots, re-sampled 12 lower-face vertices the skull
was wrongly leading, and lifted 12 brow vertices onto the host's own brow
share. So the face moves - with KOTOR's rig rather than with the one it was
modelled for. Carrying the donor's own rig across would be a name map plus a
reduction to 16 slots, and it is not needed to get a face that talks.

**How far down these reduce, which is not as far as vanilla.** A head arrives
at 2,556 triangles once its eyes are dropped, against vanilla's 440 to 796, so
it always wants decimating. It does not want decimating to *vanilla's* range.
Rendered at each budget and looked at rather than scored:

    2,000   indistinguishable from the source
    1,600   indistinguishable from the source
    1,300   the nose creases; still plainly the same face
    1,000   the nose creases badly
      700   a wedge stands out of the nose in three-quarter view

Every one of those passes `headspec`, including the last, which is the point.
The checks are topological - one piece, closed, wound outward - and a face
whose nose has collapsed into a spike is all of those things. Vanilla's 440 to
796 is a budget for topology laid out by hand around the features that matter;
a uniform reduction of a dense face has no such loyalty and needs the extra
triangles to keep the same nose.

1,300 is the recommendation. It takes the whole host model to 1,508 triangles,
comfortably under the 4,000 ceiling, and `headspec` warns about it rather than
refusing.

**A third of them are not heads.** `head_` is what the game files a species'
whole cranial anatomy under, so the catalogue includes lekku, montrals and
head tentacles, and at the top of it a Trandoshan whose `head` model is 1.96
metres tall. Measured against a vanilla head's box, after `HEAD_SCALE`, 562 of
the 993 are inside `headspec`'s 1.25 ceiling and every human head is, at 1.1
to 1.2. The rest are not too big in a way any scale fixes, so `Entry.oversize`
is measured during the scan and `catalogue(max_oversize=...)` filters on it -
a listing that offers a two-metre lizard head as a face is not a listing.

**Where the heads are.** All 993 of them are in one archive,
`swtor_main_art_dynamic_head_1.tor`. Three other likely archives were swept to
be sure - `art_creature_body_type`, `art_creature_a`, `art_creature_npc` - and
none holds a mesh named `head_`. The body-type archive holds player *bodies*,
which is a source this project has not opened yet.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from pathlib import Path

# --- the archive ------------------------------------------------------------

MYP_MAGIC = b"MYP\0"
MYP_VERSION = 6
TABLE_OFFSET_AT = 0x0C
ENTRY_SIZE = 34
BLOCK_HEADER_SIZE = 36
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"

ASSETS_DIR = "Assets"
# The one archive that holds heads. Overridable, because a future expansion
# could add another and nothing here should have to change to find it.
HEAD_ARCHIVES = ("swtor_main_art_dynamic_head_1.tor",)
# Present in every install, and named specifically enough that finding it is
# the same as finding the game.
MARKER_ARCHIVE = "swtor_main_global_1.tor"

# --- the model --------------------------------------------------------------

GR2_MAGIC = b"GAWB"
GR2_VERSION = 5
GR2_TYPE_MESH = 3

MESH_COUNT_AT = 0x18       # a u16; the u16 after it counts materials
MESHES_OFFSET_AT = 0x58
MESH_STRIDE = 0x40

# Offsets inside one mesh header.
MESH_NAME_AT = 0x00
MESH_PIECE_COUNT_AT = 0x0C   # a u16; the u16 after it counts bones
MESH_FLAGS_AT = 0x10
MESH_VERTEX_SIZE_AT = 0x14
MESH_VERTEX_COUNT_AT = 0x18
MESH_INDEX_COUNT_AT = 0x1C
MESH_VERTICES_AT = 0x20
MESH_PIECES_AT = 0x28
MESH_INDICES_AT = 0x30
MESH_BONES_AT = 0x38

BONE_STRIDE = 32           # a name pointer, then the bone's own bounding box
PIECE_STRIDE = 48          # first triangle, triangle count, then a box
SKIN_PIECE = 0             # the face and skull; piece 1, where present, is eyes

# A position is three floats at the front of every layout, whatever else the
# flags say is present.
POSITION_AT = 0
# Bit 6 of the flag word is a second UV set, and it displaces the first.
SECOND_UV_BIT = 0x40

# Per-vertex normals, packed as three unsigned bytes over [-1, 1] with a
# fourth byte of padding. Found the same way as the UVs and confirmed the same
# way: decoded across the whole head, 100% of them come out unit length
# (mean 0.999, standard deviation 0.004) and the padding byte is 255 every
# time. The channel four bytes further on decodes as unit length too and its
# fourth byte is 0 or 255, which is a tangent and a bitangent sign; nothing
# here needs it.
#
# These are *authored* normals and they are not the same as the geometric
# ones: they agree with a face-averaged normal at a median dot product of
# 0.998, but only 77.5% of vertices are within 0.8 of it. The other fifth is
# the author's hard edges - a nostril, a lip line, an eyelid - and it is
# exactly the fifth that matters. Recomputing normals from faces throws that
# away and a smooth head comes out looking faceted, which is what this module
# did until it was caught by someone looking at a render and saying the head
# looked like it had been decimated and rebuilt. It had not. It was lit wrong.
# Where it sits is its own rule, found the same way and independent of the UV
# one: the normal follows the position, displaced by eight bytes when the
# layout is skinned (four of bone indices, four of weights). Bit 8 of the flag
# word is what says so. Scored over every mesh in three archives, the winning
# channel is unit length for 100% of vertices in all five layouts and the
# runners-up score 0.00 to 0.19 - not a close call either.
SKINNED_BIT = 0x100
NORMAL_UNSKINNED_AT = 12

# --- conventions ------------------------------------------------------------

HEAD = "head"
HAIR = "hair"
OTHER = "other"

HEAD_PREFIX = "head_"
HAIR_PREFIX = "hair_"

# Ten metres to the unit. Not a correction - a unit conversion, and exact.
SCALE = 10.0
# On top of it, for heads only, and a compromise rather than a conversion.
HEAD_SCALE = 0.85

# Settled by looking at a render, and then at three more of them.
#
# A bounding box cannot answer this: a nose and the back of a skull both stick
# out, and on this head the *skull* has the longer reach, so the box says the
# face is on the side the face is not. Worse, the first render that was
# believed here was drawn under the mirrored transform described above, which
# swaps front for back as convincingly as it swaps left for right. `+y` was
# carried for three renders on the strength of it.
#
# What settled it was drawing the same head at four yaws and looking for the
# nose: it is at 180 degrees, so the head faces -y and the head pack says so.
# `headpack` supports the value, and placement rotates for it.
UP = "z"
FACING = "-y"

# The eight body types, spelled as they appear in a model's name: female and
# male, four builds each. Counted rather than assumed - the male set is
# `bma bmf bmn bms`, and there is no `bmb` however much the female set implies
# one.
BODY_TYPES = ("bfa", "bfb", "bfn", "bfs", "bma", "bmf", "bmn", "bms")

# The median vanilla KOTOR head mesh, measured over 34 of them: width, depth,
# height in metres. Not a limit - a yardstick, so a listing can say which of
# these heads is a head and which is a species with anatomy KOTOR has no room
# for. `headspec` refuses a head 1.25 times its target's box on any axis, and
# that ratio against this box is what `oversize` reports.
VANILLA_BOX = (0.161, 0.235, 0.236)

CACHE_NAME = "swtor"
CACHE_VERSION = 2


class SwtorError(RuntimeError):
    """The file is not what this understands it to be. Never guess."""


# --- reading an archive -----------------------------------------------------


@dataclass(frozen=True)
class Source:
    """Where one file sits: which archive, and how to get it back out."""

    archive: Path
    offset: int
    header: int
    packed: int
    size: int
    compressed: int

    def read(self) -> bytes:
        with self.archive.open("rb") as fh:
            return read_block(fh, self)


def read_block(fh, source: Source) -> bytes:
    """One entry's bytes, from a handle already open on its archive.

    Whether a payload is Zstandard or zlib is decided by looking at it. The
    entry's own compression flag says only *that* it is compressed, and it
    said the same thing before the game changed compressor.
    """
    fh.seek(source.offset + source.header)
    raw = fh.read(source.packed)
    if not source.compressed:
        return raw
    if raw[:4] == ZSTD_MAGIC:
        try:
            import zstandard
        except ImportError as exc:      # pragma: no cover - environment
            raise SwtorError(
                "reading The Old Republic needs the 'zstandard' package"
            ) from exc
        return zstandard.ZstdDecompressor().decompress(
            raw, max_output_size=source.size)
    import zlib

    return zlib.decompress(raw)


def entries(archive) -> list[Source]:
    """Every file in one archive, from its chain of tables.

    The tables are a linked list: a count, the offset of the next table, then
    that many fixed-size rows. Rows with a zero offset are holes left by
    patching and are dropped rather than handed on as empty files.
    """
    archive = Path(archive)
    out: list[Source] = []
    with archive.open("rb") as fh:
        magic, version = struct.unpack("<4sI", fh.read(8))
        if magic != MYP_MAGIC:
            raise SwtorError(f"{archive.name} does not start with MYP")
        if version != MYP_VERSION:
            raise SwtorError(f"{archive.name} is MYP version {version}, "
                             f"and only {MYP_VERSION} has been read")
        fh.seek(TABLE_OFFSET_AT)
        table = struct.unpack("<Q", fh.read(8))[0]
        seen = set()
        while table and table not in seen:
            seen.add(table)
            fh.seek(table)
            count, nxt = struct.unpack("<IQ", fh.read(12))
            blob = fh.read(ENTRY_SIZE * count)
            for i in range(count):
                (offset, header, packed, size, _h1, _h2, _crc,
                 comp) = struct.unpack_from("<QIIIIIIH", blob, i * ENTRY_SIZE)
                if not offset:
                    continue
                out.append(Source(archive=archive, offset=offset, header=header,
                                  packed=packed, size=size, compressed=comp))
            table = nxt
    return out


# --- reading a model --------------------------------------------------------


@dataclass
class MeshInfo:
    """One mesh's shape, before any of it is decoded."""

    name: str
    vertices: int
    triangles: int
    pieces: int
    bones: list[str] = field(default_factory=list)
    vertex_size: int = 0
    flags: int = 0
    vertices_at: int = 0
    indices_at: int = 0


@dataclass
class Model:
    """What a `.gr2` says about itself."""

    version: int
    type: int
    meshes: list[MeshInfo] = field(default_factory=list)


@dataclass
class Mesh:
    """Geometry in KOTOR's conventions, ready for a head pack."""

    name: str = "mesh"
    positions: list[tuple[float, float, float]] = field(default_factory=list)
    uvs: list[tuple[float, float]] = field(default_factory=list)
    faces: list[tuple[int, int, int]] = field(default_factory=list)
    normals: list[tuple[float, float, float]] = field(default_factory=list)
    bones: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def is_model(raw: bytes) -> bool:
    return raw[:4] == GR2_MAGIC


def _string_at(raw: bytes, at: int) -> str:
    if not at or at >= len(raw):
        return ""
    end = raw.find(b"\0", at)
    if end < 0:
        end = len(raw)
    return raw[at:end].decode("utf-8", "replace")


def _u32(raw: bytes, at: int) -> int:
    return struct.unpack_from("<I", raw, at)[0]


def normal_offset(flags: int) -> int:
    """Where the packed per-vertex normal starts inside a vertex.

    Straight after the position, and eight bytes further on when the mesh is
    skinned, because the bone indices and weights sit between them.
    """
    return NORMAL_UNSKINNED_AT + (8 if flags & SKINNED_BIT else 0)


def uv_offset(vertex_size: int, flags: int) -> int:
    """Where the first UV pair starts inside a vertex.

    Four bytes before the end, or eight when the flags say a second UV set
    follows it. Verified against all five layouts the archives contain - see
    the module docstring for the scores.
    """
    return vertex_size - (8 if flags & SECOND_UV_BIT else 4)


def parse(raw: bytes) -> Model:
    """Read a model's headers. Nothing is decoded and nothing is copied."""
    if not is_model(raw):
        raise SwtorError("not a GR2: it does not start with GAWB")
    version, kind = struct.unpack_from("<II", raw, 4)
    if version != GR2_VERSION:
        raise SwtorError(f"GR2 version {version}, and only "
                         f"{GR2_VERSION} has been read")
    count = struct.unpack_from("<H", raw, MESH_COUNT_AT)[0]
    model = Model(version=version, type=kind)
    if not count:
        return model
    meshes_at = _u32(raw, MESHES_OFFSET_AT)
    for i in range(count):
        at = meshes_at + i * MESH_STRIDE
        if at + MESH_STRIDE > len(raw):
            raise SwtorError(f"mesh header {i} runs past the end of the file")
        pieces, bone_count = struct.unpack_from("<2H", raw, at + MESH_PIECE_COUNT_AT)
        flags, vertex_size, vertices, indices = struct.unpack_from(
            "<4I", raw, at + MESH_FLAGS_AT)
        bones_at = _u32(raw, at + MESH_BONES_AT)
        bones = [_string_at(raw, _u32(raw, bones_at + k * BONE_STRIDE))
                 for k in range(bone_count)] if bones_at else []
        model.meshes.append(MeshInfo(
            name=_string_at(raw, _u32(raw, at + MESH_NAME_AT)),
            vertices=vertices,
            triangles=indices // 3,
            pieces=pieces,
            bones=bones,
            vertex_size=vertex_size,
            flags=flags,
            vertices_at=_u32(raw, at + MESH_VERTICES_AT),
            indices_at=_u32(raw, at + MESH_INDICES_AT),
        ))
    return model


def mesh(raw: bytes, *, index: int = 0, scale: float = 1.0,
         model: Model | None = None, piece: int | None = None) -> Mesh:
    """Decode one mesh into KOTOR's axes and units.

    `SCALE` is always applied, because it is a unit conversion and not an
    opinion. `scale` multiplies it, so a caller passing `HEAD_SCALE` gets the
    proportion correction on top and the default of 1.0 gets metres.

    `piece` keeps one of the mesh's pieces and drops the rest, with the
    vertices it no longer uses removed and the triangles renumbered - an
    unreferenced vertex is not harmless downstream, where the component count
    is part of whether a head is accepted.
    """
    import numpy as np

    model = model if model is not None else parse(raw)
    if not model.meshes:
        raise SwtorError("the model holds no meshes")
    if index >= len(model.meshes):
        raise SwtorError(f"mesh {index} of a model with {len(model.meshes)}")
    info = model.meshes[index]
    if info.vertex_size < 12:
        raise SwtorError(f"a {info.vertex_size}-byte vertex holds no position")

    need = info.vertices * info.vertex_size
    if info.vertices_at + need > len(raw):
        raise SwtorError(f"{info.vertices} vertices run past the end of the file")
    buffer = np.frombuffer(raw, np.uint8, need, info.vertices_at)
    buffer = buffer.reshape(info.vertices, info.vertex_size)

    positions = buffer[:, POSITION_AT:POSITION_AT + 12].copy().view(np.float32)
    positions = positions.astype(np.float64)
    # Y-up in tens of metres to Z-up in metres. A rotation about X, never the
    # swap that looks equivalent - see the module docstring.
    converted = np.column_stack([positions[:, 0], -positions[:, 2],
                                 positions[:, 1]]) * (SCALE * scale)

    out = Mesh(name=info.name, bones=list(info.bones))

    at = uv_offset(info.vertex_size, info.flags)
    uvs = None
    if at >= 12 and at + 4 <= info.vertex_size:
        uvs = buffer[:, at:at + 4].copy().view(np.float16).astype(np.float64)
    else:
        out.notes.append(f"no texture coordinates in a {info.vertex_size}-byte "
                         f"vertex with flags {info.flags:#x}")

    nat = normal_offset(info.flags)
    normals = None
    if nat + 3 <= info.vertex_size:
        packed = (buffer[:, nat:nat + 3].astype(np.float64) / 255.0) * 2.0 - 1.0
        # The same rotation the positions get. It is a rotation, so there is no
        # inverse transpose to do, and the scale is uniform so it does not tilt
        # them either.
        turned = np.column_stack([packed[:, 0], -packed[:, 2], packed[:, 1]])
        length = np.linalg.norm(turned, axis=1, keepdims=True)
        normals = turned / np.maximum(length, 1e-12)

    count = info.triangles * 3
    if info.indices_at + count * 2 > len(raw):
        raise SwtorError(f"{info.triangles} triangles run past the end of the file")
    indices = np.frombuffer(raw, np.uint16, count, info.indices_at)
    faces = indices.reshape(-1, 3)
    if faces.size and int(faces.max()) >= info.vertices:
        raise SwtorError(f"a triangle names vertex {int(faces.max())} of "
                         f"{info.vertices}")

    if piece is not None:
        spans = pieces(raw, index=index, model=model)
        if piece >= len(spans):
            raise SwtorError(f"piece {piece} of a mesh with {len(spans)}")
        start, taken = spans[piece]
        faces = faces[start:start + taken]
        kept = np.unique(faces)
        renumber = np.zeros(info.vertices, dtype=np.int64)
        renumber[kept] = np.arange(len(kept))
        faces = renumber[faces]
        converted = converted[kept]
        if uvs is not None:
            uvs = uvs[kept]
        if normals is not None:
            normals = normals[kept]

    out.positions = [tuple(float(c) for c in v) for v in converted]
    if uvs is not None:
        out.uvs = [(float(u), float(v)) for u, v in uvs]
    if normals is not None:
        out.normals = [tuple(float(c) for c in n) for n in normals]
    out.faces = [(int(a), int(b), int(c)) for a, b, c in faces]
    return out


def pieces(raw: bytes, *, index: int = 0, model: Model | None = None):
    """(first triangle, count) per piece, from the piece headers.

    A head is two pieces and they mean something: the first is the face and
    skull, the second is a pair of eyeballs. Drawn on their own, that is
    plainly all the second one is - 933 of the 993 heads have it, always
    second, always the smaller, a median of 9% of the triangles and never more
    than 32%. The other 60 have no separate eyes at all.

    It matters because a KOTOR head model carries its own `eyeRA` and `eyeLA`,
    so bringing these across duplicates them, and because decimating a head
    down to 700 triangles shatters two 136-triangle spheres into shards that
    stick out through the face. `to_pack` drops them by default.
    """
    model = model if model is not None else parse(raw)
    info = model.meshes[index]
    meshes_at = _u32(raw, MESHES_OFFSET_AT)
    at = _u32(raw, meshes_at + index * MESH_STRIDE + MESH_PIECES_AT)
    return [struct.unpack_from("<2I", raw, at + k * PIECE_STRIDE)
            for k in range(info.pieces)]


# --- what a model is --------------------------------------------------------


def kind_of(name: str) -> str:
    """What a mesh is, by the naming the game is consistent about.

    Every one of the 993 heads starts `head_` and every one of the 3,028 hair
    meshes starts `hair_`, with nothing else in the archive using either.
    """
    lowered = name.lower()
    if lowered.startswith(HEAD_PREFIX):
        return HEAD
    if lowered.startswith(HAIR_PREFIX):
        return HAIR
    return OTHER


def body_type_of(name: str) -> str | None:
    """Which body the head was modelled for, or None.

    The code sits as its own underscore-separated part of the name. This is
    the useful axis to filter a listing on: a head built for `bfn` is shaped
    to that body's neck, and 982 of the 993 heads name one.
    """
    parts = name.lower().split("_")
    for code in BODY_TYPES:
        if code in parts:
            return code
    return None


def is_player_head(name: str) -> bool:
    """Whether a head is built on one of the eight body types.

    Nearly all of them are - 982 of 993. The eleven that are not are modelled
    for a named character (Revan, Corso, Doc) rather than for a body, which
    makes this a much weaker distinction than it first looks and the reason
    nothing sorts on it.
    """
    return body_type_of(name) is not None


@dataclass(frozen=True)
class Entry:
    """One model in the game's archives, named by what is inside it."""

    name: str
    kind: str
    source: Source
    vertices: int = 0
    triangles: int = 0
    bones: int = 0
    # Width, depth and height in metres, at the unit conversion only. Measured
    # during the scan, because measuring it later means decompressing the file
    # again and a listing wants it for all 993 at once.
    box: tuple[float, float, float] = (0.0, 0.0, 0.0)

    @property
    def archive(self) -> Path:
        return self.source.archive

    @property
    def label(self) -> str:
        return self.name

    @property
    def oversize(self) -> float:
        """How many times a vanilla head this arrives as, on its worst axis.

        Measured after `HEAD_SCALE`, so it is the size a pack from `to_pack`
        actually has and can be read straight against `headspec`'s 1.25
        ceiling. 1.0 is a head the size KOTOR draws.

        No scale saves the far end of this range, which is why it is worth
        having in a listing: the top of it is lekku, montrals, head tentacles
        and a Trandoshan whose head model is nearly two metres tall.
        """
        if not any(self.box):
            return 0.0
        return max(a * HEAD_SCALE / b for a, b in zip(self.box, VANILLA_BOX))


# --- finding them -----------------------------------------------------------


def assets_dir(install) -> Path:
    root = Path(install)
    for where in (root / ASSETS_DIR, root):
        if (where / MARKER_ARCHIVE).is_file():
            return where
    raise SwtorError(f"no {ASSETS_DIR}/{MARKER_ARCHIVE} under {root}")


def archives(install, names=HEAD_ARCHIVES) -> list[Path]:
    """The archives to read, in the order given, skipping any not shipped."""
    where = assets_dir(install)
    return [where / name for name in names if (where / name).is_file()]


def _box_of(raw: bytes, model: Model, info: MeshInfo) -> tuple[float, float, float]:
    """One mesh's size in metres, from its positions.

    The model states a box of its own in the header, and for the 4,352 files
    holding a single mesh it is the same answer. It is not read here because a
    dozen files hold two meshes and the header cannot tell them apart, and a
    size that is right 99% of the time is the worst kind.
    """
    import numpy as np

    need = info.vertices * info.vertex_size
    if not need or info.vertices_at + need > len(raw):
        return (0.0, 0.0, 0.0)
    buffer = np.frombuffer(raw, np.uint8, need, info.vertices_at)
    buffer = buffer.reshape(info.vertices, info.vertex_size)
    positions = buffer[:, POSITION_AT:POSITION_AT + 12].copy().view(np.float32)
    span = (positions.max(axis=0) - positions.min(axis=0)) * SCALE
    # Into KOTOR's axes: width, depth, height.
    return (float(span[0]), float(span[2]), float(span[1]))


def scan(archive, *, kinds=(HEAD,), progress=None) -> list[Entry]:
    """Index one archive by reading what is inside every file in it.

    There is no cheaper way. A name is hashed and a model's own name is at the
    far end of a compressed payload, so every entry has to come out to be
    identified: 11,800 entries, 2.9 GB decompressed, about four seconds. That
    is why `index_of` caches.

    A model that will not parse is skipped rather than raised on. The archives
    hold textures, XML and audio banks as well, and a container that fails to
    make sense is far more likely to be one of those than a broken model.
    """
    archive = Path(archive)
    found: dict[str, Entry] = {}
    sources = entries(archive)
    with archive.open("rb") as fh:
        for i, source in enumerate(sources):
            if progress is not None:
                progress(i, len(sources))
            try:
                raw = read_block(fh, source)
            except SwtorError:
                raise
            except Exception:  # noqa: BLE001 - one bad payload is not fatal
                continue
            if not is_model(raw):
                continue
            try:
                model = parse(raw)
            except SwtorError:
                continue
            for info in model.meshes:
                kind = kind_of(info.name)
                if kind not in kinds:
                    continue
                # A name appears more than once: the archive ships lower
                # detail copies alongside the full one. Keep the densest,
                # which is the one an import wants.
                current = found.get(info.name)
                if current is not None and current.triangles >= info.triangles:
                    continue
                found[info.name] = Entry(
                    name=info.name, kind=kind, source=source,
                    vertices=info.vertices, triangles=info.triangles,
                    bones=len(info.bones), box=_box_of(raw, model, info))
    return list(found.values())


def _cache_file(archive: Path) -> Path:
    from . import thumbs as kthumbs

    stat = archive.stat()
    stamp = f"{stat.st_size}-{int(stat.st_mtime)}"
    return (kthumbs.cache_dir(CACHE_NAME)
            / f"v{CACHE_VERSION}-{archive.stem}-{stamp}.json")


def _load_cache(archive: Path, kinds) -> list[Entry] | None:
    path = _cache_file(archive)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if set(data.get("kinds", ())) != set(kinds):
        return None
    out = []
    for row in data.get("entries", ()):
        try:
            out.append(Entry(
                name=row["name"], kind=row["kind"],
                source=Source(archive=archive, offset=row["offset"],
                              header=row["header"], packed=row["packed"],
                              size=row["size"], compressed=row["compressed"]),
                vertices=row["vertices"], triangles=row["triangles"],
                bones=row["bones"], box=tuple(row["box"])))
        except (KeyError, TypeError):
            return None
    return out


def _save_cache(archive: Path, kinds, found: list[Entry]) -> None:
    path = _cache_file(archive)
    data = {
        "kinds": sorted(kinds),
        "entries": [{
            "name": e.name, "kind": e.kind, "offset": e.source.offset,
            "header": e.source.header, "packed": e.source.packed,
            "size": e.source.size, "compressed": e.source.compressed,
            "vertices": e.vertices, "triangles": e.triangles, "bones": e.bones,
            "box": list(e.box),
        } for e in found],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass            # a cache that cannot be written is not an error


def index_of(install, *, names=HEAD_ARCHIVES, kinds=(HEAD,),
             use_cache: bool = True, progress=None) -> list[Entry]:
    """Every model worth offering, cached against the archive it came from.

    The cache is keyed on the archive's size and modification time, so a game
    patch invalidates it without anything having to notice that it did.
    """
    out: list[Entry] = []
    for archive in archives(install, names):
        found = _load_cache(archive, kinds) if use_cache else None
        if found is None:
            found = scan(archive, kinds=kinds, progress=progress)
            if use_cache:
                _save_cache(archive, kinds, found)
        out.extend(found)
    return out


def catalogue(install, *, kinds=(HEAD,), index=None, body_type=None,
              max_oversize=None, **kwargs) -> list[Entry]:
    """The models worth offering, in name order.

    `index` is accepted so a caller that already scanned does not scan again.

    The two filters are the ones a character creator actually needs, because
    name order alone puts 993 heads in front of somebody choosing one.
    `body_type` narrows to heads modelled for one body. `max_oversize` drops
    the ones that will not fit a head node: at `headspec`'s own 1.25 it keeps
    562 of the 993, and every human head is inside that at 1.1 to 1.2.
    """
    found = index if index is not None else index_of(install, kinds=kinds, **kwargs)
    found = [e for e in found if e.kind in kinds]
    if body_type:
        wanted = body_type.lower()
        found = [e for e in found if body_type_of(e.name) == wanted]
    if max_oversize is not None:
        found = [e for e in found if e.oversize <= max_oversize]
    return sorted(found, key=lambda e: (e.kind != HEAD, e.name))


# --- out, as a head pack ----------------------------------------------------


def to_pack(entry: Entry, out_dir, *, scale: float | None = None,
            name: str | None = None, facing: str = FACING,
            with_eyes: bool = False) -> dict:
    """Write one model out as a head pack the Custom head tab can build.

    The pack is the same shape a `.glb` import produces, so everything
    downstream - decimation, fitting, winding repair, the solidity check -
    applies unchanged. What is Old Republic-specific ends here.

    **No texture is written, and that is a gap rather than a choice.** The
    texture exists, it is a DDS in the same archive, and it is full colour
    with the skin tone already in it rather than the greyscale a palette-driven
    engine would store - so it would need only a resize and a format change.
    What is missing is the link: pairing a head with its own face needs the
    archive's filename hash, which is unidentified. Until it is, a head built
    from here wears the host's texture, and on a KOTOR head texture that means
    eyes and a mouth painted where this face does not have them.
    """
    from kmdlswap import obj as kobj

    from . import headpack

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if scale is None:
        scale = HEAD_SCALE if entry.kind == HEAD else 1.0
    raw = entry.source.read()
    # The eyeballs are their own piece, and the host has a better pair - see
    # `pieces`. Keeping them costs triangles and shatters them on decimation.
    piece = None if with_eyes or len(pieces(raw)) < 2 else SKIN_PIECE
    found = mesh(raw, scale=scale, piece=piece)
    if piece is not None:
        found.notes.append("eyes dropped; the host model draws its own")

    kobj.write_obj(out_dir / "head.obj", found.positions, found.faces,
                   uvs=found.uvs or None, normals=found.normals or None,
                   name=out_dir.name)

    found.notes.append(
        "no texture: pairing a head with its own face needs the archive's "
        "filename hash, which is unidentified")
    if found.bones:
        found.notes.append(
            f"the donor's {len(found.bones)}-bone face rig is dropped; the "
            f"build transfers the host's own rig onto this geometry, so it "
            f"animates with the host's face")

    headpack.write_template(out_dir, name=name or entry.name)
    manifest = out_dir / headpack.MANIFEST_NAME
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["up"] = UP
    data["facing"] = facing
    data["target"] = "head"
    data["notes"] = (f"imported from The Old Republic {entry.name}"
                     f" (x{SCALE:g} for units"
                     + (f", x{scale:.3f} for fit" if abs(scale - 1.0) > 1e-6
                        else "") + ")")
    manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    return {
        "pack": out_dir,
        "name": entry.name,
        "kind": entry.kind,
        "vertices": len(found.positions),
        "triangles": len(found.faces),
        "uvs": len(found.uvs),
        "texture": None,
        "notes": found.notes,
    }


# --- drawing one, to pick it by ---------------------------------------------


def scene(entry: Entry, *, scale: float | None = None):
    """A drawable scene for one model.

    Flat colour, unlike `nwn.py`, and for a reason rather than an omission. An
    NWN head is 160-odd triangles carrying its eyes, brows and mouth entirely
    in the texture, so untextured they are all one grey mask and the drawing
    is useless for choosing. A head here is 2,828 triangles with the brow,
    nose, lips and eyelids modelled, and it is perfectly recognisable with no
    texture at all - which is just as well, since the texture cannot yet be
    found.
    """
    from . import render as krender

    if scale is None:
        scale = HEAD_SCALE if entry.kind == HEAD else 1.0
    found = mesh(entry.source.read(), scale=scale)
    return krender.from_mesh(found.positions, found.faces)


def thumbnail(entry: Entry, *, size: int = 96, root=None):
    """Draw one model's face and cache it, or None.

    Keyed on the bytes, so a redraw only happens when the model does.
    """
    import hashlib

    from . import render as krender
    from . import thumbs as kthumbs

    digest = hashlib.md5(  # noqa: S324 - naming a cache file, not a secret
        entry.source.read()).hexdigest()
    folder = Path(root) if root else kthumbs.cache_dir("thumbs") / "swtor-v1"
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
