"""Milestone 3: replacing a mesh node's geometry from an OBJ."""

from __future__ import annotations

import struct

import pytest

from kmdlswap import edit as ke
from kmdlswap import layout as kl
from kmdlswap import obj as kobj
from kmdlswap import swap as ks
from kmdlswap import topology
from kmdlswap import validate as kv
from kmdlswap import weights as kw

F32 = struct.Struct("<f")


def as_f32(v: float) -> float:
    return F32.unpack(F32.pack(v))[0]


def f32_tuple(t):
    return tuple(as_f32(x) for x in t)


@pytest.fixture(scope="module")
def hk47_bytes(pair):
    return pair("p_hk47")


@pytest.fixture(scope="module")
def hk47(hk47_bytes):
    return kl.parse(*hk47_bytes)


def roundtrip_obj(layout, node, tmp_path):
    geo = ke.extract(layout, node)
    positions, faces, uvs, normals = ks.geometry_to_obj_arrays(geo)
    path = tmp_path / f"{node.name}.obj"
    kobj.write_obj(path, positions, faces, uvs, normals, name=node.name)
    return geo, kobj.read_obj(path)


# --- OBJ ---------------------------------------------------------------------


@pytest.mark.parametrize("node_name", ["head", "InnerTorso", "TorsoHoses"])
def test_obj_roundtrip_is_lossless_at_float32(hk47, tmp_path, node_name):
    """The format stores float32, so that is the precision that must survive."""
    node = hk47.node_by_name(node_name)
    geo, mesh = roundtrip_obj(hk47, node, tmp_path)

    assert mesh.vertex_count == geo.vertex_count
    assert [tuple(f) for f in mesh.faces] == [f.vertices for f in geo.faces]
    for a, b in zip(geo.positions, mesh.positions):
        assert f32_tuple(a) == f32_tuple(b)
    for a, b in zip(geo.columns["uv1"], mesh.uvs):
        assert f32_tuple(a) == f32_tuple(b)
    for a, b in zip(geo.columns["normal"], mesh.normals):
        assert f32_tuple(a) == f32_tuple(b)


def test_obj_welds_shared_vertex_references(tmp_path):
    p = tmp_path / "quad.obj"
    p.write_text(
        "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\n"
        "vt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\n"
        "f 1/1 2/2 3/3\nf 1/1 3/3 4/4\n"
    )
    mesh = kobj.read_obj(p)
    assert mesh.vertex_count == 4  # shared corners are welded, not duplicated
    assert mesh.faces == [(0, 1, 2), (0, 2, 3)]


def test_obj_triangulates_polygons(tmp_path):
    p = tmp_path / "poly.obj"
    p.write_text("v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nf 1 2 3 4\n")
    assert kobj.read_obj(p).faces == [(0, 1, 2), (0, 2, 3)]


def test_obj_rejects_out_of_range_index(tmp_path):
    p = tmp_path / "bad.obj"
    p.write_text("v 0 0 0\nv 1 0 0\nv 1 1 0\nf 1 2 9\n")
    with pytest.raises(kobj.ObjError, match="out of range"):
        kobj.read_obj(p)


# --- full swap ---------------------------------------------------------------


@pytest.mark.parametrize("node_name", ["head", "InnerTorso", "TorsoHoses"])
def test_obj_swap_reproduces_the_mdx_exactly(hk47, hk47_bytes, tmp_path, node_name):
    """extract -> OBJ -> replace must not move a single vertex, including the
    transferred skin weights of a skinned mesh."""
    _, mdx = hk47_bytes
    node = hk47.node_by_name(node_name)
    _, mesh = roundtrip_obj(hk47, node, tmp_path)
    geo, _ = ks.build_replacement(hk47, node, mesh)
    _, out_mdx = ke.replace_geometry(hk47, node, geo)
    assert out_mdx == mdx


def test_obj_swap_only_touches_the_target_nodes_face_array(hk47, hk47_bytes, tmp_path):
    """Face normals, plane coefficients and adjacency are recomputed, so the MDL
    does change - but only inside the node being replaced."""
    mdl, _ = hk47_bytes
    node = hk47.node_by_name("head")
    _, mesh = roundtrip_obj(hk47, node, tmp_path)
    geo, _ = ks.build_replacement(hk47, node, mesh)
    out_mdl, _ = ke.replace_geometry(hk47, node, geo)

    assert len(out_mdl) == len(mdl)
    spans = sorted(hk47.spans, key=lambda s: s.start)
    for i in range(len(mdl)):
        if mdl[i] == out_mdl[i]:
            continue
        span = next(s for s in spans if s.start <= i < s.end)
        assert span.kind == "face_array"
        assert span.owner == node.index


def test_swapped_model_validates(hk47, tmp_path):
    node = hk47.node_by_name("head")
    _, mesh = roundtrip_obj(hk47, node, tmp_path)
    geo, _ = ks.build_replacement(hk47, node, mesh)
    mdl, mdx = ke.replace_geometry(hk47, node, geo)
    assert kv.check(kl.parse(mdl, mdx)).ok


def test_swap_with_different_topology(hk47):
    """Genuinely new geometry, not a round trip: a coarse box in a skinned
    node's place. Weights must transfer onto topology sharing nothing with the
    original."""
    node = hk47.node_by_name("TorsoHoses")
    geo = ke.extract(hk47, node)
    xs = [p[0] for p in geo.positions]
    ys = [p[1] for p in geo.positions]
    zs = [p[2] for p in geo.positions]
    lo = (min(xs), min(ys), min(zs))
    hi = (max(xs), max(ys), max(zs))
    corners = [
        (lo[0], lo[1], lo[2]), (hi[0], lo[1], lo[2]),
        (hi[0], hi[1], lo[2]), (lo[0], hi[1], lo[2]),
        (lo[0], lo[1], hi[2]), (hi[0], lo[1], hi[2]),
        (hi[0], hi[1], hi[2]), (lo[0], hi[1], hi[2]),
    ]
    quads = [
        (0, 1, 2, 3), (5, 4, 7, 6), (4, 0, 3, 7),
        (1, 5, 6, 2), (3, 2, 6, 7), (4, 5, 1, 0),
    ]
    mesh = kobj.ObjMesh(name="box")
    for q in quads:
        base = len(mesh.positions)
        for c in q:
            mesh.positions.append(corners[c])
            mesh.uvs.append((0.0, 0.0))
        mesh.faces.append((base, base + 1, base + 2))
        mesh.faces.append((base, base + 2, base + 3))

    new_geo, report = ks.build_replacement(hk47, node, mesh)
    assert new_geo.vertex_count == 24
    assert report.new_triangles == 12
    assert report.max_influences >= 1
    assert not kw.check(new_geo.influences)

    mdl, mdx = ke.replace_geometry(hk47, node, new_geo)
    assert kv.check(kl.parse(mdl, mdx)).ok
    after = kl.parse(mdl, mdx)
    assert after.node_by_name("TorsoHoses").vertex_count == 24
    assert [n.name for n in after.nodes] == [n.name for n in hk47.nodes]


@pytest.mark.parametrize(
    ("model", "node_name", "column"),
    [
        ("c_bmspecdiff", "RLeg", "tangent"),
        ("crossgob", "Corner09", "uv2"),
    ],
)
def test_refuses_columns_it_cannot_author(pair, model, node_name, column):
    """A mesh needing tangent frames or a second UV set is refused, not
    zero-filled. Character models never carry these - only rooms and
    placeables do - but the refusal has to be real, not theoretical."""
    lay = kl.parse(*pair(model))
    node = lay.node_by_name(node_name)
    geo = ke.extract(lay, node)
    mesh = kobj.ObjMesh(
        positions=[tuple(p) for p in geo.positions],
        uvs=[(0.0, 0.0)] * geo.vertex_count,
        faces=[f.vertices for f in geo.faces],
    )
    with pytest.raises(ValueError, match="cannot author") as exc:
        ks.build_replacement(lay, node, mesh)
    assert column in str(exc.value)


# --- weights -----------------------------------------------------------------


def test_weight_transfer_reproduces_source_weights(hk47):
    """Transferring a mesh's weights onto its own vertices must return them."""
    node = hk47.node_by_name("TorsoHoses")
    geo = ke.extract(hk47, node)
    got = kw.transfer(
        geo.positions, [f.vertices for f in geo.faces], geo.influences, geo.positions
    )
    assert not kw.check(got)
    for original, new in zip(geo.influences, got):
        a = {i.bone_slot: i.weight for i in original}
        b = {i.bone_slot: i.weight for i in new}
        assert set(a) == set(b)
        for slot in a:
            assert abs(a[slot] - b[slot]) < 1e-4


@pytest.mark.parametrize("cap", [1, 2, 3, 4])
def test_weight_transfer_respects_the_influence_cap(hk47, cap):
    node = hk47.node_by_name("TorsoHoses")
    geo = ke.extract(hk47, node)
    got = kw.transfer(
        geo.positions, [f.vertices for f in geo.faces], geo.influences, geo.positions,
        max_influences=cap,
    )
    assert max(len(i) for i in got) <= cap
    assert not kw.check(got)  # still normalised after truncation


def test_weight_transfer_rejects_impossible_caps(hk47):
    node = hk47.node_by_name("TorsoHoses")
    geo = ke.extract(hk47, node)
    with pytest.raises(ValueError, match="max_influences"):
        kw.transfer(
            geo.positions, [f.vertices for f in geo.faces], geo.influences, geo.positions,
            max_influences=8,
        )


# --- adjacency ---------------------------------------------------------------


def test_rebuilt_adjacency_is_always_in_range(hk47):
    for node in hk47.nodes:
        if not node.is_mesh or not node.vertex_count or node.in_animation is not None:
            continue
        if "saber" in node.flags:
            continue
        geo = ke.extract(hk47, node)
        if not geo.faces:
            continue
        adj = topology.build_adjacency([f.vertices for f in geo.faces], geo.positions)
        assert not topology.check_adjacency(adj, len(geo.faces))


def test_rebuilt_adjacency_mostly_matches_vanilla(hk47):
    """We recover vanilla's convention but not its exact weld tolerance."""
    total = matched = 0
    for node in hk47.nodes:
        if not node.is_mesh or not node.vertex_count or node.in_animation is not None:
            continue
        if "saber" in node.flags:
            continue
        geo = ke.extract(hk47, node)
        if not geo.faces:
            continue
        adj = topology.build_adjacency([f.vertices for f in geo.faces], geo.positions)
        total += len(geo.faces)
        matched += sum(1 for f, a in zip(geo.faces, adj) if f.adjacent == a)
    assert matched / total > 0.95


def test_capping_discards_only_the_weakest_influences(hk47):
    """A cap keeps the strongest influences and renormalises what remains."""
    node = hk47.node_by_name("TorsoHoses")
    geo = ke.extract(hk47, node)
    full = kw.transfer(
        geo.positions, [f.vertices for f in geo.faces], geo.influences, geo.positions
    )
    capped = kw.transfer(
        geo.positions, [f.vertices for f in geo.faces], geo.influences, geo.positions,
        max_influences=1,
    )
    for a, b in zip(full, capped):
        assert len(b) == 1
        assert b[0].weight == pytest.approx(1.0)
        # The surviving bone is the one that was strongest before capping.
        assert b[0].bone_slot == max(a, key=lambda x: x.weight).bone_slot
