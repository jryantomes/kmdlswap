"""Correcting facial weights that proximity transfer binds to the wrong bones.

``weights.transfer`` finds, for each new vertex, the closest point on the host's
*surface* and inherits that triangle's influences. On a body, or anywhere the
two shapes agree, that is right. On a face it has a specific failure: where the
replacement sits even slightly off the host's surface - a different brow, a
fuller lip, a longer chin - the nearest triangle can belong to the skull rather
than to the small mobile bone that ought to own that spot. The vertex renders
correctly and never moves, and nothing reports a problem.

**Which vertices are wrong is not obvious, and averages hide it.** The useful
measure is which bone *leads* each vertex, because that is what decides whether
it moves. Measured on Jade Empire's ``h_common01_`` converted onto Carth, as the
share of vertices in each band led by each kind of bone:

======================  ==================  ================
band                    vanilla p_carthh    plain transfer
======================  ==================  ================
upper lip, led by skull  26%                **41%**
upper lip, led by mouth  48%                25%
lower lip, led downward  88%                97%
lower lip, led by mouth  0%                 0%
======================  ==================  ================

So the lower lip is *fine* - better bound than vanilla, in fact - and the upper
lip is where proximity fails, with two fifths of it led by a bone that never
moves. Mean weight shares suggested the opposite, that the whole mouth region
was skull-heavy and the lower lip starved; that reading was an artefact of
averaging over bands that contain both lips.

**So the correction is targeted, not blanket.** A vertex qualifies only when the
skull leads it *and* the host's own anatomy at the same place has a mobile bone
leading instead. Everything else is left exactly as transferred. That matters:
a blanket version of this pass fixed the upper lip and simultaneously dragged
the lower lip from 97% down to 84% while leaking upper-lip weight onto it, which
is the very failure it was meant to prevent.

Qualifying vertices are re-sampled in *anatomical* space - each mesh normalised
into its own bounding box, so "a third of the way up, slightly left of centre,
at the front" means the same thing on both heads whatever their proportions.

**Nothing here is hardcoded to a rig.** The skull is identified as whichever
bone leads the most host vertices outside the lower face, and replacements come
from the host being built onto, so this works on a rig this project has not
seen. The census behind the region bounds is in ``reports/SKINNING_FINDINGS.md``:
all 101 skinned K1 heads share one 16-bone rig whose vertical order is identical
everywhere - brows at 65% of head height, skull 56%, eyes 55%, nose 45%,
``f_um_g`` 36%, corners 33%, ``f_llm_g``/``f_rlm_g`` 30%, ``f_jaw_g`` 22%.

An earlier version worked on boundary loops, on the belief that converted heads
carry an open mouth that KOTOR heads lack. That was wrong, and wrong in a way
worth recording: read across islands, a separate lip piece's own edge looks
exactly like the rim of a hole. ``h_common01_``'s face shell has one hole, the
neck, same as Carth's. Its lips are separate closed pieces lying on a solid face.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from .mdx import Influence

# How far up the head the correction reaches, as a fraction of its height. The
# eye line sits at 55% and the nose at 45%; stopping at half keeps this to the
# mouth, jaw and chin, where the mobile bones are small enough for proximity to
# miss them.
EYE_LINE = 0.5

# Front half only. The back of the head is skull, and it is genuinely head_g.
FRONT = 0.5

# The eye socket, as a fraction of head height, and how much of the host's
# answer the brows may carry there.
#
# This region has the opposite problem to the lower face. There, proximity gives
# the skull work that belongs to a mobile bone. Here it gives a mobile bone -
# the brow, which is the nearest thing to an eye - work that belongs to the
# skull: measured on `h_mercf01_`, 28% of the skin around the eyes sat on brow
# bones against Carth's 5%, so the whole eye socket moved whenever the brows
# did. Reported from the game as the skin around the eyes moving.
#
# It is a share, not an extent. Capping by how far down the host's brows reach
# corrects almost nothing - his reach that low too, just weakly.
#
# **The host's band and the target's are not the same band.** This was the
# defect behind the second report, of the brow lifting the top eyelid: the
# constant was 0.50-0.60 for both, and while Carth's eyeballs span 0.541-0.610,
# `h_mercf01_`'s span 0.567-0.662. So the cap landed on the bottom third of her
# eye and left the top two thirds - the upper lid, carrying more weight than the
# part that was corrected - at 24.8% brow. The host's band is a constant here
# because the K1 facial rig is identical across all 101 skinned heads; the
# target's is measured from its own eyes and passed in.
HOST_EYE_BAND = (0.500, 0.610)

# How far below the eyes the socket reaches, as a fraction of head height. It is
# the distance the host's band already ran below his own eyeballs, applied to
# the target's eyes so both bands cover the same anatomy.
SOCKET = HOST_EYE_BAND[1] - HOST_EYE_BAND[0] - 0.069   # his eyes are 0.069 tall

# How much of the anatomical opinion to take on a vertex that qualifies. These
# are vertices the skull has taken from a mobile bone, so there is nothing worth
# preserving in the proximity answer and the replacement is total. It fades over
# `FADE` below the eye line only to avoid a hard edge across the face.
STRENGTH = 1.0
FADE = 0.12

# Host vertices consulted per target vertex, inverse-distance weighted. Small on
# purpose: averaging over more of them blurs the boundary between the upper and
# lower lip, which is the one distinction this must not lose. Measured on
# `h_common01_`, going from 1 to 10 neighbours doubles the amount of upper-lip
# weight that leaks onto the lower lip, from 11% to 22%.
NEIGHBOURS = 1

MAX_INFLUENCES = 4


def _normalise(points: np.ndarray) -> np.ndarray:
    """Into the unit cube of the mesh's own bounding box.

    This is what makes the two heads comparable: a longer jaw or a wider skull
    stops mattering, and only the anatomical position does.
    """
    lo = points.min(axis=0)
    hi = points.max(axis=0)
    span = np.where(hi - lo > 1e-9, hi - lo, 1.0)
    return (points - lo) / span


def region_mask(positions: np.ndarray) -> np.ndarray:
    """The lower front of the face, where the failure was measured."""
    unit = _normalise(positions)
    return (unit[:, 2] < EYE_LINE) & (unit[:, 1] > FRONT)


def _strength(unit_height: np.ndarray) -> np.ndarray:
    """Full strength through the region, easing off just under the eye line.

    An earlier version ramped across the whole region, which sounds gentler and
    is useless: the mouth sits at 36% of head height, close enough to the eye
    line at 50% that it received only a sixth of the correction. The fade is
    there to prevent a visible seam, not to moderate the fix.
    """
    ramp = np.clip((EYE_LINE - unit_height) / FADE, 0.0, 1.0)
    return STRENGTH * ramp


def _static_bone(host_influences, region: np.ndarray) -> int | None:
    """The bone that owns the skull, found without reference to any name.

    It is whichever bone dominates the most host vertices *outside* the lower
    front of the face - which is the skull by construction, on any rig. Deriving
    it beats hardcoding ``head_g`` because it keeps this working on a host whose
    rig this project has not seen.
    """
    tally: dict[int, int] = {}
    for index, infl in enumerate(host_influences):
        if index < len(region) and region[index]:
            continue
        if not infl:
            continue
        top = max(infl, key=lambda f: f.weight)
        tally[top.bone_slot] = tally.get(top.bone_slot, 0) + 1
    if not tally:
        return None
    return max(tally.items(), key=lambda kv: kv[1])[0]


def _brow_bones(host_influences, unit_host: np.ndarray, skull: int) -> set[int]:
    """Bones the host uses above its own eye band - the brows, by position.

    Found rather than named, so this holds on a rig this project has not seen.
    """
    tally: dict[int, float] = {}
    for index, infl in enumerate(host_influences):
        if index >= len(unit_host):
            continue
        if unit_host[index][2] < HOST_EYE_BAND[1] or unit_host[index][1] <= FRONT:
            continue
        for f in infl:
            if f.bone_slot != skull:
                tally[f.bone_slot] = tally.get(f.bone_slot, 0.0) + f.weight
    if not tally:
        return set()
    strongest = max(tally.values())
    return {slot for slot, w in tally.items() if w >= strongest * 0.2}


def _band_share(host_influences, unit_host: np.ndarray, bones: set[int]) -> float:
    """What share of the host's own eye band those bones carry."""
    total = on = 0.0
    for index, infl in enumerate(host_influences):
        if index >= len(unit_host) or unit_host[index][1] <= FRONT:
            continue
        if not (HOST_EYE_BAND[0] <= unit_host[index][2] <= HOST_EYE_BAND[1]):
            continue
        for f in infl:
            total += f.weight
            if f.bone_slot in bones:
                on += f.weight
    return (on / total) if total else 0.0


def rebalance(
    positions,
    influences: list[list[Influence]],
    host_positions,
    host_influences: Sequence[Sequence[Influence]],
    *,
    neighbours: int = NEIGHBOURS,
    max_influences: int = MAX_INFLUENCES,
    eye_band: tuple[float, float] | None = None,
) -> tuple[list[list[Influence]], list[str]]:
    """Re-sample lower-face vertices the skull has taken from a mobile bone.

    Returns new influences and a line describing what changed, or the input
    untouched when there is nothing to correct. Safe on any mesh: a body, an
    unskinned mesh, and a head whose facial weights already came out right all
    return unchanged, because a vertex is only touched when the skull leads it
    and the host's anatomy at that spot says it should not.
    """
    if not influences or not host_influences:
        return influences, []
    P = np.asarray([p[:3] for p in positions], dtype=np.float64)
    H = np.asarray([p[:3] for p in host_positions], dtype=np.float64)
    if len(P) != len(influences) or len(H) != len(host_influences):
        return influences, []
    if len(P) < 4 or len(H) < 4:
        return influences, []

    unit_p = _normalise(P)
    unit_h = _normalise(H)
    mask = region_mask(P)
    if not mask.any():
        return influences, []

    skull = _static_bone(host_influences, region_mask(H))
    if skull is None:
        return influences, []

    strength = _strength(unit_p[:, 2])
    out = [list(f) for f in influences]
    moved = 0
    shifted = 0.0

    targets = np.flatnonzero(mask)
    k = min(neighbours, len(H))
    for index in targets:
        alpha = float(strength[index])
        if alpha <= 0.0:
            continue

        # Only vertices the skull has taken. A lower-face vertex already led by
        # a mobile bone is working, and correcting it can only make it worse:
        # measured on `h_common01_`, the lower lip arrives 97% dominated by
        # bones that move it downward - better than vanilla's 88% - and a
        # blanket pass dropped that to 84% while leaking upper-lip weight onto
        # it. The upper lip is where the failure lives, at 41% skull-dominated
        # against vanilla's 26%.
        current = out[index]
        if not current or max(current, key=lambda f: f.weight).bone_slot != skull:
            continue

        delta = unit_h - unit_p[index]
        d2 = np.einsum("ij,ij->i", delta, delta)
        nearest = np.argpartition(d2, k - 1)[:k]

        # Inverse distance, so a host vertex sitting exactly on this spot
        # dominates and a distant one barely registers.
        w = 1.0 / np.sqrt(np.maximum(d2[nearest], 1e-12))
        w /= w.sum()

        anatomical: dict[int, float] = {}
        for host_index, share in zip(nearest, w):
            for f in host_influences[host_index]:
                anatomical[f.bone_slot] = anatomical.get(f.bone_slot, 0.0) + share * f.weight
        if not anatomical:
            continue
        # If the host's own anatomy says skull here too, then skull is right and
        # there is nothing to correct - the brow ridge and the sides of the jaw
        # are genuinely skull on a vanilla head as well.
        if max(anatomical.items(), key=lambda kv: kv[1])[0] == skull:
            continue

        have = {f.bone_slot: f.weight for f in out[index]}
        pool = {
            slot: (1 - alpha) * have.get(slot, 0.0) + alpha * anatomical.get(slot, 0.0)
            for slot in set(have) | set(anatomical)
        }
        merged = _finalise(pool, max_influences)
        if not merged:
            continue

        after = {f.bone_slot: f.weight for f in merged}
        change = sum(abs(after.get(s, 0.0) - have.get(s, 0.0)) for s in set(after) | set(have))
        if change > 1e-6:
            moved += 1
            shifted += change
        out[index] = merged

    # The brows' share of the eye socket, held to the host's own.
    eyed = 0
    brow = _brow_bones(host_influences, unit_h, skull)
    want = _band_share(host_influences, unit_h, brow) if brow else 0.0
    band = eye_band if eye_band is not None else HOST_EYE_BAND
    if brow:
        for index in range(len(P)):
            height = float(unit_p[index][2])
            if not (band[0] <= height <= band[1]):
                continue
            if float(unit_p[index][1]) <= FRONT:
                continue
            have = {f.bone_slot: f.weight for f in out[index]}
            total = sum(have.values()) or 1.0
            on_brow = sum(w for s, w in have.items() if s in brow) / total
            if on_brow <= want + 0.02:
                continue
            keep = want / on_brow if on_brow > 0 else 0.0
            pool = {s: (w * keep if s in brow else w) for s, w in have.items()}
            pool[skull] = pool.get(skull, 0.0) + (on_brow - want) * total
            merged = _finalise(pool, max_influences)
            if merged:
                out[index] = merged
                eyed += 1

    if not moved and not eyed:
        return influences, []
    lines = []
    if moved:
        lines.append(
            f"facial rig: {moved} of {int(mask.sum())} lower-face vertices were led by "
            f"the skull where the host's anatomy has a mobile bone; re-sampled "
            f"(mean weight moved {shifted / moved:.2f})"
        )
    if eyed:
        lines.append(
            f"eye rig: {eyed} vertices around the eyes held to the host's own brow "
            f"share ({want:.0%}) - the brow was carrying the eye socket"
        )
    return out, lines


def _finalise(pool: dict[int, float], max_influences: int = MAX_INFLUENCES) -> list[Influence]:
    ranked = sorted(pool.items(), key=lambda kv: (-kv[1], kv[0]))[:max_influences]
    ranked = [(slot, w) for slot, w in ranked if w > 1e-4]
    total = sum(w for _, w in ranked)
    if total <= 0:
        return []
    return [Influence(slot, w / total) for slot, w in ranked]
