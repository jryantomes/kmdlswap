"""Milestone 2: the rewrite mechanism.

Two halves. The no-op swap proves extraction and rebuild are faithful (all
deltas zero, output must be byte-identical). The resize tests prove the splice
and offset-fixup logic, which a no-op never exercises.
"""

from __future__ import annotations

import struct

import pytest

from kmdlswap import edit as ke
from kmdlswap import layout as kl
from kmdlswap import validate as kv
from kmdlswap.rewrite import RewriteError


@pytest.fixture(scope="module")
def hk47_bytes(pair):
    return pair("p_hk47")


@pytest.fixture(scope="module")
def hk47(hk47_bytes):
    return kl.parse(*hk47_bytes)


# --- no-op ------------------------------------------------------------------


@pytest.mark.parametrize("node_name", ["head", "InnerTorso", "TorsoHoses", "L_hand"])
def test_noop_swap_is_byte_identical(hk47, hk47_bytes, node_name):
    mdl, mdx = hk47_bytes
    node = hk47.node_by_name(node_name)
    out_mdl, out_mdx = ke.replace_geometry(hk47, node, ke.extract(hk47, node))
    assert out_mdl == mdl
    assert out_mdx == mdx


def test_noop_swap_across_every_mesh_in_the_model(hk47, hk47_bytes):
    mdl, mdx = hk47_bytes
    meshes = [n for n in hk47.nodes if n.is_mesh and n.in_animation is None and n.vertex_count]
    assert len(meshes) > 20
    for node in meshes:
        out_mdl, out_mdx = ke.replace_geometry(hk47, node, ke.extract(hk47, node))
        assert (out_mdl, out_mdx) == (mdl, mdx), f"{node.name} did not round-trip"


def test_saber_blades_are_refused_not_mangled(pair):
    lay = kl.parse(*pair("w_lghtsbr_001"))
    saber = next(n for n in lay.nodes if "saber" in n.flags)
    with pytest.raises(ValueError, match="saber"):
        ke.extract(lay, saber)


# --- resize -----------------------------------------------------------------


def _drop_last_vertices(geo: ke.MeshGeometry, drop: int) -> ke.MeshGeometry:
    """Shrink a mesh by removing trailing vertices and any face using them."""
    keep = geo.vertex_count - drop
    smaller = ke.MeshGeometry(
        vertex_count=keep,
        columns={k: v[:keep] for k, v in geo.columns.items()},
        influences=geo.influences[:keep],
        faces=[f for f in geo.faces if max(f.vertices) < keep],
        trailing=geo.trailing,
    )
    return smaller


def test_shrinking_a_mesh_produces_a_valid_smaller_model(hk47, hk47_bytes):
    mdl, mdx = hk47_bytes
    node = hk47.node_by_name("head")
    geo = ke.extract(hk47, node)
    smaller = _drop_last_vertices(geo, 40)
    assert smaller.triangle_count < geo.triangle_count

    out_mdl, out_mdx = ke.replace_geometry(hk47, node, smaller)
    assert len(out_mdl) < len(mdl)
    assert len(out_mdx) < len(mdx)

    # The result must parse, cover every byte, and resolve every pointer - the
    # splice is only correct if the offsets it rewrote all still land properly.
    rep = kv.check(kl.parse(out_mdl, out_mdx))
    assert not rep.gaps, f"{len(rep.gaps)} gaps, {rep.gap_bytes} bytes"
    assert not rep.overlaps
    assert not rep.dangling, rep.dangling[:3]
    assert rep.identity_mdl and rep.identity_mdx


def test_shrink_updates_counts_and_leaves_other_nodes_alone(hk47, hk47_bytes):
    node = hk47.node_by_name("head")
    geo = ke.extract(hk47, node)
    smaller = _drop_last_vertices(geo, 40)
    out_mdl, out_mdx = ke.replace_geometry(hk47, node, smaller)

    after = kl.parse(out_mdl, out_mdx)
    new_node = after.node_by_name("head")
    assert new_node.vertex_count == smaller.vertex_count
    assert new_node.face_count == smaller.triangle_count

    # Hierarchy is untouched: same nodes, same names, same casing, same parents.
    assert [n.name for n in after.nodes] == [n.name for n in hk47.nodes]
    assert [n.parent for n in after.nodes] == [n.parent for n in hk47.nodes]
    assert after.supermodel == hk47.supermodel
    assert after.animation_names == hk47.animation_names

    # Every other mesh keeps its geometry byte for byte.
    for old in hk47.nodes:
        if not old.is_mesh or old.name == "head" or not old.vertex_count:
            continue
        if "saber" in old.flags or old.in_animation is not None:
            continue
        new = next(n for n in after.nodes if n.index == old.index)
        assert new.vertex_count == old.vertex_count
        assert ke.extract(after, new).columns == ke.extract(hk47, old).columns


def test_growing_a_mesh_produces_a_valid_larger_model(hk47, hk47_bytes):
    mdl, _ = hk47_bytes
    node = hk47.node_by_name("InnerTorso")
    geo = ke.extract(hk47, node)

    # Duplicate the vertex block and add a face over the copies.
    bigger = ke.MeshGeometry(
        vertex_count=geo.vertex_count * 2,
        columns={k: v + v for k, v in geo.columns.items()},
        influences=geo.influences + geo.influences,
        faces=list(geo.faces)
        + [
            ke.Face(f.normal, f.plane, f.material, (0xFFFF, 0xFFFF, 0xFFFF),
                    tuple(v + geo.vertex_count for v in f.vertices))
            for f in geo.faces
        ],
        trailing=geo.trailing,
    )
    out_mdl, out_mdx = ke.replace_geometry(hk47, node, bigger)
    assert len(out_mdl) > len(mdl)

    rep = kv.check(kl.parse(out_mdl, out_mdx))
    assert rep.ok, (
        f"gaps={len(rep.gaps)} overlaps={len(rep.overlaps)} dangling={rep.dangling[:2]}"
    )
    after = kl.parse(out_mdl, out_mdx)
    assert after.node_by_name("InnerTorso").vertex_count == geo.vertex_count * 2


def test_header_sizes_track_the_new_buffers(hk47):
    node = hk47.node_by_name("head")
    smaller = _drop_last_vertices(ke.extract(hk47, node), 40)
    out_mdl, out_mdx = ke.replace_geometry(hk47, node, smaller)

    assert struct.unpack_from("<I", out_mdl, 4)[0] == len(out_mdl) - 12
    assert struct.unpack_from("<I", out_mdl, 8)[0] == len(out_mdx)
    assert struct.unpack_from("<I", out_mdl, 12 + 176)[0] == len(out_mdx)


# --- refusals ---------------------------------------------------------------


def test_face_referencing_a_missing_vertex_is_refused(hk47):
    node = hk47.node_by_name("head")
    geo = ke.extract(hk47, node)
    geo.faces[0] = ke.Face(
        geo.faces[0].normal, geo.faces[0].plane, geo.faces[0].material,
        geo.faces[0].adjacent, (0, 1, geo.vertex_count + 5),
    )
    with pytest.raises(RewriteError, match="references vertex"):
        ke.replace_geometry(hk47, node, geo)


def test_more_than_four_influences_is_refused(hk47):
    node = hk47.node_by_name("TorsoHoses")
    geo = ke.extract(hk47, node)
    from kmdlswap.mdx import Influence

    geo.influences[0] = [Influence(0, 0.25) for _ in range(5)]
    with pytest.raises(RewriteError, match="at most 4"):
        ke.replace_geometry(hk47, node, geo)


def test_skinned_mesh_without_influences_is_refused(hk47):
    node = hk47.node_by_name("TorsoHoses")
    geo = ke.extract(hk47, node)
    geo.influences = []
    with pytest.raises(RewriteError, match="influence lists"):
        ke.replace_geometry(hk47, node, geo)
