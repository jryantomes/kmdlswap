"""The between-launch cache for whole-install answers.

The point of it is that the second launch does not pay what the first one did,
so the tests are about the two things that can go wrong with that bargain:
serving an answer for the wrong install, and serving a stale one.
"""

from __future__ import annotations

import pytest

from kmdlfun import surveys


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Keep the cache out of the real ~/.kmdlfun."""
    monkeypatch.setattr(surveys, "HOME", tmp_path / "surveys")
    return tmp_path


def fake_install(root, name: str, *, override=()):
    """A folder that looks enough like an install to be fingerprinted."""
    d = root / name
    (d / "Override").mkdir(parents=True)
    (d / "chitin.key").write_bytes(b"KEY ")
    for f in override:
        (d / "Override" / f).write_bytes(b"x")
    return d


def test_the_second_ask_does_not_do_the_work_again(home):
    install = fake_install(home, "swkotor")
    calls = []

    def work():
        calls.append(1)
        return {"p_hk47": "head"}

    assert surveys.cached(install, "kinds", work) == {"p_hk47": "head"}
    assert surveys.cached(install, "kinds", work) == {"p_hk47": "head"}
    assert len(calls) == 1, "the answer should have come off disk the second time"


def test_two_installs_do_not_share_an_answer(home):
    """The whole point is that KOTOR and KOTOR II hold different models, so a
    cache that mixed them up would be worse than no cache at all."""
    one = fake_install(home, "swkotor")
    two = fake_install(home, "kotor2")

    surveys.remember(one, "kinds", {"p_carthh": "head"})
    surveys.remember(two, "kinds", {"p_atton": "head"})

    assert surveys.recall(one, "kinds") == {"p_carthh": "head"}
    assert surveys.recall(two, "kinds") == {"p_atton": "head"}


def test_a_changed_install_throws_the_answer_away(home):
    """A mod dropped into Override changes what every one of these scans would
    find, so the fingerprint has to notice it."""
    install = fake_install(home, "swkotor")
    surveys.remember(install, "droids", {"p_hk47": ["head"]})
    assert surveys.recall(install, "droids") is not None

    (install / "Override" / "p_hk47.mdl").write_bytes(b"modded")
    assert surveys.recall(install, "droids") is None, (
        "a new file in Override must invalidate the cache"
    )


def test_a_repacked_install_throws_the_answer_away(home):
    install = fake_install(home, "swkotor")
    surveys.remember(install, "kinds", {"p_carthh": "head"})
    (install / "chitin.key").write_bytes(b"KEY LONGER NOW")
    assert surveys.recall(install, "kinds") is None


def test_sets_survive_the_round_trip(home):
    """The droid catalogue keeps a set per model and JSON cannot, so it goes
    through `sets` on the way out and `unsets` on the way back."""
    install = fake_install(home, "swkotor")
    cat = {"p_hk47": {"head", "torso"}, "p_t3m3": {"head"}}

    first = surveys.cached(install, "droids", lambda: cat,
                           to_disk=surveys.sets, from_disk=surveys.unsets)
    second = surveys.cached(install, "droids", lambda: pytest.fail("read again"),
                            to_disk=surveys.sets, from_disk=surveys.unsets)
    assert first == cat
    assert second == cat, "sets, not the sorted lists that were written"


def test_forgetting_one_install_leaves_the_other(home):
    one = fake_install(home, "swkotor")
    two = fake_install(home, "kotor2")
    surveys.remember(one, "kinds", {"a": "head"})
    surveys.remember(two, "kinds", {"b": "head"})

    surveys.forget(one)
    assert surveys.recall(one, "kinds") is None
    assert surveys.recall(two, "kinds") == {"b": "head"}

    surveys.forget()
    assert surveys.recall(two, "kinds") is None


def test_a_home_it_cannot_write_is_not_an_error(home, monkeypatch):
    """Being slow is a much better failure than not starting."""
    install = fake_install(home, "swkotor")
    # A file, so `mkdir` cannot make a folder there.
    monkeypatch.setattr(surveys, "HOME", install / "chitin.key" / "nope")
    surveys.remember(install, "kinds", {"a": "head"})       # must not raise
    assert surveys.recall(install, "kinds") is None
    assert surveys.cached(install, "kinds", lambda: {"a": "head"}) == {"a": "head"}


def test_a_missing_install_is_still_answerable(home):
    """`stamp` is asked before anything has checked the folder is real."""
    surveys.remember(home / "not here", "kinds", {})
    assert surveys.recall(home / "not here", "kinds") == {}
