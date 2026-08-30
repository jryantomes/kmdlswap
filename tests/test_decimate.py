"""Decimation must not break what the acceptance criteria check for.

That is the whole reason for choosing edge collapse: it cannot disconnect a
mesh, and on a closed surface it cannot open one. A mesh that passed `one piece`
and `closed` before must still pass after, however far it is reduced.
"""

from __future__ import annotations

import pytest

from kmdlfun import decimate, headgen, headspec
from kmdlswap import edit as ke
from kmdlswap import layout as kl
from kmdlswap import obj as kobj


def dense_head(rings=40, segments=60):
    dirs, faces, uvs = headgen.uv_sphere(rings, segments)
    m = kobj.ObjMesh(name="dense")
    m.positions = [headgen.shape(d) for d in dirs]
    m.faces = faces
    m.uvs = uvs
    return m


@pytest.fixture(scope="module")
def reduced():
    return decimate.simplify(dense_head(), 700)


def test_it_hits_the_budget(reduced):
    assert reduced.before > 4000
    assert reduced.after <= 700


def test_it_stays_one_piece_and_closed(reduced):
    """The property that makes edge collapse the right operation."""
    components, share, degenerate, boundary, _ = headspec.topology(reduced.mesh)
    assert components == 1
    assert boundary == 0, "a closed mesh must stay closed"
    assert degenerate == 0


def test_the_result_is_accepted_by_the_spec(reduced):
    v = headspec.check_mesh(reduced.mesh)
    assert v.accepted, [str(f) for f in v.failures]


def test_it_keeps_the_silhouette(reduced):
    """Quadric error simplifies flat regions first, so the overall shape should
    barely move even at a 15x reduction."""
    before = dense_head()

    def box(m):
        lo = [min(p[i] for p in m.positions) for i in range(3)]
        hi = [max(p[i] for p in m.positions) for i in range(3)]
        return [hi[i] - lo[i] for i in range(3)]

    b, a = box(before), box(reduced.mesh)
    for i in range(3):
        assert abs(a[i] - b[i]) / b[i] < 0.06, f"axis {i} moved {b[i]:.3f} -> {a[i]:.3f}"


def test_uvs_are_resampled_onto_the_survivors(reduced):
    assert len(reduced.mesh.uvs) == len(reduced.mesh.positions)
    assert all(0.0 - 1e-6 <= u <= 1.0 + 1e-6 for uv in reduced.mesh.uvs for u in uv)


def test_normals_are_recomputed(reduced):
    assert len(reduced.mesh.normals) == len(reduced.mesh.positions)
    for n in reduced.mesh.normals:
        assert abs(sum(c * c for c in n) ** 0.5 - 1.0) < 1e-6


def test_bad_collapses_are_refused(reduced):
    """Face flips are what produce the pinched dark creases in bad automatic
    reductions, so the guard should actually be firing."""
    assert reduced.refused_flip > 0


def test_a_mesh_already_under_budget_is_left_alone():
    m = dense_head(rings=8, segments=10)
    result = decimate.simplify(m, 5000)
    assert result.after == result.before
    assert result.collapses == 0
    assert result.mesh is m


def test_it_works_on_a_vanilla_head(pair):
    """Real data, not just a generated sphere."""
    layout = kl.parse(*pair("p_carthh"))
    node = layout.node_by_name("Head")
    geo = ke.extract(layout, node)
    m = kobj.ObjMesh(name="Head")
    m.positions = [tuple(p) for p in geo.positions]
    m.faces = [f.vertices for f in geo.faces]
    m.uvs = [tuple(u) for u in geo.columns["uv1"]]

    result = decimate.simplify(m, 300)
    assert result.after <= 300
    components, _, degenerate, _, _ = headspec.topology(result.mesh)
    assert components == 1
    assert degenerate == 0


def test_welding_merges_split_seams():
    """OBJ vertices split at a UV seam share a position; decimating them
    independently would tear the mesh apart along that seam."""
    m = kobj.ObjMesh(name="seam")
    m.positions = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 0)]  # 0 and 3 coincide
    m.faces = [(0, 1, 2), (3, 2, 1)]
    unique, mapping = decimate._weld(m.positions)
    assert len(unique) == 3
    assert mapping[0] == mapping[3]
