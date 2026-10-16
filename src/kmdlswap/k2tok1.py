"""A KOTOR II model, as KOTOR I reads it (2026-10-01; Goto's Yacht as the Due Diligence).

The two games' binary models differ in two things only, both measured, not assumed:

1. The function-pointer words the compiler baked in - the model header's pair, each
   animation header's pair, and each mesh subheader's pair (one pair per mesh type).
   Measured over the 1,126 models both games ship under the same name: each K2 pair maps to
   exactly one K1 pair, with no exceptions (K2_TO_K1 below).
2. K2's trimesh subheader is 8 bytes longer: offsets 316-323 (K2's dirt texture, dirt
   coordinate space and hide-in-holograms fields), with every field before them at the same
   offset in both games and every field after them 8 bytes later in K2. The word at 312 -
   beaming, RENDER, two more - is common to both (over 12,675 meshes the two games share it
   matches K2's 312 far more than K2's 320). The cut was 312-319 at first: it dropped the
   render flag, and whole floors of Goto's Yacht were not drawn - the stars showed through
   (harness, 2026-10-01).

So the conversion deletes those 8 bytes from every mesh subheader - the splice engine
(rewrite.Rewriter) moves everything after them and re-aims every stored pointer - and swaps
the pointer pairs. Geometry, MDX, controllers and everything else stay byte for byte.
"""

from __future__ import annotations

import struct

from ._io import MDL_BASE
from .layout import parse
from .rewrite import Rewriter

MODEL_POINTERS = {"K2": (4285200, 4216320), "K1": (4273776, 4216096)}
ANIM_POINTERS = {"K2": (4284816, 4522928), "K1": (4273392, 4451552)}
# a mesh subheader's pair, K2 -> K1 (plain, AABB and saber meshes share one; skin; dangly)
MESH_POINTERS = {
    (4216880, 4216896): (4216656, 4216672),
    (4216816, 4216832): (4216592, 4216608),
    (4216864, 4216848): (4216640, 4216624),
}
K2_DIRT_AT, K2_DIRT_SIZE = 316, 8


def k2_to_k1(mdl: bytes, mdx: bytes) -> tuple[bytes, bytes]:
    L = parse(mdl, mdx)
    if L.game != "K2":
        raise ValueError(f"not a KOTOR II model ({L.game})")
    rw = Rewriter(L)
    rw.set_bytes(MDL_BASE, struct.pack("<2I", *MODEL_POINTERS["K1"]))
    for s in L.spans:
        if s.kind == "anim_header":
            have = struct.unpack_from("<2I", mdl, s.start)
            if have != ANIM_POINTERS["K2"]:
                raise ValueError(f"animation header at {s.start}: unknown pointers {have}")
            rw.set_bytes(s.start, struct.pack("<2I", *ANIM_POINTERS["K1"]))
    cuts = []
    for n in L.nodes:
        if not n.trimesh_at:
            continue
        have = struct.unpack_from("<2I", mdl, n.trimesh_at)
        if have not in MESH_POINTERS:
            raise ValueError(f"{n.name}: unknown mesh pointers {have}")
        rw.set_bytes(n.trimesh_at, struct.pack("<2I", *MESH_POINTERS[have]))
        at = n.trimesh_at + K2_DIRT_AT
        rw.replace_mdl(at, at + K2_DIRT_SIZE, b"")
        cuts.append(at)
    # an empty list still holds an address (children, controllers, controller data with a
    # count of 0): not a live pointer, so the splice engine leaves it - and after the cuts it
    # can point past the end of the file (351narb's door_32 did; PyKotor seeks there and
    # fails). Moved by the cuts before it, like a live one
    live = {o.loc for o in L.offsets}
    for n in L.nodes:
        pos = MDL_BASE + n.offset
        for field, count_at in ((44, 48), (56, 60), (68, 72)):
            loc = pos + field
            off, count = struct.unpack_from("<2I", mdl, loc)[0], struct.unpack_from("<I", mdl, pos + count_at)[0]
            if count == 0 and loc not in live and off not in (0, 0xFFFFFFFF):
                rw.set_u32(loc, off - K2_DIRT_SIZE * sum(1 for c in cuts if c < MDL_BASE + off))
    return rw.apply()
