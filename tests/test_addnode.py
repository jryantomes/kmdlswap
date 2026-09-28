"""Adding a mesh node (kmdlswap.addnode) - GH0-RFK's eyes and mouth light, 2026-09-28.

On vanilla p_hk47, whose Mesh01 (the eye panel) is the template it was written for.
"""

from __future__ import annotations

import pytest

from kmdlswap import edit as ke
from kmdlswap import layout as kl
from kmdlswap import validate as kv
from kmdlswap.addnode import add_mesh_node, set_selfillum
from kmdlswap.rewrite import Rewriter


@pytest.fixture(scope="module")
def hk47_bytes(pair):
    return pair("p_hk47")


@pytest.fixture(scope="module")
def added(hk47_bytes):
    return add_mesh_node(*hk47_bytes, "Mesh01", "eyes2", "talkdummy")


def test_result_is_a_clean_model(added):
    rep = kv.check(kl.parse(*added))
    assert rep.identity_mdl and rep.identity_mdx
    assert not rep.gaps and not rep.overlaps and not rep.dangling


def test_new_node_is_a_copy_under_the_parent(hk47_bytes, added):
    before, after = kl.parse(*hk47_bytes), kl.parse(*added)
    new, tpl = after.node_by_name("eyes2"), after.node_by_name("Mesh01")
    assert after.nodes[new.parent].name == "talkdummy"
    assert after.node_count == before.node_count + 1
    # numbered in depth-first order like every other node: the engine will not load a model
    # whose numbers disagree with it (in game, 2026-09-28)
    geo = [n for n in after.nodes if n.in_animation is None]
    assert all(n.node_id == n.index for n in geo)
    assert [n.name for n in geo if n.name != "eyes2"] == [n.name for n in before.nodes if n.in_animation is None]
    a, b = ke.extract(after, tpl), ke.extract(after, new)
    assert a.positions == b.positions and len(a.faces) == len(b.faces)


def test_every_old_mesh_and_animation_is_unchanged(hk47_bytes, added):
    before, after = kl.parse(*hk47_bytes), kl.parse(*added)
    assert after.animation_names == before.animation_names
    for n in (n for n in before.nodes if n.in_animation is None and n.is_mesh):
        assert ke.extract(after, after.node_by_name(n.name)).positions == ke.extract(before, n).positions


def test_skin_bonemaps_grow_with_the_node_count(hk47_bytes, added):
    before, after = kl.parse(*hk47_bytes), kl.parse(*added)
    new = after.node_by_name("eyes2").node_id
    for b, a in zip((n for n in before.nodes if n.in_animation is None and n.is_skin),
                    (n for n in after.nodes if n.in_animation is None and n.is_skin)):
        assert len(a.bonemap) == after.node_count
        assert a.bonemap[new] == -1
        assert a.bonemap[:new] + a.bonemap[new + 1:] == b.bonemap   # every other node keeps its slot


def test_animation_nodes_follow_the_renumbering(hk47_bytes, added):
    before, after = kl.parse(*hk47_bytes), kl.parse(*added)
    names = lambda L: sorted((n.in_animation, n.name) for n in L.nodes if n.in_animation)
    assert names(before) == names(after)          # each animation node still names its node


def test_a_duplicate_name_is_refused(added):
    with pytest.raises(ValueError):
        add_mesh_node(*added, "Mesh01", "eyes2", "talkdummy")


def test_resting_selfillum_can_be_set(added):
    mdl = set_selfillum(*added, "Mesh01", 0.0)
    assert kv.check(kl.parse(mdl, added[1])).identity_mdl


def test_an_insert_right_after_a_pointer_is_not_a_straddle(hk47_bytes):
    """Growing an array by a slot at its end: the last pointer ends where the insert
    begins, and must move with its own bytes, not be refused (fixed 2026-09-28)."""
    L = kl.parse(*hk47_bytes)
    names = next(s for s in L.spans if s.kind == "name_offset_array")
    rw = Rewriter(L)
    rw.replace_mdl(names.end, names.end, b"\0\0\0\0")
    rw.apply()
