"""Reshaping a mesh to look like another one, without changing its topology.

Why this exists, rather than simply transplanting the donor's vertices:

Changing a skinned head mesh's **vertex count** breaks facial animation in-game.
That was established by bisection (reports/HEAD_ANIMATION_FINDINGS.md): moving a
head's vertices is safe, resizing an unrelated mesh in the same model is safe,
but adding three vertices that no face even references - with every position,
face and weight otherwise untouched - stops the mouth and eyebrows moving. The
mechanism is not understood. Body meshes do not behave this way.

So for heads the donor's topology cannot be used. What can be done is to keep the
host's own vertices, faces and weights exactly, and *move* each host vertex onto
the donor's surface. The count never changes, so the animation keeps working,
and the silhouette becomes the donor's.

The trade-off is honest and worth stating: the result has the host's resolution
and the host's UVs. A donor with finer detail than the host cannot express it,
and where the two shapes differ a lot the host's topology will stretch.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from kmdlswap.weights import _closest_points_on_triangles


def snap_to_surface(
    points: Sequence[tuple[float, ...]],
    target_positions: Sequence[tuple[float, ...]],
    target_faces: Sequence[tuple[int, int, int]],
    *,
    strength: float = 1.0,
    chunk: int = 256,
) -> list[tuple[float, float, float]]:
    """Move each point onto the closest point of a target surface.

    ``strength`` blends between the original shape (0.0) and the target surface
    (1.0), so a partial reshape is possible.
    """
    if not target_faces:
        raise ValueError("target mesh has no faces to snap to")

    src = np.asarray([p[:3] for p in target_positions], dtype=np.float64)
    tri = np.asarray(target_faces, dtype=np.int64)
    pts = np.asarray([p[:3] for p in points], dtype=np.float64)
    a, b, c = src[tri[:, 0]], src[tri[:, 1]], src[tri[:, 2]]

    out: list[tuple[float, float, float]] = []
    for start in range(0, len(pts), chunk):
        block = pts[start : start + chunk]
        dist2, bary = _closest_points_on_triangles(block, a, b, c)
        best = np.argmin(dist2, axis=1)
        for i, t in enumerate(best):
            corners = tri[t]
            w = bary[i, t]
            landed = w[0] * src[corners[0]] + w[1] * src[corners[1]] + w[2] * src[corners[2]]
            final = block[i] + (landed - block[i]) * strength
            out.append((float(final[0]), float(final[1]), float(final[2])))
    return out


def recompute_vertex_normals(
    positions: Sequence[tuple[float, ...]],
    faces: Sequence[tuple[int, int, int]],
) -> list[tuple[float, float, float]]:
    """Area-weighted vertex normals, for geometry that has just been moved."""
    acc = [[0.0, 0.0, 0.0] for _ in positions]
    for i0, i1, i2 in faces:
        p0, p1, p2 = positions[i0], positions[i1], positions[i2]
        u = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
        v = (p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2])
        n = (
            u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0],
        )
        for i in (i0, i1, i2):
            acc[i][0] += n[0]
            acc[i][1] += n[1]
            acc[i][2] += n[2]
    out = []
    for n in acc:
        length = (n[0] ** 2 + n[1] ** 2 + n[2] ** 2) ** 0.5
        out.append(
            (n[0] / length, n[1] / length, n[2] / length)
            if length > 1e-12
            else (0.0, 0.0, 1.0)
        )
    return out
