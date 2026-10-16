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


def test_fillable_slots_drops_other_and_keeps_part_order(k1):
    from kmdlswap import layout as kl

    slots = kdroid.fillable_slots(kl.parse(*k1.read(UNIBODY)))
    keys = [key for key, _label, _nodes in slots]

    assert "other" not in keys, "hoses and finger plates are not mix points"
    assert keys[0] == "head", "head comes first, as in parts.PARTS"
    assert {"head", "torso", "limb"} <= set(keys)
    assert all(nodes for _k, _l, nodes in slots), "no empty group is offered"


def test_catalogue_and_base_filter_leave_out_the_turrets(install_path, k1):
    cat = kdroid.catalogue(str(install_path), library=k1)
    assert kdroid.part_categories(_layout(k1, UNIBODY)) == cat[UNIBODY]

    bases = kdroid.buildable_bases(cat)
    assert UNIBODY in bases and OTHER_DROID in bases and HUMANOID_DROID in bases
    # A spider walker / bare astromech / turret has no torso, so it is not a
    # base - every one of its parts would land in "other".
    for headless_body in ("c_drdspyder", "l_astro02", "c_drdsentry"):
        if headless_body in cat:
            assert headless_body not in bases


def test_donors_for_only_offers_droids_that_have_the_part(install_path, k1):
    cat = kdroid.catalogue(str(install_path), library=k1)

    neck_donors = kdroid.donors_for(cat, "neck", exclude=UNIBODY)
    assert UNIBODY not in neck_donors
    assert all("neck" in cat[d] for d in neck_donors)
    # T3-M4 has a neck; the spider droid does not.
    assert OTHER_DROID in neck_donors
    if "c_drdspyder" in cat:
        assert "c_drdspyder" not in neck_donors


def _layout(lib, name):
    from kmdlswap import layout as kl

    return kl.parse(*lib.read(name))


def test_auto_donor_node_ignores_separators_but_not_ambiguity(k1):
    """`R_upper_arm` and `R_UpperArm` are the same word punctuated by two
    different modellers, and that mismatch was the commonest reason a droid mix
    silently skipped a part. Squashing case and separators pairs them - but only
    when one donor node squashes to that form, because HK-47 itself carries both
    `F-1` and `F_1` and guessing between two is worse than saying so."""
    from kmdlswap import layout as kl

    hk = kl.parse(*k1.read(UNIBODY))
    war = kl.parse(*k1.read(HUMANOID_DROID))

    assert kdroid.auto_donor_node("R_upper_arm", war) == "R_UpperArm"
    assert kdroid.auto_donor_node("R-upper-arm", hk) == "R_upper_arm"
    # 'F1' squashes onto both F-1 and F_1, so it must refuse rather than pick.
    assert kdroid.auto_donor_node("F1", hk) is None
    # An exact name still wins outright, before any squashing.
    assert kdroid.auto_donor_node("F-1", hk) == "F-1"


def test_positional_matching_pairs_what_no_name_could(k1):
    """`R_calf` and `R_Shin` are the same part named by two people who did not
    confer, and no string work pairs them - but both sit in the same place on a
    droid, which is a fact about the model rather than about the naming."""
    from kmdlswap import layout as kl

    hk = kl.parse(*k1.read(UNIBODY))
    war = kl.parse(*k1.read(HUMANOID_DROID))

    assert kdroid.auto_donor_node("R_calf", war) is None, "no name in common"
    m = kdroid.match_donor_node(hk, "R_calf", war)
    assert m is not None and m.donor_node == "R_Shin"
    assert m.by_position and m.distance < 0.1

    # A palm answers for a palm, not for the finger on it: `parts.py` buckets
    # both as "hand", and the hierarchy is what separates them.
    palm = kdroid.match_donor_node(hk, "L_hand", war)
    assert palm is not None and palm.donor_node == "LHandDrd"

    # Off by default nowhere, but switchable off everywhere.
    assert kdroid.match_donor_node(hk, "R_calf", war, positional=False) is None


def test_positional_matching_keeps_left_and_right_apart(k1):
    """A left arm on a right shoulder reads as a rigging fault rather than a
    naming one, so the pairing must not cross sides. It does not need a rule:
    normalised, a left part sits at a low x and a right part at a high one.

    HK-47's `L_hand01` is the exception that proves it - the model calls it
    left and hangs it off `R_lower_arm`, so pairing it with a *right* hand is
    the correct answer and the one position gives.
    """
    from kmdlswap import layout as kl

    hk = kl.parse(*k1.read(UNIBODY))
    war = kl.parse(*k1.read(HUMANOID_DROID))

    for host, donor in (("L_hand", "LHandDrd"), ("L_calf", "L_Shin"),
                        ("R_calf", "R_Shin"), ("LTrgrFngr", "LFngr1")):
        m = kdroid.match_donor_node(hk, host, war)
        assert m is not None and m.donor_node == donor, f"{host} -> {m and m.donor_node}"

    assert hk.nodes[hk.node_by_name("L_hand01").parent].name == "R_lower_arm", (
        "the premise: HK-47's 'L_hand01' is really its right hand"
    )
    m = kdroid.match_donor_node(hk, "L_hand01", war)
    assert m is not None and m.donor_node == "RHandDrd"


def test_positional_matching_refuses_rather_than_reaching(k1):
    """A donor with nothing in that region says so instead of offering its
    nearest unrelated lump."""
    from kmdlswap import layout as kl

    hk = kl.parse(*k1.read(UNIBODY))
    spider = kl.parse(*k1.read("c_drdspyder"))

    # The spider walker's only standard part is a head, so it cannot answer
    # for a calf however far the search is willing to reach.
    assert kdroid.match_donor_node(hk, "R_calf", spider) is None
    found, distance = kdroid.positional_donor_node(hk, "R_calf", spider)
    assert found is None

    # And the limit is what refuses it: a wide enough one finds something.
    assert kdroid.POSITION_LIMIT < 1.0


def test_build_records_how_each_part_was_paired(k1):
    base_mdl, base_mdx = k1.read(UNIBODY)
    result = kdroid.build(base_mdl, base_mdx, UNIBODY, [
        kdroid.SlotChoice("head", HUMANOID_DROID),          # same name
        kdroid.SlotChoice("R_upper_arm", HUMANOID_DROID),   # separators
        kdroid.SlotChoice("R_calf", HUMANOID_DROID),        # position only
    ], k1)

    by_node = {s.host_node: s for s in result.slots}
    assert by_node["head"].matched_by == "name"
    assert by_node["R_upper_arm"].matched_by == "separators"
    assert by_node["R_calf"].matched_by == "position"
    assert "by position" in by_node["R_calf"].how
    assert by_node["head"].how == "", "a plain name match needs no explaining"
    assert result.applied == ["head", "R_upper_arm", "R_calf"]


def test_split_donor_reads_the_game_namespace():
    assert kdroid.split_donor("c_drdwar") == ("", "c_drdwar")
    assert kdroid.split_donor("k2/c_condrdl") == ("K2", "c_condrdl")
    assert kdroid.split_donor("K2/c_condrdl") == ("K2", "c_condrdl")


def test_build_takes_each_part_from_the_game_its_choice_names(k1, k2_path):
    """One droid, both games: the head from KOTOR II and an arm from KOTOR.

    The donor cache has to key on (game, model), not model - both games ship a
    `c_drdwar`, and they are not the same file.
    """
    from kmdlfun.library import ModelLibrary

    k2 = ModelLibrary(str(k2_path))
    base_mdl, base_mdx = k1.read(UNIBODY)
    choices = [
        kdroid.SlotChoice("head", "c_condrdl", "Head", donor_game="K2"),
        kdroid.SlotChoice("R_upper_arm", HUMANOID_DROID),
    ]
    result = kdroid.build(base_mdl, base_mdx, UNIBODY, choices, k1,
                          donor_libraries={"K2": k2})

    assert result.applied == ["head", "R_upper_arm"], [
        s.note or (s.transplant and s.transplant.error) for s in result.slots]
    assert result.slots[0].donor_game == "K2"
    assert result.slots[0].donor_label == "K2/c_condrdl"
    assert result.slots[1].donor_game == "" and result.slots[1].donor_label == "c_drdwar"
    for slot in result.slots:
        assert slot.transplant.alignment.drift < 0.05, "both sit on their joint"

    from kmdlswap import layout as kl
    from kmdlswap import validate as kv

    assert kv.check(kl.parse(result.mdl, result.mdx)).ok


def test_a_part_from_a_game_with_no_library_is_skipped_not_raised(k1):
    """Naming K2 without a K2 install is a note on that part, not a crash that
    loses the parts that were fine."""
    base_mdl, base_mdx = k1.read(UNIBODY)
    choices = [
        kdroid.SlotChoice("head", HUMANOID_DROID),
        kdroid.SlotChoice("R_upper_arm", "c_condrdl", donor_game="K2"),
    ]
    result = kdroid.build(base_mdl, base_mdx, UNIBODY, choices, k1)

    assert result.slots[0].ok
    assert not result.slots[1].ok
    assert "no K2 install" in result.slots[1].note
    assert result.applied == ["head"]


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
