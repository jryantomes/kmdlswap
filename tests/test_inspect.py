"""Milestone 1 acceptance: a report a human can use to choose a target node."""

from __future__ import annotations

import pytest

from kmdlswap import inspect as kinspect
from kmdlswap import layout as kl
from kmdlswap import mdx as kmdx


@pytest.fixture(scope="module")
def hk47(pair):
    return kl.parse(*pair("p_hk47"))


def test_report_covers_everything_the_brief_asks_for(hk47):
    text = kinspect.report(hk47)
    assert "P_HK47" in text  # exact casing, not lowercased
    assert "supermodel" in text
    assert "bounding box" in text
    assert "TorsoHoses" in text  # a skinned mesh
    assert "max influences/vertex observed" in text
    assert "bones referenced" in text


def test_names_keep_exact_casing_and_paths(hk47):
    head = hk47.node_by_name("head", exact=True)
    assert head.name == "head"
    assert head.path(hk47.nodes) == "P_HK47/cutscenedummy/rootdummy/InnerTorso/Fore_body/Neck/Hturn_g/head"
    with pytest.raises(KeyError):
        hk47.node_by_name("HEAD", exact=True)


def test_skin_weights_resolve_to_real_bone_nodes(hk47):
    torso = hk47.node_by_name("TorsoHoses")
    assert torso.is_skin
    facts = kinspect.mesh_facts(hk47, torso)
    assert facts.bone_names == ["InnerTorso", "Fore_body"]
    # Vanilla skin weights are normalised; we rely on this when transferring.
    lo, hi = facts.weight_sum_range
    assert abs(lo - 1.0) < 1e-4 and abs(hi - 1.0) < 1e-4


def test_bonemap_is_indexed_by_node_not_by_vertex(hk47):
    """Settles a design question: the bonemap does not resize with geometry."""
    geometry = [n for n in hk47.nodes if n.in_animation is None]
    torso = hk47.node_by_name("TorsoHoses")
    assert len(torso.bonemap) == len(geometry)
    assert len(torso.bonemap) != torso.vertex_count

    slot_nodes = kmdx.bone_slot_nodes(hk47, torso)
    for slot, node in slot_nodes.items():
        assert torso.bonemap[node.index] == slot


def test_influence_count_never_exceeds_four(hk47):
    for node in hk47.nodes:
        if not (node.is_skin and node.in_animation is None):
            continue
        for infl in kmdx.influences(hk47, node):
            assert 1 <= len(infl) <= 4


def test_mdx_positions_match_the_mdl_side_vertex_array(pair):
    """Each mesh stores positions twice - in the MDX stream and in an MDL-side
    array. A geometry swap must keep both in step, so verify they agree now."""
    import struct

    lay = kl.parse(*pair("p_hk47"))
    node = lay.node_by_name("head")
    mdx_pos = kmdx.positions(lay, node)
    vertices_offset = struct.unpack_from("<I", lay.mdl, node.trimesh_at + 328)[0]
    base = 12 + vertices_offset
    mdl_pos = [
        struct.unpack_from("<3f", lay.mdl, base + i * 12) for i in range(node.vertex_count)
    ]
    assert mdx_pos == mdl_pos
