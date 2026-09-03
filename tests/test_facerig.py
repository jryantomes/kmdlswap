"""Facial weights that proximity transfer binds to the skull instead of a bone
that moves.

The measurements behind this are in the module docstring; what is tested here is
the behaviour that follows from them. The one that matters most is the negative:
this pass must leave a correctly-bound vertex alone. A blanket version fixed the
upper lip and broke the lower one, and only a test that asserts "nothing else
changed" catches that class of regression.
"""

from __future__ import annotations

import numpy as np
import pytest

from kmdlswap import facerig
from kmdlswap.mdx import Influence


SKULL = 0
MOUTH = 1
JAW = 2


def grid(n=6, *, low=0.0, high=1.0):
    """A little slab of vertices spanning the unit cube, front half included."""
    xs = np.linspace(low, high, n)
    return [(float(x), float(y), float(z)) for x in xs for y in xs for z in xs]


def led_by(slot):
    return [Influence(slot, 1.0)]


def test_a_vertex_the_skull_took_is_given_back():
    """The whole point: skull leads it here, a mobile bone leads it on the host."""
    points = grid()
    host = list(points)
    # The host says every low front vertex belongs to the mouth.
    host_infl = [
        led_by(MOUTH) if (p[2] < 0.4 and p[1] > 0.6) else led_by(SKULL) for p in host
    ]
    # Transfer got them all wrong and gave them to the skull.
    infl = [led_by(SKULL) for _ in points]

    out, lines = facerig.rebalance(points, infl, host, host_infl)

    corrected = [
        i for i, p in enumerate(points)
        if p[2] < 0.35 and p[1] > 0.7 and out[i][0].bone_slot == MOUTH
    ]
    assert corrected, "nothing was handed back to the mouth bone"
    assert lines and "facial rig" in lines[0]


def test_a_vertex_already_led_by_a_mobile_bone_is_untouched():
    """The regression that a blanket pass caused: the lower lip arrived better
    bound than vanilla and a blanket correction made it worse."""
    points = grid()
    host = list(points)
    host_infl = [led_by(MOUTH) if p[2] < 0.4 else led_by(SKULL) for p in host]
    infl = [led_by(JAW) for _ in points]

    out, lines = facerig.rebalance(points, infl, host, host_infl)

    assert out == infl
    assert lines == []


def test_the_skull_keeps_what_is_genuinely_skull():
    """A brow ridge is skull on a vanilla head too. If the host agrees with the
    transfer, there is nothing to correct."""
    points = grid()
    host = list(points)
    host_infl = [led_by(SKULL) for _ in host]
    infl = [led_by(SKULL) for _ in points]

    out, lines = facerig.rebalance(points, infl, host, host_infl)

    assert out == infl
    assert lines == []


def test_the_back_of_the_head_is_left_alone():
    """Only the lower *front* qualifies; the back of a skull is skull."""
    points = grid()
    host = list(points)
    host_infl = [led_by(MOUTH) for _ in host]
    infl = [led_by(SKULL) for _ in points]

    out, _ = facerig.rebalance(points, infl, host, host_infl)

    for i, p in enumerate(points):
        unit_y, unit_z = p[1], p[2]
        if unit_y < facerig.FRONT or unit_z > facerig.EYE_LINE:
            assert out[i] == infl[i], f"vertex at {p} is outside the region"


def test_the_skull_is_found_without_being_named():
    """It is whichever bone leads the most host vertices outside the lower face,
    so a host rig this project has never seen still works."""
    points = grid()
    region = facerig.region_mask(np.asarray(points, dtype=float))
    host_infl = [led_by(MOUTH) if region[i] else led_by(99) for i in range(len(points))]

    assert facerig._static_bone(host_infl, region) == 99


def test_weights_stay_normalised_and_within_the_stride():
    """Four influences is what the MDX stride holds, and vanilla weights sum to
    one. A correction that broke either would be rejected at write time."""
    points = grid()
    host = list(points)
    rng = np.random.default_rng(0)
    host_infl = []
    for _ in host:
        slots = rng.choice(np.arange(1, 9), size=5, replace=False)
        w = rng.random(5)
        w /= w.sum()
        host_infl.append([Influence(int(s), float(x)) for s, x in zip(slots, w)])
    infl = [led_by(SKULL) for _ in points]

    out, _ = facerig.rebalance(points, infl, host, host_infl)

    for f in out:
        assert 1 <= len(f) <= facerig.MAX_INFLUENCES
        assert sum(x.weight for x in f) == pytest.approx(1.0, abs=1e-6)
        assert all(x.weight > 0 for x in f)


@pytest.mark.parametrize(
    "positions, influences, host_positions, host_influences",
    [
        ([], [], grid(), [led_by(SKULL)] * 216),
        (grid(), [led_by(SKULL)] * 216, [], []),
        (grid(), [led_by(SKULL)] * 3, grid(), [led_by(SKULL)] * 216),  # mismatched
        ([(0.0, 0.0, 0.0)], [led_by(SKULL)], grid(), [led_by(SKULL)] * 216),  # too small
    ],
)
def test_nothing_to_work_with_returns_the_input(
    positions, influences, host_positions, host_influences
):
    """Called on every skinned build, so every degenerate case is a quiet
    no-op rather than an exception."""
    out, lines = facerig.rebalance(
        positions, influences, host_positions, host_influences
    )
    assert out is influences
    assert lines == []


def test_a_mesh_of_a_different_size_is_still_comparable():
    """Normalising into each mesh's own box is what lets a small head inherit
    from a large one; without it the anatomical lookup finds nothing."""
    points = grid()
    host = [(p[0] * 10, p[1] * 10, p[2] * 10) for p in points]
    host_infl = [led_by(MOUTH) if p[2] < 4.0 and p[1] > 6.0 else led_by(SKULL) for p in host]
    infl = [led_by(SKULL) for _ in points]

    out, lines = facerig.rebalance(points, infl, host, host_infl)

    assert lines, "a ten-times-larger host taught it nothing"
    assert any(f[0].bone_slot == MOUTH for f in out)
