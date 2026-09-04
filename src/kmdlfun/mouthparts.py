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

import numpy as np

from kmdlfun import parts as kparts
from kmdlfun import space
from kmdlswap import mdx as kmdx

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
