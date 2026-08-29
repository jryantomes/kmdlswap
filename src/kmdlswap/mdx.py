"""Reading the MDX vertex stream.

The MDX has no header: it is per-mesh-node vertex blocks laid end to end. A
mesh's trimesh subheader says where its block starts and how wide one vertex is;
the per-component offsets inside that stride say where each attribute sits.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .layout import Layout, NodeInfo

NO_OFFSET = 0xFFFFFFFF


class MdxBitmap:
    """Which attributes a mesh's stride carries."""

    VERTEX = 0x0001
    UV1 = 0x0002
    UV2 = 0x0004
    UV3 = 0x0008
    UV4 = 0x0010
    NORMAL = 0x0020
    COLOR = 0x0040
    TANGENT = 0x0080


@dataclass(slots=True)
class Influence:
    """One bone's pull on one vertex. ``bone_slot`` indexes the qbones/tbones
    arrays; use :func:`bone_slot_nodes` to get the node it names.

    ``stride_slot`` records which of the four MDX slots this influence occupied.
    A handful of vanilla vertices leave slot 0 empty and start at slot 1, so
    compacting on rebuild would change bytes for no reason. New geometry can
    leave it at -1, and slots are then filled in order.
    """

    bone_slot: int
    weight: float
    stride_slot: int = -1


# Per-component offsets live in the trimesh subheader as 13 consecutive u32s
# starting at +252: data_size, bitmap, then one offset per attribute.
COLUMNS: tuple[tuple[str, int, int, str], ...] = (
    # (name, trimesh field offset, width in bytes, struct format)
    ("vertex", 260, 12, "3f"),
    ("normal", 264, 12, "3f"),
    ("color", 268, 12, "3f"),
    ("uv1", 272, 8, "2f"),
    ("uv2", 276, 8, "2f"),
    ("uv3", 280, 8, "2f"),
    ("uv4", 284, 8, "2f"),
    ("tangent", 288, 36, "9f"),
)
SKIN_COLUMN_BYTES = 32  # 4 weights + 4 bone slots, both float32


@dataclass(slots=True)
class StrideLayout:
    """Which attribute columns a mesh's MDX vertex carries, and where."""

    stride: int
    bitmap: int
    columns: dict[str, int]  # name -> byte offset within the stride
    weights_offset: int = NO_OFFSET
    bones_offset: int = NO_OFFSET

    @property
    def accounted_bytes(self) -> int:
        total = sum(w for name, _, w, _ in COLUMNS if name in self.columns)
        if self.weights_offset != NO_OFFSET:
            total += SKIN_COLUMN_BYTES
        return total


def stride_layout(layout: Layout, node: NodeInfo) -> StrideLayout:
    """Describe a mesh's MDX stride, and prove we understand all of it.

    Every vanilla stride is exactly the sum of its declared columns plus 32
    bytes of skin data when skinned - there is no unexplained padding. We assert
    that rather than assume it: rebuilding a stride we do not fully understand
    would silently drop bytes.
    """
    stride = _mdx_field(layout, node, 252)
    bitmap = _mdx_field(layout, node, 256)
    columns = {
        name: off
        for name, field, _, _ in COLUMNS
        if (off := _mdx_field(layout, node, field)) != NO_OFFSET
    }
    sl = StrideLayout(stride=stride, bitmap=bitmap, columns=columns)
    if node.is_skin:
        sl.weights_offset = node.mdx_weights_offset
        sl.bones_offset = node.mdx_bones_offset
    if sl.accounted_bytes != stride:
        raise ValueError(
            f"{node.name}: MDX stride {stride} != {sl.accounted_bytes} accounted for by "
            f"columns {sorted(columns)}{' + skin' if node.is_skin else ''}; refusing to "
            f"rebuild a stride we do not fully understand"
        )
    return sl


def _column(mdx: bytes, node: NodeInfo, offset_in_stride: int, count: int, fmt: str):
    """Read one attribute column across every vertex of a mesh block."""
    if offset_in_stride == NO_OFFSET:
        return None
    s = struct.Struct("<" + fmt)
    base = node.mdx_data_offset + offset_in_stride
    return [s.unpack_from(mdx, base + v * node.mdx_stride) for v in range(count)]


def positions(layout: Layout, node: NodeInfo) -> list[tuple[float, float, float]]:
    off = _mdx_field(layout, node, 260)
    cols = _column(layout.mdx, node, off, node.vertex_count, "3f")
    return cols or []


def normals(layout: Layout, node: NodeInfo) -> list[tuple[float, float, float]]:
    off = _mdx_field(layout, node, 264)
    cols = _column(layout.mdx, node, off, node.vertex_count, "3f")
    return cols or []


def uvs(layout: Layout, node: NodeInfo) -> list[tuple[float, float]]:
    off = _mdx_field(layout, node, 272)
    cols = _column(layout.mdx, node, off, node.vertex_count, "2f")
    return cols or []


def _mdx_field(layout: Layout, node: NodeInfo, field_offset: int) -> int:
    """Read one of the per-component MDX offsets out of the trimesh subheader."""
    return struct.unpack_from("<I", layout.mdl, node.trimesh_at + field_offset)[0]


def influences(layout: Layout, node: NodeInfo) -> list[list[Influence]]:
    """Per-vertex bone influences, zero-weight slots dropped.

    The stride reserves four (weight, bone) pairs. How many the engine actually
    honours is a separate, empirical question - see the census in
    ``tools/influence_census.py``.
    """
    if not node.is_skin or node.mdx_weights_offset == NO_OFFSET:
        return []
    mdx = layout.mdx
    w4 = struct.Struct("<4f")
    out: list[list[Influence]] = []
    for v in range(node.vertex_count):
        base = node.mdx_data_offset + v * node.mdx_stride
        weights = w4.unpack_from(mdx, base + node.mdx_weights_offset)
        slots = w4.unpack_from(mdx, base + node.mdx_bones_offset)
        out.append(
            [
                Influence(int(b), w, i)
                for i, (w, b) in enumerate(zip(weights, slots))
                if w > 0.0 and int(b) >= 0
            ]
        )
    return out


def bone_slot_nodes(layout: Layout, node: NodeInfo) -> dict[int, NodeInfo]:
    """Invert the bonemap: bone slot -> the geometry node that *is* that bone.

    ``bonemap`` holds one entry per geometry node, in node order, giving that
    node's slot in the qbones/tbones arrays (-1 when it is not a bone). It is
    indexed by node, not by vertex, so it does not resize when geometry changes.
    """
    geometry = [n for n in layout.nodes if n.in_animation is None]
    mapping: dict[int, NodeInfo] = {}
    for node_index, slot in enumerate(node.bonemap):
        if slot >= 0 and node_index < len(geometry):
            mapping[slot] = geometry[node_index]
    return mapping


def block_size(layout: Layout, node: NodeInfo) -> int:
    """Actual on-disk size of this mesh's MDX block, which can exceed
    ``vertex_count * stride`` - vanilla meshes often carry a trailing vertex."""
    for span in layout.mdx_spans:
        if span.owner == node.index:
            return span.size
    return 0
