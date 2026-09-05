"""Keeping a head's teeth and tongue, and seating them inside the new face.

A KOTOR head is not one mesh. The face is `Head`, and the mouth interior is two
or three separate nodes beside it - teeth and a tongue - each with its own rest
transform placing it behind the lips. They are near-universal: across the 106
head models in K1, 104 carry a `tongue` and essentially all carry teeth, under
three naming schemes (`teethua`/`teethla` on 54, `teethupper`/`teethlower` on
44, `teethua01`/`teethla01` on 3, which is Carth).

When a converted head replaces `Head`, the build hides every other visible node,
because they were shaped for a face that is gone and would otherwise float. For
hair and eyelids that is right. For the mouth interior it is not: those parts sit
*inside* the head rather than on its surface, and hiding them leaves a mouth that
opens onto nothing. Reported from the game as a mouth that looks "taped shut" -
the lips move, and there is no tongue or teeth behind them.

**Why they cannot simply be left visible.** They are positioned for the host's
face, and a converted face is rarely the same depth. Measured in model space,
Carth's teeth sit 0.0085 behind his lip surface; the Jade Empire head's face at
the same height is 0.0137 shallower, which puts those same teeth 0.0052 *in
front* of the new lips. They render as a permanent grimace, which is what an
early attempt at this looked like and why the idea was wrongly abandoned.

So the parts are kept and moved back, to the clearance they had on the host.
That figure is not assumed - both the host's clearance and the replacement's
face depth are measured from the geometry, so a deeper face pulls them forward
and a shallower one pushes them back.

**The move has to be made to the geometry, not the node.** A first version of
this edited each node's rest position in its header, which measured correct in
the file and did nothing in game: `teethUa01` and `teethLa01` both carry a
position controller (type 8), and the engine takes the controller's value over
the header field. `tongue` is skinned, so its node position is bypassed too.
Offsetting the vertices instead cannot be overridden by anything, and the stored
bounding box is transported with them - the engine culls and sorts by that box,
so leaving it describing the old position would be a defect of its own.

Only depth is corrected. The teeth already bracket the mouth vertically (Carth's
span 0.0702 to 0.0922 in model space, against the Jade head's lips at 0.0783 to
0.0864) and are narrow enough to fit, so moving them in z or scaling them would
be inventing a correction for a problem that is not there.
"""

from __future__ import annotations

import struct

import numpy as np

from kmdlfun import parts as kparts
from kmdlfun import space
from kmdlswap import mdx as kmdx
from kmdlswap._io import MDL_BASE

# Controller kinds, from the 16-byte controller entry.
POSITION_CONTROLLER = 8

# Mouth interior, under every naming scheme the K1 corpus uses.
TEETH = ("teethua", "teethla", "teethupper", "teethlower", "teethua01", "teethla01")
TONGUE = ("tongue",)


def is_mouth_part(name: str) -> bool:
    """Whether a node is mouth interior rather than facial surface.

    Deliberately a prefix test on `teeth`: the corpus shows three schemes and
    there is no reason to think a mod will not add a fourth.
    """
    lowered = name.lower()
    return lowered.startswith("teeth") or lowered in TONGUE


def mouth_parts(layout) -> list:
    """The head's mouth-interior mesh nodes."""
    return [n for n in kparts.mesh_nodes(layout) if is_mouth_part(n.name)]


def _model_space(layout, node, rest) -> np.ndarray:
    P = np.asarray(kmdx.positions(layout, node), dtype=float)
    if not len(P):
        return P
    r = rest[node.index]
    return (np.asarray(r.rotation, dtype=float) @ P.T).T + np.asarray(r.position, dtype=float)


def _local_clearance(face: np.ndarray, part: np.ndarray, mid_y: float) -> float | None:
    """The tightest gap between a part and the face *at the part's own spot*.

    Measured locally, vertex by vertex, and it has to be: taking the face's
    frontmost point over a whole height band instead sweeps in the brow and the
    nose ridge, which stand far in front of an eye socket. Measured on Carth,
    that band gives 0.0153 for his eyeballs where the local figure is 0.0023 -
    seven times too much. Applied as a correction it buried a converted head's
    eyes inside its skull, and the head had no eyes at all in game.

    A `want` from one method and a `have` from the other cannot be compared.
    Both sides of any seating decision use this.
    """
    gaps = []
    for q in part:
        near = face[
            (np.abs(face[:, 2] - q[2]) < 0.005)
            & (np.abs(face[:, 0] - q[0]) < 0.008)
            & (face[:, 1] > mid_y)
        ]
        if len(near):
            gaps.append(float(near[:, 1].max() - q[1]))
    return min(gaps) if gaps else None


def _face_depth(face: np.ndarray, low: float, high: float, half_width: float) -> float | None:
    """How far forward the face reaches, over the height the mouth occupies.

    Restricted to the middle of the face by ``half_width`` so that a cheek or an
    ear cannot stand in for the lips.
    """
    if not len(face):
        return None
    band = face[
        (face[:, 2] >= low) & (face[:, 2] <= high) & (np.abs(face[:, 0]) <= half_width)
    ]
    if len(band) < 4:
        return None
    return float(band[:, 1].max())


def seat(layout, mdl: bytes, mdx: bytes, node, host_layout=None):
    """Move the mouth interior back behind the replacement's lips.

    ``layout`` is the model *after* the face has been replaced; ``host_layout``
    is the original, used to measure the clearance the parts are supposed to
    have. Returns ``(mdl, mdx, lines)``, with the bytes unchanged and no lines
    when there is nothing to move.
    """
    host_layout = host_layout if host_layout is not None else layout
    parts = mouth_parts(layout)
    if not parts:
        return mdl, mdx, []

    rest = space.rest_pose(layout)
    host_rest = space.rest_pose(host_layout)

    interior = [_model_space(layout, p, rest) for p in parts]
    interior = [p for p in interior if len(p)]
    if not interior:
        return mdl, mdx, []
    stacked = np.concatenate(interior)
    low, high = float(stacked[:, 2].min()), float(stacked[:, 2].max())
    half_width = max(float(np.abs(stacked[:, 0]).max()) * 1.5, 1e-4)

    new_face = _model_space(layout, node, rest)
    host_node = next(
        (n for n in kparts.mesh_nodes(host_layout) if n.name.lower() == node.name.lower()),
        None,
    )
    if host_node is None:
        return mdl, mdx, []
    old_face = _model_space(host_layout, host_node, host_rest)

    new_depth = _face_depth(new_face, low, high, half_width)
    old_depth = _face_depth(old_face, low, high, half_width)
    if new_depth is None or old_depth is None:
        return mdl, mdx, []

    # The clearance the host had, reproduced against the new face. Measuring the
    # host rather than picking a number means a head whose teeth were always
    # tight stays tight, and one with room keeps its room.
    front = float(stacked[:, 1].max())
    want = old_depth - front
    shift = (new_depth - want) - front
    if abs(shift) < 1e-5:
        return mdl, mdx, []

    from kmdlswap import edit as ke
    from kmdlswap import layout as kl

    out = mdl
    current_mdx = None
    names = []
    for part in parts:
        after = kl.parse(out, current_mdx) if current_mdx is not None else layout
        target = next(
            (n for n in kparts.mesh_nodes(after) if n.name.lower() == part.name.lower()),
            None,
        )
        if target is None:
            continue
        r = rest[part.index]
        # The vertices are in node space, so a model-space shift has to be
        # rotated into it. The rest rotation is orthonormal, so that is its
        # transpose.
        local = tuple(
            float(v) for v in np.asarray(r.rotation, dtype=float).T @ np.array([0.0, shift, 0.0])
        )
        geo = ke.extract(after, target)
        geo.columns["vertex"] = [
            tuple(p[i] + local[i] for i in range(3)) for p in geo.positions
        ]
        out, current_mdx = ke.replace_geometry(
            after, target, geo, moved=ke.UniformScale(1.0, local)
        )
        names.append(part.name)

    if not names:
        return mdl, mdx, []

    direction = "back" if shift < 0 else "forward"
    return out, current_mdx, [
        f"mouth interior: moved {', '.join(names)} {direction} by {abs(shift):.4f} "
        f"to sit {want:.4f} behind the new lips, as on the host"
    ]


# --- the cavity behind the lips, and a claim that did not survive measuring ---
#
# A KOTOR head lines the inside of its mouth with a recessed pocket. Carth's is
# 8 vertices and 6 faces, sitting 0.0251 to 0.0515 behind his lip surface, every
# one sampling the same flat dark patch of his texture (luminance 33.7).
#
# It looked as though a converted head lacked the depth, and it does not. Jade
# Empire's `h_common01_` carries an 11-vertex interior at **0.0160 to 0.0494**
# against Carth's 0.0251 to 0.0515 - within a few thousandths. An earlier
# reading here made it three times shallower by comparing Carth's *deepest*
# vertices against the Jade bag's *frontmost* point, which are not the same
# quantity. A depth correction was written against that reading and moved the
# interior by 0.0004, which is nothing; it is removed rather than left to look
# like it does something.
#
# What does differ is how it is painted: luminance ~127 against Carth's 33.7.
# The geometry is where it should be and reads as lip rather than as a hole
# because it is mid-tone rather than dark. That is a texture difference, not a
# conversion fault, and repainting it is editing the artist's intent.


def seat_islands(mesh, pieces, shell, want: float, what: str = "the lip") -> list[str]:
    """Push a head's *own* teeth back to the clearance the host's teeth have.

    `seat` above moves the host's teeth, which are separate nodes. A converted
    head usually carries its own as islands inside the mesh, and those have
    never been touched - on Jade Empire's `h_common01_` the upper teeth clear
    the lip surface by **0.0030** against the 0.0085 the same build gives
    Carth's. At rest that is enough; it is not enough once the upper lip lifts,
    and the teeth come through the lip as a white bar. Reported from the game
    exactly so.

    Each piece is moved as one, by the difference between its tightest clearance
    and the wanted one, so its shape and its position along the mouth are kept.
    """
    if not pieces or want is None or want <= 0:
        return []
    P = np.asarray([p[:3] for p in mesh.positions], dtype=np.float64)
    if not len(shell):
        return []
    lo, hi = P.min(axis=0), P.max(axis=0)
    mid_y = (lo[1] + hi[1]) / 2
    front_shell = [s for s in shell if P[s][1] > mid_y]
    if not front_shell:
        return []

    lines = []
    for name, idx in pieces:
        if not idx:
            continue
        gaps = []
        for v in idx:
            near = [
                s for s in front_shell
                if abs(P[s][2] - P[v][2]) < 0.004 and abs(P[s][0] - P[v][0]) < 0.006
            ]
            if near:
                gaps.append(max(P[s][1] for s in near) - P[v][1])
        if not gaps:
            continue
        have = float(min(gaps))
        shift = want - have
        if shift <= 1e-4:
            continue
        for v in idx:
            x, y, z = mesh.positions[v][:3]
            mesh.positions[v] = (x, y - shift, z)
        lines.append(
            f"{name}: moved back {shift:.4f} to clear {what} by {want:.4f}, "
            f"the clearance the host keeps (was {have:.4f})"
        )
    return lines


def teeth_clearance(host_positions, host_layout, host_node) -> float | None:
    """How far the host keeps its own teeth behind its lip surface."""
    parts = mouth_parts(host_layout)
    if not parts:
        return None
    rest = space.rest_pose(host_layout)
    interior = [_model_space(host_layout, p, rest) for p in parts]
    interior = [p for p in interior if len(p)]
    if not interior:
        return None
    stacked = np.concatenate(interior)
    low, high = float(stacked[:, 2].min()), float(stacked[:, 2].max())
    half_width = max(float(np.abs(stacked[:, 0]).max()) * 1.5, 1e-4)
    face = _model_space(host_layout, host_node, rest)
    depth = _face_depth(face, low, high, half_width)
    if depth is None:
        return None
    return float(depth - stacked[:, 1].max())


# --- eyes --------------------------------------------------------------------
#
# A KOTOR head blinks with separate eyelid *meshes*: `eyeLlid` and `eyeRlid`,
# 18 vertices each, not skinned, parented to `head_g` and moved by the engine.
# The face itself does not deform to blink - the host's eye region is 88%
# `head_g`. So hiding those lids, as the build did for every part that was not
# the replaced node, removes blinking altogether. Reported from the game as
# neither converted head ever blinking.
#
# The eyeballs are the other half. Carth's clear his face surface by 0.0153 at
# their tightest; a converted head's own eyes came out at -0.0017, which is
# through the face. That is the same failure as the teeth in the mouth, and it
# reads the same way: eyes sitting on the surface rather than behind the eyeline.

EYELIDS = ("eyellid", "eyerlid")


def is_eyelid(name: str) -> bool:
    """Whether a node is an eyelid, which is what does the blinking."""
    return name.lower() in EYELIDS


def eyelids(layout) -> list:
    return [n for n in kparts.mesh_nodes(layout) if is_eyelid(n.name)]


def eye_clearance(host_layout, host_node) -> float | None:
    """How far the host keeps its eyeballs behind its face at the eye line."""
    balls = [
        n for n in kparts.mesh_nodes(host_layout)
        if n.name.lower() in ("eyela", "eyera")
    ]
    if not balls:
        return None
    rest = space.rest_pose(host_layout)
    eye = np.concatenate([_model_space(host_layout, n, rest) for n in balls])
    face = _model_space(host_layout, host_node, rest)
    if not len(face) or not len(eye):
        return None
    mid_y = (float(face[:, 1].min()) + float(face[:, 1].max())) / 2
    return _local_clearance(face, eye, mid_y)


def find_eyes(positions, faces, *, band=(0.50, 0.70)):
    """The replacement's own eyeballs: a pair of like-sized islands up front.

    Returns a list of index lists, empty when the head has no eyes of its own.
    """
    from kmdlswap import lips as klips

    P = np.asarray([p[:3] for p in positions], dtype=np.float64)
    if len(P) < 12 or not faces:
        return []
    lo, hi = P.min(axis=0), P.max(axis=0)
    height = float(hi[2] - lo[2])
    if height <= 0:
        return []
    mid_y = (lo[1] + hi[1]) / 2
    limit = max(6, int(0.10 * len(P)))

    found = []
    for island in klips.islands(P, faces)[1:]:
        if not (6 <= len(island) <= limit):
            continue
        q = P[island]
        centre = q.mean(axis=0)
        if not (band[0] <= (centre[2] - lo[2]) / height <= band[1]):
            continue
        if centre[1] <= mid_y:
            continue
        found.append(island)
    # A pair, left and right, of comparable size.
    if len(found) < 2:
        return []
    found.sort(key=len, reverse=True)
    a, b = found[0], found[1]
    if len(b) < 0.5 * len(a):
        return []
    return [a, b]


# How close a seated lid may come to the new face before it is pulled back.
# A lid is meant to sit just under the skin; through it is a defect, and the
# host's own margin (0.0059) is more than any converted head is guaranteed.
LID_MARGIN = 0.0010


def seat_eyelids(layout, mdl: bytes, mdx: bytes, node, host_layout=None):
    """Carry the host's eyelids onto the eyes the replacement brought with it.

    **The lid belongs to an eye, not to a face.** An earlier version seated the
    lids the way the teeth are seated - by matching the clearance the host keeps
    between its lids and its own face skin - and that is the wrong invariant. It
    moves the lid in depth only, and the eyes of a converted head are rarely at
    the host's eye *height*. Measured on `h_mercf01_`: her eyeballs sit 0.0140
    above Carth's and 0.0352 in front of them, so a depth-only correction left
    the lid at y +0.1206 with the eyeball at +0.1292 - the lid behind the eye it
    is supposed to close over, and below it as well. It would have blinked
    inside the skull, which is what the two earlier attempts looked like.

    So the lid is translated by the vector that carries the host's own eyeball
    onto the replacement's, per side. That preserves the whole lid-to-eye
    relationship the blink animation was authored against - Carth's lid centre
    sits 0.0029 in front of his eyeball's and 0.0049 above it - instead of
    reconstructing it from one measurement. On `h_mercf01_` it lands the lid
    front at +0.1329 against an eyeball front of +0.1292, still 0.0032 behind
    the face skin at that spot.

    The move is made to the node position, header *and* controller, not to the
    geometry: a lid blinks by rotating about its own pivot, so moving its
    vertices and leaving the pivot behind swings it through an arc.
    """
    host_layout = host_layout if host_layout is not None else layout
    lids = eyelids(layout)
    if not lids:
        return mdl, mdx, []

    host_rest = space.rest_pose(host_layout)
    host_balls = {
        n.name.lower()[3]: _model_space(host_layout, n, host_rest)
        for n in kparts.mesh_nodes(host_layout)
        if n.name.lower() in ("eyela", "eyera")
    }
    if len(host_balls) != 2:
        return mdl, mdx, []

    rest = space.rest_pose(layout)
    # `node` is the host's; the built model is a different parse of a different
    # file, so its indices are not interchangeable. Find it again by name.
    here = next(
        (n for n in kparts.mesh_nodes(layout) if n.name.lower() == node.name.lower()),
        None,
    )
    if here is None:
        return mdl, mdx, []
    face = _model_space(layout, here, rest)
    eyes = _own_eyes(layout, here, rest)
    if len(eyes) != 2 or not len(face):
        return mdl, mdx, []
    # Left is -x, matching the `eyeL`/`eyeR` naming on the host.
    eyes.sort(key=lambda A: float(A[:, 0].mean()))
    new_balls = {"l": eyes[0], "r": eyes[1]}
    mid_y = (float(face[:, 1].min()) + float(face[:, 1].max())) / 2

    out = bytearray(mdl)
    lines = []
    for lid in lids:
        side = lid.name.lower()[3]
        if side not in host_balls or side not in new_balls:
            continue
        delta = new_balls[side].mean(axis=0) - host_balls[side].mean(axis=0)
        here = _model_space(layout, lid, rest)
        if not len(here):
            continue
        # Never through the skin. Depth is the only axis worth clamping: it is
        # the one the face varies in.
        gap = _local_clearance(face, here + delta, mid_y)
        if gap is not None and gap < LID_MARGIN:
            delta[1] -= LID_MARGIN - gap
            gap = LID_MARGIN
        local = _to_parent(layout, rest, lid, delta)
        if not _shift_position_controller(out, lid, local):
            continue
        where = (f"({delta[0]:+.4f}, {delta[1]:+.4f}, {delta[2]:+.4f}), the "
                 f"vector from the host's eyeball to this one")
        behind = "" if gap is None else f" - it sits {gap:.4f} behind the face there"
        lines.append(f"{lid.name}: moved onto the head's own eye by {where}{behind}")

    if not lines:
        return mdl, mdx, []
    return bytes(out), mdx, ["eyelids: they are what blinks"] + lines


def _own_eyes(layout, node, rest) -> list:
    """The replacement's own eyeballs, as model-space point sets."""
    from kmdlswap import edit as kedit

    P = kmdx.positions(layout, node)
    try:
        faces = [f.vertices for f in kedit.extract(layout, node).faces]
    except Exception:
        return []
    islands = find_eyes(P, faces)
    if not islands:
        return []
    r = rest[node.index]
    R = np.asarray(r.rotation, dtype=float)
    t = np.asarray(r.position, dtype=float)
    out = []
    for island in islands:
        A = np.asarray([P[i][:3] for i in island], dtype=float)
        out.append((R @ A.T).T + t)
    return out


def _to_parent(layout, rest, node, delta) -> tuple:
    """A model-space translation in the space the node's position is stored in.

    Which is the *parent's*, not the node's own - a node's position places it
    inside its parent. Using the node's own rotation happens to agree whenever
    the node carries no local rotation of its own, and quietly does not when it
    does.
    """
    parent = getattr(node, "parent", None)
    R = (np.asarray(rest[parent].rotation, dtype=float)
         if parent is not None and parent in rest else np.eye(3))
    return tuple(float(v) for v in R.T @ np.asarray(delta, dtype=float))


def _shift_position_controller(mdl: bytearray, node, delta) -> bool:
    """Move a node's rest position: header *and* position controller.

    Both, because vanilla keeps them identical - checked across every mesh node
    of `p_carthh`, header and controller agree to 1e-6 on all nine. Editing one
    leaves the model disagreeing with itself, and that is exactly what happened
    in §29: the header was moved, the controller was not, the engine read the
    controller and the teeth did not budge.

    The header field is not enough - the engine reads the controller over it,
    which is why the teeth had to be moved in geometry (§29). But geometry is
    not enough either for anything that *rotates*: an eyelid blinks by turning
    about its node pivot (controller type 20 in `pause1`), so moving its
    vertices while leaving the pivot behind makes it swing through an arc
    instead of closing over the eye. In game, a head that never blinks.

    Moving the controller moves the pivot and the geometry together.
    """
    at = MDL_BASE + node.offset
    current = struct.unpack_from("<3f", mdl, at + 16)
    struct.pack_into(
        "<3f", mdl, at + 16, *(float(current[i] + delta[i]) for i in range(3))
    )
    controllers_offset, count = struct.unpack_from("<II", mdl, at + 56)
    data_offset, data_length = struct.unpack_from("<II", mdl, at + 68)
    if not count or controllers_offset >= 0xFFFFFF00:
        # The header alone is all this node has.
        return True
    for i in range(count):
        entry = MDL_BASE + controllers_offset + i * 16
        kind = struct.unpack_from("<I", mdl, entry)[0]
        if kind != POSITION_CONTROLLER:
            continue
        rows, _timekey, datakey = struct.unpack_from("<HHH", mdl, entry + 6)
        columns = struct.unpack_from("<B", mdl, entry + 12)[0] & 0x0F
        if rows < 1 or columns < 3:
            continue
        for row in range(rows):
            base = MDL_BASE + data_offset + (datakey + row * columns) * 4
            current = struct.unpack_from("<3f", mdl, base)
            struct.pack_into(
                "<3f", mdl, base, *(float(current[j] + delta[j]) for j in range(3))
            )
        return True
    # A node with controllers but no position one: the header carries it.
    return True
