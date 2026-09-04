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


def test_the_pieces_behind_the_face_follow_the_shell():
    """They inherit from the face in front of them rather than from an ideal
    profile.

    Giving them the idealised lip weights made them swing on the jaw pivot far
    harder than the shell they sit behind, and in game the interior sailed out
    through the opening as a flat slab. A piece tucked behind a lip has to move
    with that lip, whatever it happens to be doing.
    """
    points, faces = head_with_separate_lips()
    shell = set(lips.islands(np.asarray(points, dtype=float), faces)[0])
    # The shell is led by one bone, the pieces behind it by another. If they
    # follow, the pieces end up on the shell's.
    infl = [
        led_by(NAMES["f_jaw_g"]) if i in shell else led_by(NAMES["head_g"])
        for i in range(len(points))
    ]

    out, lines = lips.bind(points, faces, infl, RIG)

    assert lines and "follow the shell" in lines[0]
    upper, lower, bag = lips.find_lips(points, faces)
    for v in list(upper) + list(lower) + list(bag or []):
        assert out[v][0].bone_slot == NAMES["f_jaw_g"], (
            "a piece behind the face kept its own weights instead of the shell's"
        )


def test_a_piece_behind_the_face_never_moves_on_its_own():
    """Whatever the shell does, the piece behind it does the same. Any
    divergence shows in game as the interior separating from the mouth."""
    points, faces = head_with_separate_lips()
    P = np.asarray(points, dtype=float)
    shell = np.asarray(lips.islands(P, faces)[0], dtype=int)
    infl = [led_by(NAMES["head_g"]) for _ in points]
    for i in shell:
        infl[i] = [Influence(NAMES["f_um_g"], 0.6), Influence(NAMES["f_lmc_g"], 0.4)]

    out, _ = lips.bind(points, faces, infl, RIG)

    upper, lower, bag = lips.find_lips(points, faces)
    for v in list(upper) + list(lower) + list(bag or []):
        d = P[shell] - P[v]
        nearest = int(shell[np.argmin(np.einsum("ij,ij->i", d, d))])
        assert {(f.bone_slot, round(f.weight, 6)) for f in out[v]} == {
            (f.bone_slot, round(f.weight, 6)) for f in out[nearest]
        }


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


# --- an aperture closed to zero width ---------------------------------------
#
# The failure that survived four passes. Jade Empire models a mouth as a hole
# whose two rims sit on the same coordinates, so every analysis that welds by
# position - which is all of them, because welding is what stops a UV seam
# looking like a hole - reports a solid face. Worse, `weights.transfer` samples
# the host by position, so it hands both rims identical weights by construction
# and they can never part.


def head_with_a_zero_width_mouth():
    """Two surfaces meeting along a line of doubled vertices, front and back.

    Above the line the faces belong to one copy, below it to the other. In
    space they touch; in topology they are two boundaries.

    There is a second such line at the *back*, because that is the shape of the
    bug this fixture exists for: Jade heads carry a coincident seam running
    right around the skull at jaw height, indistinguishable from a lip rim by
    the above/below test alone. Binding it apart split the head open along a
    line that went all the way round.
    """
    points, faces = [], []
    n = 9
    xs = [-0.1 + 0.2 * i / (n - 1) for i in range(n)]

    def strip(y, z0, z1):
        base = len(points)
        for x in xs:
            points.append((x, y, z0))
            points.append((x, y, z1))
        for i in range(n - 1):
            a, b = base + 2 * i, base + 2 * i + 1
            c, d = base + 2 * (i + 1), base + 2 * (i + 1) + 1
            faces.append((a, b, c))
            faces.append((b, d, c))

    strip(0.1, 0.36, 0.50)    # the mouth: above the line, ending on it
    strip(0.1, 0.36, 0.22)    # the mouth: below it, on the same line
    strip(-0.1, 0.36, 0.50)   # the skull seam, at the back, same height
    strip(-0.1, 0.36, 0.22)
    return points, faces


MOUTH_BOX = (0.0, 0.36, 0.12, 0.02)   # centre_x, centre_z, half_x, half_z


def test_a_zero_width_aperture_is_found():
    points, faces = head_with_a_zero_width_mouth()

    upper, lower = lips.split_rims(points, faces, band=(0.0, 1.0), near=MOUTH_BOX)

    assert upper and lower, "the doubled mouth line was not detected"
    assert set(upper).isdisjoint(lower)


def test_a_plain_uv_seam_is_not_mistaken_for_one():
    """A seam has all its copies on the same side of the line. Binding one
    apart would tear the face open along a texture boundary."""
    points, faces = head_with_a_zero_width_mouth()
    # Duplicate every vertex in place without giving the copies any faces:
    # coincident, but not a rim pair.
    points = list(points) + list(points)

    upper, lower = lips.split_rims(points, faces, band=(0.0, 1.0), near=MOUTH_BOX)

    for v in list(upper) + list(lower):
        assert v < len(points) // 2, "a face-less duplicate was treated as a rim"


def test_a_seam_away_from_the_mouth_is_left_alone():
    """The regression that reached the game: a coincident seam runs around the
    skull at the same height as the mouth, and binding it apart tore the head
    open along it. In the build that shipped, 103 vertices were bound, spanning
    x +-0.068 against a head half-width of 0.085 and reaching from the back of
    the head to the front. The mouth is x +-0.023."""
    points, faces = head_with_a_zero_width_mouth()
    P = np.asarray(points, dtype=float)
    mid_y = (P[:, 1].min() + P[:, 1].max()) / 2

    upper, lower = lips.split_rims(points, faces, band=(0.0, 1.0), near=MOUTH_BOX)

    assert upper and lower, "the mouth itself must still be found"
    for v in list(upper) + list(lower):
        assert P[v][1] > mid_y, f"vertex at y={P[v][1]:+.3f} is on the back of the head"


def test_without_somewhere_to_aim_nothing_is_bound():
    """`near` is required. The above/below test alone cannot tell a lip rim
    from any other coincident seam, so with no mouth to aim at this returns
    nothing rather than guessing."""
    points, faces = head_with_a_zero_width_mouth()

    assert lips.split_rims(points, faces, band=(0.0, 1.0)) == ([], [])


def head_with_lips_and_a_seam():
    """Lip pieces *and* a zero-width aperture, which is what a real one has.

    `bind` locates the mouth from the lip pieces and only then looks for a
    seam, so both have to be present for the path to run at all.
    """
    points, faces = head_with_separate_lips()

    n = 7
    xs = [-0.02 + 0.04 * i / (n - 1) for i in range(n)]

    def strip(z0, z1):
        base = len(points)
        for x in xs:
            points.append((x, 0.13, z0))
            points.append((x, 0.13, z1))
        for i in range(n - 1):
            a, b = base + 2 * i, base + 2 * i + 1
            c, d = base + 2 * (i + 1), base + 2 * (i + 1) + 1
            faces.append((a, b, c))
            faces.append((b, d, c))

    strip(0.365, 0.40)   # above the mouth line, ending on it
    strip(0.365, 0.33)   # below it, on the same line
    return points, faces


def test_the_two_rims_are_bound_to_bones_that_pull_them_apart():
    """The whole point: at the same position, proximity transfer gives both
    rims the same weights, so the mouth cannot open however it is animated."""
    points, faces = head_with_lips_and_a_seam()
    infl = [led_by(NAMES["head_g"]) for _ in points]

    out, lines = lips.bind(points, faces, infl, RIG)

    assert any("mouth seam" in line for line in lines), lines
    P = np.asarray(points, dtype=float)
    rim = P[sorted(set(lips.find_lips(points, faces)[0]) | set(lips.find_lips(points, faces)[1]))]
    box = (
        float(rim[:, 0].min() + rim[:, 0].max()) / 2,
        float(rim[:, 2].min() + rim[:, 2].max()) / 2,
        float(rim[:, 0].max() - rim[:, 0].min()) / 2 * 1.6,
        float(rim[:, 2].max() - rim[:, 2].min()) / 2 * 2.0,
    )
    upper, lower = lips.split_rims(points, faces, near=box)
    assert upper and lower
    ups = {out[v][0].bone_slot for v in upper}
    downs = {out[v][0].bone_slot for v in lower}
    assert ups != downs, "both rims still lead with the same bone"
