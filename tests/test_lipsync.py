"""Making a mouth move for a line nobody recorded.

Confirmed in game on 2026-09-01: KOTOR plays a `.lip` with no `.wav` behind it.
That is what makes this possible at all - the community's route needs the CSLU
toolkit to derive phonemes from a recording, and with no recording there is
nothing to derive from. What is left is a duration and a list of mouth shapes.

These tests are about it being *plausible*, not accurate. Nothing is being
synchronised, so there is nothing to be accurate against.
"""

from __future__ import annotations

import pytest

from kmdlfun import lipsync

# Measured from a shipped line, `nm13aabast01059_`: 4.71s and 38 keyframes.
VANILLA_PER_SECOND = 8.1


def shapes(lip):
    return [k.shape.name for k in lip]


def test_a_line_becomes_a_lip():
    lip = lipsync.build("Hold on. Before you run off.")
    frames = list(lip)

    assert lip.length > 0
    assert len(frames) > 4
    assert frames[0].time == 0.0
    assert all(a.time <= b.time for a, b in zip(frames, frames[1:])), "out of order"
    assert frames[-1].time <= lip.length + 1e-6


def test_it_opens_and_closes_on_neutral():
    """A mouth left open when the line stops is the obvious failure."""
    lip = lipsync.build("Who are you working for?")
    names = shapes(lip)

    assert names[0] == "NEUTRAL"
    assert names[-1] == "NEUTRAL"


def test_the_density_matches_what_the_game_ships():
    """Too few and it gapes, too many and it flutters."""
    lip = lipsync.build("Interested parties. Concerned citizens. "
                        "People who do not care for droids.")
    per_second = len(list(lip)) / lip.length

    assert VANILLA_PER_SECOND * 0.6 < per_second < VANILLA_PER_SECOND * 1.6, per_second


def test_the_shapes_follow_the_letters():
    """Not a phoneme engine, but `m`, `b` and `p` close the lips and it would
    be visibly wrong if they did not."""
    closed = shapes(lipsync.build("Mmm bumpy pumpkin bimbam"))
    assert closed.count("MPB") > len(closed) // 4, closed

    rounded = shapes(lipsync.build("oooo ooze moon"))
    assert "OOH" in rounded

    bitten = shapes(lipsync.build("fifty five vivid favours"))
    assert "FV" in bitten


def test_a_longer_line_takes_longer():
    short = lipsync.build("Yes.")
    long = lipsync.build("Yes, and I would like to explain at considerable "
                         "length exactly why that is the case.")
    assert long.length > short.length


def test_length_is_bounded():
    """A stray field of text should not produce a five minute mouth."""
    assert lipsync.build("a").length >= lipsync.MIN_LENGTH
    assert lipsync.build("word " * 5000).length <= lipsync.MAX_LENGTH


def test_a_given_length_wins():
    lip = lipsync.build("Short line.", seconds=7.5)
    assert lip.length == pytest.approx(7.5)
    assert len(list(lip)) > 20, "it should fill the time it was given"


def test_punctuation_and_junk_do_not_break_it():
    for text in ("...", "!!!", "12345", "-- ?? --", "Ω≈ç√"):
        lip = lipsync.build(text)
        assert list(lip), f"no frames for {text!r}"
        assert lip.length >= lipsync.MIN_LENGTH


def test_it_writes_a_file_the_game_format_can_read(tmp_path):
    from pykotor.resource.formats.lip import read_lip

    path = tmp_path / "test.lip"
    size = lipsync.write("Hold on there.", path)

    assert size == path.stat().st_size > 0
    back = read_lip(path.read_bytes())
    assert back.length == pytest.approx(lipsync.build("Hold on there.").length)
    assert list(back)


def test_shapes_are_ones_the_format_knows():
    from pykotor.resource.formats.lip import LIPShape

    known = {s.name for s in LIPShape}
    for mapping in (lipsync.DIGRAPHS, lipsync.LETTERS):
        assert set(mapping.values()) <= known, set(mapping.values()) - known
