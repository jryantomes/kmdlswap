"""Installing into Override, reversibly and without harming other mods."""

from __future__ import annotations

import pytest

from kmdlfun import install as kinstall


@pytest.fixture
def fake_game(tmp_path):
    game = tmp_path / "game"
    (game / "Override").mkdir(parents=True)
    build = tmp_path / "build"
    build.mkdir()
    (build / "p_hk47.mdl").write_bytes(b"model")
    (build / "p_hk47.mdx").write_bytes(b"mesh")
    (build / "tripohead.tga").write_bytes(b"texture")
    (build / "notes.txt").write_text("ignored")
    return game, build


def test_collects_only_installable_files(fake_game):
    _, build = fake_game
    names = {p.name for p in kinstall.collect(build)}
    assert names == {"p_hk47.mdl", "p_hk47.mdx", "tripohead.tga"}


def test_collects_from_one_level_of_subfolders(tmp_path):
    build = tmp_path / "out"
    (build / "bighead").mkdir(parents=True)
    (build / "bighead" / "p_hk47.mdl").write_bytes(b"x")
    assert [p.name for p in kinstall.collect(build)] == ["p_hk47.mdl"]


def test_install_then_remove_restores_override(fake_game):
    game, build = fake_game
    override = game / "Override"

    installed = kinstall.apply(game, build)
    assert set(installed) == {"p_hk47.mdl", "p_hk47.mdx", "tripohead.tga"}
    assert (override / "p_hk47.mdl").read_bytes() == b"model"

    removed = kinstall.remove(game)
    assert set(removed) == set(installed)
    assert not list(override.glob("*.mdl"))
    assert not kinstall.read_manifest(game)


def test_refuses_to_clobber_a_file_it_did_not_install(fake_game):
    """A hand-installed mod must not be silently overwritten."""
    game, build = fake_game
    (game / "Override" / "p_hk47.mdl").write_bytes(b"somebody elses mod")

    p = kinstall.plan(game, build)
    assert [f.name for f in p.foreign] == ["p_hk47.mdl"]
    with pytest.raises(PermissionError, match="did not install"):
        kinstall.apply(game, build)
    assert (game / "Override" / "p_hk47.mdl").read_bytes() == b"somebody elses mod"

    kinstall.apply(game, build, allow_foreign=True)
    assert (game / "Override" / "p_hk47.mdl").read_bytes() == b"model"


def test_remove_leaves_other_mods_alone(fake_game):
    """The case that matters: p_hkrfk sitting next to our p_hk47."""
    game, build = fake_game
    other = game / "Override" / "p_hkrfk.mdl"
    other.write_bytes(b"users own mod")

    kinstall.apply(game, build)
    kinstall.remove(game)

    assert other.is_file()
    assert other.read_bytes() == b"users own mod"


def test_reinstalling_our_own_file_is_not_a_clash(fake_game):
    game, build = fake_game
    kinstall.apply(game, build)
    p = kinstall.plan(game, build)
    assert not p.foreign
    assert len(p.ours) == 3
