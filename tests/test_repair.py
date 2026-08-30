"""Making a foreign mesh usable: consistent winding, and cropping a bust.

Both exist because of real inputs. A scanned head arrived with 22.5% of its
faces wound against their neighbours - invisible in any two-sided viewer, holes
in game. The same file was a bust, 1.9 tall against 1.07 wide, nearly all hair.
"""

from __future__ import annotations

import pytest

from kmdlfun import repair
from kmdlswap.obj import ObjMesh


def box(scale=1.0):
    """A closed cube, wound consistently outward."""
    corners = [
        (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
        (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1),
    ]
    quads = [
        (0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
        (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
    ]
    m = ObjMesh(name="box")
    m.positions = [tuple(c * scale for c in p) for p in corners]
    m.uvs = [(0.0, 0.0)] * 8
    for q in quads:
        m.faces.append((q[0], q[1], q[2]))
        m.faces.append((q[0], q[2], q[3]))
    return m


def disagreeing(mesh) -> int:
    """Face pairs sharing an edge that traverse it the same way round."""
    from collections import defaultdict

    seen = defaultdict(int)
    for f in mesh.faces:
        for k in range(3):
            seen[(f[k], f[(k + 1) % 3])] += 1
    return sum(1 for count in seen.values() if count > 1)


# --- winding ------------------------------------------------------------------


def test_an_already_consistent_mesh_is_left_alone():
    fixed, flipped = repair.unify_winding(box())
    assert flipped == 0
    assert fixed.faces == box().faces


def test_mixed_winding_is_made_consistent():
    m = box()
    m.faces = [f if i % 3 else (f[0], f[2], f[1]) for i, f in enumerate(m.faces)]
    assert disagreeing(m) > 0, "the fixture is not actually inconsistent"

    fixed, flipped = repair.unify_winding(m)
    assert flipped > 0
    assert disagreeing(fixed) == 0


def test_a_wholly_inside_out_mesh_is_turned_outward():
    """Consistent is not enough - a mesh can be uniformly inside out, which no
    edge-by-edge check can see."""
    m = box()
    m.faces = [(f[0], f[2], f[1]) for f in m.faces]
    assert repair.signed_volume(m.positions, m.faces) < 0

    fixed, _ = repair.unify_winding(m)
    assert repair.signed_volume(fixed.positions, fixed.faces) > 0


def test_an_OPEN_mesh_that_is_inside_out_is_still_turned_outward():
    """The case that put a hollow head in game.

    Cropping a bust opens the mesh along the cut. The old test for "is this
    inside out" was the signed volume, which only means anything on a closed
    surface, so a cropped head could be judged fine while being entirely
    inverted - and in game the front faces are culled and you see straight
    through to the inside of the back of the skull.
    """
    m, _ = repair.crop_below(box(), 0.5, axis=2)
    assert any(
        len([f for f in m.faces if v in f]) for v in range(len(m.positions))
    ), "fixture is empty"
    m.faces = [(f[0], f[2], f[1]) for f in m.faces]        # turn it inside out
    assert repair.outward_fraction(m.positions, m.faces) < 0.5

    fixed, _ = repair.unify_winding(m)
    assert repair.outward_fraction(fixed.positions, fixed.faces) > 0.5


def test_outward_fraction_is_area_weighted():
    """A swarm of tiny crumpled faces must not outvote the skull."""
    m = box()
    big = repair.outward_fraction(m.positions, m.faces)
    assert big > 0.99

    # Many tiny inward-facing faces, scattered symmetrically so they do not move
    # the centre. By count they swamp the box ten to one; by area they are dust.
    import math

    tiny = ObjMesh(name="tiny")
    tiny.positions = list(m.positions)
    tiny.faces = list(m.faces)
    base = len(tiny.positions)
    for i in range(200):
        a = 2.0 * math.pi * i / 200.0
        cx, cy = 0.3 * math.cos(a), 0.3 * math.sin(a)
        tiny.positions.extend([(cx, cy, 0.0), (cx + 1e-3, cy, 0.0), (cx, cy + 1e-3, 0.0)])
        tiny.faces.append((base, base + 2, base + 1))
        base += 3

    assert len(tiny.faces) > len(m.faces) * 10, "the fixture must dominate by count"
    assert repair.outward_fraction(tiny.positions, tiny.faces) > 0.9


def test_seam_split_vertices_do_not_stop_the_walk():
    """Positions are welded first. Without that, a mesh split at UV seams has no
    shared indices there and the walk stops at every seam."""
    m = box()
    split = ObjMesh(name="split")
    for f in m.faces:                      # every corner its own vertex
        base = len(split.positions)
        for v in f:
            split.positions.append(m.positions[v])
            split.uvs.append((0.0, 0.0))
        split.faces.append((base, base + 1, base + 2))
    split.faces = [
        f if i % 2 else (f[0], f[2], f[1]) for i, f in enumerate(split.faces)
    ]

    fixed, flipped = repair.unify_winding(split)
    assert flipped > 0
    assert repair.signed_volume(fixed.positions, fixed.faces) > 0


def test_normals_come_back_smooth_across_shared_positions():
    m = box()
    fixed, _ = repair.unify_winding(m)
    assert len(fixed.normals) == len(fixed.positions)
    for n in fixed.normals:
        assert sum(c * c for c in n) == pytest.approx(1.0, abs=1e-6)


# --- cropping -----------------------------------------------------------------


def test_crop_removes_the_lower_part_and_renumbers():
    m = box()
    cropped, cut = repair.crop_below(m, 0.5, axis=2)
    assert cut > 0
    assert all(max(cropped.positions[v][2] for v in f) >= 0.0 for f in cropped.faces)
    # Indices must be rebased, not left pointing at the original array.
    assert cropped.faces
    assert max(max(f) for f in cropped.faces) < len(cropped.positions)
    assert len(cropped.uvs) == len(cropped.positions)


def test_cropping_nothing_changes_nothing():
    m = box()
    cropped, cut = repair.crop_below(m, 0.0, axis=2)
    assert cut == 0
    assert cropped is m


def test_a_face_straddling_the_cut_is_kept():
    """Keeping only faces wholly above would saw through the surface and leave a
    ragged edge; keeping any face that reaches above the line cuts cleanly."""
    m = ObjMesh(name="strip")
    m.positions = [(0, 0, -1.0), (1, 0, -1.0), (0, 0, 1.0), (1, 0, 1.0)]
    m.faces = [(0, 1, 2), (1, 3, 2)]
    cropped, cut = repair.crop_below(m, 0.9, axis=2)
    assert cut == 0, "both faces reach above the line, so both stay"
