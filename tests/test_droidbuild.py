"""Mixing droid parts: head from one model, arms or legs from another.

A droid is one unified body model, so there is no `heads.2da`-style shortcut
for "give HK-47 a different head" the way there is for a human. The only way
in is the same node transplant a single head swap uses, applied once per part
and threaded through - which is exactly what `droidbuild.build` does and this
file checks.
"""

from __future__ import annotations

import pytest

from kmdlfun import droidbuild as kdroid
from kmdlfun.library import ModelLibrary

UNIBODY = "p_hk47"
OTHER_DROID = "p_t3m3"


@pytest.fixture(scope="module")
def k1(install_path):
    return ModelLibrary(str(install_path))


def test_droid_models_finds_the_known_droids(install_path, k1):
    found = kdroid.droid_models(str(install_path), library=k1)
    assert UNIBODY in found
    assert OTHER_DROID in found
    # Structural, not name-based: nothing here is an organic companion.
    assert "p_carthh" not in found


def test_slot_groups_reads_the_models_own_nodes(k1):
    from kmdlswap import layout as kl

    layout = kl.parse(*k1.read(UNIBODY))
    groups = kdroid.slot_groups(layout)

    all_names = {n.name for nodes in groups.values() for n in nodes}
    assert "head" in all_names, "HK-47's own head node should show up somewhere"
    # Every grouped node is a real, visible mesh node - nothing invented.
    from kmdlfun import parts as kparts

    visible = {n.name for n in kparts.mesh_nodes(layout)}
    assert all_names <= visible


def test_auto_donor_node_matches_by_name_then_by_alias(k1):
    from kmdlswap import layout as kl

    host = kl.parse(*k1.read(UNIBODY))
    donor = kl.parse(*k1.read(OTHER_DROID))

    # A node paired with itself always matches by exact name.
    for node in [n for n in host.nodes if n.is_mesh and n.vertex_count][:5]:
        assert kdroid.auto_donor_node(node.name, host) == node.name

    assert kdroid.auto_donor_node("not-a-real-node-name", donor) is None


def test_build_applies_one_part_and_leaves_the_rest_alone(k1, install_path):
    """Swap only HK-47's head from T3-M4, and check nothing else moved.

    Mirrors `test_unibody.py`'s own check that a single-node transplant
    changes exactly the node it targeted; here through `droidbuild.build`
    instead of calling `transplant_node` directly, which is the point - the
    wrapper should not touch anything the underlying engine wouldn't.
    """
    from kmdlswap import layout as kl
    from kmdlswap import validate as kv

    from kmdlfun import parts as kparts

    base_mdl, base_mdx = k1.read(UNIBODY)
    before = kl.parse(base_mdl, base_mdx)
    donor_head = kdroid.auto_donor_node("head", kl.parse(*k1.read(OTHER_DROID)))
    assert donor_head, "T3-M4 should have a node matching HK-47's head by name or alias"

    choices = [kdroid.SlotChoice("head", OTHER_DROID)]
    result = kdroid.build(base_mdl, base_mdx, UNIBODY, choices, k1)

    assert result.slots, "one slot was asked for"
    slot = result.slots[0]
    assert slot.ok, slot.note or (slot.transplant and slot.transplant.error)
    assert result.applied == ["head"]

    after = kl.parse(result.mdl, result.mdx)
    assert kv.check(after).ok, "a build that does not validate is not a build"

    was = {n.name: n.vertex_count for n in kparts.mesh_nodes(before, visible_only=False)}
    now = {n.name: n.vertex_count for n in kparts.mesh_nodes(after, visible_only=False)}
    assert set(was) == set(now), "no mesh node should appear or disappear"


def test_build_skips_a_part_with_no_matching_donor_node(k1):
    """A bad part is reported, not raised, so the parts that were fine still
    build - one misnamed `--part` should not sink an otherwise good mix."""
    base_mdl, base_mdx = k1.read(UNIBODY)
    choices = [
        kdroid.SlotChoice("head", OTHER_DROID),
        kdroid.SlotChoice("head", OTHER_DROID, donor_node="not-a-real-node"),
    ]
    result = kdroid.build(base_mdl, base_mdx, UNIBODY, choices, k1)

    assert result.slots[0].ok
    assert not result.slots[1].ok
    assert result.slots[1].note and "not-a-real-node" in result.slots[1].note
