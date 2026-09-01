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


# --- timing from a recording ------------------------------------------------


def riff(data_bytes: int, *, declared_data: int | None = None,
         declared_riff: int | None = None, byte_rate: int = 22050,
         rate: int | None = None) -> bytes:
    """A WAV, optionally with a header that lies about its own size.

    `rate` is separate from `byte_rate` on purpose: the reader refuses a
    sample rate no recorder produces, which is how it spots a fake header, and
    tying the two together in the fixture would hide that.
    """
    import struct

    fmt = struct.pack("<HHIIHH", 1, 1, rate if rate else byte_rate, byte_rate, 1, 8)
    body = bytes(data_bytes)
    data_size = data_bytes if declared_data is None else declared_data
    chunks = (b"fmt " + struct.pack("<I", len(fmt)) + fmt
              + b"data" + struct.pack("<I", data_size) + body)
    riff_size = (len(chunks) + 4) if declared_riff is None else declared_riff
    return b"RIFF" + struct.pack("<I", riff_size) + b"WAVE" + chunks


def test_a_wav_gives_its_real_length(tmp_path):
    path = tmp_path / "line.wav"
    path.write_bytes(riff(22050 * 3))
    assert lipsync.duration_of(path) == pytest.approx(3.0, abs=0.01)


def test_a_header_that_lies_is_measured_instead(tmp_path):
    """The case that matters. `rfk_carth_a1.wav` declares a RIFF size of 50
    bytes and a data chunk of zero inside a 368 KB file, so `wave.open` reports
    0.00 seconds - and a lip built on that would never move at all."""
    path = tmp_path / "lying.wav"
    path.write_bytes(riff(22050 * 5, declared_data=0, declared_riff=50))

    import wave

    with wave.open(str(path)) as w:
        assert w.getnframes() == 0, "the standard library believes the header"

    assert lipsync.duration_of(path) == pytest.approx(5.0, abs=0.01)


def test_something_that_is_not_audio_says_so(tmp_path):
    path = tmp_path / "notaudio.wav"
    path.write_bytes(b"this is not a wav file, not even slightly" * 4)
    assert lipsync.duration_of(path) is None
    assert lipsync.duration_of(tmp_path / "missing.wav") is None


def test_a_recording_is_found_by_the_line_it_belongs_to(tmp_path):
    (tmp_path / "abc_e01.wav").write_bytes(riff(22050))
    (tmp_path / "abc_e02.mp3").write_bytes(riff(22050))

    assert lipsync.find_audio(tmp_path, "abc_e01").name == "abc_e01.wav"
    assert lipsync.find_audio(tmp_path, "abc_e02").name == "abc_e02.mp3"
    assert lipsync.find_audio(tmp_path, "abc_e99") is None


def test_a_lip_fills_the_recording(tmp_path):
    """The point of the feature: the mouth moves for as long as the voice does,
    rather than for as long as the word count guessed."""
    path = tmp_path / "long.wav"
    path.write_bytes(riff(22050 * 12))
    seconds = lipsync.duration_of(path)

    short_text = "Yes."
    guessed = lipsync.build(short_text)
    matched = lipsync.build(short_text, seconds=seconds)

    assert guessed.length < 2.0, "four letters would be estimated as brief"
    assert matched.length == pytest.approx(12.0, abs=0.01)
    assert len(list(matched)) > len(list(guessed)) * 4, (
        "it has to fill the time, not just declare it"
    )
    assert [k.shape.name for k in matched][-1] == "NEUTRAL"


def kotor_wrapped(inner: bytes, preamble: int = 58) -> bytes:
    """A real WAV behind a decoy header.

    This is the shape a modder ends up with: the community guide for getting
    audio into KOTOR has you prepend a header, leaving the real RIFF nested
    inside. The outer one claims 8-bit 22 kHz and a data chunk of zero. Shipped
    ambient sound nests the same way behind a longer preamble.
    """
    import struct

    fmt = struct.pack("<HHIIHH", 1, 1, 22050, 22050, 1, 8)
    head = (b"RIFF" + struct.pack("<I", preamble - 8) + b"WAVE"
            + b"fmt " + struct.pack("<I", len(fmt)) + fmt
            + b"data" + struct.pack("<I", 0))
    return head.ljust(preamble, b"\0") + inner


def test_the_real_wav_inside_kotors_fake_header_is_the_one_read(tmp_path):
    """The case that matters, because it is what a modder's own files look
    like. `rfk_carth_a1.wav` reads as 16.72 seconds from its outer header and
    is really 5.76 - believing the wrapper is wrong by a factor of three, and
    the lip would run for three times as long as the voice."""
    inner = riff(64000 * 4, byte_rate=64000, rate=32000)   # 4s of 16-bit 32k
    path = tmp_path / "wrapped.wav"
    path.write_bytes(kotor_wrapped(inner))

    assert lipsync.duration_of(path) == pytest.approx(4.0, abs=0.01)


def test_the_470_byte_preamble_is_handled_too(tmp_path):
    """Shipped ambient sound uses a longer wrapper - 0x1D6 - the same way."""
    inner = riff(22050 * 2)
    path = tmp_path / "ambient.wav"
    path.write_bytes(kotor_wrapped(inner, preamble=470))

    assert lipsync.duration_of(path) == pytest.approx(2.0, abs=0.01)


def test_a_header_over_mp3_data_is_refused_rather_than_guessed(tmp_path):
    """Shipped *voice* is a third shape - MP3 behind a WAV header - and nothing
    in that header is true; `af.wav` claims 384 kHz. Timing it needs frame
    decoding, and a confident wrong length is worse than none: it produces a
    lip that silently does not match. SithCodec decodes these properly, and
    anything it has been through reads like an ordinary file."""
    path = tmp_path / "fake.wav"
    path.write_bytes(riff(500_000, byte_rate=768_000, rate=384_000))

    assert lipsync.duration_of(path) is None


def test_an_ordinary_recording_still_reads(tmp_path):
    """Whatever a normal recorder writes must not be caught by any of this."""
    for rate, byte_rate in ((22050, 44100), (44100, 88200), (48000, 96000)):
        path = tmp_path / f"plain{rate}.wav"
        path.write_bytes(riff(byte_rate * 3, byte_rate=byte_rate, rate=rate))
        assert lipsync.duration_of(path) == pytest.approx(3.0, abs=0.01), rate
