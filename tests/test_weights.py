"""Skin weight transfer, and the bones it would otherwise lose.

Transfer samples the *source* surface at the *target's* vertices. A bone whose
region is small, or which sits where the two shapes disagree, can get no sample
at all and silently stop driving anything. It fails quietly, which is the worst
way to fail: in game it reads as "that part of the face doesn't move", and the
build report says nothing.
"""

from __future__ import annotations

import numpy as np
import pytest

from kmdlswap import edit as ke
from kmdlswap import layout as kl
from kmdlswap import weights as kw
from kmdlswap.mdx import Influence


def strip(width=1.0, rows=5, cols=5, z=0.0):
    """A flat grid in XY, and its triangles."""
    positions, faces = [], []
    for r in range(rows):
        for c in range(cols):
            positions.append((c * width / (cols - 1), r * width / (rows - 1), z))
    for r in range(rows - 1):
        for c in range(cols - 1):
            i = r * cols + c
            faces.append((i, i + 1, i + cols))
            faces.append((i + 1, i + cols + 1, i + cols))
    return positions, faces


def smooth_stand_in(host_positions):
    """A smooth ellipsoid filling the host's box.

    Two earlier versions of this helper proved nothing, and both failures were
    informative. Decimating the head keeps every bone, because the vertices stay
    on the *same surface* and every region still gets sampled. A fine ellipsoid
    keeps them too, for the same reason - being a different shape is not enough.
    Bones are lost when the donor is too *coarse* for a small region to be the
    nearest thing to any of its vertices.

    Measured against Carth's 16 bones: a 362-vertex sphere loses none, 146
    loses two, and 34 loses six. This uses 34.
    """
    from kmdlfun import headgen

    src = np.asarray([p[:3] for p in host_positions])
    lo, hi = src.min(axis=0), src.max(axis=0)
    centre, half = (hi + lo) / 2.0, (hi - lo) / 2.0
    dirs, _, _ = headgen.uv_sphere(5, 8)
    return [tuple(centre + np.asarray(d) * half) for d in dirs]


def test_a_bone_confined_to_one_corner_is_lost_without_rescue():
    """The failure this exists to fix, reproduced deliberately.

    Bone 9 owns a single source vertex in one corner. The target samples the
    surface elsewhere, so nothing inherits it.
    """
    src, faces = strip()
    influences = [[Influence(0, 1.0)] for _ in src]
    influences[0] = [Influence(9, 1.0)]          # the far corner, and only it

    target = [(0.5, 0.5, 0.0), (0.6, 0.6, 0.0), (0.9, 0.9, 0.0)]
    out = kw.transfer(src, faces, influences, target)
    assert 9 not in {i.bone_slot for infl in out for i in infl}

    claimed = kw.claim_orphan_bones(src, influences, target, out)
    assert claimed == {9: 1}
    assert 9 in {i.bone_slot for infl in out for i in infl}
    assert not kw.check(out)


def test_the_rescued_bone_lands_nearest_its_own_region():
    """Counting bones is not enough - a bone reinstated in the wrong place is
    worse than one left out, because it deforms something it should not."""
    src, faces = strip()
    influences = [[Influence(0, 1.0)] for _ in src]
    influences[0] = [Influence(9, 1.0)]          # source corner at (0, 0, 0)

    target = [(0.05, 0.05, 0.0), (0.5, 0.5, 0.0), (0.95, 0.95, 0.0)]
    out = kw.transfer(src, faces, influences, target)
    kw.claim_orphan_bones(src, influences, target, out)

    holders = [i for i, infl in enumerate(out) if any(x.bone_slot == 9 for x in infl)]
    assert holders == [0], f"bone 9 belongs on the nearest vertex, got {holders}"


def test_a_bone_that_transferred_fine_is_left_alone():
    src, faces = strip()
    influences = [[Influence(3, 1.0)] for _ in src]
    target = [(0.5, 0.5, 0.0), (0.25, 0.75, 0.0)]
    out = kw.transfer(src, faces, influences, target)
    before = [list(infl) for infl in out]

    assert kw.claim_orphan_bones(src, influences, target, out) == {}
    assert out == before


def test_rescue_keeps_the_rules_vanilla_obeys():
    """At most four influences, summing to one - a rescue that broke either
    would trade a silent bone for a corrupt mesh."""
    src, faces = strip()
    influences = []
    for i in range(len(src)):
        influences.append([Influence(0, 0.4), Influence(1, 0.3),
                           Influence(2, 0.2), Influence(3, 0.1)])
    influences[0] = [Influence(9, 1.0)]

    target = [(0.05, 0.05, 0.0), (0.5, 0.5, 0.0)]
    out = kw.transfer(src, faces, influences, target)
    kw.claim_orphan_bones(src, influences, target, out)

    assert not kw.check(out)
    for infl in out:
        assert len(infl) <= kw.MAX_INFLUENCES
        assert sum(x.weight for x in infl) == pytest.approx(1.0, abs=1e-6)


def test_the_claimed_weight_matches_what_the_bone_held():
    """Reinstating at the source weight keeps the fix proportional: a bone that
    barely mattered gets barely anything, rather than a fixed nudge that would
    over-drive it."""
    src, faces = strip()
    influences = [[Influence(0, 1.0)] for _ in src]
    influences[0] = [Influence(9, 0.25), Influence(0, 0.75)]

    # Every target sits far from the corner, so nothing inherits bone 9.
    target = [(0.9, 0.9, 0.0), (0.8, 0.95, 0.0)]
    out = kw.transfer(src, faces, influences, target)
    assert 9 not in {i.bone_slot for infl in out for i in infl}

    kw.claim_orphan_bones(src, influences, target, out)
    holder = next(infl for infl in out if any(x.bone_slot == 9 for x in infl))
    got = next(x.weight for x in holder if x.bone_slot == 9)
    assert got == pytest.approx(0.25, abs=1e-6)
    assert sum(x.weight for x in holder) == pytest.approx(1.0, abs=1e-6)


# --- against a real head -----------------------------------------------------


def test_every_bone_of_a_real_head_survives_transfer(pair):
    """Carth's head onto a mesh too coarse to sample every bone's region.

    The real case that prompted this lost four bones - all three brows and one
    nose - onto a generated head, and read in game as a face whose brows never
    move.
    """
    layout = kl.parse(*pair("p_carthh"))
    geo = ke.extract(layout, layout.node_by_name("Head"))
    smooth = smooth_stand_in(geo.positions)

    out = kw.transfer(
        geo.positions, [f.vertices for f in geo.faces], geo.influences, smooth
    )
    host_bones = {i.bone_slot for infl in geo.influences for i in infl}
    lost = host_bones - {i.bone_slot for infl in out for i in infl}
    assert lost, "expected transfer alone to lose bones onto a smooth head"

    kw.claim_orphan_bones(geo.positions, geo.influences, smooth, out)
    assert {i.bone_slot for infl in out for i in infl} == host_bones
    assert not kw.check(out)


def test_rescued_bones_stay_in_their_own_neighbourhood(pair):
    """Spatial sanity on real data: a rescued bone must end up near where it
    acted on the host, not merely somewhere."""
    layout = kl.parse(*pair("p_carthh"))
    geo = ke.extract(layout, layout.node_by_name("Head"))
    smooth = smooth_stand_in(geo.positions)

    out = kw.transfer(
        geo.positions, [f.vertices for f in geo.faces], geo.influences, smooth
    )
    claimed = kw.claim_orphan_bones(geo.positions, geo.influences, smooth, out)
    assert claimed, "nothing was rescued, so this proves nothing"

    src = np.asarray([p[:3] for p in geo.positions])
    tgt = np.asarray([p[:3] for p in smooth])
    extent = float(np.linalg.norm(src.max(axis=0) - src.min(axis=0)))

    for slot in claimed:
        host_centre = np.mean(
            [src[i] for i, infl in enumerate(geo.influences)
             if any(x.bone_slot == slot for x in infl)], axis=0
        )
        new_centre = np.mean(
            [tgt[i] for i, infl in enumerate(out)
             if any(x.bone_slot == slot for x in infl)], axis=0
        )
        drift = float(np.linalg.norm(new_centre - host_centre))
        assert drift < 0.25 * extent, (
            f"bone {slot} was reinstated {drift:.4f} away, "
            f"{drift / extent:.0%} of the head's size"
        )
