"""A Jade Empire body, written into a KOTOR body model.

A head has a route into KOTOR already: it becomes a head pack, and the pack is
spliced into a host. A body could not take that route, because a KOTOR body is
skinned and a head is not. Its geometry is not parented to a bone - it is
weighted across many, four influences to a vertex, and the engine will not skin
one mesh to more than seventeen of them. Jade ships a body as a single mesh
weighted to forty-five.

So the body arrives in pieces. `jade.partition` cuts it where KOTOR cuts its
own - Torso, LArm, RArm, Legs - and each piece replaces the host node that does
that job. The host keeps its skeleton, its bone tables, its animations and its
hooks; what changes is the geometry hanging off them, and the weights, which
are resampled from the host's own surface so that every one of them lands on a
bone the host actually has.

Nothing here writes into the game. The result is bytes, and installing them is
a separate, deliberate act.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import jade, space
from .library import ModelLibrary

TORSO = jade.TORSO

# The bodies worth building onto, and the reason there is more than one: a
# host's `headhook` is where the engine hangs the head, and the male and female
# skeletons do not put it at the same height. The male bodies hook at z 1.525,
# the female ones at 1.450.
#
# That 0.075 decides whether a ported body reaches its own head. Jade's women
# top out around 1.47, so on a male host the head floats with a quarter-inch of
# bare neck under it, and on a female host it is covered with room to spare.
# The fix is to pick the right host, not to stretch the body up to a hook that
# was never meant for it.
HOSTS = ("P_CarthBB", "PMBBM", "PFBBM")
FEMALE_HOSTS = ("PFBBM",)

# A KOTOR texture reference is a 32-byte field and the resref that fills it is
# 16 characters. Named from the model rather than the folder: the folder is the
# caller's choice and truncating it puts the cut in the wrong place.
RESREF_STEM = 14


@dataclass
class Built:
    """What came out, and what it cost."""

    resref: str = ""
    host: str = ""
    mdl: bytes = b""
    mdx: bytes = b""
    texture: str = ""
    texture_bytes: bytes = b""
    lines: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.mdl and self.mdx)


def limb_for(node_name: str) -> str | None:
    """Which of `jade.partition`'s limbs a host node wants, or None.

    KOTOR is not consistent about the names: `PMBBM` calls them torso, armL and
    armR, `PFBBM` Torso, LArm and RArm, `P_CarthBB` those plus Legs. They are
    consistent about the words in them.
    """
    name = node_name.lower()
    if "torso" in name:
        return jade.TORSO
    if "leg" in name:
        return "Legs"
    if "arm" in name:
        side = name.replace("arm", "")
        if "l" in side:
            return "LArm"
        if "r" in side:
            return "RArm"
    return None


# How far a body may be resized to meet the head it wears. A Jade garment with
# a lower collar than KOTOR's needs about 2 percent; anything asking for much
# more is not a collar mismatch, it is the wrong host, and stretching a body
# that far breaks it against the skeleton it hangs on - the bones stay the
# host's whatever the mesh does.
SEAT_LIMIT = 0.06


def neck_column(body_positions, head_scene):
    """Where the head's neck lands, and how high the body reaches under it.

    Not a bounding box. The body's highest point is a shoulder, and comparing
    that with the head's lowest says "covered" while the neck hangs over a
    hole - which is exactly the check that passed while the gap was visible.

    Nor a column around `headhook`: a head's neck sits a good way forward of
    its hook, and a column on the hook measures the back of the collar, which
    is the high side. It has to be the neck's own footprint.
    """
    import numpy as np

    worn = np.asarray(head_scene.positions, dtype=float)
    if not len(worn):
        return None
    bottom = worn[:, 2].min()
    ring = worn[worn[:, 2] < bottom + 0.02]
    if len(ring) < 3:
        return None
    cx, cy = float(ring[:, 0].mean()), float(ring[:, 1].mean())
    radius = max(float(np.ptp(ring[:, 0])), float(np.ptp(ring[:, 1]))) / 2.0
    body = np.asarray(body_positions, dtype=float)
    under = body[np.hypot(body[:, 0] - cx, body[:, 1] - cy) <= radius]
    if not len(under):
        return bottom, float("-inf"), float(body[:, 2].min())
    return bottom, float(under[:, 2].max()), float(body[:, 2].min())


def seat_scale(parts, host_layout, head_layout):
    """How to resize a body so its collar meets the head, as (factor, why).

    The target is the host's own relationship with that head, whatever it is:
    reproduce it and a head that sits right on the host sits right here.
    Uniform and about the floor, so the feet stay on it.

    `why` is one of `open` (the collar rings the neck rather than meeting it,
    which is a garment with a neck hole and wants nothing done), `reaches`
    (already tall enough - a collar is allowed to be high), or `raise`.
    """
    import numpy as np

    from . import render as krender

    placed = krender.place_head(host_layout, head_layout)
    if placed is None:
        return None, "no hook"
    host = neck_column(krender.from_layout(host_layout).positions, placed)
    ours = neck_column(
        np.vstack([np.asarray(p.positions) for p in parts if p.positions]),
        placed)
    if host is None or ours is None:
        return None, "no neck"
    _bottom, host_top, _host_floor = host
    _b, our_top, our_floor = ours
    if our_top == float("-inf"):
        return None, "open"
    if host_top == float("-inf") or our_top <= our_floor:
        return None, "no neck"
    want = (host_top - our_floor) / (our_top - our_floor)
    return want, ("raise" if want > 1.0 else "reaches")


def _turn(rest, vector):
    """A direction in the node's space. Rotated, never moved."""
    return tuple(sum(rest.rotation[k][i] * vector[k] for k in range(3))
                 for i in range(3))


def _merge(parts: list):
    """Every part of one limb, joined into a single mesh for one host node.

    A body can arrive as several Jade meshes - a figure, a chestplate, a vein
    of trim - and each contributes to the same limbs. A host node is one node
    and takes one mesh, so they are joined here rather than fighting over it.
    """
    positions: list = []
    faces: list = []
    uvs: list = []
    normals: list = []
    weight: dict = {}
    for part in parts:
        base = len(positions)
        positions.extend(part.positions)
        faces.extend((a + base, b + base, c + base) for a, b, c in part.faces)
        # UVs and normals are per vertex, so a part missing them would shift
        # every later part's. Pad rather than let that happen.
        uvs.extend(part.uvs if len(part.uvs) == len(part.positions)
                   else [(0.0, 0.0)] * len(part.positions))
        normals.extend(part.normals if len(part.normals) == len(part.positions)
                       else [(0.0, 0.0, 1.0)] * len(part.positions))
        if part.material:
            weight[part.material] = weight.get(part.material, 0) + len(part.faces)
    material = max(weight, key=lambda m: weight[m]) if weight else None
    return positions, faces, uvs, normals, material, weight


def run(entry, *, host: str = HOSTS[0], install=None, jade_install=None,
        pose: float | None = jade.KOTOR_ARM_REST,
        scale: float = jade.BODY_SCALE, head=None) -> Built:
    """Build one Jade body onto one KOTOR host. Returns the bytes, not a file.

    `head` is the head model this body will be worn with, and giving it seats
    the collar against that head's neck. Without it the body is built at its
    own size, which is right until you put a KOTOR head on it: Jade cuts some
    of its collars lower than KOTOR does, and the neck then ends in mid air.
    """
    from kmdlswap import edit as kedit
    from kmdlswap import layout as kl
    from kmdlswap import obj as kobj
    from kmdlswap import swap as kswap

    out = Built(resref=entry.resref, host=host)
    lib = ModelLibrary(install)
    if not lib.has(host):
        raise jade.JadeError(f"the install has no {host} to build onto")
    mdl, mdx = lib.read(host)

    model = jade._parse(*jade.read(entry))
    parts = jade.partition(model, pose=pose, scale=scale)

    if head is not None:
        want, why = seat_scale(parts, kl.parse(mdl, mdx), head)
        if why == "open":
            out.lines.append(
                "seated: the collar rings the neck rather than meeting it - "
                "a garment with a neck hole, and nothing to close")
        elif want is None:
            out.warnings.append(
                "could not find where this head's neck lands, so the body is "
                "built at its own size")
        elif why == "reaches":
            out.lines.append(
                "seated: the collar already reaches the head's neck")
        elif want - 1.0 > SEAT_LIMIT:
            out.warnings.append(
                f"the collar falls {want - 1:.0%} short of this head's neck, "
                f"past the {SEAT_LIMIT:.0%} worth correcting - built at its own "
                f"size, and the host is probably the wrong one")
        else:
            scale *= want
            parts = jade.partition(model, pose=pose, scale=scale)
            out.lines.append(
                f"seated: raised {want - 1:.1%} so the collar meets the head's "
                f"neck, the way {host} meets it")
    by_limb: dict = {}
    for part in parts:
        by_limb.setdefault(part.limb, []).append(part)

    # Jade builds 49 of its 112 people with a head on the body, sometimes with
    # a mask over that. KOTOR hangs the head on `headhook` as its own model, so
    # a body that brings its own wears two - and the one you see is the wrong
    # one, sitting a little higher and a little wider than the real face.
    head = by_limb.pop(jade.HEAD_LIMB, None)
    if head:
        out.lines.append(
            f"left the Jade head behind ({sum(len(p.faces) for p in head)} "
            f"triangles) - KOTOR hangs its own on headhook")

    # The texture is found before the splice, because each node's reference to
    # it is written as part of that node's rewrite.
    _dress(out, entry, parts, jade_install)

    layout = kl.parse(mdl, mdx)
    wanted = [n.name for n in layout.nodes
              if n.in_animation is None and n.is_skin and limb_for(n.name)]
    if not wanted:
        raise jade.JadeError(f"{host} has no skinned body meshes to replace")

    # A three-node host - every female body, and `PMBBM` - keeps its legs
    # inside its torso mesh rather than in one of their own. Fold ours the same
    # way rather than dropping them: that is not a workaround, it is how KOTOR
    # builds those bodies.
    taken = {limb_for(n) for n in wanted}
    for limb in sorted(set(by_limb) - taken):
        moved = by_limb.pop(limb)
        by_limb.setdefault(TORSO, []).extend(moved)
        out.lines.append(
            f"{host} has no {limb} node, so those "
            f"{sum(len(p.faces) for p in moved)} triangles go in the torso - "
            f"which is where {host} keeps its own")

    for node_name in wanted:
        limb = limb_for(node_name)
        group = by_limb.get(limb)
        if not group:
            out.warnings.append(f"nothing to put in {node_name}")
            continue
        positions, faces, uvs, normals, material, spread = _merge(group)
        if len(spread) > 1:
            kept = sum(n for m, n in spread.items() if m == material)
            total = sum(spread.values())
            out.warnings.append(
                f"{node_name} draws {len(spread)} Jade textures but a KOTOR "
                f"node wears one: {total - kept} of {total} triangles will "
                f"take the wrong one")

        layout = kl.parse(mdl, mdx)
        node = layout.node_by_name(node_name)
        # A skinned mesh's vertices are stored in its *node's* space, and the
        # node is not always at the origin: `P_CarthBB` keeps all four within a
        # centimetre of it, but `PFBBM` hangs its torso at z 1.042 and offset
        # sideways. Written as model space they came out a metre high on that
        # host - and one centimetre low on Carth, which is small enough to look
        # like nothing and is a third of the gap under his head.
        rest = space.rest_pose(layout)[node.index]
        local = [rest.to_local(p) for p in positions]
        turned = [_turn(rest, n) for n in normals] if normals else normals
        mesh = kobj.ObjMesh(name=node_name, positions=local, faces=faces,
                            uvs=uvs, normals=turned)
        # `facial_rig=False` matters: those two passes look for a brow band and
        # for lips, and on a torso they find something and rebind it.
        geo, report = kswap.build_replacement(layout, node, mesh,
                                              facial_rig=False)
        mdl, mdx = kedit.replace_geometry(layout, node, geo,
                                          texture=out.texture or None)
        out.lines.append(
            f"{node_name}: {report.old_vertices} vertices and "
            f"{report.old_triangles} triangles became {report.new_vertices} "
            f"and {report.new_triangles}, on {report.bones_used} bones")

    out.mdl, out.mdx = mdl, mdx
    return out


def _dress(out: Built, entry, parts: list, jade_install) -> None:
    """Find the body's texture and give it a name KOTOR can hold."""
    root = jade_install or jade._install_of(entry)
    if root is None:
        out.warnings.append("no Jade install to read the texture from - "
                            "it will wear the host's")
        return
    seen: dict = {}
    for part in parts:
        if part.material and part.limb != jade.HEAD_LIMB:
            seen[part.material] = seen.get(part.material, 0) + len(part.faces)
    for material in sorted(seen, key=lambda m: -seen[m]):
        name = jade.texture_name(root, material)
        data = jade.texture(root, name) if name else None
        if data:
            stem = (entry.resref.strip("_").lower() or "jadebody")
            out.texture = stem[:RESREF_STEM] + "01"
            out.texture_bytes = data
            out.lines.append(f"texture {name} decoded from .txb")
            return
    out.warnings.append("no texture found - it will wear the host's")


def write(out: Built, folder) -> list:
    """Put a build on disk. Never inside the game - that is a separate act."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    written = [folder / f"{out.host}.mdl", folder / f"{out.host}.mdx"]
    written[0].write_bytes(out.mdl)
    written[1].write_bytes(out.mdx)
    if out.texture_bytes:
        skin = folder / f"{out.texture}.tga"
        skin.write_bytes(out.texture_bytes)
        written.append(skin)
    return written
