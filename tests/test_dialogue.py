"""Giving a whole conversation a mouth.

The engine side of this was settled in game on 2026-09-01: a `.lip` plays with
no recording behind it, and 26 generated files drove the broker's conversation
from end to end. What is tested here is the bookkeeping around that - which
lines get a file, what they are named, and the promise that the dialogue the
modder points at is not the one that gets written to.
"""

from __future__ import annotations

import pytest

from kmdlfun import dialogue as kdlg


def build_dlg(entries, replies=(), *, named=False):
    """A dialogue in memory, so these tests need no install.

    `named` gives every line a VO_ResRef up front, which is the difference
    between a dialogue that needs assigning and one that does not.
    """
    from pykotor.common.language import LocalizedString
    from pykotor.common.misc import ResRef
    from pykotor.resource.formats.gff import GFF, GFFList, bytes_gff

    gff = GFF()
    for listname, texts, tag in ((kdlg.ENTRIES, entries, "e"),
                                 (kdlg.REPLIES, replies, "r")):
        items = gff.root.set_list(listname, GFFList())
        for i, text in enumerate(texts):
            struct = items.add(i)
            struct.set_locstring("Text", LocalizedString.from_english(text))
            struct.set_resref("VO_ResRef",
                              ResRef(f"vo{tag}{i:02d}" if named and text else ""))
    return bytes_gff(gff)


@pytest.fixture
def dlg(tmp_path):
    def write(entries, replies=(), *, named=False, name="talk.dlg"):
        path = tmp_path / name
        path.write_bytes(build_dlg(entries, replies, named=named))
        return path
    return write


@pytest.fixture
def out(tmp_path):
    return tmp_path / "lips"


LINES = ["Hold on. Before you run off.",
         "Interested parties. Concerned citizens.",
         "Smart. Enough credits to make a difference."]


# --- what gets a file -------------------------------------------------------


def test_every_spoken_line_gets_a_lip(dlg, out):
    job = kdlg.run(dlg(LINES, named=True), out)

    assert job.written == 3
    assert all(p.is_file() and p.stat().st_size > 0 for p in job.files)
    assert {p.suffix for p in job.files} == {".lip"}


def test_a_line_with_no_text_is_structure_not_speech(dlg, out):
    """Branches and end nodes carry no Text. A lip for one is a file the
    engine will never ask for."""
    job = kdlg.run(dlg(["Something.", "", "   ", "Else."], named=True), out)

    assert job.written == 2


def test_replies_are_left_out_unless_asked_for(dlg, out):
    source = dlg(LINES, ["Who wants to know?", "Not interested."], named=True)

    assert kdlg.run(source, out).written == 3
    assert kdlg.run(source, out, replies=True).written == 5


def test_a_missing_dialogue_says_so(tmp_path):
    with pytest.raises(kdlg.DialogueError, match="no such dialogue"):
        kdlg.run(tmp_path / "nothing.dlg", tmp_path / "out")


# --- naming the lines -------------------------------------------------------


def test_lines_with_no_vo_resref_are_skipped_and_counted(dlg, out):
    """Silently writing nothing would look like the tool had failed."""
    job = kdlg.run(dlg(LINES), out, assign=False)

    assert job.written == 0
    assert job.skipped == 3
    assert "assigning gives them one" in " ".join(kdlg.summarise(job))


def test_assigning_names_them_and_writes_the_dialogue_beside_the_lips(dlg, out):
    """The bug this replaced wrote all 26 lips and then crashed here, on the
    one path the feature exists for: `source` was the dialogue path and was
    also rebound to a timing label inside the loop."""
    job = kdlg.run(dlg(LINES), out, assign=True)

    assert job.written == 3
    assert job.assigned == 3
    assert job.dialogue_copy is not None
    assert job.dialogue_copy.is_file()
    assert job.dialogue_copy.name == "talk.dlg"


def test_the_original_dialogue_is_never_touched(dlg, out):
    source = dlg(LINES)
    before = source.read_bytes()

    job = kdlg.run(source, out, assign=True)

    assert source.read_bytes() == before, "it edited the modder's file"
    assert job.dialogue_copy != source


def test_the_copy_actually_carries_the_new_names(dlg, out):
    from pykotor.resource.formats.gff import read_gff

    job = kdlg.run(dlg(LINES), out, assign=True)
    items = read_gff(job.dialogue_copy.read_bytes()).root.get_list(kdlg.ENTRIES)
    names = [str(items.at(i).value("VO_ResRef")) for i in range(3)]

    assert all(names), "a line was left unnamed"
    assert {n.lower() for n in names} == {p.stem.lower() for p in job.files
                                          if p.suffix == ".lip"}


def test_a_name_fits_the_field(dlg, out):
    """VO_ResRef is 16 bytes. A longer one is truncated by the writer, and two
    lines that truncate to the same thing overwrite each other's lip."""
    source = dlg(LINES, name="a_very_long_dialogue_name.dlg")
    job = kdlg.run(source, out, assign=True)

    assert all(len(line.vo) <= kdlg.RESREF_MAX for line in job.lines)
    assert len({line.vo for line in job.lines}) == job.written


def test_replies_and_entries_do_not_collide(dlg, out):
    """Both lists are indexed from zero, so the tag is what keeps entry 0 and
    reply 0 apart."""
    job = kdlg.run(dlg(["Entry nought."], ["Reply nought."]), out,
                   assign=True, replies=True)

    assert len({line.vo for line in job.lines}) == 2


def test_a_dialogue_that_already_names_its_lines_keeps_those_names(dlg, out):
    job = kdlg.run(dlg(LINES, named=True), out, assign=True)

    assert job.assigned == 0
    assert job.dialogue_copy is None, "nothing changed, so nothing to install"
    assert [line.vo for line in job.lines] == ["voe00", "voe01", "voe02"]


# --- how long each one runs -------------------------------------------------


def wav(seconds, *, byte_rate=22050):
    import struct

    fmt = struct.pack("<HHIIHH", 1, 1, byte_rate, byte_rate, 1, 8)
    body = bytes(int(byte_rate * seconds))
    chunks = (b"fmt " + struct.pack("<I", len(fmt)) + fmt
              + b"data" + struct.pack("<I", len(body)) + body)
    return b"RIFF" + struct.pack("<I", len(chunks) + 4) + b"WAVE" + chunks


def test_without_recordings_the_length_is_estimated(dlg, out):
    job = kdlg.run(dlg(LINES, named=True), out)

    assert job.estimated == 3
    assert job.timed == 0
    assert all(line.seconds > 0 for line in job.lines)


def test_a_recording_sets_the_length_of_its_own_line(dlg, out, tmp_path):
    """The point of the feature: the mouth moves for as long as the voice
    does, not for as long as the word count guessed."""
    audio = tmp_path / "vo"
    audio.mkdir()
    (audio / "voe00.wav").write_bytes(wav(9.0))

    job = kdlg.run(dlg(LINES, named=True), out, audio=audio)
    timed = next(line for line in job.lines if line.vo == "voe00")

    assert job.timed == 1
    assert job.estimated == 2, "lines with no recording still get a lip"
    assert timed.seconds == pytest.approx(9.0, abs=0.05)
    assert timed.timing == "voe00.wav"


def test_a_recording_that_cannot_be_read_is_reported_not_guessed(dlg, out,
                                                                 tmp_path):
    """Shipped voice is MP3 behind a WAV header. A confident wrong length
    makes a lip that silently drifts against audio that is playing."""
    audio = tmp_path / "vo"
    audio.mkdir()
    (audio / "voe00.wav").write_bytes(b"not audio, not even slightly" * 8)

    job = kdlg.run(dlg(LINES, named=True), out, audio=audio)

    assert job.unreadable == ["voe00.wav"]
    assert job.timed == 0
    assert job.estimated == 3, "it fell back rather than believing the header"
    assert "could not read a length" in " ".join(kdlg.summarise(job))


def test_a_forced_length_wins_over_everything(dlg, out, tmp_path):
    audio = tmp_path / "vo"
    audio.mkdir()
    (audio / "voe00.wav").write_bytes(wav(9.0))

    job = kdlg.run(dlg(LINES, named=True), out, audio=audio, seconds=4.0)

    assert {line.seconds for line in job.lines} == {4.0}
    assert {line.timing for line in job.lines} == {"given"}


# --- what it reports back ---------------------------------------------------


def test_progress_knows_where_it_ends(dlg, out):
    """A bar with no denominator is worse than no bar."""
    seen = []
    kdlg.run(dlg(LINES, named=True), out,
             progress=lambda n, total, vo: seen.append((n, total)))

    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_the_summary_says_what_still_needs_a_decision(dlg, out):
    job = kdlg.run(dlg(LINES), out, assign=True)
    text = " ".join(kdlg.summarise(job))

    assert "3 lip file(s) written" in text
    assert "The original was not touched" in text
    assert "estimated from the word count" in text


def test_the_summary_does_not_run_on_for_a_long_conversation(dlg, out):
    job = kdlg.run(dlg([f"Line number {i}." for i in range(30)], named=True), out)
    lines = kdlg.summarise(job)

    assert job.written == 30
    assert any("and 26 more" in line for line in lines)
    assert len(lines) < 12, "a log is not a transcript"
