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

# The node header keeps a node's rest position at this offset, in *parent* space.
POSITION_AT = space.POSITION_AT
MDL_BASE = 12

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


def seat(layout, mdl: bytes, node, host_layout=None) -> tuple[bytes, list[str]]:
    """Move the mouth interior back behind the replacement's lips.

    ``layout`` is the model *after* the face has been replaced; ``host_layout``
    is the original, used to measure the clearance the parts are supposed to
    have. Returns the model bytes and a line per part moved.
    """
    host_layout = host_layout if host_layout is not None else layout
    parts = mouth_parts(layout)
    if not parts:
        return mdl, []

    rest = space.rest_pose(layout)
    host_rest = space.rest_pose(host_layout)

    interior = [_model_space(layout, p, rest) for p in parts]
    interior = [p for p in interior if len(p)]
    if not interior:
        return mdl, []
    stacked = np.concatenate(interior)
    low, high = float(stacked[:, 2].min()), float(stacked[:, 2].max())
    half_width = max(float(np.abs(stacked[:, 0]).max()) * 1.5, 1e-4)

    new_face = _model_space(layout, node, rest)
    host_node = next(
        (n for n in kparts.mesh_nodes(host_layout) if n.name.lower() == node.name.lower()),
        None,
    )
    if host_node is None:
        return mdl, []
    old_face = _model_space(host_layout, host_node, host_rest)

    new_depth = _face_depth(new_face, low, high, half_width)
    old_depth = _face_depth(old_face, low, high, half_width)
    if new_depth is None or old_depth is None:
        return mdl, []

    # The clearance the host had, reproduced against the new face. Measuring the
    # host rather than picking a number means a head whose teeth were always
    # tight stays tight, and one with room keeps its room.
    front = float(stacked[:, 1].max())
    want = old_depth - front
    shift = (new_depth - want) - front
    if abs(shift) < 1e-5:
        return mdl, []

    out = bytearray(mdl)
    lines = []
    for part in parts:
        r = rest[part.index]
        parent_rotation = np.asarray(r.rotation, dtype=float)
        # The position field is in parent space, so a model-space shift has to
        # be rotated into it. The rest rotation is orthonormal, so that is its
        # transpose.
        local = parent_rotation.T @ np.array([0.0, shift, 0.0])
        at = MDL_BASE + part.offset + POSITION_AT
        current = struct.unpack_from("<3f", out, at)
        struct.pack_into(
            "<3f", out, at, *(float(current[i] + local[i]) for i in range(3))
        )
        lines.append(part.name)

    direction = "back" if shift < 0 else "forward"
    return bytes(out), [
        f"mouth interior: moved {', '.join(lines)} {direction} by {abs(shift):.4f} "
        f"to sit {want:.4f} behind the new lips, as on the host"
    ]
