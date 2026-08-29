"""Skin weight transfer from an original mesh to replacement geometry.

For each new vertex, find the closest point on the *surface* of the original
mesh and inherit the bone influences of the triangle containing it, blended by
barycentric coordinates. That is better than nearest-vertex: it interpolates
across a triangle rather than snapping to whichever corner happens to be
nearest, so weights vary smoothly where the original did.

The census in reports/SKINNING_FINDINGS.md sets the rules this has to respect:
at most 4 influences per vertex (the MDX stride holds exactly four, and no
vanilla vertex exceeds it), and weights normalised to 1.0 (vanilla's are, to
within float32 rounding).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from .mdx import Influence

MAX_INFLUENCES = 4

# Barycentric blending across a seam can leave a bone with a vanishing share.
# Vanilla never stores such influences, and they cost a stride slot that a real
# bone could use, so drop anything below this and renormalise.
MIN_WEIGHT = 1e-3


def _closest_points_on_triangles(
    points: np.ndarray, a: np.ndarray, b: np.ndarray, c: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Closest point on each triangle to each query point.

    ``points`` is (P,3); ``a``/``b``/``c`` are (T,3). Returns squared distances
    (P,T) and barycentric coordinates (P,T,3). Standard region-based solution
    (Ericson, *Real-Time Collision Detection*), vectorised.
    """
    ab = b - a
    ac = c - a
    p = points[:, None, :]
    ap = p - a[None, :, :]

    d1 = np.einsum("tj,ptj->pt", ab, ap)
    d2 = np.einsum("tj,ptj->pt", ac, ap)
    bp = p - b[None, :, :]
    d3 = np.einsum("tj,ptj->pt", ab, bp)
    d4 = np.einsum("tj,ptj->pt", ac, bp)
    cp = p - c[None, :, :]
    d5 = np.einsum("tj,ptj->pt", ab, cp)
    d6 = np.einsum("tj,ptj->pt", ac, cp)

    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2
    denom = va + vb + vc

    # Interior case, then override with each edge/corner region in turn.
    with np.errstate(divide="ignore", invalid="ignore"):
        inv = np.where(np.abs(denom) > 1e-20, 1.0 / denom, 0.0)
        v = vb * inv
        w = vc * inv
    u = 1.0 - v - w

    def set_bary(mask, uu, vv, ww):
        np.copyto(u, uu, where=mask)
        np.copyto(v, vv, where=mask)
        np.copyto(w, ww, where=mask)

    zero = np.zeros_like(u)
    one = np.ones_like(u)

    # Vertex regions
    set_bary((d1 <= 0) & (d2 <= 0), one, zero, zero)
    set_bary((d3 >= 0) & (d4 <= d3), zero, one, zero)
    set_bary((d6 >= 0) & (d5 <= d6), zero, zero, one)

    # Edge regions
    with np.errstate(divide="ignore", invalid="ignore"):
        ab_denom = d1 - d3
        t_ab = np.where(np.abs(ab_denom) > 1e-20, d1 / np.where(ab_denom == 0, 1, ab_denom), 0.0)
        m = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
        set_bary(m, 1.0 - t_ab, t_ab, zero)

        ac_denom = d2 - d6
        t_ac = np.where(np.abs(ac_denom) > 1e-20, d2 / np.where(ac_denom == 0, 1, ac_denom), 0.0)
        m = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
        set_bary(m, 1.0 - t_ac, zero, t_ac)

        bc_denom = (d4 - d3) + (d5 - d6)
        t_bc = np.where(
            np.abs(bc_denom) > 1e-20, (d4 - d3) / np.where(bc_denom == 0, 1, bc_denom), 0.0
        )
        m = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
        set_bary(m, zero, 1.0 - t_bc, t_bc)

    bary = np.stack([u, v, w], axis=-1)
    closest = (
        bary[..., 0:1] * a[None, :, :]
        + bary[..., 1:2] * b[None, :, :]
        + bary[..., 2:3] * c[None, :, :]
    )
    diff = closest - p
    return np.einsum("ptj,ptj->pt", diff, diff), bary


def transfer(
    source_positions: Sequence[tuple[float, ...]],
    source_faces: Sequence[tuple[int, int, int]],
    source_influences: Sequence[Sequence[Influence]],
    target_positions: Sequence[tuple[float, ...]],
    *,
    max_influences: int = MAX_INFLUENCES,
    min_weight: float = MIN_WEIGHT,
    chunk: int = 256,
) -> list[list[Influence]]:
    """Inherit skin weights from a source mesh onto new vertex positions."""
    if not source_faces:
        raise ValueError("source mesh has no faces to transfer weights from")
    if max_influences < 1 or max_influences > MAX_INFLUENCES:
        raise ValueError(f"max_influences must be 1..{MAX_INFLUENCES}, got {max_influences}")

    src = np.asarray([p[:3] for p in source_positions], dtype=np.float64)
    tri = np.asarray(source_faces, dtype=np.int64)
    tgt = np.asarray([p[:3] for p in target_positions], dtype=np.float64)
    a, b, c = src[tri[:, 0]], src[tri[:, 1]], src[tri[:, 2]]

    out: list[list[Influence]] = []
    for start in range(0, len(tgt), chunk):
        block = tgt[start : start + chunk]
        dist2, bary = _closest_points_on_triangles(block, a, b, c)
        best = np.argmin(dist2, axis=1)
        for i, t in enumerate(best):
            corners = tri[t]
            weights = bary[i, t]
            pool: dict[int, float] = {}
            for corner, bw in zip(corners, weights):
                if bw <= 0.0:
                    continue
                for infl in source_influences[corner]:
                    pool[infl.bone_slot] = pool.get(infl.bone_slot, 0.0) + bw * infl.weight
            out.append(_finalise(pool, max_influences, min_weight))
    return out


def _finalise(
    pool: dict[int, float], max_influences: int, min_weight: float = MIN_WEIGHT
) -> list[Influence]:
    """Keep the strongest influences and normalise them to sum to 1.0."""
    total_all = sum(pool.values())
    ranked = sorted(pool.items(), key=lambda kv: (-kv[1], kv[0]))[:max_influences]
    cutoff = min_weight * total_all if total_all > 0 else 0.0
    ranked = [(slot, w) for slot, w in ranked if w > cutoff]
    if not ranked:
        ranked = sorted(pool.items(), key=lambda kv: (-kv[1], kv[0]))[:1]
    ranked = [(slot, w) for slot, w in ranked if w > 0.0]
    if not ranked:
        # No source influence reached this vertex. Refusing is wrong - an
        # unweighted vertex would render but never animate - so bind it rigidly
        # to the nearest triangle's first bone if there is one at all.
        return []
    total = sum(w for _, w in ranked)
    return [Influence(slot, w / total) for slot, w in ranked]


def check(influences: Sequence[Sequence[Influence]], *, tolerance: float = 1e-4) -> list[str]:
    """Validate transferred weights against the rules vanilla data obeys."""
    problems = []
    for i, infl in enumerate(influences):
        if not infl:
            problems.append(f"vertex {i}: no bone influences")
            continue
        if len(infl) > MAX_INFLUENCES:
            problems.append(f"vertex {i}: {len(infl)} influences exceeds {MAX_INFLUENCES}")
        total = sum(x.weight for x in infl)
        if abs(total - 1.0) > tolerance:
            problems.append(f"vertex {i}: weights sum to {total:.6f}, not 1.0")
        if any(x.weight <= 0.0 for x in infl):
            problems.append(f"vertex {i}: non-positive weight")
    return problems
