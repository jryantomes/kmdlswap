"""kmdlfun: companion effects built on the kmdlswap engine."""

from __future__ import annotations

import pytest

from kmdlfun import apply as kapply
from kmdlfun import effects as keffects
from kmdlfun import parts, roster
from kmdlswap import layout as kl
from kmdlswap import validate as kv


def test_every_companion_model_exists(resources):
    missing = [
        m for c in roster.COMPANIONS for m in c.models if m.lower() not in resources
    ]
    assert not missing, f"not in install: {missing}"


def test_effect_intensity_blends_towards_no_change():
    e = keffects.resolve("bighead")
    assert e.scaled(1.0)["head"] == pytest.approx(1.6)
    assert e.scaled(0.0)["head"] == pytest.approx(1.0)
    assert e.scaled(0.5)["head"] == pytest.approx(1.3)


def test_head_models_are_recognised(pair):
    """Human companions keep their head in its own model; droids do not."""
    assert kapply.is_head_model(kl.parse(*pair("p_carthh")))
    assert not kapply.is_head_model(kl.parse(*pair("p_carthba")))
    assert not kapply.is_head_model(kl.parse(*pair("p_hk47")))


def test_head_model_scales_hair_and_eyes_too(pair):
    """Scaling only the node called 'head' would leave hair and eyes behind."""
    layout = kl.parse(*pair("p_carthh"))
    names = {layout.nodes[i].name.lower() for i in kapply.targets(layout, "head")}
    assert "head" in names
    assert any("hair" in n for n in names)
    assert any("eye" in n for n in names)
    # The neck joins the body and must stay put.
    assert not any(n.startswith("neck") for n in names)


def test_body_model_head_stub_is_not_a_head(pair):
    """p_carthbb has a small 'head_g' stub; it is not the real head."""
    layout = kl.parse(*pair("p_carthbb"))
    assert not kapply.is_head_model(layout)


def test_scaling_changes_size_but_not_topology(pair):
    from kmdlswap import edit as ke

    layout = kl.parse(*pair("p_hk47"))
    node = layout.node_by_name("head")
    geo = ke.extract(layout, node)
    before = [
        max(p[i] for p in geo.positions) - min(p[i] for p in geo.positions)
        for i in range(3)
    ]
    kapply.scale_geometry(geo, 2.0)
    after = [
        max(p[i] for p in geo.positions) - min(p[i] for p in geo.positions)
        for i in range(3)
    ]
    for b, a in zip(before, after):
        assert a == pytest.approx(b * 2.0, rel=1e-5)
    assert geo.vertex_count == node.vertex_count
    assert len(geo.faces) == node.face_count


def test_bounds_pivot_keeps_the_mesh_in_place(pair):
    from kmdlswap import edit as ke

    layout = kl.parse(*pair("p_hk47"))
    geo = ke.extract(layout, layout.node_by_name("head"))
    centre = lambda g: [  # noqa: E731
        (max(p[i] for p in g.positions) + min(p[i] for p in g.positions)) / 2
        for i in range(3)
    ]
    before = centre(geo)
    kapply.scale_geometry(geo, 1.6, pivot="bounds")
    assert centre(geo) == pytest.approx(before, abs=1e-5)


@pytest.mark.parametrize("effect_key", [e.key for e in keffects.EFFECTS])
def test_every_effect_produces_a_valid_model(pair, effect_key):
    mdl, mdx = pair("p_hk47")
    scales = keffects.resolve(effect_key).scaled(1.0)
    new_mdl, new_mdx, result = kapply.apply_to_model(
        mdl, mdx, scales, model_name="p_hk47"
    )
    assert result.ok, result.error
    assert result.changes, "effect changed nothing"
    assert kv.check(kl.parse(new_mdl, new_mdx)).ok


def test_apply_leaves_the_hierarchy_untouched(pair):
    mdl, mdx = pair("p_hk47")
    before = kl.parse(mdl, mdx)
    new_mdl, new_mdx, _ = kapply.apply_to_model(
        mdl, mdx, {"head": 1.6}, model_name="p_hk47"
    )
    after = kl.parse(new_mdl, new_mdx)
    assert [n.name for n in after.nodes] == [n.name for n in before.nodes]
    assert [n.parent for n in after.nodes] == [n.parent for n in before.nodes]
    assert after.supermodel == before.supermodel
    assert after.animation_names == before.animation_names


def test_duplicate_node_names_are_handled_by_index(pair):
    """T3-M4 has two nodes called FootL, so names cannot address nodes."""
    layout = kl.parse(*pair("p_t3m3"))
    names = [n.name for n in parts.mesh_nodes(layout)]
    assert len(names) != len(set(names))
    indices = kapply.targets(layout, "foot")
    assert len(indices) == len(set(indices))
    mdl, mdx = pair("p_t3m3")
    _, _, result = kapply.apply_to_model(mdl, mdx, {"foot": 1.5}, model_name="p_t3m3")
    assert result.ok
    assert len(result.changes) == len(indices)


def test_unknown_names_are_rejected():
    with pytest.raises(KeyError):
        roster.resolve(["gandalf"])
    with pytest.raises(KeyError):
        keffects.resolve("explode")
