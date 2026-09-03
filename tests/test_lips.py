"""Lips modelled as separate pieces, bound to the bones that move a mouth.

The failure this covers was invisible to every regional measurement taken of it:
28 lip vertices inside a band holding 285 disappear into the average, so a pass
whose own numbers looked corrected came back "about the same" in game. The tests
that matter here are therefore about *finding* the right 28 vertices, and about
leaving a head alone that does not have them.
"""

from __future__ import annotations

import numpy as np
import pytest

from kmdlswap import lips
from kmdlswap.mdx import Influence


RIG = {
    0: "head_g",
    1: "f_um_g",
    2: "f_jaw_g",
    3: "f_llm_g",
    4: "f_rlm_g",
    5: "f_lmc_g",
    6: "f_rmc_g",
}
NAMES = {v: k for k, v in RIG.items()}


def ring(centre, *, width=0.10, height=0.01, n=8):
    """A small closed strip of geometry, like a modelled lip."""
    cx, cy, cz = centre
    points, faces = [], []
    for i in range(n):
        t = 2 * np.pi * i / n
        points.append((cx + width / 2 * np.cos(t), cy, cz + height / 2 * np.sin(t)))
        points.append((cx + width / 2 * np.cos(t), cy + 0.01, cz + height / 2 * np.sin(t)))
    for i in range(n):
        a, b = 2 * i, 2 * i + 1
        c, d = (2 * ((i + 1) % n)), (2 * ((i + 1) % n) + 1)
        faces.append((a, b, c))
        faces.append((b, d, c))
    return points, faces


def head_with_separate_lips():
    """A face shell plus two lip pieces and a bag, the way a converted head is
    often built."""
    points, faces = [], []

    def add(p, f):
        base = len(points)
        points.extend(p)
        faces.extend([(a + base, b + base, c + base) for a, b, c in f])

    # A shell spanning the whole head box. It has to be much larger than the
    # lips, as a real one is - 14 lip vertices against 742 on `h_common01_` -
    # because a piece bigger than `MAX_ISLAND` of the mesh is taken to be the
    # face itself rather than something lying on it.
    shell_pts, shell_faces = ring((0.0, 0.0, 0.5), width=0.30, height=1.0, n=100)
    add(shell_pts, shell_faces)
    add(*ring((0.0, 0.12, 0.38), n=6))          # upper lip, front, in the band
    add(*ring((0.0, 0.12, 0.35), n=6))          # lower lip, just below it
    add(*ring((0.0, 0.08, 0.36), width=0.05, n=6))  # bag, behind both
    return points, faces


def led_by(slot):
    return [Influence(slot, 1.0)]


def test_the_lips_are_found_and_bound_to_bones_that_move():
    points, faces = head_with_separate_lips()
    infl = [led_by(NAMES["head_g"]) for _ in points]

    out, lines = lips.bind(points, faces, infl, RIG)

    assert lines and "lips:" in lines[0]
    found = lips.find_lips(points, faces)
    upper, lower, bag = found
    assert all(out[v][0].bone_slot == NAMES["f_um_g"] for v in upper)
    assert all(
        out[v][0].bone_slot in (NAMES["f_llm_g"], NAMES["f_rlm_g"]) for v in lower
    )
    assert bag and all(out[v][0].bone_slot == NAMES["f_jaw_g"] for v in bag)


def test_the_lower_lip_is_never_led_by_a_bone_that_lifts_it():
    """The measured failure: as much weight lifting the lower lip as dropping
    it, so the two cancel and the mouth stays shut."""
    points, faces = head_with_separate_lips()
    infl = [led_by(NAMES["f_um_g"]) for _ in points]

    out, _ = lips.bind(points, faces, infl, RIG)

    _, lower, _ = lips.find_lips(points, faces)
    for v in lower:
        assert out[v][0].bone_slot != NAMES["f_um_g"]
        assert NAMES["f_um_g"] not in {f.bone_slot for f in out[v]}


def test_the_lower_lip_splits_across_the_two_sides():
    """`f_llm_g` and `f_rlm_g` are a left/right pair; binding a whole lip to one
    of them would drag it sideways."""
    points, faces = head_with_separate_lips()
    infl = [led_by(NAMES["head_g"]) for _ in points]
    host = list(points)
    # Host weights that put f_llm_g on the left and f_rlm_g on the right.
    host_infl = [
        led_by(NAMES["f_llm_g"]) if p[0] < 0 else led_by(NAMES["f_rlm_g"]) for p in host
    ]

    out, _ = lips.bind(points, faces, infl, RIG, host, host_infl)

    _, lower, _ = lips.find_lips(points, faces)
    leaders = {out[v][0].bone_slot for v in lower}
    assert leaders == {NAMES["f_llm_g"], NAMES["f_rlm_g"]}


def test_a_head_whose_mouth_is_part_of_the_face_is_left_alone():
    """A KOTOR-built head has no lip islands. Touching one would be a
    regression on every vanilla-style head this tool already handles."""
    points, faces = ring((0.0, 0.0, 0.5), width=0.3, height=1.0, n=16)
    infl = [led_by(NAMES["head_g"]) for _ in points]

    out, lines = lips.bind(points, faces, infl, RIG)

    assert out is infl
    assert lines == []


def test_a_host_without_the_rig_is_left_alone():
    """Bodies, and anything whose bones are not a facial rig."""
    points, faces = head_with_separate_lips()
    infl = [led_by(0) for _ in points]

    out, lines = lips.bind(points, faces, infl, {0: "rootdummy", 1: "torso_g"})

    assert out is infl
    assert lines == []


def test_islands_are_welded_before_being_counted():
    """A lip split along a UV seam is several islands by index and one piece in
    space. Only the welded reading finds a mouth."""
    points, faces = ring((0.0, 0.12, 0.38), n=6)
    doubled = list(points) + list(points)  # every vertex duplicated in place
    shifted = [(a + len(points), b + len(points), c + len(points)) for a, b, c in faces]

    found = lips.islands(np.asarray(doubled, dtype=float), faces + shifted)

    assert len(found) == 1, f"welding failed: {[len(g) for g in found]} islands"
    assert len(found[0]) == len(doubled)


def test_weights_stay_normalised_and_within_the_stride():
    points, faces = head_with_separate_lips()
    infl = [led_by(NAMES["head_g"]) for _ in points]

    out, _ = lips.bind(points, faces, infl, RIG)

    for f in out:
        assert 1 <= len(f) <= lips.MAX_INFLUENCES
        assert sum(x.weight for x in f) == pytest.approx(1.0, abs=1e-6)
        assert all(x.weight > 0 for x in f)


def test_a_mismatched_influence_list_is_refused_quietly():
    points, faces = head_with_separate_lips()
    infl = [led_by(0)] * 3

    out, lines = lips.bind(points, faces, infl, RIG)

    assert out is infl
    assert lines == []
