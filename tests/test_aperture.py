"""Cutting a mouth into a face that is a solid sheet across it.

The failure this fixes was reported as "the texture is glued shut", and the
texture was innocent: the face shell reached further forward than the lips, the
teeth, the tongue and the mouth bag combined, so none of them could ever be
seen. The tests here are mostly about restraint - cutting too much is a gaping
mouth on a resting face, and cutting a head that does not need it would wreck
every vanilla-style head the tool already handles.
"""

from __future__ import annotations

import numpy as np
import pytest

from kmdlswap import aperture
from test_lips import ring


def head_with_shell_over_lips():
    """A face shell that passes *in front of* its lip pieces.

    This is the arrangement that breaks: on `h_common01_` the shell reaches to
    y +0.1048 at the mouth while the lips sit at +0.1005 and +0.0962 and the
    interior further back still, so the shell hides all of it. A fixture whose
    shell sits behind the lips has nothing to cut and tests nothing.
    """
    points, faces = [], []

    def add(p, f):
        base = len(points)
        points.extend(p)
        faces.extend([(a + base, b + base, c + base) for a, b, c in f])

    # The shell: a plane across the face, in front of everything else.
    nx, nz = 16, 22
    grid = []
    for i in range(nx):
        for k in range(nz):
            grid.append((-0.15 + 0.30 * i / (nx - 1), 0.15, k / (nz - 1)))
    cells = []
    for i in range(nx - 1):
        for k in range(nz - 1):
            a = i * nz + k
            b = a + 1
            c = (i + 1) * nz + k
            d = c + 1
            cells.append((a, b, c))
            cells.append((b, d, c))
    add(grid, cells)

    add(*ring((0.0, 0.12, 0.38), n=6))              # upper lip, behind the shell
    add(*ring((0.0, 0.12, 0.35), n=6))              # lower lip
    add(*ring((0.0, 0.09, 0.36), width=0.05, n=6))  # interior, further back
    return points, faces


def test_a_head_with_separate_lips_gets_an_opening():
    points, faces = head_with_shell_over_lips()

    kept, lines = aperture.cut(points, faces)

    assert lines and "mouth opening" in lines[0]
    assert len(kept) < len(faces), "nothing was actually removed"


def test_a_head_whose_mouth_is_part_of_the_face_is_left_alone():
    """A KOTOR-built head has no lip pieces and needs no cut. Opening one would
    put a hole in a face that works."""
    points, faces = ring((0.0, 0.0, 0.5), width=0.3, height=1.0, n=64)

    kept, lines = aperture.cut(points, faces)

    assert kept is faces
    assert lines == []


def test_the_opening_is_a_slit_at_rest_not_a_hole():
    """Geometry does not close. Cutting the whole gap between the rims leaves
    the teeth showing on a resting face - rendered, it is a snarl. The default
    height is a quarter of the rims' separation for that reason."""
    assert aperture.SCALE_HEIGHT <= 0.3

    points, faces = head_with_shell_over_lips()
    small = aperture.find(points, faces, scale_height=0.25)
    large = aperture.find(points, faces, scale_height=1.0)

    assert small is not None and large is not None
    assert small[1] < large[1], "height is not actually controlling the cut"


def test_only_the_front_of_the_head_is_cut():
    """The back of the skull sits at the same x and z as the mouth. Without a
    depth test the cut goes straight through it.

    The threshold is the lip rims' own depth, not the mesh's: the shell has far
    more vertices than the lips, so a median over everything is just the shell
    and would compare it against itself."""
    from kmdlswap import lips

    points, faces = head_with_shell_over_lips()
    P = np.asarray(points, dtype=float)
    upper, lower, _ = lips.find_lips(points, faces)
    front = float(np.median(P[sorted(set(upper) | set(lower))][:, 1]))

    found = aperture.find(points, faces)
    assert found is not None
    kept = found[0]
    removed = [f for f in faces if f not in kept]

    assert removed
    for face in removed:
        centre = P[list(face)].mean(axis=0)
        assert centre[1] > front, f"a face at depth {centre[1]:+.3f} was cut from behind"


def test_the_lips_themselves_are_never_cut():
    """Only the shell is opened. Removing the lip pieces would take away the
    rim the opening is supposed to have."""
    from kmdlswap import lips

    points, faces = head_with_shell_over_lips()
    P = np.asarray(points, dtype=float)
    upper, lower, bag = lips.find_lips(points, faces)
    protected = set(upper) | set(lower) | set(bag or [])

    found = aperture.find(points, faces)
    kept = found[0]
    removed = [f for f in faces if f not in kept]

    for face in removed:
        assert not (set(face) & protected), "a lip or bag face was cut away"


def test_a_mesh_with_no_faces_is_refused_quietly():
    kept, lines = aperture.cut([(0.0, 0.0, 0.0)] * 8, [])
    assert kept == []
    assert lines == []


class TestAgainstTheGame:
    @staticmethod
    @pytest.fixture(scope="class")
    def jade_head():
        from pathlib import Path

        from kmdlfun import installs, jade

        path = installs.detect().get(installs.JADE)
        if not path:
            pytest.skip("no Jade Empire install detected")
        entry = next(
            (e for e in jade.catalogue(Path(path)) if e.resref.lower() == "h_common01_"),
            None,
        )
        if entry is None:
            pytest.skip("h_common01_ not present")
        mesh = jade.mesh(*jade.read(entry))
        return mesh.positions, [tuple(f)[:3] for f in mesh.faces]

    def test_the_real_head_is_opened(self, jade_head):
        positions, faces = jade_head
        kept, lines = aperture.cut(positions, faces)

        assert lines, "h_common01_ has separate lips and a solid shell; it must be cut"
        assert 0 < len(faces) - len(kept) < 60, "the cut should be a slit, not a hole"

    def test_a_vanilla_kotor_head_is_untouched(self):
        """The regression that would matter most: every head this tool already
        builds correctly must come through with its face intact."""
        from kmdlfun import installs, parts as kparts
        from kmdlfun.library import ModelLibrary
        from kmdlswap import edit as ke
        from kmdlswap import layout as kl
        from kmdlswap import mdx as kmdx

        path = installs.detect().get(installs.K1)
        if not path:
            pytest.skip("no K1 install detected")
        layout = kl.parse(*ModelLibrary(path).read("p_carthh"))
        node = next(n for n in kparts.mesh_nodes(layout) if n.name.lower() == "head")
        positions = kmdx.positions(layout, node)
        faces = [f.vertices for f in ke.extract(layout, node).faces]

        kept, lines = aperture.cut(positions, faces)

        assert kept is faces
        assert lines == []
