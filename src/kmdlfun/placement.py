"""Moving a node's geometry, without moving the node.

Node positions live in node headers, which this project never rewrites - that
restraint is what keeps the hierarchy intact and the animations working. But the
geometry *inside* a node can be translated freely, and for a small detail mesh
that is indistinguishable from moving the node itself.

The use for it: after a head is replaced, fittings that belonged to the old head
- HK-47's eye bar, a visor, an antenna - are left sitting wherever the old
geometry put them. They can be hidden (see :mod:`kmdlfun.visibility`), or they
can be moved onto the new face, which usually looks better.

A translation is expressed in **model space**, because that is the space a human
can reason about, and converted into the node's own space here. Only the
rotation is applied to a delta: a difference of two points carries no
translation.
"""

from __future__ import annotations

from kmdlswap import edit as ke
from kmdlswap.layout import Layout, NodeInfo

from . import space


def to_model(rest, v):
    return tuple(
        rest.position[i] + sum(rest.rotation[i][k] * v[k] for k in range(3))
        for i in range(3)
    )


def model_bounds(layout: Layout, node: NodeInfo):
    """A node's geometry bounding box, in model space."""
    rest = space.rest_pose(layout)[node.index]
    pts = [to_model(rest, v) for v in ke.extract(layout, node).positions]
    lo = tuple(min(p[i] for p in pts) for i in range(3))
    hi = tuple(max(p[i] for p in pts) for i in range(3))
    return lo, hi


def translate_geometry(
    layout: Layout,
    node: NodeInfo,
    delta_model: tuple[float, float, float],
) -> ke.MeshGeometry:
    """Return this node's geometry shifted by a model-space delta."""
    rest = space.rest_pose(layout)[node.index]
    # Rotation only - a delta has no translation component.
    local = tuple(
        sum(rest.rotation[k][i] * delta_model[k] for k in range(3)) for i in range(3)
    )
    geo = ke.extract(layout, node)
    geo.columns["vertex"] = [
        tuple(p[i] + local[i] for i in range(3)) for p in geo.positions
    ]
    return geo


def face_surface(
    layout: Layout,
    node: NodeInfo,
    height_fraction: float,
    *,
    facing: int = 1,
    axis: int = 1,
    band: float = 0.04,
    width: float = 0.35,
):
    """Where a head's face surface sits at a given height.

    Returns ``(x_centre, surface, z)`` in model space. ``facing`` is +1 when the
    face looks along +axis and -1 when it looks along -axis; on HK-47 the eye bar
    sits at +Y, which is what identifies his front.

    Only vertices near the centre line are considered, so ears and hair do not
    drag the answer sideways.
    """
    rest = space.rest_pose(layout)[node.index]
    pts = [to_model(rest, v) for v in ke.extract(layout, node).positions]
    lo = [min(p[i] for p in pts) for i in range(3)]
    hi = [max(p[i] for p in pts) for i in range(3)]
    height = hi[2] - lo[2]
    z = lo[2] + height * height_fraction
    cx = (lo[0] + hi[0]) / 2
    near = [
        p
        for p in pts
        if abs(p[2] - z) < height * band and abs(p[0] - cx) < width * (hi[0] - lo[0])
    ]
    if not near:
        raise ValueError(f"no vertices near {height_fraction:.0%} height on {node.name!r}")
    surface = max(p[axis] for p in near) if facing > 0 else min(p[axis] for p in near)
    return cx, surface, z
