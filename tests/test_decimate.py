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
def seamed_mesh():
    """A sphere whose UVs are split into per-face islands, like a
    photogrammetry atlas. Every corner gets its own UV, so nothing may be
    shared across a face boundary."""
    m = dense_head(rings=24, segments=36)
    seamed = kobj.ObjMesh(name="seamed")
    for i, (a, b, c) in enumerate(m.faces):
        base = len(seamed.positions)
        for v in (a, b, c):
            seamed.positions.append(m.positions[v])
        # A small distinct island per face, tiled across the atlas.
        u = (i % 32) / 32.0
        w = ((i // 32) % 32) / 32.0
        seamed.uvs.extend([(u, w), (u + 0.02, w), (u, w + 0.02)])
        seamed.faces.append((base, base + 1, base + 2))
    return seamed


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


def test_uvs_are_present_and_in_range(reduced):
    assert len(reduced.mesh.uvs) == len(reduced.mesh.positions)
    assert all(0.0 - 1e-6 <= u <= 1.0 + 1e-6 for uv in reduced.mesh.uvs for u in uv)


def uv_outlier_fraction(mesh):
    """How many faces have a UV area wildly out of step with their 3D area.

    Coherent UVs give a tight distribution. UVs that jump across an atlas - a
    seam crossed by mistake - give a long tail, which is what a scrambled
    texture looks like numerically.
    """
    import statistics

    ratios = []
    for a, b, c in mesh.faces:
        p0, p1, p2 = (mesh.positions[i] for i in (a, b, c))
        u0, u1, u2 = (mesh.uvs[i] for i in (a, b, c))
        e1 = [p1[i] - p0[i] for i in range(3)]
        e2 = [p2[i] - p0[i] for i in range(3)]
        n = (e1[1] * e2[2] - e1[2] * e2[1],
             e1[2] * e2[0] - e1[0] * e2[2],
             e1[0] * e2[1] - e1[1] * e2[0])
        area3 = 0.5 * sum(x * x for x in n) ** 0.5
        area2 = 0.5 * abs((u1[0] - u0[0]) * (u2[1] - u0[1])
                          - (u2[0] - u0[0]) * (u1[1] - u0[1]))
        if area3 > 1e-12:
            ratios.append(area2 / area3)
    median = statistics.median(ratios)
    return sum(1 for r in ratios if r > median * 20) / len(ratios)


def test_uvs_do_not_cross_seams(seamed_mesh):
    """The test that would have caught the real bug.

    Resampling UVs by closest point ignores seams, and a photogrammetry atlas is
    mostly seam - one face in five came out with a UV area twenty times the
    median, and the texture rendered as concentric garbage. Checking that UVs
    merely exist and lie in [0, 1] could never have seen it.
    """
    before = uv_outlier_fraction(seamed_mesh)
    after = uv_outlier_fraction(decimate.simplify(seamed_mesh, 400).mesh)
    assert after < before + 0.03, (
        f"UV coherence collapsed: {before:.1%} of faces were outliers before, "
        f"{after:.1%} after"
    )


def test_seams_are_split_back_out(seamed_mesh):
    """A position whose corners carry different UVs must become several
    vertices again, or the seam is gone."""
    result = decimate.simplify(seamed_mesh, 400)
    unique_positions = {tuple(round(c, 6) for c in p) for p in result.mesh.positions}
    assert len(result.mesh.positions) > len(unique_positions), "no seam survived"


def test_shading_stays_smooth_across_a_seam(seamed_mesh):
    """Splitting at seams must not split the *normals* too, or the mesh shades
    faceted along every seam - which on this kind of atlas is most of it."""
    result = decimate.simplify(seamed_mesh, 400)
    by_position: dict = {}
    for p, n in zip(result.mesh.positions, result.mesh.normals):
        by_position.setdefault(tuple(round(c, 6) for c in p), []).append(n)
    shared = [ns for ns in by_position.values() if len(ns) > 1]
    assert shared, "no split positions to check"
    for ns in shared:
        for other in ns[1:]:
            assert all(abs(a - b) < 1e-9 for a, b in zip(ns[0], other)), (
                "vertices sharing a position disagree on their normal"
            )


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
