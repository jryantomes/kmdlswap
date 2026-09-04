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


def test_the_teeth_are_bound_rigidly_one_bone_each():
    """As the host binds its own: `teethUa01` is parented to `head_g` and
    `teethLa01` to `f_jaw_g`, with no skinning at all.

    Letting them follow the shell instead is what defeated every attempt to
    weight the lower lip. A 14-vertex island whose few vertices sample a steep
    weight field does not deform, it spikes, and the mouth grew fangs.
    """
    points, faces = head_with_separate_lips()
    infl = [led_by(NAMES["f_um_g"]) for _ in points]

    out, lines = lips.bind(points, faces, infl, RIG)

    upper, lower, _ = lips.find_lips(points, faces)
    for v in upper:
        assert out[v] == [Influence(NAMES["head_g"], 1.0)]
    for v in lower:
        assert out[v] == [Influence(NAMES["f_jaw_g"], 1.0)]
    assert any("rigidly" in line for line in lines)


def test_the_eyeballs_are_rigid_to_the_skull():
    """As the host parents `eyeLA` and `eyeRA` to `head_g`.

    Left to proximity transfer they take the bone nearest them, which at the eye
    line is the brow - measured on a real head, 47% and 49% on `f_lbrw_g` and
    `f_rbrw_g`. Every brow movement then swings the eyes, and in game the eyes
    were seen roaming around the face when only the brow should move.
    """
    points, faces = head_with_eyes()
    # Seeded with a facial bone rather than the skull, standing in for the brow
    # that proximity transfer actually hands them.
    infl = [led_by(NAMES["f_lmc_g"]) for _ in points]

    out, lines = lips.bind(points, faces, infl, RIG)

    P = np.asarray(points, dtype=float)
    lo, hi = P.min(axis=0), P.max(axis=0)
    height = hi[2] - lo[2]
    mid_y = (lo[1] + hi[1]) / 2
    eyes = [
        island for island in lips.islands(P, faces)[1:]
        if 6 <= len(island) <= max(6, int(lips.MAX_ISLAND * len(P)))
        and lips.EYE_BAND[0] <= (P[island].mean(axis=0)[2] - lo[2]) / height <= lips.EYE_BAND[1]
        and P[island].mean(axis=0)[1] > mid_y
    ]
    assert eyes, "the fixture has no eyes to bind"
    for island in eyes:
        for v in island:
            assert out[v] == [Influence(NAMES["head_g"], 1.0)], (
                "an eyeball still follows a facial bone"
            )


def head_with_eyes():
    """The face-over-lips head, with a pair of eyeballs behind it."""
    points, faces = head_with_a_face_over_lips()
    base = len(points)
    for cx in (-0.05, 0.05):
        pts, fcs = ring((cx, 0.12, 0.60), width=0.03, height=0.03, n=6)
        offset = len(points)
        points.extend(pts)
        faces.extend([(a + offset, b + offset, c + offset) for a, b, c in fcs])
    return points, faces


def test_the_interior_still_follows_the_face():
    """The bag lines the whole cavity and must not be rigid: bound to the jaw
    it swings down with it and the top of the opening unseals, which rendered
    against a green background as daylight through the head."""
    points, faces = head_with_separate_lips()
    P = np.asarray(points, dtype=float)
    shell = np.asarray(lips.islands(P, faces)[0], dtype=int)
    infl = [led_by(NAMES["head_g"]) for _ in points]
    for i in shell:
        infl[i] = [Influence(NAMES["f_lmc_g"], 1.0)]

    out, _ = lips.bind(points, faces, infl, RIG)

    _, _, bag = lips.find_lips(points, faces)
    assert bag
    assert all(out[v][0].bone_slot == NAMES["f_lmc_g"] for v in bag), (
        "the interior stopped following the face"
    )


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


# --- the shell opens by stretching -----------------------------------------
#
# A KOTOR mouth has no opening. The face is one closed surface, the vertices
# above the lip line lift and those below drop, and the skin between them pulls
# apart to line the cavity. A converted shell is closed the same way and needs
# the same treatment: checked on `h_common01_`, the welded shell has no boundary
# vertex anywhere near the mouth.
#
# An earlier version hunted for an aperture whose rims coincided, believing
# conversion had welded a real opening shut. There is no such aperture. What it
# found were UV-seam duplicates, told apart by comparing the mean height of each
# copy's faces - which measures the slope of the surface, not its topology.
# Binding those apart detached the lips from the face along their outline and
# left the mouth line itself welded, which is exactly how it looked in game.


def head_with_a_face_over_lips():
    """A shell that wraps front and back, with the lips behind its front.

    Both halves matter. The front has to be *in front of* the lips, because
    that is the arrangement that hides them; and there has to be a back, or the
    mesh's mid-depth sits between the shell and the lips and the front-half
    test excludes the very geometry it is meant to select.
    """
    points, faces = [], []

    def add(p, f):
        base = len(points)
        points.extend(p)
        faces.extend([(a + base, b + base, c + base) for a, b, c in f])

    # Dense enough that several rows land inside the mouth box on both sides
    # of the lip line. A coarse plane put a single row in it, all on one side,
    # and the split had nothing to work with - which is a property of the
    # fixture, not of the code.
    def plane(y, nx=16, nz=64):
        pts = [
            (-0.15 + 0.30 * i / (nx - 1), y, k / (nz - 1))
            for i in range(nx) for k in range(nz)
        ]
        cells = []
        for i in range(nx - 1):
            for k in range(nz - 1):
                a = i * nz + k
                cells.append((a, a + 1, (i + 1) * nz + k))
                cells.append((a + 1, (i + 1) * nz + k + 1, (i + 1) * nz + k))
        return pts, cells

    add(*plane(0.15))    # the face, in front of everything
    add(*plane(-0.15))   # the back of the skull
    add(*ring((0.0, 0.12, 0.38), n=6))
    add(*ring((0.0, 0.12, 0.35), n=6))
    add(*ring((0.0, 0.09, 0.36), width=0.05, n=6))
    return points, faces


def test_the_shell_splits_at_the_lip_line():
    points, faces = head_with_a_face_over_lips()
    P = np.asarray(points, dtype=float)
    infl = [led_by(NAMES["head_g"]) for _ in points]

    out, lines = lips.bind(points, faces, infl, RIG)

    assert any("stretches apart" in line for line in lines), lines
    from kmdlswap import mouthsplit

    # The same box the code uses. Writing the factors out again here is how this
    # test drifted from `bind` once already: the weighting box and the split box
    # have to be the one box, or the test asserts about vertices the code never
    # touched.
    upper, lower = lips.find_lips(points, faces)[:2]
    box = mouthsplit._box(points, upper, lower)
    above, below = lips.mouth_region(points, faces, near=box)
    assert above and below

    lifts = {NAMES["f_um_g"]}
    drops = {NAMES["f_llm_g"], NAMES["f_rlm_g"], NAMES["f_jaw_g"]}

    # Near the centre line only. The rim's strength tapers toward the corners,
    # because a mouth is widest in the middle and closed at the ends - weighting
    # the whole seam alike opens it as a rectangle, which in game read as a
    # square mouth. So a corner vertex keeps most of what it had, by design.
    def central(v):
        return abs(P[v][0] - box[0]) < box[2] * 0.4

    middle_above = [v for v in above if central(v)]
    middle_below = [v for v in below if central(v)]
    assert middle_above and middle_below
    assert all(out[v][0].bone_slot in lifts for v in middle_above), "the upper lip does not lift"
    assert all(out[v][0].bone_slot in drops for v in middle_below), "the lower lip does not drop"


def test_the_mouth_tapers_toward_its_corners():
    """A mouth is a lens, not a rectangle."""
    points, faces = head_with_a_face_over_lips()
    P = np.asarray(points, dtype=float)
    infl = [led_by(NAMES["head_g"]) for _ in points]

    out, _ = lips.bind(points, faces, infl, RIG)

    from kmdlswap import mouthsplit

    upper, lower = lips.find_lips(points, faces)[:2]
    box = mouthsplit._box(points, upper, lower)
    above, below = lips.mouth_region(points, faces, near=box)

    def moved(v):
        return sum(f.weight for f in out[v] if f.bone_slot != NAMES["head_g"])

    centre = [moved(v) for v in above + below if abs(P[v][0] - box[0]) < box[2] * 0.3]
    corner = [moved(v) for v in above + below if abs(P[v][0] - box[0]) > box[2] * 0.8]
    assert centre and corner
    assert sum(centre) / len(centre) > sum(corner) / len(corner) * 2, (
        "the corners open as strongly as the centre; the mouth is a rectangle"
    )


def test_the_split_is_confined_to_the_mouth():
    """The regression that reached the game twice: anything that reaches past
    the mouth tears the face somewhere it should not."""
    points, faces = head_with_a_face_over_lips()
    P = np.asarray(points, dtype=float)
    from kmdlswap import mouthsplit

    # The same box the code uses. Writing the factors out again here is how this
    # test drifted from `bind` once already: the weighting box and the split box
    # have to be the one box, or the test asserts about vertices the code never
    # touched.
    upper, lower = lips.find_lips(points, faces)[:2]
    box = mouthsplit._box(points, upper, lower)
    above, below = lips.mouth_region(points, faces, near=box)
    mid_y = (P[:, 1].min() + P[:, 1].max()) / 2

    for v in above + below:
        assert P[v][1] > mid_y, "the back of the head was included"
        assert abs(P[v][0] - box[0]) <= box[2]
        assert abs(P[v][2] - box[1]) <= box[3]
