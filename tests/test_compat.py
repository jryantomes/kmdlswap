"""Ranking donors by how well they will sit on a host.

The donor list is a few hundred names in no useful order, and building one to
find out costs minutes. These tests are mostly about the ranking meaning
something: that its numbers reproduce the vanilla calibration it claims to be
graded against, and that the one donor we have real in-game experience of comes
out where that experience says it should.
"""

from __future__ import annotations

import pytest

from kmdlfun import compat
from kmdlfun.library import ModelLibrary

HOST = "p_carthh"


@pytest.fixture(scope="module")
def k1(install_path):
    return ModelLibrary(str(install_path))


def measure_one(k1, donor):
    fits = compat.rank(*k1.read(HOST), k1, [donor], host_name=HOST)
    assert fits, f"{donor} produced no measurement"
    return fits[0]


def test_a_head_on_itself_is_a_perfect_fit(k1):
    """The identity case, and the only one with an answer known in advance.

    If Carth's own head does not sit perfectly in Carth's own head node, the
    measurement is wrong and nothing else it says can be trusted.
    """
    fit = measure_one(k1, HOST)
    assert fit.far == 0.0
    assert fit.mean == pytest.approx(0.0, abs=1e-6)
    assert fit.grade == "clean"
    assert fit.own_weights, "a model's own rig must match itself"


def test_the_grades_reproduce_the_vanilla_calibration(k1):
    """The thresholds are vanilla's own percentiles, so vanilla must land in
    them. If most shipped heads graded 'hard', the scale would be describing
    the game as broken rather than describing the donor."""
    from kmdlfun.library import DONOR_KINDS, classify

    names = sorted(n for n in k1.index if n.startswith(("p_", "n_")) and k1.has(n))
    donors = [n for n, k in classify(k1, names).items() if k in DONOR_KINDS]
    fits = [f for f in compat.rank(*k1.read(HOST), k1, donors, host_name=HOST)
            if not f.blocked]

    graded = [f.grade for f in fits]
    assert graded.count("clean") > len(graded) * 0.5, (
        "over half the shipped heads should be no stranger to Carth than "
        f"the median one; got {graded.count('clean')} of {len(graded)}"
    )
    assert not [f for f in fits if f.grade == "hard"], (
        "nothing the game ships should score worse than the worst thing the "
        f"game ships: {[f.donor for f in fits if f.grade == 'hard']}"
    )
    assert max(f.far for f in fits) <= compat.VANILLA_WORST + 1e-6


def test_best_first(k1):
    fits = compat.rank(*k1.read(HOST), k1, [HOST, "n_rodian", "n_dustilh"],
                       host_name=HOST)
    assert [f.donor for f in fits] == [HOST, "n_dustilh", "n_rodian"]


def test_a_donor_shaped_nothing_like_the_host_ranks_below_one_that_is(k1):
    """`n_rodian` is the vanilla head furthest from a human one that still
    ships and works, so it must rank below an ordinary human head without being
    refused outright - it is a donor this project has actually used."""
    rodian = measure_one(k1, "n_rodian")
    human = measure_one(k1, "n_dustilh")

    assert rodian.far > human.far
    assert rodian.grade == "rough"
    assert not rodian.blocked, "a usable donor must not be refused"


def test_no_vanilla_head_is_refused_any_more(k1):
    """`n_selkath` and ten others were refused for carrying a tangent column.

    That column is now authored, and it was the last one any head in the game
    carries - so every vanilla head is reachable. The refusal path still exists
    for a column this tool genuinely cannot invent; `uv2` is the remaining one,
    and no head has it.
    """
    names = [n for n in ("n_selkath", "n_rakata", "n_xorh", "twilek_m",
                         "c_rakghoul", "n_dustilh") if k1.has(n)]
    fits = compat.rank(*k1.read(HOST), k1, names, host_name=HOST)

    blocked = [f.donor for f in fits if f.blocked]
    assert not blocked, f"still refused: {blocked}"


def test_a_refused_donor_is_reported_rather_than_dropped():
    """The mechanism, without needing a model that trips it: a refusal has to
    be visible in the list and sort below everything usable, never vanish."""
    good = compat.Fit(donor="fine", donor_node="Head", host=HOST,
                      host_node="head", far=0.30)
    bad = compat.Fit(donor="nope", donor_node="Head", host=HOST,
                     host_node="head", blocked="donor 'Head' carries uv2")

    assert bad.grade == "blocked"
    assert "uv2" in bad.line and "uv2" in " ".join(bad.notes())
    assert sorted([bad, good], key=lambda f: f.rank_key)[-1] is bad, (
        "blocked donors sort last, never above a usable one"
    )


def test_a_name_the_library_does_not_have_is_skipped(k1):
    fits = compat.rank(*k1.read(HOST), k1, ["no_such_model", HOST], host_name=HOST)
    assert [f.donor for f in fits] == [HOST]


def test_the_notes_say_what_the_number_does_not(k1):
    """The number is one axis. Whether a donor needs fitting, needs decimating
    or brings extra parts are separate facts, and folding them into the score
    would hide the detail that decides whether it is worth trying."""
    fit = measure_one(k1, "n_rodian")
    assert fit.notes() is not None

    oversized = compat.Fit(donor="x", donor_node="Head", host=HOST,
                           host_node="head", far=0.02, size_ratio=2.6,
                           vertices=9000, extra_parts=["tent01", "tent02"])
    notes = " ".join(oversized.notes())
    assert "--fit" in notes
    assert "--decimate" in notes
    assert "tent01" in notes


def test_summarise_counts_by_grade():
    fits = [
        compat.Fit(donor="a", donor_node="Head", host="h", host_node="head", far=0.0),
        compat.Fit(donor="b", donor_node="Head", host="h", host_node="head", far=0.30),
        compat.Fit(donor="c", donor_node="Head", host="h", host_node="head",
                   blocked="nope"),
    ]
    assert compat.summarise(fits) == "1 clean, 1 hard, 1 blocked"


# --- K2 donors --------------------------------------------------------------


def test_a_k2_donor_can_be_ranked_against_a_k1_host(k1, k2):
    """The reason this exists: K2 offers 128 donors and no way to tell which
    are worth building."""
    fits = compat.rank(*k1.read(HOST), k2, ["n_duros", "n_quarren"], host_name=HOST)
    assert len(fits) == 2
    assert all(f.vertices > 0 for f in fits)


def test_the_quarren_ranks_the_way_it_actually_built(k1, k2):
    """The one donor with real in-game experience behind it.

    Built onto Carth it needed fitting, animated correctly once its own weights
    came across, and left two of its four mouth tentacles hanging wrong. A
    ranking that called it a clean fit would be lying about the only case we
    can check.
    """
    fit = compat.rank(*k1.read(HOST), k2, ["n_quarren"], host_name=HOST)[0]

    assert fit.grade == "rough", "not a clean fit, and the list should say so"
    assert fit.size_ratio > 1.5, "it is much wider than a human head"
    assert fit.own_weights, "its own weights do come across - that is why it animates"
    assert len(fit.extra_parts) == 4, f"four tentacles, got {fit.extra_parts}"

    notes = " ".join(fit.notes())
    assert "--fit" in notes and "tent01" in notes
