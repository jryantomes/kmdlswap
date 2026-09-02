"""The MDX tangent column, and authoring one.

Twenty-one head models across the two games were refused outright for carrying
this column - every Selkath, the Rakata, Xor, Zhar, Komad, the rakghoul and the
male Twi'leks. Refusing was right while the column was not understood.

The tests that matter here are about the *convention*, because getting it wrong
is invisible: a flipped tangent looks identical in any viewer and lights the
model wrongly in game. So the sign and the slot order are both pinned against
vanilla data rather than asserted from first principles.
"""

from __future__ import annotations

import numpy as np
import pytest

from kmdlswap import edit as ke
from kmdlswap import layout as kl
from kmdlswap import mdx as kmdx
from kmdlswap import tangents as ktangents
from kmdlswap import validate as kv
from kmdlfun.library import ModelLibrary

# Vanilla meshes that carry the column.
CARRIERS = ["n_selkath", "n_rakata", "twilek_m", "n_xorh", "c_rakghoul"]


@pytest.fixture(scope="module")
def k1(install_path):
    return ModelLibrary(str(install_path))


def carrier_geometry(k1, name):
    layout = kl.parse(*k1.read(name))
    node = layout.node_by_name("Head")
    geo = ke.extract(layout, node)
    if "tangent" not in geo.columns:
        pytest.skip(f"{name} has no tangent column in this install")
    return geo


def unit(v):
    n = np.linalg.norm(v, axis=1, keepdims=True)
    return v / np.where(n < 1e-12, 1.0, n)


# --- what the column is -----------------------------------------------------


def test_the_column_is_three_unit_vectors(k1):
    for name in CARRIERS:
        if not k1.has(name):
            continue
        T = np.asarray(carrier_geometry(k1, name).columns["tangent"], float)
        assert T.shape[1] == 9, name
        for s in (ktangents.BITANGENT, ktangents.TANGENT, ktangents.NORMAL):
            lengths = np.linalg.norm(T[:, s], axis=1)
            assert np.allclose(lengths, 1.0, atol=1e-3), (name, s, lengths.mean())


def test_the_last_slot_is_the_normal(k1):
    """Which is what makes the slot order discoverable at all."""
    for name in CARRIERS:
        if not k1.has(name):
            continue
        geo = carrier_geometry(k1, name)
        T = np.asarray(geo.columns["tangent"], float)
        N = unit(np.asarray(geo.columns["normal"], float))
        agreement = np.abs((unit(T[:, ktangents.NORMAL]) * N).sum(1)).mean()
        assert agreement > 0.9, f"{name}: slot 2 agrees with the normal only {agreement:.2f}"


def test_the_middle_slot_is_the_tangent_and_the_first_is_not(k1):
    """The order is (bitangent, tangent, normal), which is not the obvious one.

    Guessing (tangent, bitangent, normal) puts the two the wrong way round and
    nothing about the file says so.
    """
    for name in CARRIERS:
        if not k1.has(name):
            continue
        geo = carrier_geometry(k1, name)
        T = np.asarray(geo.columns["tangent"], float)
        ours = np.asarray(
            ktangents.compute(geo.positions, [f.vertices for f in geo.faces],
                              geo.columns["uv1"], geo.columns["normal"]),
            dtype=float,
        )
        with_middle = np.abs((unit(ours[:, ktangents.TANGENT])
                              * unit(T[:, ktangents.TANGENT])).sum(1)).mean()
        with_first = np.abs((unit(ours[:, ktangents.TANGENT])
                             * unit(T[:, ktangents.BITANGENT])).sum(1)).mean()
        assert with_middle > with_first, (
            f"{name}: our tangent matches slot 0 better than slot 1, so the "
            f"slot order is wrong"
        )


def test_the_sign_convention_matches_the_engines(k1):
    """The one that cannot be checked by eye.

    The engine's tangent is the negative of the standard derivation - measured
    at -0.87 to -0.93 across five meshes, never positive. `compute` applies
    that, so its output must now agree *positively* with vanilla. If this fails
    the tangents are inverted, which no viewer will show and the game will.
    """
    for name in CARRIERS:
        if not k1.has(name):
            continue
        geo = carrier_geometry(k1, name)
        T = np.asarray(geo.columns["tangent"], float)
        ours = np.asarray(
            ktangents.compute(geo.positions, [f.vertices for f in geo.faces],
                              geo.columns["uv1"], geo.columns["normal"]),
            dtype=float,
        )
        signed = ((unit(ours[:, ktangents.TANGENT])
                   * unit(T[:, ktangents.TANGENT])).sum(1)).mean()
        assert signed > 0.8, f"{name}: signed agreement {signed:+.3f}, expected > +0.8"


# --- computing one ----------------------------------------------------------


def test_a_computed_basis_is_well_formed():
    """A unit square, folded so nothing is degenerate."""
    positions = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
    faces = [(0, 1, 2), (0, 2, 3)]
    uvs = [(0, 0), (1, 0), (1, 1), (0, 1)]
    normals = [(0, 0, 1)] * 4

    out = np.asarray(ktangents.compute(positions, faces, uvs, normals), float)
    assert out.shape == (4, 9)
    assert not np.isnan(out).any()
    for s in (ktangents.BITANGENT, ktangents.TANGENT, ktangents.NORMAL):
        assert np.allclose(np.linalg.norm(out[:, s], axis=1), 1.0)
    assert np.allclose(out[:, ktangents.NORMAL], [0, 0, 1])


def test_a_degenerate_uv_triangle_does_not_produce_a_zero_or_a_nan():
    """All three corners on one UV point gives no gradient at all. A zero
    vector there reads in game as a black speck, so a fallback basis is used."""
    positions = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    faces = [(0, 1, 2)]
    uvs = [(0.5, 0.5)] * 3
    normals = [(0, 0, 1)] * 3

    out = np.asarray(ktangents.compute(positions, faces, uvs, normals), float)
    assert not np.isnan(out).any()
    assert (np.linalg.norm(out[:, ktangents.TANGENT], axis=1) > 0.9).all()
    perp = np.abs((out[:, ktangents.TANGENT] * out[:, ktangents.NORMAL]).sum(1))
    assert (perp < 1e-6).all(), "the fallback tangent must lie in the surface"


# --- end to end -------------------------------------------------------------


def test_a_host_that_carries_tangents_can_now_be_transplanted_into(k1):
    """`n_selkath` was refused outright. It now takes a donor and validates,
    with the column authored and the stride untouched."""
    from kmdlfun import transplant as ktp

    if not (k1.has("n_selkath") and k1.has("p_carthh")):
        pytest.skip("need n_selkath and p_carthh")

    mdl, mdx = k1.read("n_selkath")
    donor = kl.parse(*k1.read("p_carthh"))
    before = kmdx.stride_layout(kl.parse(mdl, mdx),
                                kl.parse(mdl, mdx).node_by_name("Head"))

    new_mdl, new_mdx, r = ktp.transplant_node(
        mdl, mdx, donor, "p_carthh", "Head", "Head", fit=True, place=True
    )
    assert r.ok, r.error
    assert "tangent" in r.swap.tangent_source or r.swap.tangent_source

    after = kl.parse(new_mdl, new_mdx)
    assert kv.check(after).ok, "the result must validate"

    node = after.node_by_name("Head")
    stride = kmdx.stride_layout(after, node)
    assert stride.stride == before.stride, "the stride must not change"
    assert set(stride.columns) == set(before.columns)

    geo = ke.extract(after, node)
    T = np.asarray(geo.columns["tangent"], float)
    N = np.asarray(geo.columns["normal"], float)
    assert len(T) == node.vertex_count
    assert not np.isnan(T).any()
    assert np.allclose(T[:, ktangents.NORMAL], N, atol=1e-6), (
        "the third slot should be the mesh's own normals"
    )
    assert (np.linalg.norm(T[:, ktangents.TANGENT], axis=1) > 0.9).all(), (
        "a zero tangent lights as a black speck in game"
    )


def test_the_donors_that_were_blocked_are_now_measurable(k1):
    """They were never really the problem: a donor's tangent column is read,
    not written, so refusing them was over-strict. Both halves are fixed."""
    from kmdlfun import compat

    names = [n for n in CARRIERS if k1.has(n)]
    fits = compat.rank(*k1.read("p_carthh"), k1, names, host_name="p_carthh")

    assert fits, "nothing measured"
    blocked = [f.donor for f in fits if f.blocked]
    assert not blocked, f"still blocked: {blocked}"


# --- the A/B kit ------------------------------------------------------------
#
# The sign is anchored to vanilla by the tests above. What they cannot show is
# whether the engine renders a basis computed for *new* geometry, so the answer
# is a pair of models differing in exactly that one thing.


def test_flipping_negates_the_tangent_and_nothing_else(k1, tmp_path):
    """Bitangent and normal have to survive untouched, or the A/B compares two
    things at once and answers neither."""
    import shutil
    import sys

    import numpy as np

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve()
                           .parent.parent / "tools"))
    import flip_tangents

    from kmdlfun import parts as kparts
    from kmdlswap import layout as kl
    from kmdlswap import mdx as kmdx

    name = next((n for n in CARRIERS if k1.has(n)), None)
    if name is None:
        pytest.skip("no tangent-bearing model in this install")

    source = tmp_path / "src"
    source.mkdir()
    mdl_bytes, mdx_bytes = k1.read(name)
    (source / f"{name}.mdl").write_bytes(mdl_bytes)
    (source / f"{name}.mdx").write_bytes(mdx_bytes)

    touched = flip_tangents.flip(source / f"{name}.mdl",
                                 source / f"{name}.mdx", tmp_path / "out")
    assert touched, "nothing was flipped"

    def column(folder):
        lay = kl.parse((folder / f"{name}.mdl").read_bytes(),
                       (folder / f"{name}.mdx").read_bytes())
        node = next(n for n in kparts.mesh_nodes(lay)
                    if kmdx.stride_layout(lay, n).columns.get("tangent")
                    is not None)
        stride = kmdx.stride_layout(lay, node)
        return np.asarray(kmdx._column(lay.mdx, node,
                                       stride.columns["tangent"],
                                       node.vertex_count, "9f"), float)

    before, after = column(source), column(tmp_path / "out")
    for label, part in (("bitangent", ktangents.BITANGENT),
                        ("normal", ktangents.NORMAL)):
        assert np.allclose(before[:, part], after[:, part]), label
    assert np.allclose(before[:, ktangents.TANGENT],
                       -after[:, ktangents.TANGENT])


def test_a_flipped_model_is_still_valid(k1, tmp_path):
    """Both halves of the pair have to load, or one of them is testing the
    loader rather than the lighting."""
    import sys

    from kmdlswap import layout as kl
    from kmdlswap import validate as kv

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve()
                           .parent.parent / "tools"))
    import flip_tangents

    name = next((n for n in CARRIERS if k1.has(n)), None)
    if name is None:
        pytest.skip("no tangent-bearing model in this install")

    source = tmp_path / "src"
    source.mkdir()
    mdl_bytes, mdx_bytes = k1.read(name)
    (source / f"{name}.mdl").write_bytes(mdl_bytes)
    (source / f"{name}.mdx").write_bytes(mdx_bytes)
    flip_tangents.flip(source / f"{name}.mdl", source / f"{name}.mdx",
                       tmp_path / "out")

    flipped = kl.parse((tmp_path / "out" / f"{name}.mdl").read_bytes(),
                       (tmp_path / "out" / f"{name}.mdx").read_bytes())
    assert kv.check(flipped).ok


def test_a_model_with_no_tangents_reports_nothing_to_flip(k1, tmp_path):
    """Saying so beats writing an identical copy and calling it a test."""
    import sys

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve()
                           .parent.parent / "tools"))
    import flip_tangents

    if not k1.has("p_carthh"):
        pytest.skip("no p_carthh")

    source = tmp_path / "src"
    source.mkdir()
    mdl_bytes, mdx_bytes = k1.read("p_carthh")
    (source / "p_carthh.mdl").write_bytes(mdl_bytes)
    (source / "p_carthh.mdx").write_bytes(mdx_bytes)

    assert flip_tangents.flip(source / "p_carthh.mdl",
                              source / "p_carthh.mdx", tmp_path / "out") == {}
