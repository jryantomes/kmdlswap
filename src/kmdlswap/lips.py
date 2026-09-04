"""Binding lips that are modelled as separate pieces to the bones that move them.

KOTOR builds a mouth as part of the face: Carth's lips are the same connected
surface as his cheeks, and they part because the vertices either side of the
mouth line are weighted to different bones. Heads authored elsewhere very often
do it the other way, with the lips as their own small closed pieces lying on a
solid face, plus a separate bag behind them. Jade Empire's ``h_common01_`` is
built exactly like that: welded, it is six islands - a 475-vertex face shell
with one hole (the neck, same as Carth), two eyes, two lip pieces of 14 vertices
each, and an 11-vertex mouth bag.

Those 28 lip vertices are the whole visible mouth, and they are the ones
proximity transfer gets most wrong, because they sit *recessed behind* the face
shell. The nearest host surface to a point tucked under Carth's lip is not his
lip - it is skull. Measured on the installed build:

=====================  ===================================
island                 what leads its vertices
=====================  ===================================
upper lip (14)         ``head_g`` 9, ``f_um_g`` 5
lower lip (14)         ``f_um_g`` 4, ``f_jaw_g`` 4, ``head_g`` 4
mouth bag (11)         ``head_g`` 5, ``f_jaw_g`` 5
=====================  ===================================

The upper lip is led by a bone that never moves. The lower lip has as much
weight lifting it as dropping it, so the two cancel and it stays shut. This is
invisible to any measurement taken over a geometric region: 28 vertices inside a
band holding 285 disappear into the average, which is how an earlier pass came
back "about the same" in game while its own numbers looked corrected.

**Why binding by name is right here.** KOTOR drives faces from ``.lip`` files
applied by the engine to bones it finds *by name* - a ``.lip`` is only a list of
``(time, shape)`` pairs into 16 shapes the engine owns, carrying no geometry of
its own. That is why all 101 skinned K1 heads share one identical 16-bone rig
with no exceptions. A head not using these names does not animate at all, so
there is no correct head this can miss.

**The profile is measured.** Across those 101 heads, resolved to each vertex's
own side: an upper-lip vertex averages ``f_um_g`` 79%, skull 8.5%, near corner
6.6%, far corner 6.1%; a lower-lip vertex averages its near lower-mouth bone
70%, its near corner 23%, ``f_jaw_g`` 5%. The rig's vertical order is identical
on every head - ``f_um_g`` at 36% of head height, corners 33%, ``f_llm_g`` and
``f_rlm_g`` 30%, ``f_jaw_g`` 22% - and ``f_llm_g``/``f_lmc_g`` sit at negative x
against ``f_rlm_g``/``f_rmc_g`` at positive, while ``f_um_g`` and ``f_jaw_g`` are
centred to within 0.0005. The side convention is still re-derived from the host
rather than assumed, so a model that mirrors x binds correctly anyway.

This runs only when two comparable lip pieces are actually found. A KOTOR-style
head, whose mouth is part of the face shell, has no such islands and is left
entirely alone.
"""

from __future__ import annotations

import collections

import numpy as np

from .mdx import Influence

UPPER = "f_um_g"
JAW = "f_jaw_g"
SKULL = "head_g"
LOWER_PAIR = ("f_llm_g", "f_rlm_g")
CORNER_PAIR = ("f_lmc_g", "f_rmc_g")

# Measured means across 101 vanilla heads, normalised to sum to 1.
UPPER_PROFILE = {"upper": 0.790, "skull": 0.085, "near_corner": 0.070, "far_corner": 0.055}
LOWER_PROFILE = {"near_lower": 0.701, "near_corner": 0.234, "jaw": 0.065}
# The bag is the inside of the mouth; it belongs to the jaw that opens it.
BAG_PROFILE = {"jaw": 0.700, "near_lower": 0.300}

# Where a mouth can sit, as a fraction of head height. Wide enough to be
# generous, narrow enough to exclude the eyes above and the neck below.
BAND = (0.18, 0.52)

# A lip piece is small. Anything larger than this share of the mesh is the face
# itself, not a piece lying on it.
MAX_ISLAND = 0.10

MAX_INFLUENCES = 4


def islands(positions: np.ndarray, faces) -> list[list[int]]:
    """Connected pieces, welded by position, largest first.

    Welding is what makes this meaningful: a lip piece split along a UV seam is
    several islands by index and one piece in space, and only the second reading
    finds a mouth. Each returned island lists every *original* index at the
    positions it covers, so callers can write weights straight back.
    """
    at: dict[tuple, list[int]] = collections.defaultdict(list)
    for i, p in enumerate(positions):
        at[(round(float(p[0]), 5), round(float(p[1]), 5), round(float(p[2]), 5))].append(i)
    rep = [0] * len(positions)
    for group in at.values():
        for i in group:
            rep[i] = group[0]

    adj: dict[int, set[int]] = collections.defaultdict(set)
    for a, b, c in faces:
        ra, rb, rc = rep[a], rep[b], rep[c]
        adj[ra] |= {rb, rc}
        adj[rb] |= {ra, rc}
        adj[rc] |= {ra, rb}

    seen: set[int] = set()
    out: list[list[int]] = []
    for start in adj:
        if start in seen:
            continue
        stack, group = [start], []
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            group.append(x)
            stack.extend(adj[x] - seen)
        full: set[int] = set()
        for v in group:
            p = positions[v]
            full.update(at[(round(float(p[0]), 5), round(float(p[1]), 5), round(float(p[2]), 5))])
        out.append(sorted(full))
    return sorted(out, key=len, reverse=True)


def find_lips(positions, faces):
    """(upper, lower, bag) island indices, or None if this is not that kind of head.

    The lips are the two widest small front islands in the mouth band that sit
    one above the other and share a lateral centre. The bag, if there is one, is
    whatever else is in the band between them and behind.
    """
    P = np.asarray([p[:3] for p in positions], dtype=np.float64)
    if len(P) < 12 or not faces:
        return None
    lo, hi = P.min(axis=0), P.max(axis=0)
    height = float(hi[2] - lo[2])
    if height <= 0:
        return None
    mid_y = (lo[1] + hi[1]) / 2
    limit = max(6, int(MAX_ISLAND * len(P)))

    found = islands(P, faces)
    candidates = []
    for island in found:
        if len(island) < 5 or len(island) > limit:
            continue
        q = P[island]
        centre = q.mean(axis=0)
        if not (BAND[0] <= (centre[2] - lo[2]) / height <= BAND[1]):
            continue
        if centre[1] <= mid_y:
            continue
        candidates.append((island, centre, float(q[:, 0].max() - q[:, 0].min())))

    if len(candidates) < 2:
        return None
    candidates.sort(key=lambda t: -t[2])
    (a, ca, wa), (b, cb, wb) = candidates[0], candidates[1]
    if wa <= 0 or wb < 0.5 * wa:
        return None
    if abs(ca[0] - cb[0]) > 0.4 * wa:
        return None
    if abs(ca[2] - cb[2]) > 0.15 * height:
        return None
    upper, lower = (a, b) if ca[2] > cb[2] else (b, a)

    # The bag sits behind the lips and between them; take the widest remaining
    # candidate that is further back than both.
    front = max(ca[1], cb[1])
    bag = None
    for island, centre, _ in candidates[2:]:
        if centre[1] < front:
            bag = island
            break
    return upper, lower, bag


def mouth_region(positions, faces, *, near):
    """The shell's own lip area, split into what lifts and what drops.

    A KOTOR mouth opens by *stretching*: the face is one closed surface across
    the mouth, the vertices above the lip line are weighted to the bone that
    lifts an upper lip and those below to the ones that drop a lower lip, and
    the skin between them pulls apart to line the cavity. Carth works exactly
    this way and has no opening at all - his ``Head`` has three boundary loops,
    the neck and two eye sockets.

    A converted shell is closed in the same way, so it needs the same treatment.
    Checked directly on ``h_common01_``: the welded shell has **no boundary
    vertex anywhere near the mouth**.

    An earlier version of this looked for an aperture whose rims coincided, on
    the theory that conversion had welded a real opening shut. There is no such
    aperture. What it actually found were UV-seam duplicates, classified by
    comparing the mean height of each copy's faces - which measures the local
    slope of the surface, not its topology. Binding those apart detached the
    lips from the face along their outline while leaving the mouth line itself
    shut, which is precisely how it looked in game: the lips split and moved,
    and the place they should have parted stayed welded.

    ``near`` is ``(centre_x, centre_z, half_x, half_z)`` from the lip pieces.
    Returns ``(upper, lower)`` shell vertex indices.
    """
    P = np.asarray([p[:3] for p in positions], dtype=np.float64)
    if len(P) < 8 or not faces:
        return [], []
    every = islands(P, faces)
    if not every:
        return [], []
    shell = set(every[0])
    centre_x, centre_z, half_x, half_z = near
    lo, hi = P.min(axis=0), P.max(axis=0)
    mid_y = (lo[1] + hi[1]) / 2

    upper, lower = [], []
    for v in shell:
        x, y, z = P[v]
        if y <= mid_y:
            continue
        if abs(x - centre_x) > half_x or abs(z - centre_z) > half_z:
            continue
        (upper if z > centre_z else lower).append(int(v))
    return upper, lower


def _sides(host_influences, slot_names: dict[int, str], host_positions: np.ndarray):
    """Mean x of the region each bone leads, read off the host's own weights."""
    centre = (float(host_positions[:, 0].min()) + float(host_positions[:, 0].max())) / 2
    got: dict[str, list[float]] = collections.defaultdict(list)
    for i, infl in enumerate(host_influences):
        named = [(slot_names[f.bone_slot], f.weight) for f in infl if f.bone_slot in slot_names]
        if not named:
            continue
        got[max(named, key=lambda kv: kv[1])[0]].append(float(host_positions[i][0]) - centre)
    return {k: float(np.mean(v)) for k, v in got.items() if v}


def bind(
    positions,
    faces,
    influences: list[list[Influence]],
    slot_names: dict[int, str],
    host_positions=None,
    host_influences=None,
    *,
    split=None,
    max_influences: int = MAX_INFLUENCES,
) -> tuple[list[list[Influence]], list[str]]:
    """Bind separate lip pieces to the bones that move a mouth.

    A quiet no-op unless the head is built with separate lips and the host
    carries the standard rig, so this is safe on any mesh.
    """
    by_name = {v.lower(): k for k, v in slot_names.items()}
    if not {UPPER, JAW, SKULL, *LOWER_PAIR, *CORNER_PAIR} <= set(by_name):
        return influences, []
    if len(influences) != len(positions):
        return influences, []

    found = find_lips(positions, faces)
    seam_upper, seam_lower = [], []
    if found is not None:
        _P = np.asarray([p[:3] for p in positions], dtype=np.float64)
        rim = _P[sorted(set(found[0]) | set(found[1]))]
        # Generous around the lips - a mouth corner reaches past the modelled
        # lip piece - but nothing like far enough to touch the skull seam.
        # The same box the face is parted along. It has to be the same: the
        # weighting decides which vertices lift and which drop, and the split
        # decides where the surface is allowed to come apart. Where the first
        # reaches past the second, faces span from a lifted vertex to a dropped
        # one with nothing between them to give, and they tear - rendered, the
        # mouth grew triangular fangs.
        from . import mouthsplit as _mouthsplit

        box = _mouthsplit._box(positions, found[0], found[1])
        if split is not None:
            # Only the vertices actually parted. Weighting the whole lip area by
            # height as well was tried and is wrong: the strong lip profiles then
            # apply to vertices the surface is not split along, so faces span
            # from a lifted vertex to a dropped one with nothing between them to
            # give. Rendered, the mouth grew triangular fangs. Aligning the two
            # boxes did not help - the problem is the breadth of the weighting,
            # not where its edge falls.
            seam_upper, seam_lower = split
        else:
            seam_upper, seam_lower = mouth_region(positions, faces, near=box)
    if found is None and not seam_upper:
        return influences, []
    if found is None:
        upper_island, lower_island, bag_island = [], [], None
    else:
        upper_island, lower_island, bag_island = found

    P = np.asarray([p[:3] for p in positions], dtype=np.float64)
    lowered = {k: v.lower() for k, v in slot_names.items()}
    if (
        host_influences is not None
        and host_positions is not None
        and len(host_influences) == len(host_positions)
    ):
        side = _sides(
            host_influences, lowered, np.asarray([p[:3] for p in host_positions], float)
        )
    else:
        side = _sides(influences, lowered, P)

    def near_far(pair: tuple[str, str], x: float) -> tuple[str, str]:
        a, b = pair
        xa, xb = side.get(a), side.get(b)
        if xa is None or xb is None or xa == xb:
            near = a if x < 0 else b
        else:
            near = a if abs(x - xa) <= abs(x - xb) else b
        return near, (b if near == a else a)

    centre_x = (float(P[:, 0].min()) + float(P[:, 0].max())) / 2
    out = [list(f) for f in influences]
    every = islands(P, faces)
    shell_index = np.asarray(every[0], dtype=int) if every else np.asarray([], dtype=int)

    def apply(island, which):
        for v in island:
            x = float(P[v][0]) - centre_x
            near_corner, far_corner = near_far(CORNER_PAIR, x)
            near_lower, _ = near_far(LOWER_PAIR, x)
            if which == "upper":
                want = {
                    UPPER: UPPER_PROFILE["upper"],
                    SKULL: UPPER_PROFILE["skull"],
                    near_corner: UPPER_PROFILE["near_corner"],
                    far_corner: UPPER_PROFILE["far_corner"],
                }
            elif which == "lower":
                want = {
                    near_lower: LOWER_PROFILE["near_lower"],
                    near_corner: LOWER_PROFILE["near_corner"],
                    JAW: LOWER_PROFILE["jaw"],
                }
            else:
                want = {
                    JAW: BAG_PROFILE["jaw"],
                    near_lower: BAG_PROFILE["near_lower"],
                }
            out[v] = _finalise({by_name[n]: w for n, w in want.items()}, max_influences)

    # The shell's own aperture first: those rims are what open the mouth.
    apply(seam_upper, "upper")
    apply(seam_lower, "lower")

    # Then the pieces lying behind the shell - lips, and the interior bag.
    #
    # These follow the face rather than a profile. Giving them the idealised
    # lip weights made them swing on the jaw pivot far harder than the shell
    # around them, and in game the interior sailed out through the opening as a
    # flat slab: "the top lip and bottom lip split and they are moving with the
    # mouth pieces". A piece tucked behind the lip has to move *with* the lip in
    # front of it, whatever that lip happens to be doing, so it inherits from
    # the nearest shell vertex - after the seam above has corrected those.
    followed = 0
    if len(shell_index):
        line = None
        if upper_island and lower_island:
            both = P[sorted(set(upper_island) | set(lower_island))]
            line = float(both[:, 2].min() + both[:, 2].max()) / 2

        # Which side of the lip line a piece may inherit from. This matters
        # because the two halves of a split line sit on identical coordinates,
        # so "the nearest shell vertex" is ambiguous exactly where it must not
        # be: a lower tooth can end up following the upper lip and then rides up
        # through it, which in game read as the teeth poking through oddly.
        def source_pool(side):
            if line is None:
                return shell_index
            keep = [
                v for v in shell_index
                if (P[v][2] >= line if side == "upper" else P[v][2] <= line)
            ]
            return np.asarray(keep, dtype=int) if keep else shell_index

        for group, side in (
            (upper_island, "upper"),
            (lower_island, "lower"),
            (bag_island or [], "lower"),
        ):
            pool = source_pool(side)
            if not len(pool):
                continue
            points = P[pool]
            for v in group:
                d = points - P[v]
                nearest = int(np.argmin(np.einsum("ij,ij->i", d, d)))
                source = out[int(pool[nearest])]
                if source:
                    out[v] = [Influence(f.bone_slot, f.weight) for f in source]
                    followed += 1

    lines = []
    if followed:
        lines.append(
            f"lips: {followed} vertices of the pieces behind the face - "
            f"{len(upper_island)} upper, {len(lower_island)} lower"
            + (f", {len(bag_island)} interior" if bag_island else "")
            + " - now follow the shell in front of them"
        )
    if seam_upper:
        lines.append(
            f"mouth: {'parted' if split is not None else 'split'} the lip line - "
            f"{len(seam_upper)} vertices above it lift, {len(seam_lower)} below it "
            f"drop - so the surface stretches apart the way a KOTOR mouth does"
        )
    return out, lines


def _finalise(pool: dict[int, float], max_influences: int = MAX_INFLUENCES) -> list[Influence]:
    ranked = sorted(pool.items(), key=lambda kv: (-kv[1], kv[0]))[:max_influences]
    ranked = [(slot, w) for slot, w in ranked if w > 1e-4]
    total = sum(w for _, w in ranked)
    if total <= 0:
        return []
    return [Influence(slot, w / total) for slot, w in ranked]
