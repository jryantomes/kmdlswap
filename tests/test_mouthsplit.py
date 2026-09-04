"""Cutting a lip line onto a face that has no line to split along.

Splitting only at existing vertices gave twelve points across the whole mouth,
and twelve points on coarse geometry open into a row of triangles rather than a
mouth - reported from the game as "two little triangles you can see through to
the teeth", visible only while talking, which is what an opening seam of twelve
points looks like.
"""

from __future__ import annotations

import numpy as np
import pytest

from kmdlswap import mouthsplit
from kmdlswap.obj import ObjMesh


def slab(nx=9, nz=9):
    """Two planes in x/z - a front and a back.

    Both are needed. The cut only takes points on the front half of the head,
    so a mesh at a single depth has its own midpoint for a midline and every
    candidate is rejected. A flat fixture tests nothing here.
    """
    mesh = ObjMesh(name="slab")

    def plane(y):
        base = len(mesh.positions)
        for i in range(nx):
            for k in range(nz):
                mesh.positions.append((-0.1 + 0.2 * i / (nx - 1), y, k / (nz - 1)))
                mesh.uvs.append((i / (nx - 1), k / (nz - 1)))
        for i in range(nx - 1):
            for k in range(nz - 1):
                a = base + i * nz + k
                mesh.faces.append((a, a + 1, base + (i + 1) * nz + k))
                mesh.faces.append(
                    (a + 1, base + (i + 1) * nz + k + 1, base + (i + 1) * nz + k)
                )

    plane(0.1)
    plane(-0.1)
    return mesh


# centre_x, centre_z, half_x, half_z. The line sits *between* two rows of the
# slab on purpose: at z = 0.5 the slab has a row of vertices exactly on it, so
# edges end on the line rather than crossing it and there is nothing to cut.
BOX = (0.0, 0.44, 0.08, 0.2)


def test_points_land_exactly_on_the_line():
    mesh = slab()
    added = mouthsplit.cut_along_line(mesh, BOX)

    assert added > 0
    P = np.asarray(mesh.positions, dtype=float)
    new = P[-added:]
    assert np.allclose(new[:, 2], BOX[1], atol=1e-9), "a cut point is off the line"


def test_the_line_gets_more_points_than_the_mesh_had():
    """The whole reason for cutting: the seam has to be dense enough to read as
    a mouth rather than as a row of triangles."""
    mesh = slab()
    before = sum(1 for p in mesh.positions if abs(p[2] - BOX[1]) < 1e-9)
    mouthsplit.cut_along_line(mesh, BOX)
    after = sum(1 for p in mesh.positions if abs(p[2] - BOX[1]) < 1e-9)

    assert after > before


def test_nothing_is_left_with_a_t_junction():
    """Cutting by face rather than by edge leaves a cut face meeting an uncut
    neighbour, and a T-junction is a crack. Every edge is used by one or two
    faces and never by a face that ignored the subdivision."""
    mesh = slab()
    mouthsplit.cut_along_line(mesh, BOX)

    import collections

    edges = collections.Counter()
    for a, b, c in mesh.faces:
        for u, v in ((a, b), (b, c), (c, a)):
            edges[frozenset((u, v))] += 1
    assert all(n <= 2 for n in edges.values()), "an edge is shared by three faces"

    P = np.asarray(mesh.positions, dtype=float)
    on_line = {i for i, p in enumerate(P) if abs(p[2] - BOX[1]) < 1e-9}
    for a, b, c in mesh.faces:
        for u, v in ((a, b), (b, c), (c, a)):
            # No edge may straddle the line while a cut point sits on it: that
            # is the T-junction this is guarding against.
            if (P[u][2] - BOX[1]) * (P[v][2] - BOX[1]) >= 0:
                continue
            if abs(P[u][0] - BOX[0]) > BOX[2] or abs(P[v][0] - BOX[0]) > BOX[2]:
                continue
            mid_x = (P[u][0] + P[v][0]) / 2
            near = [
                i for i in on_line
                if abs(P[i][0] - mid_x) < 1e-6 and P[i][1] == pytest.approx(P[u][1])
            ]
            assert not near, "an uncut edge crosses the line where a point exists"


def test_a_face_keeps_its_area():
    """Retriangulation must cover exactly what it replaced. A dropped sliver is
    a hole in the face; an overlapping one z-fights."""
    mesh = slab()
    P0 = np.asarray(mesh.positions, dtype=float)
    before = sum(
        float(np.linalg.norm(np.cross(P0[b] - P0[a], P0[c] - P0[a]))) / 2
        for a, b, c in mesh.faces
    )
    mouthsplit.cut_along_line(mesh, BOX)
    P1 = np.asarray(mesh.positions, dtype=float)
    after = sum(
        float(np.linalg.norm(np.cross(P1[b] - P1[a], P1[c] - P1[a]))) / 2
        for a, b, c in mesh.faces
    )

    assert after == pytest.approx(before, rel=1e-6)


def test_uvs_are_interpolated_not_invented():
    """A cut point sits partway along an edge and its UV has to sit the same way
    along that edge's UVs, or the texture tears at the mouth."""
    mesh = slab()
    added = mouthsplit.cut_along_line(mesh, BOX)

    P = np.asarray(mesh.positions, dtype=float)
    UV = np.asarray(mesh.uvs, dtype=float)
    assert len(UV) == len(P)
    # On this slab v runs with z, so a point on the line has the line's v.
    for i in range(len(P) - added, len(P)):
        assert UV[i][1] == pytest.approx(BOX[1], abs=1e-6)


def test_a_mesh_with_nothing_crossing_is_untouched():
    mesh = slab()
    before = (len(mesh.positions), len(mesh.faces))

    assert mouthsplit.cut_along_line(mesh, (0.0, 5.0, 0.08, 0.2)) == 0
    assert (len(mesh.positions), len(mesh.faces)) == before
