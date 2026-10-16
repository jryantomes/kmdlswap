"""An animation from one model added to another (2026-10-07: sitting in KOTOR I - the user: "I want to
be able to sit in chairs in KOTOR"; KOTOR II's sit animations onto K1's supermodels).

    add_animation(target, source, anim, new_name) -> (mdl, mdx)

Both models in KOTOR I's format (a KOTOR II source goes through k2tok1 first). The animation is
written anew at the end of the target's MDL data, not copied as raw spans:

  * its header, with the new name;
  * its node tree, each node bound to the TARGET's bone of the same name - an animation node
    carries its bone's node number (+2) and name index (+4) exactly as the geometry node does
    (measured on s_female03: "meditate"'s pelvis_g = (68, 5) = the geometry pelvis_g's);
    the source's root binds to the target's root; nodes whose bone the target lacks (KOTOR II's
    robe and sleeve bones) are left out, their subtrees with them;
  * each node's controllers and controller data byte for byte (the key data is self-contained:
    the controller rows index into the node's own data block);
  * the events, if any.

The target's animation array gains one entry and its two counts one each (the splice engine
moves everything after the grown array and re-aims every stored pointer). The MDX is untouched:
an animation has no vertex data.
"""

from __future__ import annotations

import struct

from ._io import MDL_BASE
from .layout import NULL_OFFSETS, parse
from .rewrite import Rewriter

NODE_HEADER = 80
ANIM_HEADER = 136
CONTROLLER = 16
EVENT = 36


class TransplantError(Exception):
    pass


def _u32(b, at):
    return struct.unpack_from("<I", b, at)[0]


def add_animation(target: tuple[bytes, bytes], source: tuple[bytes, bytes], anim: str, new_name: str,
                  keys=None) -> tuple[bytes, bytes]:
    """keys: optional (node name, controller rows, data block) -> (controller rows, data block), to
    rewrite a node's keys on the way (the rows' offsets index into the returned data block)."""
    tmdl, tmdx = target
    smdl, smdx = source
    Lt, Ls = parse(tmdl, tmdx), parse(smdl, smdx)
    if Lt.game != "K1" or Ls.game != "K1":
        raise TransplantError(f"both models must be KOTOR I's (target {Lt.game}, source {Ls.game})")
    if anim not in Ls.animation_names:
        raise TransplantError(f"source has no animation {anim!r}")
    if new_name in Lt.animation_names:
        raise TransplantError(f"target already has an animation {new_name!r}")

    # the target's bones: name -> (node number at +2, name index at +4)
    bones = {}
    troot = None
    for n in Lt.nodes:
        if n.in_animation is None:
            pos = MDL_BASE + n.offset
            sup, nid = struct.unpack_from("<2H", tmdl, pos + 2)
            bones[n.name.lower()] = (sup, nid)
            if n.parent is None:
                troot = (sup, nid)

    # the source animation's header and node tree
    s_header = next(s.start for s in Ls.spans
                    if s.kind == "anim_header" and smdl[s.start + 8:s.start + 40].split(b"\0")[0].decode() == anim)
    troot_name = next(n.name for n in Lt.nodes if n.in_animation is None and n.parent is None)
    sroot_name = next(n.name for n in Ls.nodes if n.in_animation is None and n.parent is None)
    snodes = [n for n in Ls.nodes if n.in_animation == anim]
    sroot = next(n for n in snodes if n.parent is None)
    kept, dropped = [], []

    def walk(n):
        if n is not sroot and n.name.lower() not in bones:
            dropped.append(n.name)
            return
        kept.append(n)
        for c in n.children:
            walk(Ls.nodes[c])
    walk(sroot)

    # layout of the new block, offsets relative to its start (MDL-data space)
    final_start = (len(tmdl) - MDL_BASE) + 4          # after the animation array grows by one entry
    out = bytearray()

    def here():
        return final_start + len(out)

    header_at = here()
    out += bytes(ANIM_HEADER)
    node_at = {}
    for n in kept:                                    # headers first, each node's arrays after it
        node_at[n.index] = None
    plan = []
    for n in kept:
        spos = MDL_BASE + n.offset
        node_at[n.index] = here()
        out += bytes(NODE_HEADER)
        ctrl_off, ctrl_n = _u32(smdl, spos + 56), _u32(smdl, spos + 60)
        data_off, data_n = _u32(smdl, spos + 68), _u32(smdl, spos + 72)
        kids = [c for c in n.children if Ls.nodes[c] in kept]
        ca = here(); out += bytes(4 * len(kids))
        ctrls = smdl[MDL_BASE + ctrl_off:MDL_BASE + ctrl_off + ctrl_n * CONTROLLER] \
            if ctrl_n and ctrl_off not in NULL_OFFSETS else b""
        data = smdl[MDL_BASE + data_off:MDL_BASE + data_off + data_n * 4] \
            if data_n and data_off not in NULL_OFFSETS else b""
        if keys is not None:
            ctrls, data = keys(n.name, bytes(ctrls), bytes(data))
            ctrl_n, data_n = len(ctrls) // CONTROLLER, len(data) // 4
        cc = here()
        out += ctrls
        cd = here()
        out += data
        plan.append((n, spos, kids, ca, cc, cd, ctrl_n, data_n))

    # events
    ev_off, ev_n = _u32(smdl, s_header + 120), _u32(smdl, s_header + 124)
    events_at = here() if ev_n and ev_off not in NULL_OFFSETS else 0xFFFFFFFF
    if events_at != 0xFFFFFFFF:
        out += smdl[MDL_BASE + ev_off:MDL_BASE + ev_off + ev_n * EVENT]

    rel = lambda a: a - final_start                  # position in `out`

    # node headers
    for n, spos, kids, ca, cc, cd, ctrl_n, data_n in plan:
        h = bytearray(smdl[spos:spos + NODE_HEADER])
        sup, nid = troot if n is sroot else bones[n.name.lower()]
        struct.pack_into("<2H", h, 2, sup, nid)
        struct.pack_into("<I", h, 8, header_at)                          # the owning geometry header
        parent = n.parent if n is not sroot else None
        struct.pack_into("<I", h, 12, node_at[parent] if parent is not None else 0)
        struct.pack_into("<3I", h, 44, ca if kids else 0, len(kids), len(kids))
        struct.pack_into("<3I", h, 56, cc if ctrl_n else 0, ctrl_n, ctrl_n)
        struct.pack_into("<3I", h, 68, cd if data_n else 0, data_n, data_n)
        at = rel(node_at[n.index])
        out[at:at + NODE_HEADER] = h
        for i, c in enumerate(kids):
            struct.pack_into("<I", out, rel(ca) + 4 * i, node_at[c])

    # the animation header: the source's, renamed, its root and events re-aimed
    h = bytearray(smdl[s_header:s_header + ANIM_HEADER])
    name = new_name.encode()
    if len(name) > 31:
        raise TransplantError(f"name too long: {new_name!r}")
    h[8:40] = name + bytes(32 - len(name))
    struct.pack_into("<I", h, 40, node_at[sroot.index])
    # the animation's root names the model it was made for (KOTOR II's "S_Female02"): the target's
    root = h[88:120].split(b"\0")[0].decode()
    if root.lower() == sroot_name.lower():
        h[88:120] = troot_name.encode() + bytes(32 - len(troot_name))
    struct.pack_into("<I", h, 44, len(kept))                             # node count
    struct.pack_into("<3I", h, 120, events_at if ev_n else 0, ev_n, ev_n)
    out[0:ANIM_HEADER] = h

    # into the target: one more entry in the animation array, the counts, the block at the end
    rw = Rewriter(Lt)
    counts = [c for c in Lt.counts if c.array_id in ("animation_count", "animation_count2")]
    for c in counts:
        rw.set_u32(c.loc, c.value + 1)
    arr = next((s for s in Lt.spans if s.kind == "anim_offset_array"), None)
    if arr is not None:
        rw.replace_mdl(arr.end, arr.end, struct.pack("<I", header_at))
        rw.replace_mdl(len(tmdl), len(tmdl), bytes(out))
    else:
        # no animations yet (a body model): the array is made too, just before the animation -
        # final_start already counts its 4 bytes; the header's array pointer (just before the
        # first count) is aimed at it
        array_loc = min(c.loc for c in counts) - 4
        rw.set_u32(array_loc, final_start - 4)
        rw.replace_mdl(len(tmdl), len(tmdl), struct.pack("<I", header_at) + bytes(out))
    mdl, mdx = rw.apply()
    check = parse(mdl, mdx)
    if new_name not in check.animation_names:
        raise TransplantError("the new animation is not in the result")
    return mdl, mdx, dropped
