"""Extracting one mesh node's geometry and putting geometry back.

Everything the engine needs is rebuilt from decoded components, so a swap is a
real rewrite of the geometry arrays - not a byte copy that happens to work.
Feeding a node its own geometry back must therefore reproduce the file exactly;
that is the Milestone 2 proof that the mechanism is sound.

Fields whose purpose is not understood - face adjacency, the counters array, the
per-mesh average/diffuse/ambient - are carried through verbatim rather than
recomputed. Preserve the vanilla value rather than invent one.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from . import mdx as kmdx
from ._io import MDL_BASE
from .layout import Layout, NodeInfo
from .rewrite import RewriteError, Rewriter

_FACE = struct.Struct("<3ffI3H3H")
_VEC3 = struct.Struct("<3f")


@dataclass(slots=True)
class Face:
    normal: tuple[float, float, float]
    plane: float
    material: int
    adjacent: tuple[int, int, int]
    vertices: tuple[int, int, int]

    def pack(self) -> bytes:
        return _FACE.pack(*self.normal, self.plane, self.material, *self.adjacent, *self.vertices)


@dataclass
class MeshGeometry:
    """One mesh node's geometry, fully decoded.

    ``columns`` holds every MDX attribute the mesh carries, keyed by name, one
    entry per vertex - so a rebuild reproduces whatever the original had rather
    than only the attributes this tool happens to know by name.
    """

    vertex_count: int
    columns: dict[str, list[tuple[float, ...]]] = field(default_factory=dict)
    influences: list[list[kmdx.Influence]] = field(default_factory=list)
    faces: list[Face] = field(default_factory=list)
    # Trailing bytes of the MDX block, past the real vertices. Vanilla writes a
    # sentinel vertex there - position (1e7, 1e7, 1e7) or (1e6, 1e6, 1e6), the
    # rest zeroed, and on skinned meshes weight[0] = 1.0 with bone slot 0. Its
    # purpose is not documented and it does not depend on the geometry, so it is
    # carried through verbatim rather than regenerated.
    trailing: bytes = b""

    @property
    def positions(self) -> list[tuple[float, ...]]:
        return self.columns.get("vertex", [])

    @property
    def triangle_count(self) -> int:
        return len(self.faces)


def _require_swappable(node: NodeInfo) -> None:
    if not node.is_mesh:
        raise ValueError(f"{node.name!r} is not a mesh node")
    if "saber" in node.flags:
        raise ValueError(
            f"{node.name!r} is a lightsaber blade: its geometry lives in MDL-side saber "
            f"arrays rather than the MDX stream, and swapping it is out of scope"
        )
    if not node.vertex_count:
        raise ValueError(f"{node.name!r} has no vertices")


def extract(layout: Layout, node: NodeInfo) -> MeshGeometry:
    _require_swappable(node)
    sl = kmdx.stride_layout(layout, node)

    geo = MeshGeometry(vertex_count=node.vertex_count)
    for name, _, _, fmt in kmdx.COLUMNS:
        if name not in sl.columns:
            continue
        s = struct.Struct("<" + fmt)
        base = node.mdx_data_offset + sl.columns[name]
        geo.columns[name] = [
            s.unpack_from(layout.mdx, base + v * sl.stride) for v in range(node.vertex_count)
        ]
    geo.influences = kmdx.influences(layout, node)

    faces_offset = struct.unpack_from("<I", layout.mdl, node.trimesh_at + 8)[0]
    base = MDL_BASE + faces_offset
    for i in range(node.face_count):
        f = _FACE.unpack_from(layout.mdl, base + i * 32)
        geo.faces.append(
            Face(
                normal=f[0:3], plane=f[3], material=f[4],
                adjacent=f[5:8], vertices=f[8:11],
            )
        )

    block_start = node.mdx_data_offset + node.vertex_count * sl.stride
    geo.trailing = layout.mdx[block_start : node.mdx_data_offset + kmdx.block_size(layout, node)]
    return geo


def build_mdx_block(layout: Layout, node: NodeInfo, geo: MeshGeometry) -> bytes:
    """Rebuild the mesh's MDX block from decoded components, then append the
    original trailing sentinel unchanged."""
    sl = kmdx.stride_layout(layout, node)
    out = bytearray(sl.stride * geo.vertex_count)

    for name, _, _, fmt in kmdx.COLUMNS:
        if name not in sl.columns:
            continue
        values = geo.columns.get(name)
        if values is None:
            continue
        if len(values) != geo.vertex_count:
            raise RewriteError(
                f"{node.name}: column {name!r} has {len(values)} entries, "
                f"expected {geo.vertex_count}"
            )
        s = struct.Struct("<" + fmt)
        off = sl.columns[name]
        for v, value in enumerate(values):
            s.pack_into(out, v * sl.stride + off, *value)

    if sl.weights_offset != kmdx.NO_OFFSET:
        w4 = struct.Struct("<4f")
        for v in range(geo.vertex_count):
            infl = geo.influences[v] if v < len(geo.influences) else []
            if len(infl) > 4:
                raise RewriteError(
                    f"{node.name}: vertex {v} has {len(infl)} influences; the MDX stride "
                    f"holds at most 4 and no vanilla vertex exceeds 4"
                )
            # Unused slots carry weight 0 and bone index -1, as vanilla does.
            weights = [0.0, 0.0, 0.0, 0.0]
            slots = [-1.0, -1.0, -1.0, -1.0]
            free = (i for i in range(4) if all(x.stride_slot != i for x in infl))
            for x in infl:
                pos = x.stride_slot if x.stride_slot >= 0 else next(free)
                if weights[pos] != 0.0:
                    raise RewriteError(
                        f"{node.name}: vertex {v} has two influences claiming MDX slot {pos}"
                    )
                weights[pos] = x.weight
                slots[pos] = float(x.bone_slot)
            w4.pack_into(out, v * sl.stride + sl.weights_offset, *weights)
            w4.pack_into(out, v * sl.stride + sl.bones_offset, *slots)

    return bytes(out) + geo.trailing


def replace_geometry(layout: Layout, node: NodeInfo, geo: MeshGeometry) -> tuple[bytes, bytes]:
    """Rewrite one mesh node's geometry. Returns new (mdl, mdx) bytes.

    Only the arrays that belong to this node are touched. Node names, the
    hierarchy, controllers, supermodel references, skin bone tables, and every
    other node's data pass through untouched; offsets displaced by the splice
    are corrected by the rewriter.
    """
    _require_swappable(node)
    if node.is_skin and len(geo.influences) != geo.vertex_count:
        raise RewriteError(
            f"{node.name} is skinned but geometry supplies {len(geo.influences)} "
            f"influence lists for {geo.vertex_count} vertices"
        )
    if geo.vertex_count > 0xFFFF:
        raise RewriteError(f"{node.name}: {geo.vertex_count} vertices exceeds the u16 count field")
    for i, f in enumerate(geo.faces):
        for vi in f.vertices:
            if vi >= geo.vertex_count:
                raise RewriteError(
                    f"{node.name}: face {i} references vertex {vi} but the mesh has "
                    f"{geo.vertex_count} vertices"
                )

    rw = Rewriter(layout)
    t = node.trimesh_at
    spans = {s.kind: s for s in layout.spans_of(node.index)}

    # --- MDX block
    mdx_span = next((s for s in layout.mdx_spans if s.owner == node.index), None)
    if mdx_span is not None:
        rw.replace_mdx(mdx_span.start, mdx_span.end, build_mdx_block(layout, node, geo))

    # --- face array
    if "face_array" in spans:
        s = spans["face_array"]
        rw.replace_mdl(s.start, s.end, b"".join(f.pack() for f in geo.faces))

    # --- MDL-side duplicate of the vertex positions
    if "mdl_vertex_array" in spans:
        s = spans["mdl_vertex_array"]
        positions = geo.positions
        if len(positions) != geo.vertex_count:
            raise RewriteError(f"{node.name}: no vertex positions to write")
        rw.replace_mdl(s.start, s.end, b"".join(_VEC3.pack(*p) for p in positions))

    # --- vertex index array, which mirrors the face vertex triples
    if "vertexindices" in spans:
        s = spans["vertexindices"]
        indices = [i for f in geo.faces for i in f.vertices]
        rw.replace_mdl(s.start, s.end, struct.pack(f"<{len(indices)}H", *indices))
        if "indices_counts" in spans:
            rw.set_u32(spans["indices_counts"].start, len(indices))

    # --- counts stored in the trimesh subheader
    rw.set_u32(t + 12, len(geo.faces))
    rw.set_u32(t + 16, len(geo.faces))
    rw.set_u16(t + 304, geo.vertex_count)

    return rw.apply()
