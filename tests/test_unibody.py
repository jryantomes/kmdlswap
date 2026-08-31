"""Putting a head on a unified body, and custom head packs, from the app.

HK-47 is one model: its head is a node among forty-odd droid-named meshes
rather than a separate head model. That made it invisible to both routes the
app offered. Whole-model pairing needs half the node names to agree and HK-47
shares exactly one with any head model, so its donor list came out empty; and
head packs - the thing that actually put a face on HK-47 in the first place -
were command line only.

Both are about the same distinction: filling *one named node* is a different
job from swapping two whole models, and needs a different test for whether it
can be done.
"""

from __future__ import annotations

import json

import pytest

from kmdlfun import compat, headbuild
from kmdlfun.library import ModelLibrary

UNIBODY = "p_hk47"


@pytest.fixture(scope="module")
def k1(install_path):
    return ModelLibrary(str(install_path))


@pytest.fixture(scope="module")
def vanilla_pack(tmp_path_factory, k1):
    """A head pack made from a vanilla head.

    Real third-party packs fail for their own reasons - the scanned head in
    `packs/` is only 53% solid - and a test about the plumbing should not fail
    for a reason that belongs to the mesh. This one is solid, the right density
    and the right scale by construction.
    """
    from kmdlswap import edit as ke
    from kmdlswap import layout as kl
    from kmdlswap import obj as kobj

    folder = tmp_path_factory.mktemp("pack")
    layout = kl.parse(*k1.read("n_dustilh"))
    geo = ke.extract(layout, layout.node_by_name("Head"))
    uvs = [tuple(u) for u in geo.columns["uv1"]] if "uv1" in geo.columns else None
    kobj.write_obj(
        folder / "head.obj",
        [tuple(p[:3]) for p in geo.positions],
        [f.vertices for f in geo.faces],
        uvs=uvs,
        name="head",
    )
    (folder / "head.json").write_text(json.dumps({
        "name": "Vanilla Head", "target": "head",
        "facing": "y", "up": "z", "anchor": "centre",
    }), encoding="utf-8")
    return folder


# --- the node is the target, not the model ----------------------------------


def test_a_unified_body_has_a_head_node_worth_filling(k1):
    """The thing that made this look impossible, stated as a fact.

    HK-47's head is unskinned - a rigid child node - which is the *easy* case:
    the pack's own topology and UVs are used as they stand, with no weight
    transfer to get wrong.
    """
    from kmdlswap import layout as kl

    layout = kl.parse(*k1.read(UNIBODY))
    head = compat.head_node(layout)

    assert head is not None, "HK-47 has a head node"
    assert head.name == "head"
    assert not head.is_skin, "rigid, so the mesh goes in as authored"


def test_whole_model_pairing_finds_nothing_and_that_is_correct(k1):
    """Not a bug to be fixed - the rule is right for the job it was written for.

    A dewback shares one node name with Carth, a `head` of an entirely
    different shape, while a real donor head shares seven or eight. Coverage is
    what tells those apart. It just cannot answer "can this one node be
    filled", which is a different question.
    """
    from kmdlfun import catalogue as kc
    from kmdlswap import layout as kl

    index = kc.ModelIndex()
    for name in (UNIBODY, "p_carthh", "n_dustilh"):
        index.add(kc.describe(kl.parse(*k1.read(name)), name))

    c = index.compare(UNIBODY, "p_carthh")
    assert not c.usable
    assert c.shared == 1, "exactly one name in common: the head"
    assert c.coverage < 0.05
    assert not index.donors_for(UNIBODY, usable_only=True), (
        "which is why the donor list came out empty"
    )


def test_a_head_donor_measures_well_against_the_unibody_head_node(k1):
    """The geometry was never the problem. Ranking finds plenty of good fits."""
    donors = ["p_carthh", "n_dustilh", "p_missionh", "c_drdspyder"]
    fits = compat.rank(*k1.read(UNIBODY), k1, donors, host_name=UNIBODY)

    assert fits, "no donor could be measured against HK-47's head node"
    good = [f for f in fits if f.grade in ("clean", "good")]
    assert good, f"expected usable donors, got {[(f.donor, f.grade) for f in fits]}"
    assert fits[0].far <= fits[-1].far


# --- head packs, shared by the CLI and the app ------------------------------


def test_a_pack_is_checked_before_anything_is_written(vanilla_pack, install_path):
    result = headbuild.run(
        vanilla_pack, install=str(install_path), host=UNIBODY, node="head",
        fit=True, repair=True, build=False,
    )
    assert result.ok, result.verdict
    assert not result.built, "checking must not build"
    assert result.node_name == "head"
    assert any("solid" in line for line in result.lines)
    assert result.verdict.startswith("ACCEPTED")


def test_a_pack_that_fails_is_refused_and_builds_nothing(install_path, tmp_path):
    """The scanned head in `packs/` is 53% solid - it renders full of holes in
    game while looking fine in any viewer, which is exactly why the check
    exists. A refusal must produce no files."""
    pack = "packs/scanhead"
    import os

    if not os.path.isdir(pack):
        pytest.skip("the scanned head pack is not in this checkout")

    result = headbuild.run(
        pack, install=str(install_path), host=UNIBODY, node="head",
        decimate=690, fit=True, repair=True, build=True,
    )
    assert not result.ok
    assert result.failures
    assert not result.built, "a rejected pack must never be built"
    assert result.verdict.startswith("REJECTED")
    assert headbuild.write(result, tmp_path, UNIBODY) == []
    assert not list(tmp_path.iterdir())


def test_a_pack_builds_into_the_unibody_head_node(vanilla_pack, install_path, tmp_path):
    """The whole point: a mesh from outside the game, onto HK-47."""
    from kmdlswap import layout as kl
    from kmdlswap import validate as kv

    from kmdlfun import parts as kparts

    result = headbuild.run(
        vanilla_pack, install=str(install_path), host=UNIBODY, node="head",
        fit=True, repair=True, build=True,
    )
    assert result.ok, result.verdict
    assert result.built

    after = kl.parse(result.mdl, result.mdx)
    assert kv.check(after).ok, "a build that does not validate is not a build"

    # HK-47's body is untouched: only the head node changed.
    before = kl.parse(*ModelLibrary(str(install_path)).read(UNIBODY))
    was = {n.name: n.vertex_count for n in kparts.mesh_nodes(before)}
    now = {n.name: n.vertex_count for n in kparts.mesh_nodes(after)}
    assert set(was) == set(now), "no mesh node should appear or disappear"
    changed = [k for k in was if was[k] != now[k]]
    assert changed == ["head"], f"only the head should change, got {changed}"

    written = headbuild.write(result, tmp_path, UNIBODY)
    assert {p.name for p in written} == {f"{UNIBODY}.mdl", f"{UNIBODY}.mdx"}
    assert (tmp_path / f"{UNIBODY}.mdl").stat().st_size > 0


def test_hiding_is_a_choice_not_a_default(vanilla_pack, install_path):
    """`hide=None` leaves the host alone; `hide=[]` means "everything else".

    On a head model that default is right - the host's hair and eyes were
    shaped for the face that is gone. On a unified body it would hide the
    entire droid, so the caller has to ask for it.
    """
    from kmdlswap import layout as kl

    from kmdlfun import parts as kparts

    kept = headbuild.run(vanilla_pack, install=str(install_path), host=UNIBODY,
                         node="head", fit=True, build=True, hide=None)
    hidden = headbuild.run(vanilla_pack, install=str(install_path), host=UNIBODY,
                           node="head", fit=True, build=True, hide=[])

    visible_kept = len(kparts.mesh_nodes(kl.parse(kept.mdl, kept.mdx)))
    visible_hidden = len(kparts.mesh_nodes(kl.parse(hidden.mdl, hidden.mdx)))

    assert visible_kept > 40, "HK-47 keeps its body when nothing is asked to hide"
    assert visible_hidden == 1, "hiding everything else leaves only the new head"
