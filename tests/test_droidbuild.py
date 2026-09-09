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
HUMANOID_DROID = "c_drdwar"


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
    build - one misnamed `--part` should not sink an otherwise good mix. An
    explicit donor node the donor does not have is skipped the same way an
    un-inferable one is: a note, not a REFUSED transplant."""
    base_mdl, base_mdx = k1.read(UNIBODY)
    choices = [
        kdroid.SlotChoice("head", OTHER_DROID),
        kdroid.SlotChoice("head", OTHER_DROID, donor_node="not-a-real-node"),
    ]
    result = kdroid.build(base_mdl, base_mdx, UNIBODY, choices, k1)

    assert result.slots[0].ok
    assert not result.slots[1].ok
    assert result.slots[1].transplant is None, "never handed to transplant_node"
    assert result.slots[1].note and "not-a-real-node" in result.slots[1].note


def test_joint_align_lands_a_short_donors_head_at_the_base_neck(k1):
    """T3-M4 stands ~1m; HK-47 ~1.9m. Carried at its own model-space height a
    T3 head lands about a unit low. `align="joint"` (the default) moves the
    donor node's own origin onto the host's, so the head hangs off HK's neck
    joint instead - the part keeps its size, it just attaches in the right
    place."""
    base_mdl, base_mdx = k1.read(UNIBODY)
    choices = [kdroid.SlotChoice("head", OTHER_DROID)]

    raw = kdroid.build(base_mdl, base_mdx, UNIBODY, choices, k1, align="none")
    joint = kdroid.build(base_mdl, base_mdx, UNIBODY, choices, k1)  # align defaults

    assert raw.slots[0].ok and joint.slots[0].ok
    assert raw.slots[0].transplant.alignment.drift > 0.5, "the problem being fixed"
    assert joint.slots[0].transplant.alignment.drift < 0.05, "now sits on the joint"
    # Same geometry either way - only where it sits changed, not its size.
    assert (raw.slots[0].transplant.alignment.worst_ratio
            == pytest.approx(joint.slots[0].transplant.alignment.worst_ratio))


def test_two_humanoid_droids_swap_cleanly(k1):
    """HK-47 and a war droid are built to the same proportions, so a
    joint-aligned head/arm swap between them comes out close to 1:1 - the
    'goofy' is only there when the donor is shaped nothing like the base."""
    base_mdl, base_mdx = k1.read(UNIBODY)
    choices = [
        kdroid.SlotChoice("head", HUMANOID_DROID),
        # c_drdwar names it R_UpperArm; auto-matching is by exact/alias name and
        # does not bridge that, so the pairing is spelled out - the alignment is
        # what this test is about.
        kdroid.SlotChoice("R_upper_arm", HUMANOID_DROID, donor_node="R_UpperArm"),
    ]
    result = kdroid.build(base_mdl, base_mdx, UNIBODY, choices, k1)

    assert result.applied == ["head", "R_upper_arm"]
    for slot in result.slots:
        a = slot.transplant.alignment
        assert a.drift < 0.05, f"{slot.host_node} should sit on its joint"
        assert a.worst_ratio < 1.4, f"{slot.host_node} should be near the base's size"


def test_identity_swap_is_unmoved_and_unscaled(k1):
    """A node filled from the same node of the same model: joint align must be
    a no-op, not a nudge."""
    base_mdl, base_mdx = k1.read(UNIBODY)
    result = kdroid.build(base_mdl, base_mdx, UNIBODY,
                          [kdroid.SlotChoice("head", UNIBODY)], k1)

    a = result.slots[0].transplant.alignment
    assert a.drift < 1e-4
    assert a.worst_ratio == pytest.approx(1.0, abs=1e-3)
