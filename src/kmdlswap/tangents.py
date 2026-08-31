"""Computing the per-vertex tangent basis some meshes carry.

Twenty-one head models across the two games were refused outright because their
`Head` carries an MDX `tangent` column and the writer would not invent one -
every Selkath, the Rakata, Xor, Zhar, Komad, the rakghoul, and the male
Twi'leks. Refusing was right while the column was not understood. It is now.

**What the column holds.** Thirty-six bytes, nine floats, three unit vectors -
and not in the order the name suggests. Measured against five vanilla meshes
that carry one:

* **Slot 2 is the normal.** It agrees with the mesh's own normal column to a
  mean dot of 0.94-0.97.
* **Slot 1 is the tangent**, and it is the *negative* of what the standard
  derivation gives: the signed dot is -0.87 to -0.93 across every mesh
  measured, never positive. The engine's V axis runs the other way.
* **Slot 0 is the bitangent.** It correlates -0.86 to -0.89 with
  `slot2 x slot1`.

So the layout is (bitangent, tangent, normal), which is worth writing down
because guessing the obvious order gets it wrong in a way that only shows up as
subtly bad lighting.

**Exactness is not the goal, and is not available.** 76-86% of vanilla vertices
agree within 0.9 with a straight recomputation; the rest differ because BioWare
smoothed across their own seam and smoothing-group rules, which are not
recorded anywhere in the file. What a replacement needs is a *valid* basis for
its own geometry, not BioWare's basis for geometry that is gone. The vanilla
figures are kept as a regression check on the convention - the sign especially,
since a flipped tangent is invisible in a viewer and wrong in game.

Filling the column also keeps the stride and every header field exactly as they
were: only the data changes. Dropping the column instead would mean rewriting
the stride and the bitmap, which is a much larger claim about what the engine
tolerates.
"""

from __future__ import annotations

import numpy as np

# Slot order within the 9-float column.
BITANGENT = slice(0, 3)
TANGENT = slice(3, 6)
NORMAL = slice(6, 9)


def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=1, keepdims=True)
    return v / np.where(n < 1e-12, 1.0, n)


def compute(positions, faces, uvs, normals=None) -> list[tuple[float, ...]]:
    """A (bitangent, tangent, normal) basis per vertex, nine floats each.

    Standard derivation - per-face from the UV gradient, accumulated to the
    vertices it touches, then normalised - with the engine's sign convention
    applied. Face contributions are left unnormalised on purpose, so a large
    triangle counts for more than a sliver; that is what the vanilla values
    look like.
    """
    P = np.asarray([p[:3] for p in positions], dtype=np.float64)
    F = np.asarray([tuple(f)[:3] for f in faces], dtype=np.int64)
    UV = np.asarray([t[:2] for t in uvs], dtype=np.float64)

    if normals is not None and len(normals) == len(P):
        N = _unit(np.asarray([n[:3] for n in normals], dtype=np.float64))
    else:
        N = _vertex_normals(P, F)

    tan = np.zeros_like(P)
    bit = np.zeros_like(P)
    if len(F):
        p0, p1, p2 = P[F[:, 0]], P[F[:, 1]], P[F[:, 2]]
        w0, w1, w2 = UV[F[:, 0]], UV[F[:, 1]], UV[F[:, 2]]
        e1, e2 = p1 - p0, p2 - p0
        d1, d2 = w1 - w0, w2 - w0

        denom = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
        # A degenerate UV triangle has no gradient to give. It contributes
        # nothing rather than an infinity.
        safe = np.abs(denom) > 1e-12
        r = np.zeros_like(denom)
        r[safe] = 1.0 / denom[safe]

        t = (e1 * d2[:, 1, None] - e2 * d1[:, 1, None]) * r[:, None]
        b = (e2 * d1[:, 0, None] - e1 * d2[:, 0, None]) * r[:, None]
        for i in range(3):
            np.add.at(tan, F[:, i], t)
            np.add.at(bit, F[:, i], b)

    # The engine's tangent runs against the standard derivation - see the
    # module docstring; the sign was measured, not assumed.
    tangent = -_unit(tan)
    bitangent = _unit(bit)

    # A vertex no triangle could give a gradient to still needs a basis, or the
    # engine reads a zero vector and lights it as a black speck. Any direction
    # perpendicular to the normal will do.
    empty = np.linalg.norm(tan, axis=1) < 1e-12
    if empty.any():
        fallback = np.cross(N[empty], np.array([0.0, 0.0, 1.0]))
        degenerate = np.linalg.norm(fallback, axis=1) < 1e-6
        if degenerate.any():
            fallback[degenerate] = np.cross(
                N[empty][degenerate], np.array([0.0, 1.0, 0.0])
            )
        tangent[empty] = _unit(fallback)
        bitangent[empty] = _unit(np.cross(N[empty], tangent[empty]))

    out = np.concatenate([bitangent, tangent, N], axis=1)
    return [tuple(float(x) for x in row) for row in out]


def _vertex_normals(P: np.ndarray, F: np.ndarray) -> np.ndarray:
    N = np.zeros_like(P)
    if len(F):
        fn = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
        for i in range(3):
            np.add.at(N, F[:, i], fn)
    return _unit(N)
