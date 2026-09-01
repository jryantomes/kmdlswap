"""Finding the games without being told where they are.

The app used to carry three hardcoded folders per game and pick the first that
existed. That works on the machine the list was written on; anywhere else it
produced an empty box, which reads as a broken app rather than as one that has
not looked hard enough.

The rule that matters here is that identification never trusts a folder name.
`chitin.key` means "an Aurora game" and nothing more - both KOTOR games have
one - so the executable decides.
"""

from __future__ import annotations

import json

import pytest

from kmdlfun import installs


def make_game(root, key, *, exe=None, chitin=True):
    """A folder that looks like an install, or deliberately does not."""
    game = next(g for g in installs.GAMES if g.key == key)
    root.mkdir(parents=True, exist_ok=True)
    if chitin:
        (root / "chitin.key").write_bytes(b"KEY V1  ")
    (root / (exe or game.exe[0])).write_bytes(b"MZ")
    return root


# --- identifying a folder ---------------------------------------------------


def test_a_folder_is_identified_by_its_executable(tmp_path):
    assert installs.identify(make_game(tmp_path / "swkotor", installs.K1)) == installs.K1
    assert installs.identify(make_game(tmp_path / "k2", installs.K2)) == installs.K2
    assert installs.identify(make_game(tmp_path / "je", installs.JADE)) == installs.JADE


def test_the_folder_name_is_never_what_decides(tmp_path):
    """Somebody's KOTOR II lives in a folder called `swkotor`. Trusting the
    name would hand the app the wrong game and every model would be wrong."""
    odd = make_game(tmp_path / "swkotor", installs.K2)

    assert installs.identify(odd) == installs.K2


def test_chitin_alone_is_not_enough(tmp_path):
    """Both KOTOR games have one, so it cannot tell them apart, and plenty of
    other Aurora games have one too."""
    folder = tmp_path / "something"
    folder.mkdir()
    (folder / "chitin.key").write_bytes(b"KEY V1  ")

    assert installs.identify(folder) is None


def test_an_executable_without_the_data_is_not_an_install(tmp_path):
    """A shortcut folder, or a half-deleted install."""
    folder = make_game(tmp_path / "swkotor", installs.K1, chitin=False)

    assert installs.identify(folder) is None


def test_asking_about_nothing_is_not_an_error(tmp_path):
    assert installs.identify(tmp_path / "does_not_exist") is None
    assert installs.identify(tmp_path / "empty") is None


# --- Steam's own index ------------------------------------------------------


def test_the_steam_index_is_read_for_libraries_on_other_drives(tmp_path,
                                                               monkeypatch):
    """The case the hardcoded list could never cover: a game on D: because the
    first drive filled up."""
    steam = tmp_path / "Steam"
    (steam / "steamapps").mkdir(parents=True)
    other = tmp_path / "OtherDrive"
    (other / "steamapps" / "common").mkdir(parents=True)
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n'
        f'\t"0"\n\t{{\n\t\t"path"\t\t"{str(steam).replace(chr(92), chr(92) * 2)}"\n\t}}\n'
        f'\t"1"\n\t{{\n\t\t"path"\t\t"{str(other).replace(chr(92), chr(92) * 2)}"\n\t}}\n}}\n',
        encoding="utf-8")
    monkeypatch.setattr(installs, "STEAM_ROOTS", (str(steam),))
    monkeypatch.setattr(installs, "OTHER_ROOTS", ())

    libraries = installs.steam_libraries()
    assert other in libraries

    make_game(other / "steamapps" / "common" / "swkotor", installs.K1)
    found = installs.look()

    assert found.get(installs.K1) == str(other / "steamapps" / "common" / "swkotor")
    assert "Steam library" in found.how[installs.K1]


def test_a_renamed_steam_folder_is_still_found(tmp_path, monkeypatch):
    """People rename these. The name is a hint about where to look, not the
    test for what it is."""
    steam = tmp_path / "Steam"
    common = steam / "steamapps" / "common"
    common.mkdir(parents=True)
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        f'"path"\t\t"{str(steam).replace(chr(92), chr(92) * 2)}"', encoding="utf-8")
    monkeypatch.setattr(installs, "STEAM_ROOTS", (str(steam),))
    monkeypatch.setattr(installs, "OTHER_ROOTS", ())

    make_game(common / "kotor but modded", installs.K1)
    found = installs.look()

    assert found.get(installs.K1).endswith("kotor but modded")


def test_a_missing_steam_is_not_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(installs, "STEAM_ROOTS", (str(tmp_path / "nope"),))
    assert installs.steam_libraries() == []


def test_nothing_installed_gives_an_empty_answer_not_a_crash(tmp_path,
                                                             monkeypatch):
    monkeypatch.setattr(installs, "STEAM_ROOTS", ())
    monkeypatch.setattr(installs, "OTHER_ROOTS", ())
    found = installs.look()

    assert found.paths == {}
    assert found.get(installs.K1) == ""


# --- remembering ------------------------------------------------------------


def test_what_was_found_is_remembered(tmp_path):
    config = tmp_path / "installs.json"
    game = make_game(tmp_path / "swkotor", installs.K1)

    installs.save({installs.K1: str(game)}, config)
    assert json.loads(config.read_text())[installs.K1] == str(game)
    assert installs.remembered(installs.K1, config) == str(game)


def test_a_remembered_path_that_is_gone_is_not_offered(tmp_path):
    """An uninstalled game, or a drive that is not plugged in. Handing back a
    dead path is worse than handing back nothing."""
    config = tmp_path / "installs.json"
    installs.save({installs.K1: str(tmp_path / "vanished")}, config)

    assert installs.remembered(installs.K1, config) == ""


def test_a_remembered_path_that_is_now_a_different_game_is_refused(tmp_path):
    config = tmp_path / "installs.json"
    swapped = make_game(tmp_path / "swkotor", installs.K2)
    installs.save({installs.K1: str(swapped)}, config)

    assert installs.remembered(installs.K1, config) == ""


def test_a_corrupt_config_is_ignored(tmp_path):
    config = tmp_path / "installs.json"
    config.write_text("{not json at all", encoding="utf-8")

    assert installs.load(config) == {}
    assert installs.remembered(installs.K1, config) == ""


def test_detect_prefers_what_it_already_knows(tmp_path, monkeypatch):
    """The search should happen once, not on every launch."""
    config = tmp_path / "installs.json"
    game = make_game(tmp_path / "swkotor", installs.K1)
    installs.save({installs.K1: str(game)}, config)

    called = []
    monkeypatch.setattr(installs, "look",
                        lambda **kw: called.append(kw) or installs.Found())

    found = installs.detect(config=config)
    assert found.get(installs.K1) == str(game)
    assert found.how[installs.K1] == "remembered"
    # It still looks for the games it has no answer for.
    assert called, "it should still search for the ones it does not know"


def test_detect_can_be_told_to_ignore_the_cache(tmp_path, monkeypatch):
    config = tmp_path / "installs.json"
    installs.save({installs.K1: str(make_game(tmp_path / "a", installs.K1))},
                  config)
    monkeypatch.setattr(installs, "look", lambda **kw: installs.Found())

    assert installs.detect(config=config, use_cache=False).get(installs.K1) == ""


# --- against the real machine -----------------------------------------------


def test_it_finds_this_machines_install(install_path):
    """`install_path` is the fixture the rest of the suite runs against, so if
    detection cannot find it, detection is wrong."""
    found = installs.look()
    got = found.get(installs.K1)

    assert got, f"searched {found.searched}"
    assert installs.identify(got) == installs.K1


def test_looking_is_quick_enough_to_do_on_startup(install_path):
    """It runs on the way up, so it cannot take a noticeable moment."""
    import time

    start = time.monotonic()
    installs.look()
    assert time.monotonic() - start < 5.0
