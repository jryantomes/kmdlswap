"""Builds as named, kept folders.

Everything used to land in one directory as `p_carthh.mdl`, so each build
destroyed the last: no keeping two heads side by side, no going back to one
that worked, and no answering "what is this file?" a day later.
"""

from __future__ import annotations

import json

import pytest

from kmdlfun import builds as kbuilds


def make(root, name, files=None, manifest=None):
    return kbuilds.save(
        root, name,
        files or {"p_carthh.mdl": b"model", "p_carthh.mdx": b"mesh"},
        manifest or {"kind": "transplant",
                     "host": {"model": "p_carthh", "game": "K1"},
                     "donor": {"model": "n_bith", "game": "K1"}},
    )


def test_a_build_records_what_it_is(tmp_path):
    build = make(tmp_path, "p_carthh-n_bith")
    on_disk = json.loads((build.path / kbuilds.MANIFEST).read_text(encoding="utf-8"))

    assert on_disk["host"]["model"] == "p_carthh"
    assert on_disk["donor"]["model"] == "n_bith"
    assert on_disk["created"]
    assert {f["name"] for f in on_disk["files"]} == {"p_carthh.mdl", "p_carthh.mdx"}
    assert all(f["md5"] for f in on_disk["files"])


def test_a_second_build_does_not_eat_the_first(tmp_path):
    """The whole point. Both must survive with their own files."""
    first = make(tmp_path, "p_carthh-n_bith")
    name = kbuilds.unique_name(tmp_path, "p_carthh-n_bith")
    second = kbuilds.save(tmp_path, name, {"p_carthh.mdl": b"different"},
                          {"host": {"model": "p_carthh"}})

    assert first.path != second.path
    assert (first.path / "p_carthh.mdl").read_bytes() == b"model"
    assert (second.path / "p_carthh.mdl").read_bytes() == b"different"
    assert len(kbuilds.find(tmp_path)) == 2


def test_a_build_can_be_checked_against_its_own_manifest(tmp_path):
    """So a folder that has been edited by hand says so rather than pretending."""
    build = make(tmp_path, "checkme")
    assert build.check() == []

    (build.path / "p_carthh.mdl").write_bytes(b"tampered")
    assert any("has changed" in p for p in kbuilds.load(build.path).check())

    (build.path / "p_carthh.mdx").unlink()
    assert any("missing" in p for p in kbuilds.load(build.path).check())


def test_a_folder_with_no_manifest_is_still_listed(tmp_path):
    """Output from before this existed, or something dropped in by hand.
    Hiding files the user can plainly see would be worse than listing them."""
    loose = tmp_path / "old_build"
    loose.mkdir()
    (loose / "p_hk47.mdl").write_bytes(b"x")

    found = kbuilds.find(tmp_path)
    assert [b.name for b in found] == ["old_build"]
    assert found[0].manifest.get("unmanaged")


def test_a_folder_with_nothing_in_it_is_not_a_build(tmp_path):
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "readme.txt").write_text("hello")
    assert kbuilds.find(tmp_path) == []


def test_names_are_made_safe_for_the_filesystem(tmp_path):
    build = kbuilds.save(tmp_path, "p_carthh <- n_quarren!!", {"a.mdl": b"x"}, {})
    assert build.path.name == "p_carthh---n_quarren"
    assert build.path.is_dir()


def test_the_summary_says_what_it_came_from(tmp_path):
    build = make(tmp_path, "cross", manifest={
        "host": {"model": "p_carthh", "game": "K1"},
        "donor": {"model": "n_quarren", "game": "K2"},
    })
    assert "p_carthh <- n_quarren" in build.summary
    assert "K2 donor" in build.summary, "a cross-game build should say so"


def test_newest_first(tmp_path):
    a = kbuilds.save(tmp_path, "older", {"x.mdl": b"1"}, {"created": "2020-01-01T00:00:00"})
    b = kbuilds.save(tmp_path, "newer", {"x.mdl": b"2"}, {"created": "2030-01-01T00:00:00"})
    assert [x.name for x in kbuilds.find(tmp_path)] == [b.name, a.name]


def test_a_build_folder_is_what_install_takes(tmp_path):
    """Install used to point at the output directory, which now holds several
    builds and cannot be installed as a unit."""
    from kmdlfun import install as kinstall

    build = make(tmp_path / "store", "one")
    game = tmp_path / "game"
    (game / "Override").mkdir(parents=True)

    plan = kinstall.plan(game, build.path)
    assert {p.name for p in plan.new} == {"p_carthh.mdl", "p_carthh.mdx"}, (
        "the manifest must not be installed alongside the models"
    )


# --- telling heads from bodies ----------------------------------------------


def test_models_are_sorted_by_what_a_head_swap_can_take(pair, install_path):
    """The question is "can I take a head off it", not "is it a head model".

    Those differ: `apply.is_head_model` means "no torso and no limbs", which is
    right for deciding how to scale something and wrong here - a kath hound has
    neither and is not somewhere to get a face.
    """
    from kmdlfun.library import (DONOR_KINDS, ModelLibrary,
                                 character_models, classify)

    lib = ModelLibrary(str(install_path))
    wanted = ["p_carthh", "p_carthbb", "p_hk47", "n_bith", "c_kath"]
    kinds = classify(lib, [n for n in wanted if lib.has(n)])

    assert kinds["p_carthh"] == "head", "a model that is a head"
    assert kinds["p_carthbb"] == "body", "a body has no head to give"
    assert kinds["p_hk47"] == "creature", "self-contained, head inside"
    assert kinds["n_bith"] == "creature"
    if "c_kath" in kinds:
        assert kinds["c_kath"] == "other", "a kath hound has no head node"

    offerable = {n for n, k in kinds.items() if k in DONOR_KINDS}
    assert "p_carthh" in offerable and "p_hk47" in offerable
    assert "p_carthbb" not in offerable


def test_classification_cuts_the_list_down(install_path):
    """The point of it: a donor list of every model is mostly things that
    cannot go on a neck."""
    from kmdlfun.library import (DONOR_KINDS, ModelLibrary, character_models,
                                 classify)

    lib = ModelLibrary(str(install_path))
    names = character_models(str(install_path), lib)
    kinds = classify(lib, names)
    offerable = [n for n, k in kinds.items() if k in DONOR_KINDS]

    assert len(offerable) < len(names) * 0.7, (
        f"{len(offerable)} of {len(names)} - the filter is barely filtering"
    )
    assert len(offerable) > 20, "but it must not throw away most of the good ones"


def test_the_games_own_head_list_is_used_rather_than_a_name_pattern(install_path):
    """Character models are named `p_`, `n_` or `c_` - but heads are not.

    The thirty player-creation heads are `pmhc01` and `pfha03`, and the
    commoner heads are `comm_a_f`. None match the prefix test, so none were
    ever offered: forty-two ordinary human faces, twenty-one of each, invisible
    in every list in the app. `heads.2da` is the game's own answer to "what is
    a head", and it also turns up `ad_saul` and `czerka_com_h`, which follow no
    convention at all.
    """
    from kmdlfun.library import PREFIXES, ModelLibrary, character_models, head_models

    lib = ModelLibrary(str(install_path))
    offered = character_models(str(install_path), lib)

    assert "pfhc01" in offered and "pmhc01" in offered, "player heads are missing"
    assert "comm_a_f" in offered and "comm_a_m" in offered, "commoner heads are missing"
    assert "p_carthh" in offered, "the prefixed models must still be there"

    by_prefix = [n for n in offered if n.startswith(PREFIXES)]
    assert len(offered) > len(by_prefix) + 40, (
        f"only {len(offered) - len(by_prefix)} models came from heads.2da"
    )

    # Every name offered is a model that actually exists. heads.2da points at
    # `p_bastillah`, with two Ls, which is not a file.
    assert all(lib.has(n) for n in offered)
    named = head_models(str(install_path))
    assert "p_bastillah" in named and "p_bastillah" not in offered


def test_the_player_heads_are_usable_donors(install_path):
    """Not just listed - they have to survive classification as somewhere a
    head can come from, or listing them changes nothing."""
    from kmdlfun.library import DONOR_KINDS, ModelLibrary, classify

    lib = ModelLibrary(str(install_path))
    wanted = [n for n in ("pfhc01", "pmhc01", "comm_a_f") if lib.has(n)]
    if not wanted:
        pytest.skip("no player heads in this install")

    kinds = classify(lib, wanted)
    for name in wanted:
        assert kinds[name] in DONOR_KINDS, f"{name} classified as {kinds[name]}"


def test_a_head_knows_which_body_it_is_worn_with(install_path):
    """So a preview can show it where it will sit rather than floating.

    `appearance.2da` pairs each head with a body. A self-contained model has
    none and must say so rather than guessing at one.
    """
    from kmdlfun.library import ModelLibrary, body_for_head

    lib = ModelLibrary(str(install_path))
    assert body_for_head(str(install_path), "p_carthh", lib) == "p_carthbb"
    assert body_for_head(str(install_path), "p_bastilah", lib) == "p_bastilabb"

    for self_contained in ("p_hk47", "p_t3m3"):
        if lib.has(self_contained):
            assert body_for_head(str(install_path), self_contained, lib) is None, (
                f"{self_contained} is its own body"
            )

    # Whatever it returns has to be a model that exists, or the preview breaks.
    for head in ("n_dustilh", "pfhc01", "twilek_m"):
        if lib.has(head):
            body = body_for_head(str(install_path), head, lib)
            assert body is None or lib.has(body), (head, body)

    assert body_for_head(str(install_path), "no_such_head", lib) is None
