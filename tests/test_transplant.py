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
    _, _, result = ktp.transplant_node(
        mdl, mdx, dustil, "n_dustilh", "Head", "Head", reshape=True
    )
    assert result.ok, result.error
    a = result.alignment
    assert a.worst_ratio < 1.2, f"donor is {a.worst_ratio:.2f}x the host part"
    assert a.drift < 0.02, f"donor sits {a.drift:.3f} away from the host part"


def test_transplant_produces_a_valid_model(carth_head, dustil):
    mdl, mdx = carth_head
    new_mdl, new_mdx, result = ktp.transplant_node(
        mdl, mdx, dustil, "n_dustilh", "Head", "Head", reshape=True
    )
    assert result.ok, result.error
    assert kv.check(kl.parse(new_mdl, new_mdx)).ok


def test_transplant_leaves_the_hierarchy_and_other_nodes_alone(carth_head, dustil):
    mdl, mdx = carth_head
    before = kl.parse(mdl, mdx)
    new_mdl, new_mdx, _ = ktp.transplant_node(
        mdl, mdx, dustil, "n_dustilh", "Head", "Head", reshape=True
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


def test_weights_come_from_the_host_not_the_donor(pair):
    """The donor's rig never crosses over. Bone slots index the HOST's bonemap,
    which is what makes a foreign-rigged donor safe.

    Uses body models, so the real weight-transfer path runs - a head would be
    refused for changing its vertex count.
    """
    from kmdlswap import mdx as kmdx

    mdl, mdx = pair("p_bastilaba")
    donor = kl.parse(*pair("p_bastilabb"))
    before = kl.parse(mdl, mdx)
    host_node = before.node_by_name("torso")
    assert host_node.is_skin
    host_slots = {
        x.bone_slot for infl in kmdx.influences(before, host_node) for x in infl
    }

    new_mdl, new_mdx, result = ktp.transplant_node(
        mdl, mdx, donor, "p_bastilabb", "torso", "torso"
    )
    assert result.ok, result.error
    after = kl.parse(new_mdl, new_mdx)
    new_node = after.node_by_name("torso")
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
        host_mdl, host_mdx, donor, "n_wookiem", node, pairs[node], reshape=True
    )
    _, _, fitted = ktp.transplant_node(
        host_mdl, host_mdx, donor, "n_wookiem", node, pairs[node],
        fit=True, reshape=True,
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


def test_refuses_to_change_a_head_models_vertex_count(pair):
    """Established in-game: it stops the mouth and eyebrows moving."""
    host_mdl, host_mdx = pair("p_carthh")
    donor = kl.parse(*pair("n_dustilh"))
    _, _, result = ktp.transplant_node(
        host_mdl, host_mdx, donor, "n_dustilh", "Head", "Head"
    )
    assert not result.ok
    assert "vertices rather than" in result.error
    assert "--reshape" in result.error


def test_reshape_is_allowed_and_preserves_the_host_exactly(pair):
    """The reshape path keeps count, faces, UVs and weights, moving positions."""
    from kmdlswap import mdx as kmdx

    host_mdl, host_mdx = pair("p_carthh")
    donor = kl.parse(*pair("n_dustilh"))
    before = kl.parse(host_mdl, host_mdx)
    new_mdl, new_mdx, result = ktp.transplant_node(
        host_mdl, host_mdx, donor, "n_dustilh", "Head", "Head", reshape=True
    )
    assert result.ok, result.error
    assert result.reshaped
    # File sizes must not move: that is the property the engine cares about.
    assert len(new_mdl) == len(host_mdl)
    assert len(new_mdx) == len(host_mdx)

    after = kl.parse(new_mdl, new_mdx)
    a = before.node_by_name("Head")
    b = after.node_by_name("Head")
    assert b.vertex_count == a.vertex_count
    ga, gb = ke.extract(before, a), ke.extract(after, b)
    assert [f.vertices for f in ga.faces] == [f.vertices for f in gb.faces]
    assert ga.columns.get("uv1") == gb.columns.get("uv1")

    # Weights pass through verbatim; re-deriving them silently drops a bone.
    ia = kmdx.influences(before, a)
    ib = kmdx.influences(after, b)
    for p, q in zip(ia, ib):
        assert {x.bone_slot: round(x.weight, 5) for x in p} == {
            x.bone_slot: round(x.weight, 5) for x in q
        }


def test_with_texture_takes_the_donors_mapping_and_texture(pair):
    """A textured reshape: host topology, donor UVs, donor texture."""
    import struct

    host_mdl, host_mdx = pair("p_carthh")
    donor = kl.parse(*pair("n_dustilh"))
    before = kl.parse(host_mdl, host_mdx)
    new_mdl, new_mdx, result = ktp.transplant_node(
        host_mdl, host_mdx, donor, "n_dustilh", "Head", "Head",
        reshape=True, with_texture=True,
    )
    assert result.ok, result.error
    # Still the safe configuration: nothing resizes.
    assert len(new_mdl) == len(host_mdl) and len(new_mdx) == len(host_mdx)

    after = kl.parse(new_mdl, new_mdx)
    a, b = before.node_by_name("Head"), after.node_by_name("Head")

    def texture_of(layout, node):
        raw = layout.mdl[node.trimesh_at + 88 : node.trimesh_at + 120]
        return raw.split(b"\x00")[0].decode("ascii")

    assert texture_of(before, a) == "P_CarthH01"
    assert texture_of(after, b) == "N_DustilH01"
    ga, gb = ke.extract(before, a), ke.extract(after, b)
    assert ga.columns.get("uv1") != gb.columns.get("uv1"), "UVs should be the donor's"
    assert [f.vertices for f in ga.faces] == [f.vertices for f in gb.faces]


def test_texture_name_must_fit_the_field(pair):
    from kmdlswap.rewrite import RewriteError

    mdl, mdx = pair("p_carthh")
    lay = kl.parse(mdl, mdx)
    node = lay.node_by_name("Head")
    geo = ke.extract(lay, node)
    with pytest.raises(RewriteError, match="does not fit"):
        ke.replace_geometry(lay, node, geo, texture="x" * 40)


def test_hiding_a_node_is_a_one_byte_patch(pair):
    """A node the donor lacks cannot be removed - the hierarchy is never
    touched - but it can be told not to draw, which is what vanilla does to the
    18,058 mesh nodes it keeps as invisible skeleton boxes."""
    from kmdlfun import parts as kparts
    from kmdlfun import visibility as kvis

    mdl, mdx = pair("p_carthh")
    lay = kl.parse(mdl, mdx)
    node = lay.node_by_name("hair")
    assert kparts.renders(lay, node)

    out = kvis.set_rendered(mdl, node, False)
    assert len(out) == len(mdl)
    assert sum(1 for a, b in zip(mdl, out) if a != b) == 1

    after = kl.parse(out, mdx)
    assert not kparts.renders(after, after.node_by_name("hair"))
    assert kv.check(after).ok
    # Nothing else moved.
    assert [n.name for n in after.nodes] == [n.name for n in lay.nodes]
    assert len(kparts.mesh_nodes(after)) == len(kparts.mesh_nodes(lay)) - 1


def test_hide_nodes_reports_what_it_hid(pair):
    from kmdlfun import visibility as kvis

    mdl, mdx = pair("p_carthh")
    lay = kl.parse(mdl, mdx)
    out, hidden = kvis.hide_nodes(lay, mdl, ["hair", "nonexistent"])
    assert hidden == ["hair"]
    assert kv.check(kl.parse(out, mdx)).ok
