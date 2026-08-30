"""Structural parse of a K1 MDL/MDX pair into a span map.

We never re-interpret geometry. We locate it. The output is a :class:`Layout`:
an ordered list of byte spans covering the whole file, plus every stored offset
and count field, keyed by where it lives so an edit can patch it in place.

Identity is by construction: concatenating the spans reproduces the original
bytes exactly, so a no-op round-trip cannot drift.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ._io import MDL_BASE, Reader, cstr_at
from .nodes import (
    AABB_HEADER_SIZE,
    AABB_NODE_SIZE,
    ANIM_HEADER_SIZE,
    CONTROLLER_SIZE,
    DANGLY_HEADER_SIZE,
    EMITTER_HEADER_SIZE,
    EVENT_SIZE,
    FACE_SIZE,
    FILE_HEADER_SIZE,
    LIGHT_HEADER_SIZE,
    MODEL_HEADER_SIZE,
    NODE_HEADER_SIZE,
    REFERENCE_HEADER_SIZE,
    SABER_HEADER_SIZE,
    SKIN_HEADER_SIZE,
    TRIMESH_HEADER_SIZE_K1,
    NodeFlag,
    flag_names,
)

NULL_OFFSETS = (0, 0xFFFFFFFF)


class ParseError(Exception):
    """The file does not match our understanding of the format. Never guess."""


@dataclass(slots=True)
class Span:
    start: int
    end: int
    kind: str
    owner: int | None = None  # index into Layout.nodes, when node-owned

    @property
    def size(self) -> int:
        return self.end - self.start


@dataclass(slots=True)
class OffsetField:
    """A stored pointer. ``loc`` is where the u32 lives; ``value`` is what it
    holds; ``space`` says which file it points into."""

    loc: int
    value: int
    space: str  # "MDL" | "MDX"
    target_kind: str
    owner: int | None = None

    @property
    def absolute(self) -> int:
        return MDL_BASE + self.value if self.space == "MDL" else self.value


@dataclass(slots=True)
class CountField:
    loc: int
    value: int
    array_id: str
    owner: int | None = None


@dataclass(slots=True)
class NodeInfo:
    index: int
    offset: int  # MDL-space offset of the node header
    type_id: int
    node_id: int
    name_id: int
    name: str
    parent: int | None
    children: list[int] = field(default_factory=list)
    in_animation: str | None = None  # animation name, if this node is anim-local

    # mesh facts, populated for MESH nodes
    vertex_count: int = 0
    face_count: int = 0
    mdx_stride: int = 0
    mdx_bitmap: int = 0
    mdx_data_offset: int = 0
    trimesh_at: int = 0  # absolute file position of the trimesh subheader
    skin_at: int = 0
    bones: tuple[int, ...] = ()  # fixed 16-slot table; entries past the used
    # count are uninitialised garbage, so prefer the bonemap
    textures: tuple[str, str] = ("", "")

    # byte offsets of the weight/bone columns *within* the MDX vertex stride
    mdx_weights_offset: int = 0xFFFFFFFF
    mdx_bones_offset: int = 0xFFFFFFFF
    # bonemap: one float per geometry node; value is that node's bone slot in
    # the qbones/tbones arrays, or -1 when the node is not a bone.
    bonemap: tuple[int, ...] = ()

    @property
    def flags(self) -> list[str]:
        return flag_names(self.type_id)

    @property
    def is_mesh(self) -> bool:
        return bool(self.type_id & NodeFlag.MESH)

    @property
    def is_skin(self) -> bool:
        return bool(self.type_id & NodeFlag.SKIN)

    def path(self, nodes: list[NodeInfo]) -> str:
        parts = [self.name]
        p = self.parent
        while p is not None:
            parts.append(nodes[p].name)
            p = nodes[p].parent
        return "/".join(reversed(parts))


@dataclass
class Layout:
    mdl: bytes
    mdx: bytes
    model_name: str = ""
    supermodel: str = ""
    root_node_offset: int = 0
    node_count: int = 0
    bbox: tuple[float, ...] = ()
    radius: float = 0.0
    animation_names: list[str] = field(default_factory=list)

    spans: list[Span] = field(default_factory=list)
    mdx_spans: list[Span] = field(default_factory=list)
    offsets: list[OffsetField] = field(default_factory=list)
    counts: list[CountField] = field(default_factory=list)
    nodes: list[NodeInfo] = field(default_factory=list)

    # ---- lookups ----------------------------------------------------------

    def node_by_name(self, name: str, *, exact: bool = False) -> NodeInfo:
        """Geometry nodes only (animation node-trees reuse the same names)."""
        pool = [n for n in self.nodes if n.in_animation is None]
        hits = [n for n in pool if (n.name == name if exact else n.name.lower() == name.lower())]
        if not hits:
            raise KeyError(f"no node named {name!r}")
        if len(hits) > 1:
            raise KeyError(f"{name!r} is ambiguous: {[n.path(self.nodes) for n in hits]}")
        return hits[0]

    def spans_of(self, node_index: int) -> list[Span]:
        return [s for s in self.spans if s.owner == node_index]


class _Parser:
    def __init__(self, mdl: bytes, mdx: bytes):
        self.mdl = mdl
        self.mdx = mdx
        self.L = Layout(mdl=mdl, mdx=mdx)
        self.r = Reader(mdl)
        self._seen_node_offsets: set[int] = set()
        self._cur_anim: str | None = None

    # ---- span/field bookkeeping ------------------------------------------

    def span(self, start: int, size: int, kind: str, owner: int | None = None) -> None:
        if size < 0:
            raise ParseError(f"negative span size {size} for {kind} at {start}")
        if start < 0 or start + size > len(self.mdl):
            raise ParseError(f"{kind} span [{start}, {start + size}) out of bounds")
        self.L.spans.append(Span(start, start + size, kind, owner))

    def mdx_span(self, start: int, size: int, kind: str, owner: int | None = None) -> None:
        if start < 0 or start + size > len(self.mdx):
            raise ParseError(f"MDX {kind} span [{start}, {start + size}) out of bounds")
        self.L.mdx_spans.append(Span(start, start + size, kind, owner))

    def off(self, loc: int, value: int, target_kind: str, owner: int | None = None,
            space: str = "MDL") -> None:
        self.L.offsets.append(OffsetField(loc, value, space, target_kind, owner))

    def cnt(self, loc: int, value: int, array_id: str, owner: int | None = None) -> None:
        self.L.counts.append(CountField(loc, value, array_id, owner))

    # ---- entry point ------------------------------------------------------

    def parse(self) -> Layout:
        self._file_header()
        self._model_header()
        self._name_array()
        self._node(self.L.root_node_offset, parent=None)
        self._animations()
        self._mdx_blocks()
        return self.L

    # ---- top-level structures --------------------------------------------

    def _file_header(self) -> None:
        if len(self.mdl) < FILE_HEADER_SIZE:
            raise ParseError("file shorter than the 12-byte wrapper")
        r = self.r.seek(0)
        zero, mdl_data_size, mdx_size = r.u32(), r.u32(), r.u32()
        if zero != 0:
            raise ParseError(f"wrapper word 0 is {zero}, expected 0 (binary MDL?)")
        if mdl_data_size + FILE_HEADER_SIZE != len(self.mdl):
            raise ParseError(
                f"wrapper mdl_data_size {mdl_data_size} + 12 != file size {len(self.mdl)}"
            )
        if mdx_size != len(self.mdx):
            raise ParseError(f"wrapper mdx_size {mdx_size} != MDX file size {len(self.mdx)}")
        self.span(0, FILE_HEADER_SIZE, "file_header")
        self.cnt(4, mdl_data_size, "mdl_data_size")
        self.cnt(8, mdx_size, "mdx_size")

    def _model_header(self) -> None:
        base = MDL_BASE
        self.span(base, MODEL_HEADER_SIZE, "model_header")
        r = self.r.seek(base)
        r.skip(8)  # layout tokens - function pointers, preserved verbatim
        self.L.model_name = r.cstr(32)
        self.L.root_node_offset = r.u32()
        self.L.node_count = r.u32()

        self.off(base + 40, self.L.root_node_offset, "node_header")
        self.cnt(base + 44, self.L.node_count, "node_count")

        r.seek(base + 88)
        self.anim_array_offset = r.u32()
        self.anim_count = r.u32()
        # With no animations the offset field still holds a stale value pointing
        # into node data; it is not a live pointer, so do not treat it as one.
        if self.anim_count:
            self.off(base + 88, self.anim_array_offset, "anim_offset_array")
        self.cnt(base + 92, self.anim_count, "animation_count")
        self.cnt(base + 96, r.u32(), "animation_count2")

        r.seek(base + 104)
        self.L.bbox = (*r.vec3(), *r.vec3())
        self.L.radius = r.f32()
        r.skip(4)  # anim_scale
        self.L.supermodel = r.cstr(32)

        # A node pointer sitting immediately after the supermodel name, which
        # this parser skipped over for a long time and so never relocated.
        #
        # It resolves to the *exact start of a node header* in all 164 vanilla
        # character models - `neck_g` in head models, the model's own root in
        # body models - so it is a pointer, not data. Leaving it stale is what
        # made the engine refuse to skin a model: grow any array that sits
        # before its target and it lands 36 bytes short, inside the previous
        # node, and the whole model loads rigid. That reproduced every in-game
        # probe result, including the two that had looked like a
        # skinned-versus-unskinned distinction.
        #
        # The name is inferred from where it points, not from documentation.
        # See reports/SKIN_ROOT_POINTER_FINDINGS.md.
        r.seek(base + 168)
        super_root = r.u32()
        if super_root not in NULL_OFFSETS:
            self.off(base + 168, super_root, "node_header")

        r.seek(base + 176)
        self.cnt(base + 176, r.u32(), "model_mdx_size")
        self.cnt(base + 180, r.u32(), "model_mdx_offset")
        self.name_array_offset = r.u32()
        self.name_count = r.u32()
        self.off(base + 184, self.name_array_offset, "name_offset_array")
        self.cnt(base + 188, self.name_count, "name_offsets_count")
        self.cnt(base + 192, r.u32(), "name_offsets_count2")

    def _name_array(self) -> None:
        self.names: list[str] = []
        if self.name_array_offset in NULL_OFFSETS or self.name_count == 0:
            return
        start = MDL_BASE + self.name_array_offset
        self.span(start, self.name_count * 4, "name_offset_array")
        r = Reader(self.mdl, start)
        name_offsets = [r.u32() for _ in range(self.name_count)]
        for i, no in enumerate(name_offsets):
            self.off(start + i * 4, no, "name_string")
            pos = MDL_BASE + no
            name = cstr_at(self.mdl, pos)
            self.names.append(name)
            self.span(pos, len(name) + 1, "name_string")

    # ---- node tree --------------------------------------------------------

    def _node(self, offset: int, parent: int | None) -> int:
        if offset in NULL_OFFSETS:
            raise ParseError(f"null node offset with parent {parent}")
        pos = MDL_BASE + offset
        if pos in self._seen_node_offsets:
            raise ParseError(f"node at MDL offset {offset} visited twice (cyclic tree?)")
        self._seen_node_offsets.add(pos)

        r = Reader(self.mdl, pos)
        type_id = r.u16()
        r.u16()  # padding / supernode
        node_id = r.u16()
        name_id = r.u16()

        idx = len(self.L.nodes)
        name = self.names[node_id] if 0 <= node_id < len(self.names) else ""
        info = NodeInfo(
            index=idx,
            offset=offset,
            type_id=type_id,
            node_id=node_id,
            name_id=name_id,
            name=name,
            parent=parent,
            in_animation=self._cur_anim,
        )
        self.L.nodes.append(info)
        if parent is not None:
            self.L.nodes[parent].children.append(idx)

        self.span(pos, NODE_HEADER_SIZE, "node_header", idx)
        # offset_to_root points at the owning geometry header (the model header
        # for the geometry tree, the animation header for an animation's tree).
        self.off(pos + 8, r.seek(pos + 8).u32(), "geometry_header", idx)
        parent_off = r.u32()
        if parent_off not in NULL_OFFSETS:
            self.off(pos + 12, parent_off, "node_header", idx)

        r.seek(pos + 44)
        children_offset, children_count = r.u32(), r.u32()
        self.cnt(pos + 48, children_count, "children_count", idx)
        self.cnt(pos + 52, r.u32(), "children_count2", idx)
        controllers_offset, controller_count = r.u32(), r.u32()
        self.cnt(pos + 60, controller_count, "controller_count", idx)
        self.cnt(pos + 64, r.u32(), "controller_count2", idx)
        controller_data_offset, controller_data_length = r.u32(), r.u32()
        self.cnt(pos + 72, controller_data_length, "controller_data_length", idx)
        self.cnt(pos + 76, r.u32(), "controller_data_length2", idx)

        # --- subheaders, in on-disk order
        sub = pos + NODE_HEADER_SIZE
        saber_at: int | None = None
        if type_id & NodeFlag.MESH:
            info.trimesh_at = sub
            self.span(sub, TRIMESH_HEADER_SIZE_K1, "trimesh_header", idx)
            sub += TRIMESH_HEADER_SIZE_K1
        if type_id & NodeFlag.SKIN:
            info.skin_at = sub
            self.span(sub, SKIN_HEADER_SIZE, "skin_header", idx)
            sub += SKIN_HEADER_SIZE
        if type_id & NodeFlag.LIGHT:
            self.span(sub, LIGHT_HEADER_SIZE, "light_header", idx)
            self._light_arrays(sub, idx)
            sub += LIGHT_HEADER_SIZE
        if type_id & NodeFlag.EMITTER:
            self.span(sub, EMITTER_HEADER_SIZE, "emitter_header", idx)
            sub += EMITTER_HEADER_SIZE
        if type_id & NodeFlag.REFERENCE:
            self.span(sub, REFERENCE_HEADER_SIZE, "reference_header", idx)
            sub += REFERENCE_HEADER_SIZE
        if type_id & NodeFlag.DANGLY and info.trimesh_at:
            self.span(sub, DANGLY_HEADER_SIZE, "dangly_header", idx)
            self._dangly_arrays(sub, idx)
            sub += DANGLY_HEADER_SIZE
        if type_id & NodeFlag.SABER and info.trimesh_at:
            self.span(sub, SABER_HEADER_SIZE, "saber_header", idx)
            saber_at = sub
            sub += SABER_HEADER_SIZE
        aabb_root = None
        if type_id & NodeFlag.AABB and info.trimesh_at:
            self.span(sub, AABB_HEADER_SIZE, "aabb_header", idx)
            aabb_root = Reader(self.mdl, sub).u32()
            self.off(sub, aabb_root, "aabb_node", idx)
            sub += AABB_HEADER_SIZE

        # --- node-owned arrays
        if controllers_offset not in NULL_OFFSETS and controller_count:
            self.off(pos + 56, controllers_offset, "controller_array", idx)
            self.span(MDL_BASE + controllers_offset, controller_count * CONTROLLER_SIZE,
                      "controller_array", idx)
        if controller_data_offset not in NULL_OFFSETS and controller_data_length:
            self.off(pos + 68, controller_data_offset, "controller_data", idx)
            self.span(MDL_BASE + controller_data_offset, controller_data_length * 4,
                      "controller_data", idx)

        if info.trimesh_at:
            self._trimesh_arrays(info)
        if info.skin_at:
            self._skin_arrays(info)
        if saber_at is not None:
            self._saber_arrays(saber_at, info)
        if aabb_root not in (None, *NULL_OFFSETS):
            self._aabb_tree(aabb_root, idx)

        # --- recurse
        child_offsets: list[int] = []
        if children_offset not in NULL_OFFSETS and children_count:
            self.off(pos + 44, children_offset, "children_array", idx)
            cstart = MDL_BASE + children_offset
            self.span(cstart, children_count * 4, "children_array", idx)
            cr = Reader(self.mdl, cstart)
            child_offsets = [cr.u32() for _ in range(children_count)]
            for i, co in enumerate(child_offsets):
                self.off(cstart + i * 4, co, "node_header", idx)
        for co in child_offsets:
            self._node(co, parent=idx)
        return idx

    # ---- mesh arrays ------------------------------------------------------

    def _trimesh_arrays(self, info: NodeInfo) -> None:
        t = info.trimesh_at
        idx = info.index
        r = Reader(self.mdl, t)

        r.seek(t + 8)
        faces_offset, faces_count = r.u32(), r.u32()
        self.cnt(t + 12, faces_count, "faces_count", idx)
        self.cnt(t + 16, r.u32(), "faces_count2", idx)
        info.face_count = faces_count

        r.seek(t + 176)
        icounts_offset, icounts_count = r.u32(), r.u32()
        self.cnt(t + 180, icounts_count, "indices_counts_count", idx)
        self.cnt(t + 184, r.u32(), "indices_counts_count2", idx)
        ioffs_offset, ioffs_count = r.u32(), r.u32()
        self.cnt(t + 192, ioffs_count, "indices_offsets_count", idx)
        self.cnt(t + 196, r.u32(), "indices_offsets_count2", idx)
        counters_offset, counters_count = r.u32(), r.u32()
        self.cnt(t + 204, counters_count, "counters_count", idx)
        self.cnt(t + 208, r.u32(), "counters_count2", idx)

        info.textures = (Reader(self.mdl, t + 88).cstr(32), Reader(self.mdl, t + 120).cstr(32))

        r.seek(t + 252)
        info.mdx_stride = r.u32()
        info.mdx_bitmap = r.u32()

        r.seek(t + 304)
        info.vertex_count = r.u16()

        r.seek(t + 324)
        info.mdx_data_offset = r.u32()
        vertices_offset = r.u32()

        if faces_offset not in NULL_OFFSETS and faces_count:
            self.off(t + 8, faces_offset, "face_array", idx)
            self.span(MDL_BASE + faces_offset, faces_count * FACE_SIZE, "face_array", idx)

        # indices_counts[i] gives the length of the i-th vertexindices array,
        # indices_offsets[i] points at it. Vanilla models always have one.
        counts_list: list[int] = []
        if icounts_offset not in NULL_OFFSETS and icounts_count:
            self.off(t + 176, icounts_offset, "indices_counts", idx)
            start = MDL_BASE + icounts_offset
            self.span(start, icounts_count * 4, "indices_counts", idx)
            cr = Reader(self.mdl, start)
            counts_list = [cr.u32() for _ in range(icounts_count)]

        if ioffs_offset not in NULL_OFFSETS and ioffs_count:
            self.off(t + 188, ioffs_offset, "indices_offsets", idx)
            start = MDL_BASE + ioffs_offset
            self.span(start, ioffs_count * 4, "indices_offsets", idx)
            orr = Reader(self.mdl, start)
            for i in range(ioffs_count):
                vi_offset = orr.u32()
                if vi_offset in NULL_OFFSETS:
                    continue
                self.off(start + i * 4, vi_offset, "vertexindices", idx)
                n = counts_list[i] if i < len(counts_list) else 0
                self.span(MDL_BASE + vi_offset, n * 2, "vertexindices", idx)

        if counters_offset not in NULL_OFFSETS and counters_count:
            self.off(t + 200, counters_offset, "counters", idx)
            self.span(MDL_BASE + counters_offset, counters_count * 4, "counters", idx)

        if vertices_offset not in NULL_OFFSETS and info.vertex_count:
            self.off(t + 328, vertices_offset, "mdl_vertex_array", idx)
            self.span(MDL_BASE + vertices_offset, info.vertex_count * 12,
                      "mdl_vertex_array", idx)

    def _skin_arrays(self, info: NodeInfo) -> None:
        s = info.skin_at
        idx = info.index
        wr = Reader(self.mdl, s + 12)
        info.mdx_weights_offset, info.mdx_bones_offset = wr.u32(), wr.u32()

        r = Reader(self.mdl, s + 20)
        bonemap_offset, bonemap_count = r.u32(), r.u32()
        self.cnt(s + 24, bonemap_count, "bonemap_count", idx)
        qbones_offset, qbones_count = r.u32(), r.u32()
        self.cnt(s + 32, qbones_count, "qbones_count", idx)
        self.cnt(s + 36, r.u32(), "qbones_count2", idx)
        tbones_offset, tbones_count = r.u32(), r.u32()
        self.cnt(s + 44, tbones_count, "tbones_count", idx)
        self.cnt(s + 48, r.u32(), "tbones_count2", idx)
        unk_offset, unk_count = r.u32(), r.u32()
        self.cnt(s + 56, unk_count, "skin_unknown0_count", idx)
        self.cnt(s + 60, r.u32(), "skin_unknown0_count2", idx)
        br = Reader(self.mdl, s + 64)
        info.bones = tuple(br.u16() for _ in range(16))

        for offset, count, stride, kind, loc in (
            (bonemap_offset, bonemap_count, 4, "bonemap", s + 20),
            (qbones_offset, qbones_count, 16, "qbones", s + 28),
            (tbones_offset, tbones_count, 12, "tbones", s + 40),
            (unk_offset, unk_count, 4, "skin_unknown0", s + 52),
        ):
            if offset in NULL_OFFSETS or not count:
                continue
            self.off(loc, offset, kind, idx)
            self.span(MDL_BASE + offset, count * stride, kind, idx)

        if bonemap_offset not in NULL_OFFSETS and bonemap_count:
            br = Reader(self.mdl, MDL_BASE + bonemap_offset)
            info.bonemap = tuple(int(br.f32()) for _ in range(bonemap_count))

    def _light_arrays(self, l: int, idx: int) -> None:
        """Lens-flare data: three parallel float arrays plus an array of texture
        name offsets pointing at NUL-terminated strings.

        Layout confirmed empirically against the corpus: ``flare_radius`` (f32)
        comes FIRST, then five (offset, count, count2) triples. PyKotor reads
        the radius after the triples, which mis-frames the whole subheader -
        one more reason its round-trip fails.
        """
        r = Reader(self.mdl, l + 4)
        fields = []
        for _ in range(5):  # unknown0, flare sizes, positions, colors, textures
            loc = r.pos
            offset, count = r.u32(), r.u32()
            r.u32()  # duplicate count
            fields.append((loc, offset, count))

        for (loc, offset, count), (stride, kind) in zip(
            fields,
            ((4, "light_unknown0"), (4, "flare_sizes"), (4, "flare_positions"),
             (12, "flare_colors"), (4, "flare_texture_offsets")),
        ):
            self.cnt(loc + 4, count, kind, idx)
            if offset in NULL_OFFSETS or not count:
                continue
            self.off(loc, offset, kind, idx)
            start = MDL_BASE + offset
            self.span(start, count * stride, kind, idx)
            if kind != "flare_texture_offsets":
                continue
            tr = Reader(self.mdl, start)
            for i in range(count):
                so = tr.u32()
                if so in NULL_OFFSETS:
                    continue
                self.off(start + i * 4, so, "flare_texture_name", idx)
                spos = MDL_BASE + so
                self.span(spos, len(cstr_at(self.mdl, spos)) + 1, "flare_texture_name", idx)

    def _saber_arrays(self, s: int, info: NodeInfo) -> None:
        """Saber blades keep their geometry in the MDL rather than the MDX:
        three arrays of ``vertex_count`` entries (positions, texcoords, normals)."""
        idx = info.index
        r = Reader(self.mdl, s)
        vertices_offset, texcoords_offset, normals_offset = r.u32(), r.u32(), r.u32()
        n = info.vertex_count
        for loc, offset, stride, kind in (
            (s + 0, vertices_offset, 12, "saber_vertices"),
            (s + 4, texcoords_offset, 8, "saber_texcoords"),
            (s + 8, normals_offset, 12, "saber_normals"),
        ):
            if offset in NULL_OFFSETS or not n:
                continue
            self.off(loc, offset, kind, idx)
            self.span(MDL_BASE + offset, n * stride, kind, idx)

    def _dangly_arrays(self, d: int, idx: int) -> None:
        r = Reader(self.mdl, d)
        constraints_offset, constraints_count = r.u32(), r.u32()
        self.cnt(d + 4, constraints_count, "constraints_count", idx)
        self.cnt(d + 8, r.u32(), "constraints_count2", idx)
        r.seek(d + 24)
        danglyverts_offset = r.u32()
        if constraints_offset not in NULL_OFFSETS and constraints_count:
            self.off(d, constraints_offset, "dangly_constraints", idx)
            self.span(MDL_BASE + constraints_offset, constraints_count * 4,
                      "dangly_constraints", idx)
        if danglyverts_offset not in NULL_OFFSETS and constraints_count:
            self.off(d + 24, danglyverts_offset, "danglyverts", idx)
            self.span(MDL_BASE + danglyverts_offset, constraints_count * 12,
                      "danglyverts", idx)

    def _aabb_tree(self, root: int, idx: int) -> None:
        """Walk the AABB tree; each node is 40 bytes with two child offsets."""
        stack = [root]
        seen: set[int] = set()
        while stack:
            off = stack.pop()
            if off in NULL_OFFSETS or off in seen:
                continue
            seen.add(off)
            pos = MDL_BASE + off
            if pos + AABB_NODE_SIZE > len(self.mdl):
                raise ParseError(f"AABB node at {off} runs past end of file")
            self.span(pos, AABB_NODE_SIZE, "aabb_node", idx)
            r = Reader(self.mdl, pos + 24)
            left, right = r.u32(), r.u32()
            for loc, child in ((pos + 24, left), (pos + 28, right)):
                if child not in NULL_OFFSETS:
                    self.off(loc, child, "aabb_node", idx)
                    stack.append(child)

    # ---- animations -------------------------------------------------------

    def _animations(self) -> None:
        if self.anim_array_offset in NULL_OFFSETS or not self.anim_count:
            return
        start = MDL_BASE + self.anim_array_offset
        self.span(start, self.anim_count * 4, "anim_offset_array")
        r = Reader(self.mdl, start)
        anim_offsets = [r.u32() for _ in range(self.anim_count)]
        for i, ao in enumerate(anim_offsets):
            self.off(start + i * 4, ao, "anim_header")
            self._animation(ao)

    def _animation(self, offset: int) -> None:
        pos = MDL_BASE + offset
        self.span(pos, ANIM_HEADER_SIZE, "anim_header")
        r = Reader(self.mdl, pos + 8)
        anim_name = r.cstr(32)
        self.L.animation_names.append(anim_name)
        root_node_offset = r.u32()
        self.off(pos + 40, root_node_offset, "node_header")

        r.seek(pos + 120)
        events_offset, event_count = r.u32(), r.u32()
        self.cnt(pos + 124, event_count, "event_count")
        self.cnt(pos + 128, r.u32(), "event_count2")
        if events_offset not in NULL_OFFSETS and event_count:
            self.off(pos + 120, events_offset, "event_array")
            self.span(MDL_BASE + events_offset, event_count * EVENT_SIZE, "event_array")

        prev, self._cur_anim = self._cur_anim, anim_name
        try:
            self._node(root_node_offset, parent=None)
        finally:
            self._cur_anim = prev

    # ---- MDX --------------------------------------------------------------

    def _mdx_blocks(self) -> None:
        """Each mesh node owns one contiguous MDX block. Block size is derived
        from the *next* block's start where possible, because vanilla meshes
        commonly carry a trailing dummy vertex beyond ``vertex_count``."""
        # NB: 0 is a legitimate MDX offset - the first block starts there - so
        # only 0xFFFFFFFF counts as "no block" in MDX space. A mesh with no
        # vertices (stride is then the 0xFFFFFFFF sentinel) owns no block at
        # all, and its stale offset 0 must not be mistaken for one.
        meshes = [
            n for n in self.L.nodes
            if n.is_mesh
            and n.vertex_count
            and n.mdx_stride not in (0, 0xFFFFFFFF)
            and n.mdx_data_offset != 0xFFFFFFFF
        ]
        meshes.sort(key=lambda n: n.mdx_data_offset)
        for i, n in enumerate(meshes):
            start = n.mdx_data_offset
            nominal = n.vertex_count * n.mdx_stride
            limit = meshes[i + 1].mdx_data_offset if i + 1 < len(meshes) else len(self.mdx)
            size = limit - start if limit >= start + nominal else nominal
            self.off(n.trimesh_at + 324, start, "mdx_block", n.index, space="MDX")
            self.mdx_span(start, size, "mdx_block", n.index)


def parse(mdl: bytes, mdx: bytes) -> Layout:
    return _Parser(mdl, mdx).parse()
