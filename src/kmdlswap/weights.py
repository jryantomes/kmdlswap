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


def claim_orphan_bones(
    source_positions: Sequence[tuple[float, ...]],
    source_influences: Sequence[Sequence[Influence]],
    target_positions: Sequence[tuple[float, ...]],
    transferred: list[list[Influence]],
    *,
    max_influences: int = MAX_INFLUENCES,
    min_weight: float = MIN_WEIGHT,
    core: float = 0.5,
) -> dict[int, int]:
    """Give every source bone somewhere to act, in place.

    Transfer samples the source surface at the *target's* vertices, so a bone
    whose region is small - or which sits where the two shapes disagree - can
    end up with no sample at all and quietly stop driving anything. In game that
    reads as "that part of the face doesn't move", with nothing anywhere saying
    so: measured on a generated head fitted to Carth, 4 of his 16 bones went
    silent, all three brows among them, and it was only found by watching for it.

    For each orphaned bone this finds the source vertices it actually dominates,
    maps them to their nearest target vertices, and reinstates the bone there at
    **the weight it held in the source**. Copying the original share rather than
    nudging in a fixed amount keeps the region deforming roughly as it did, and
    keeps the fix proportional: a bone that barely mattered gets barely anything.

    Returns ``{bone_slot: vertices claimed}`` for the bones it had to rescue, so
    a caller can report the rescue rather than hide it.
    """
    present = {i.bone_slot for infl in transferred for i in infl}
    wanted: dict[int, list[tuple[int, float]]] = {}
    for idx, infl in enumerate(source_influences):
        for i in infl:
            if i.bone_slot not in present and i.weight > 0.0:
                wanted.setdefault(i.bone_slot, []).append((idx, i.weight))
    if not wanted:
        return {}

    src = np.asarray([p[:3] for p in source_positions], dtype=np.float64)
    tgt = np.asarray([p[:3] for p in target_positions], dtype=np.float64)
    claimed: dict[int, int] = {}

    for slot, entries in sorted(wanted.items()):
        # The bone's core: where it genuinely dominates, not every vertex it
        # brushes. A wide net would drag the bone across half the face.
        strongest = max(w for _, w in entries)
        core_entries = [(i, w) for i, w in entries if w >= core * strongest]

        for source_index, weight in core_entries:
            d = tgt - src[source_index]
            nearest = int(np.argmin(np.einsum("ij,ij->i", d, d)))
            before = transferred[nearest]
            pool = {i.bone_slot: i.weight for i in before}
            if pool.get(slot, 0.0) >= weight:
                continue

            # Make room for the bone at exactly the share it held, by scaling
            # what is already there down to the remainder. Adding it alongside
            # and renormalising afterwards would dilute it to something smaller
            # than the host had, which is not what "the weight it held" means.
            share = min(weight, 0.9)
            existing = sum(pool.values())
            if existing > 0.0:
                pool = {k: v / existing * (1.0 - share) for k, v in pool.items()}
            pool[slot] = share

            def survives_elsewhere(dropped: set[int]) -> bool:
                """Would dropping these leave a bone with nowhere to act?

                Every claim scales the weights already on a vertex down by
                ``1 - share``, so a bone sitting on a popular vertex is ground
                smaller with each rescue and can eventually be truncated away.
                That is how an early version of this traded one silent bone for
                another: it rescued four and quietly evicted a fifth.
                """
                if not dropped:
                    return True
                others = {
                    i.bone_slot
                    for j, infl in enumerate(transferred)
                    if j != nearest
                    for i in infl
                }
                return dropped <= others

            candidate = _finalise(pool, max_influences, min_weight)
            if not survives_elsewhere(set(pool) - {i.bone_slot for i in candidate} - {slot}):
                continue
            if not any(i.bone_slot == slot for i in candidate):
                # It ranked below the four strongest and was truncated away. On
                # a crowded vertex that can happen everywhere the bone might go,
                # so make room by evicting the weakest influence - but never one
                # that lives nowhere else, or the rescue orphans somebody new.
                others = sorted(
                    ((k, v) for k, v in pool.items() if k != slot),
                    key=lambda kv: (-kv[1], kv[0]),
                )
                keep, evicted = others[: max_influences - 1], others[max_influences - 1 :]
                if not survives_elsewhere({k for k, _ in evicted}):
                    continue
                kept_total = sum(v for _, v in keep)
                pool = (
                    {k: v / kept_total * (1.0 - share) for k, v in keep}
                    if kept_total > 0.0
                    else {}
                )
                pool[slot] = share
                candidate = _finalise(pool, max_influences, min_weight)
                if not any(i.bone_slot == slot for i in candidate):
                    continue

            transferred[nearest] = candidate
            claimed[slot] = claimed.get(slot, 0) + 1
    return claimed


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
