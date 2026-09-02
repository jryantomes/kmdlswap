"""What the app remembers about how somebody likes to use it.

Kept apart from `installs`, which remembers where the games are: that is a fact
about the machine and is re-checked every launch, while this is a choice a
person made and should survive being wrong.
"""

from __future__ import annotations

from kmdlfun import prefs


def test_a_preference_survives_a_round_trip(tmp_path):
    config = tmp_path / "prefs.json"
    prefs.remember(prefs.MODE, prefs.ADVANCED, config)

    assert prefs.recall(prefs.MODE, path=config) == prefs.ADVANCED
    assert prefs.mode(config) == prefs.ADVANCED


def test_remembering_one_thing_keeps_the_others(tmp_path):
    config = tmp_path / "prefs.json"
    prefs.save({"colour": "green", prefs.MODE: prefs.ADVANCED}, config)
    prefs.remember(prefs.MODE, prefs.BASIC, config)

    assert prefs.recall("colour", path=config) == "green"


def test_basic_is_what_a_new_install_gets(tmp_path):
    """The setting exists to help newcomers, and new is their common case."""
    assert prefs.mode(tmp_path / "nothing.json") == prefs.BASIC


def test_an_unreadable_file_falls_back_rather_than_failing(tmp_path):
    """A preference is never worth failing to start over."""
    config = tmp_path / "prefs.json"
    config.write_text("{not json", encoding="utf-8")

    assert prefs.load(config) == {}
    assert prefs.mode(config) == prefs.BASIC


def test_a_value_that_means_nothing_any_more_falls_back(tmp_path):
    config = tmp_path / "prefs.json"
    prefs.save({prefs.MODE: "expert"}, config)

    assert prefs.mode(config) == prefs.BASIC


def test_a_missing_folder_is_created(tmp_path):
    config = tmp_path / "deep" / "down" / "prefs.json"
    prefs.remember(prefs.MODE, prefs.BASIC, config)

    assert config.is_file()
