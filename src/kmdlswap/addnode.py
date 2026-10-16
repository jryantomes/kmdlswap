"""Add a mesh node to a K1 model: a copy of an existing one, under a parent of choice.

Written for GH0-RFK (2026-09-28): his eyes and a new mouth light each need a mesh of their
own under `talkdummy`, and the host had only one (`Mesh01`). The copy is then filled with
new geometry the usual way (`edit.replace_geometry`), so what it starts with does not matter.

Two passes, so nothing that already exists moves by hand:

1. The splice engine grows three kinds of array by one entry each - the model's name
   offsets, the parent's children, and every skin's bonemap (one float per geometry node,
   so a new node needs its -1) - and bumps their counts and the node count. The new node's
   number is its depth-first place, and every node after it is renumbered (see below).
   Every stored pointer is shifted by the engine. The two new pointer slots hold a
   placeholder.
2. The new node's name, header, subheaders and arrays are appended to the end of the MDL,
   and its vertex block to the end of the MDX, with the copy's own pointers re-aimed at
   its own arrays; then the placeholders are filled in and the sizes follow.

The result parses with no gaps, overlaps or dangling pointers (validate.check), which is
the same bar every other edit here has to clear.
"""

from __future__ import annotations

import struct

from ._io import MDL_BASE
from .layout import parse
from .rewrite import Rewriter

_U32 = struct.Struct("<I")


def add_mesh_node(mdl: bytes, mdx: bytes, template: str, name: str, parent: str) -> tuple[bytes, bytes]:
    L = parse(mdl, mdx)
    geo = [n for n in L.nodes if n.in_animation is None]
    if any(n.name.lower() == name.lower() for n in geo):
        raise ValueError(f"the model already has a node named {name!r}")
    tpl, par = L.node_by_name(template), L.node_by_name(parent)
    if not tpl.is_mesh or tpl.is_skin or tpl.children:
        raise ValueError(f"{template}: only a childless, unskinned mesh can be copied")
    # Node numbers are depth-first order - the engine relies on it: a copy numbered 58 but
    # sitting at depth-first place 10 (under talkdummy) stopped every save he was in from
    # loading (in-game harness, 2026-09-28). So the new node takes its depth-first place and
    # every node after it moves up one: in the geometry tree, in every animation's tree, in
    # the name list (indexed by node number), in the skins' bonemaps (one entry per node) and
    # in their bone tables (node numbers).
    if any(n.node_id != n.index for n in geo):
        raise ValueError("geometry node numbers are not depth-first order; not renumbering")

    def subtree(i):
        out = [i]
        for c in L.nodes[i].children:
            out += subtree(c)
        return out

    new_id = max(subtree(par.index)) + 1

    # ---- pass 1: make room in place, renumber ---------------------------------------
    rw = Rewriter(L)
    name_arr = next(s for s in L.spans if s.kind == "name_offset_array")
    name_slot = name_arr.start + 4 * new_id
    rw.replace_mdl(name_slot, name_slot, bytes(4))
    for c in L.counts:
        if c.array_id in ("name_offsets_count", "name_offsets_count2", "node_count"):
            rw.set_u32(c.loc, c.value + 1)
    kids = [s for s in L.spans if s.kind == "children_array" and s.owner == par.index]
    if not kids:
        raise ValueError(f"{parent} has no children array to grow")
    rw.replace_mdl(kids[0].end, kids[0].end, bytes(4))
    for c in L.counts:
        if c.owner == par.index and c.array_id in ("children_count", "children_count2"):
            rw.set_u32(c.loc, c.value + 1)
    bonemap_slots = []
    for skin in (n for n in geo if n.is_skin):
        bm = [s for s in L.spans if s.kind == "bonemap" and s.owner == skin.index]
        if not bm or bm[0].size // 4 != L.node_count:
            raise ValueError(f"{skin.name}: bonemap is not one entry per node")
        bonemap_slots.append(bm[0].start + 4 * new_id)
        rw.replace_mdl(bonemap_slots[-1], bonemap_slots[-1], struct.pack("<f", -1.0))
        for c in L.counts:
            if c.owner == skin.index and c.array_id == "bonemap_count":
                rw.set_u32(c.loc, c.value + 1)
        used = sum(1 for v in skin.bonemap if v >= 0)
        for k, b in enumerate(skin.bones[:used]):
            if b >= new_id:
                rw.set_u16(skin.skin_at + 64 + 2 * k, b + 1)
    for n in L.nodes:                                      # geometry and animation trees
        at = MDL_BASE + n.offset
        supernode, node_id = struct.unpack_from("<HH", L.mdl, at + 2)
        if node_id >= new_id:
            rw.set_u16(at + 4, node_id + 1)
        if supernode >= new_id:
            rw.set_u16(at + 2, supernode + 1)
    mdl1, mdx1 = rw.apply()
    inserts = sorted([name_slot, kids[0].end] + bonemap_slots)

    def moved(pos: int) -> int:
        """Where an original MDL position lands after pass 1 (inserts at or before it push it on)."""
        return pos + 4 * sum(1 for i in inserts if i <= pos)

    # ---- pass 2: append the node ------------------------------------------------------
    out = bytearray(mdl1)
    name_at = len(out)
    # no padding: it would be a gap (bytes nothing owns), and the engine does not need it -
    # GH0-RFK's model has 3,668 of its node headers at 2 mod 4 and runs as it is
    out += name.encode("ascii") + b"\0"
    pieces = sorted((s for s in L.spans if s.owner == tpl.index), key=lambda s: s.start)
    where = {}
    for s in pieces:
        where[s.start] = len(out)
        out += L.mdl[s.start:s.end]

    def remap(abs_pos: int) -> int | None:
        for s in pieces:
            if s.start <= abs_pos < s.end:
                return where[s.start] + (abs_pos - s.start)
        return None

    mdx_out = bytearray(mdx1)
    mdx_blocks = [s for s in L.mdx_spans if s.owner == tpl.index]
    mdx_where = {}
    for s in mdx_blocks:
        mdx_where[s.start] = len(mdx_out)
        mdx_out += L.mdx[s.start:s.end]

    node_new = where[MDL_BASE + tpl.offset]
    for o in (o for o in L.offsets if o.owner == tpl.index):
        loc = remap(o.loc)
        if loc is None:
            raise ValueError(f"{template}: pointer at {o.loc} is outside its own spans")
        if o.space == "MDX":
            s = next(b for b in mdx_blocks if b.start <= o.value < b.end)
            value = mdx_where[s.start] + (o.value - s.start)
        elif o.target_kind == "geometry_header":
            value = o.value                               # the model header does not move
        elif o.target_kind == "node_header" and o.loc == MDL_BASE + tpl.offset + 12:
            value = moved(MDL_BASE + par.offset) - MDL_BASE    # its parent
        else:
            target = remap(o.absolute)
            if target is None:
                raise ValueError(f"{template}: {o.target_kind} pointer leaves the node")
            value = target - MDL_BASE
        _U32.pack_into(out, loc, value)
    struct.pack_into("<HH", out, node_new + 2, new_id, new_id)          # supernode, node number

    # the placeholders: the new name's offset, the parent's new child
    hdr = MDL_BASE
    names_off, names_n = struct.unpack_from("<2I", out, hdr + 184)
    _U32.pack_into(out, MDL_BASE + names_off + 4 * new_id, name_at - MDL_BASE)
    par_at = moved(MDL_BASE + par.offset)
    kids_off, kids_n = struct.unpack_from("<2I", out, par_at + 44)
    _U32.pack_into(out, MDL_BASE + kids_off + 4 * (kids_n - 1), node_new - MDL_BASE)

    _U32.pack_into(out, 4, len(out) - MDL_BASE)
    _U32.pack_into(out, 8, len(mdx_out))
    _U32.pack_into(out, MDL_BASE + 176, len(mdx_out))
    return bytes(out), bytes(mdx_out)


def add_anim_node(mdl: bytes, mdx: bytes, anim: str, name: str, parent: str,
                  controllers: list[tuple[int, list[float], list[list[float]]]]) -> bytes:
    """Give animation `anim` a node for geometry node `name`, carrying `controllers`
    [(type, key times, [values per key])] - e.g. (100, times, [[r, g, b], ...]) for
    self-illumination. Written for GH0-RFK's blink (user, 2026-10-01: "hook his eye lights to
    blinking animation"): his eyes are a node of their own (add_mesh_node), which no animation
    knew about.

    The node goes under the animation's `parent` node, or its root when that animation has no
    such node (pause2 animates no head). Same two passes as add_mesh_node: grow the parent's
    children array in place (pointers shift with it), then append the node header, its
    controller array and its data at the end. Animation nodes are matched to the model's by
    node number, so the new one takes the geometry node's. Nothing is renumbered.
    """
    from .nodes import CONTROLLER_SIZE
    L = parse(mdl, mdx)
    geo = next((n for n in L.nodes if n.in_animation is None and n.name.lower() == name.lower()), None)
    if geo is None:
        raise ValueError(f"the model has no node named {name!r}")
    tree = [n for n in L.nodes if n.in_animation == anim]
    if not tree:
        raise ValueError(f"the model has no animation {anim!r}")
    if any(n.name.lower() == name.lower() for n in tree):
        raise ValueError(f"{anim} already has a node {name!r}")
    par = next((n for n in tree if n.name.lower() == parent.lower()), None) \
        or next(n for n in tree if n.parent is None)
    par_at = MDL_BASE + par.offset

    # ---- pass 1: room for one more child --------------------------------------------
    rw = Rewriter(L)
    kids = [s for s in L.spans if s.kind == "children_array" and s.owner == par.index]
    if not kids:
        raise ValueError(f"{anim}/{par.name} has no children array to grow")
    insert_at = kids[0].end
    rw.replace_mdl(insert_at, insert_at, bytes(4))
    for c in L.counts:
        if c.owner == par.index and c.array_id in ("children_count", "children_count2"):
            rw.set_u32(c.loc, c.value + 1)
    mdl1, mdx1 = rw.apply()

    def moved(pos: int) -> int:
        return pos + (4 if insert_at <= pos else 0)

    # ---- pass 2: append the node, its controllers and their data ------------------------
    out = bytearray(mdl1)
    node_at = len(out)
    header = bytearray(L.mdl[par_at:par_at + 80])
    struct.pack_into("<HHHH", header, 0, 1, geo.node_id, geo.node_id, 0)   # a plain node
    root_ptr = struct.unpack_from("<I", L.mdl, par_at + 8)[0]                # the animation header
    struct.pack_into("<I", header, 8, moved(MDL_BASE + root_ptr) - MDL_BASE)
    struct.pack_into("<I", header, 12, moved(par_at) - MDL_BASE)
    struct.pack_into("<7f", header, 16, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)
    struct.pack_into("<3I", header, 44, 0, 0, 0)                            # no children
    data: list[float] = []
    ctl = bytearray()
    for ctype, times, values in controllers:
        cols = len(values[0])
        if len(times) != len(values) or any(len(v) != cols for v in values):
            raise ValueError(f"controller {ctype}: {len(times)} times, {len(values)} rows")
        tk = len(data)
        data += times
        dk = len(data)
        for v in values:
            data += v
        ctl += struct.pack("<IHHHHB3x", ctype, 0xFFFF, len(times), tk, dk, cols)
    out += header
    ctl_at = len(out)
    out += ctl
    data_at = len(out)
    out += struct.pack(f"<{len(data)}f", *data)
    struct.pack_into("<3I", out, node_at + 56, ctl_at - MDL_BASE, len(controllers), len(controllers))
    struct.pack_into("<3I", out, node_at + 68, data_at - MDL_BASE, len(data), len(data))

    # the placeholder: the parent's new child
    kids_off, kids_n = struct.unpack_from("<2I", out, moved(par_at) + 44)
    _U32.pack_into(out, MDL_BASE + kids_off + 4 * (kids_n - 1), node_at - MDL_BASE)
    _U32.pack_into(out, 4, len(out) - MDL_BASE)
    assert len(ctl) == CONTROLLER_SIZE * len(controllers)
    return bytes(out)


def set_selfillum(mdl: bytes, mdx: bytes, node: str, value: float) -> bytes:
    """A geometry node's resting self-illumination (controller 100), all three channels."""
    from .nodes import CONTROLLER_SIZE
    L = parse(mdl, mdx)
    n = L.node_by_name(node)
    pos = MDL_BASE + n.offset
    co, cc = struct.unpack_from("<2I", mdl, pos + 56)
    do, _dl = struct.unpack_from("<2I", mdl, pos + 68)
    out = bytearray(mdl)
    for k in range(cc):
        ctype, _u, rows, _t, dstart, cols = struct.unpack_from("<IHHHHB", mdl, MDL_BASE + co + k * CONTROLLER_SIZE)
        if ctype == 100:
            for r in range(rows):
                for c in range(cols & 0x0F):
                    struct.pack_into("<f", out, MDL_BASE + do + 4 * (dstart + r * (cols & 0x0F) + c), value)
            return bytes(out)
    raise ValueError(f"{node} has no self-illumination controller")
