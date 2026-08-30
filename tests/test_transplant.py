"""Moving geometry between models without touching either hierarchy."""

from __future__ import annotations

import pytest

from kmdlfun import transplant as ktp
from kmdlswap import edit as ke
from kmdlswap import layout as kl
from kmdlswap import validate as kv


@pytest.fixture(scope="module")
def carth_head(pair):
    return pair("p_carthh")


@pytest.fixture(scope="module")
def dustil(pair):
    return kl.parse(*pair("n_dustilh"))


def test_matching_pairs_nodes_across_models(carth_head, dustil):
    host = kl.parse(*carth_head)
    pairs = ktp.match_nodes(host, dustil)
    assert ("Head", "Head") in pairs
    assert len(pairs) >= 5


def test_matching_ignores_case(pair):
    """A swap never renames, so casing is only a pairing heuristic."""
    host = kl.parse(*pair("p_carthh"))
    donor = kl.parse(*pair("p_bastilah"))
    pairs = dict(ktp.match_nodes(host, donor))
    # Carth has "Head", Bastila has "head" - they must still pair.
    assert pairs.get("Head", "").lower() == "head"


def test_transplant_lands_in_the_right_place(carth_head, dustil):
    """Donor geometry is stored in the donor node's frame, so it has to be
    re-expressed in the host's. If that maths is wrong the part flies off."""
    mdl, mdx = carth_head
    _, _, result = ktp.transplant_node(mdl, mdx, dustil, "n_dustilh", "Head", "Head")
    assert result.ok, result.error
    a = result.alignment
    assert a.worst_ratio < 1.2, f"donor is {a.worst_ratio:.2f}x the host part"
    assert a.drift < 0.02, f"donor sits {a.drift:.3f} away from the host part"


def test_transplant_produces_a_valid_model(carth_head, dustil):
    mdl, mdx = carth_head
    new_mdl, new_mdx, result = ktp.transplant_node(
        mdl, mdx, dustil, "n_dustilh", "Head", "Head"
    )
    assert result.ok
    assert kv.check(kl.parse(new_mdl, new_mdx)).ok


def test_transplant_leaves_the_hierarchy_and_other_nodes_alone(carth_head, dustil):
    mdl, mdx = carth_head
    before = kl.parse(mdl, mdx)
    new_mdl, new_mdx, _ = ktp.transplant_node(
        mdl, mdx, dustil, "n_dustilh", "Head", "Head"
    )
    after = kl.parse(new_mdl, new_mdx)

    assert [n.name for n in after.nodes] == [n.name for n in before.nodes]
    assert [n.parent for n in after.nodes] == [n.parent for n in before.nodes]
    assert after.supermodel == before.supermodel
    assert after.animation_names == before.animation_names

    for old in before.nodes:
        if not old.is_mesh or old.name == "Head" or not old.vertex_count:
            continue
        if old.in_animation is not None or "saber" in old.flags:
            continue
        new = next(n for n in after.nodes if n.index == old.index)
        assert ke.extract(after, new).columns == ke.extract(before, old).columns


def test_weights_come_from_the_host_not_the_donor(carth_head, dustil):
    """The donor's rig never crosses over. Bone slots index the HOST's bonemap,
    which is what makes a foreign-rigged donor safe."""
    from kmdlswap import mdx as kmdx

    mdl, mdx = carth_head
    before = kl.parse(mdl, mdx)
    host_node = before.node_by_name("Head")
    if not host_node.is_skin:
        pytest.skip("host head is not skinned")
    host_slots = {
        x.bone_slot for infl in kmdx.influences(before, host_node) for x in infl
    }

    new_mdl, new_mdx, result = ktp.transplant_node(
        mdl, mdx, dustil, "n_dustilh", "Head", "Head"
    )
    assert result.ok
    after = kl.parse(new_mdl, new_mdx)
    new_node = after.node_by_name("Head")
    new_slots = {x.bone_slot for infl in kmdx.influences(after, new_node) for x in infl}
    assert new_slots <= host_slots, "transplant introduced a bone slot the host does not have"


def test_fit_rescales_a_mismatched_donor(pair):
    host_mdl, host_mdx = pair("p_carthh")
    donor = kl.parse(*pair("n_wookiem"))
    host = kl.parse(host_mdl, host_mdx)
    pairs = dict(ktp.match_nodes(host, donor))
    node = next((h for h in pairs if h.lower() == "head"), None)
    if node is None:
        pytest.skip("no shared head node with this donor")

    _, _, loose = ktp.transplant_node(
        host_mdl, host_mdx, donor, "n_wookiem", node, pairs[node]
    )
    _, _, fitted = ktp.transplant_node(
        host_mdl, host_mdx, donor, "n_wookiem", node, pairs[node], fit=True
    )
    assert loose.ok and fitted.ok
    assert fitted.alignment.worst_ratio <= loose.alignment.worst_ratio
    assert fitted.alignment.drift <= loose.alignment.drift + 1e-6


def test_refuses_a_saber_or_unauthorable_node(pair):
    host = kl.parse(*pair("p_carthh"))
    donor = kl.parse(*pair("c_bmspecdiff"))  # carries tangent frames
    host_node = host.node_by_name("Head")
    donor_node = donor.node_by_name("RLeg")
    assert ktp.check_pair(host, host_node, donor, donor_node) is not None
