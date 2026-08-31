"""Renaming a model, so a build can be added instead of substituting a vanilla one.

Dropping `p_carthh.mdl` into Override replaces Carth for the whole game and two
builds cannot coexist. A new resref is what a modder needs, and the filename is
not enough - the model carries its own name inside it.

Most of these tests are about what must *not* change. The name appears in
several roles and two of them are traps: a texture whose name starts with the
model's, and an animation field that usually holds the model name and sometimes
holds a node's.
"""

from __future__ import annotations

import struct

import pytest

from kmdlswap import layout as kl
from kmdlswap import rename as krename
from kmdlswap import validate as kv
from kmdlfun import parts as kparts
from kmdlfun import render as krender
from kmdlfun.library import ModelLibrary

MDL_BASE = 12


@pytest.fixture(scope="module")
def k1(install_path):
    return ModelLibrary(str(install_path))


def anim_roots(mdl: bytes) -> list[str]:
    array_offset, count = struct.unpack_from("<II", mdl, MDL_BASE + 88)
    if not count or array_offset in (0, 0xFFFFFFFF):
        return []
    out = []
    for offset in struct.unpack_from("<%dI" % count, mdl, MDL_BASE + array_offset):
        at = MDL_BASE + offset + 88
        out.append(mdl[at:at + 32].split(b"\0")[0].decode("ascii", "replace"))
    return out


def textures(layout) -> set[str]:
    return {krender.node_texture(layout, n) for n in kparts.mesh_nodes(layout)} - {""}


# --- it works ---------------------------------------------------------------


@pytest.mark.parametrize("new", ["p_myhead", "p_x", "p_a_very_long_custom_head_name"])
def test_a_renamed_model_still_validates(k1, new):
    """Shorter, longer and about the same. The name table is a packed run of
    strings, so a length change moves everything after it - which is the splice
    engine's job and the reason this does not patch bytes by hand."""
    mdl, mdx = k1.read("p_carthh")
    out, outx = krename.rename(mdl, mdx, new)
    after = kl.parse(out, outx)

    assert kv.check(after).ok, f"{new} did not validate"
    assert after.model_name == new
    assert outx == mdx, "the MDX holds no names and must come back unchanged"


def test_the_root_node_is_renamed_too(k1):
    """The engine finds the model's root by name, and it is named after the
    model. Renaming one without the other leaves them disagreeing."""
    mdl, mdx = k1.read("p_carthh")
    before = kl.parse(mdl, mdx)
    root = [n for n in before.nodes if n.in_animation is None][0]
    assert root.name == before.model_name

    out, outx = krename.rename(mdl, mdx, "p_myhead")
    after = kl.parse(out, outx)
    assert [n for n in after.nodes if n.in_animation is None][0].name == "p_myhead"


def test_nothing_else_moves(k1):
    """Node and animation counts, and the geometry itself."""
    mdl, mdx = k1.read("p_carthh")
    before = kl.parse(mdl, mdx)
    out, outx = krename.rename(mdl, mdx, "p_myhead")
    after = kl.parse(out, outx)

    assert len(after.nodes) == len(before.nodes)
    assert after.animation_names == before.animation_names
    assert after.supermodel == before.supermodel
    for a, b in zip(kparts.mesh_nodes(before), kparts.mesh_nodes(after)):
        assert a.name == b.name or a.name == before.model_name
        assert a.vertex_count == b.vertex_count


# --- the two traps ----------------------------------------------------------


def test_the_texture_is_not_renamed(k1):
    """Carth's model is `P_CarthH` and his texture is `P_CarthH01`.

    A search-and-replace across the file renames eight texture references and
    produces an untextured character that passes every validator.
    """
    mdl, mdx = k1.read("p_carthh")
    before = textures(kl.parse(mdl, mdx))
    out, outx = krename.rename(mdl, mdx, "p_myhead")

    assert textures(kl.parse(out, outx)) == before == {"P_CarthH01"}


@pytest.mark.parametrize(("model", "keep"),
                         [("p_hk47", {"InnerTorso", "talkdummy"}),
                          ("p_t3m3", {"Neck"})])
def test_animations_rooted_at_a_node_keep_that_node(k1, model, keep):
    """The animation field at +88 usually holds the model name and sometimes a
    node's. Two of HK-47's seventy-five animations are rooted at `InnerTorso`
    and `talkdummy`; rewriting those re-roots them onto a node that no longer
    answers to the name.
    """
    if not k1.has(model):
        pytest.skip(f"{model} not in this install")
    mdl, mdx = k1.read(model)
    old = kl.parse(mdl, mdx).model_name

    out, _ = krename.rename(mdl, mdx, "p_renamed")
    roots = set(anim_roots(out))

    assert keep <= roots, f"lost {keep - roots}"
    assert old not in roots, "the model's own name should be gone"
    assert "p_renamed" in roots


# --- refusing ---------------------------------------------------------------


@pytest.mark.parametrize("bad", ["", "has space", "p-dash", "x" * 32, "p_é"])
def test_a_name_the_engine_cannot_use_is_refused(bad):
    with pytest.raises(krename.RenameError):
        krename.check_name(bad)


def test_renaming_to_the_same_name_changes_nothing(k1):
    mdl, mdx = k1.read("p_carthh")
    out, outx = krename.rename(mdl, mdx, "P_CarthH")
    assert out == mdl and outx == mdx


def test_the_name_survives_a_round_trip(k1):
    mdl, mdx = k1.read("p_carthh")
    once, oncex = krename.rename(mdl, mdx, "p_temporary_name")
    back, backx = krename.rename(once, oncex, "P_CarthH")

    assert kl.parse(back, backx).model_name == "P_CarthH"
    assert kv.check(kl.parse(back, backx)).ok
    assert len(back) == len(mdl), "back to the original size"


@pytest.mark.slow
def test_every_head_in_the_game_can_be_renamed(k1, install_path):
    from kmdlfun.library import DONOR_KINDS, character_models, classify

    names = [n for n, k in classify(k1, character_models(str(install_path), k1)).items()
             if k in DONOR_KINDS]
    bad = []
    for name in names:
        try:
            out, outx = krename.rename(*k1.read(name), "p_renamed")
            if not kv.check(kl.parse(out, outx)).ok:
                bad.append(name)
        except Exception as exc:  # noqa: BLE001
            bad.append(f"{name}: {type(exc).__name__}: {exc}")
    assert not bad, bad[:10]
