"""Where a part is anchored, in model space.

Geometry is stored in each node's own space, and node header positions are not
ours to move, so the only freedom a scale has is *inside* a node. Scaling each
node about its own bounding-box centre pins every node's centre exactly where it
was. For a part that is one node that is fine. For a head that is ten nodes it
is wrong, and visibly so: the face skin grows past the eyeballs, which stay put
and end up inside the skull, and the skullcap sinks into the head it is supposed
to sit on. The parts come apart because each one grew about a different point.

The fix is to scale the whole group about ONE point in model space. This module
walks the rest-pose hierarchy to find that point and converts it into each
node's own space, where the scale is actually applied.

The maths, for a node whose rest transform is ``x -> R x + t`` and a pivot ``C``
in model space::

    model space:  p  ->  C + f (p - C)
    node space:   v  ->  f v + (1 - f) R^T (C - t)

which is a uniform scale by ``f`` plus a constant translation - exactly what the
splice path can express, and exact for every node in the group at once.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from kmdlswap.layout import Layout

# Fixed fields of the 80-byte node header.
POSITION_AT = 16
ORIENTATION_AT = 28
# Stored w, x, y, z. PyKotor's reader agrees, and so does the geometry: in every
# human head model neck_g and Hturn_g read as an equal and opposite ~10 degree
# tilt about X only under w-first. Under x-first they would be ~172 degrees.
_VEC3 = struct.Struct("<3f")
_VEC4 = struct.Struct("<4f")

Vec3 = tuple[float, float, float]
Mat3 = tuple[Vec3, Vec3, Vec3]

IDENTITY: Mat3 = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


@dataclass(frozen=True)
class Rest:
    """A node's rest-pose transform in model space: ``x -> rotation @ x + position``."""

    rotation: Mat3
    position: Vec3

    def to_local(self, point: Vec3) -> Vec3:
        """A model-space point in this node's own space (rotation is orthonormal,
        so the inverse is the transpose)."""
        d = tuple(point[i] - self.position[i] for i in range(3))
        return tuple(sum(self.rotation[k][i] * d[k] for k in range(3)) for i in range(3))


def quat_to_matrix(q: tuple[float, float, float, float]) -> Mat3:
    w, x, y, z = q
    n = w * w + x * x + y * y + z * z
    if n < 1e-12:  # an all-zero orientation appears in a few vanilla nodes
        return IDENTITY
    s = 2.0 / n
    return (
        (1 - s * (y * y + z * z), s * (x * y - z * w), s * (x * z + y * w)),
        (s * (x * y + z * w), 1 - s * (x * x + z * z), s * (y * z - x * w)),
        (s * (x * z - y * w), s * (y * z + x * w), 1 - s * (x * x + y * y)),
    )


def _mat_mul(a: Mat3, b: Mat3) -> Mat3:
    return tuple(
        tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3)
    )


def _apply(m: Mat3, v: Vec3) -> Vec3:
    return tuple(sum(m[i][k] * v[k] for k in range(3)) for i in range(3))


def rest_pose(layout: Layout) -> dict[int, Rest]:
    """Model-space rest transform of every geometry node, by node index.

    Animation node-trees are skipped: they carry the same names and their own
    controllers, and none of them owns geometry we edit.
    """
    out: dict[int, Rest] = {}
    for node in layout.nodes:
        if node.in_animation is not None:
            continue
        at = 12 + node.offset  # MDL offsets are relative to byte 12
        position = _VEC3.unpack_from(layout.mdl, at + POSITION_AT)
        rotation = quat_to_matrix(_VEC4.unpack_from(layout.mdl, at + ORIENTATION_AT))
        if node.parent is None or node.parent not in out:
            out[node.index] = Rest(rotation, position)
            continue
        parent = out[node.parent]
        out[node.index] = Rest(
            _mat_mul(parent.rotation, rotation),
            tuple(parent.position[i] + _apply(parent.rotation, position)[i] for i in range(3)),
        )
    return out


def scale_offset(rest: Rest, pivot: Vec3, factor: float) -> Vec3:
    """The node-space translation that turns a local scale by ``factor`` into a
    scale of the whole model about ``pivot``."""
    local = rest.to_local(pivot)
    return tuple((1.0 - factor) * local[i] for i in range(3))
