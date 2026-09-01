"""Making a mouth move for a line that has no recording.

Confirmed in game on 2026-09-01: KOTOR plays a `.lip` with no `.wav` behind it.
That matters, because it is the difference between this being possible and not.
The community's route to lip files goes through the CSLU toolkit, which derives
phonemes from a recording and is effectively unobtainable now - but with no
audio there is nothing to derive *from*. What is left is a duration and a list
of mouth shapes, which is all a lip file is.

So the shapes come from the **text**. English spelling is a poor guide to
pronunciation and this makes no attempt to be a phoneme engine: it walks the
letters, maps the ones that clearly imply a mouth position, and lets the rest
pass as a neutral-ish vowel. `m`, `b` and `p` close the lips; `f` and `v` bite
the lip; `o` and `u` round it. Watched at conversational speed that reads as
speech, because what the eye checks is whether the mouth moves *with* the
words, not whether it is saying them.

Timing is estimated from the word count. Measured against a shipped line -
`nm13aabast01059_`, 4.71 seconds and 38 keyframes - vanilla runs about eight
shapes a second, which is the density used here.

What this is not: lip *sync*. Nothing is being synchronised, because there is
nothing to synchronise to. It is a mouth that moves while a subtitle is on
screen, which for an unvoiced NPC is the whole of what anyone wanted.
"""

from __future__ import annotations

import re

# Roughly eight shapes a second, from `nm13aabast01059_`: 38 keyframes in 4.71s.
SHAPES_PER_SECOND = 8.0
# Ordinary speech is about two and a half words a second.
WORDS_PER_SECOND = 2.5
MIN_LENGTH = 1.0
MAX_LENGTH = 30.0

# Only the letters that clearly imply a mouth position. Everything else is left
# to the vowel fallback rather than guessed at.
DIGRAPHS = {
    "th": "TH", "sh": "SH", "ch": "SH", "ph": "FV", "ng": "NG",
    "oo": "OOH", "ee": "EE", "ou": "OOH", "ow": "OH", "ai": "EH", "ea": "EE",
}
LETTERS = {
    "a": "AH", "e": "EH", "i": "EE", "o": "OH", "u": "OOH", "y": "Y",
    "m": "MPB", "b": "MPB", "p": "MPB",
    "f": "FV", "v": "FV",
    "s": "STS", "z": "STS", "c": "STS",
    "t": "TD", "d": "TD",
    "k": "KG", "g": "KG", "q": "KG",
    "l": "L", "n": "NG", "r": "AH", "w": "OOH", "h": "EH", "j": "SH", "x": "KG",
}


def estimate_length(text: str) -> float:
    """How long the line would take to say."""
    words = len(re.findall(r"[\w']+", text)) or 1
    return max(MIN_LENGTH, min(MAX_LENGTH, words / WORDS_PER_SECOND))


def shapes_for(text: str) -> list[str]:
    """The mouth positions the text implies, in order."""
    lowered = re.sub(r"[^a-z ]+", " ", text.lower())
    out: list[str] = []
    i = 0
    while i < len(lowered):
        pair = lowered[i:i + 2]
        if pair in DIGRAPHS:
            out.append(DIGRAPHS[pair])
            i += 2
            continue
        letter = lowered[i]
        if letter == " ":
            # A gap between words closes the mouth a little, which is most of
            # what makes it read as speech rather than chewing.
            if out and out[-1] != "NEUTRAL":
                out.append("NEUTRAL")
        elif letter in LETTERS:
            shape = LETTERS[letter]
            if not out or out[-1] != shape:
                out.append(shape)
        i += 1
    return out or ["NEUTRAL"]


def build(text: str, *, seconds: float | None = None):
    """A LIP for a line of dialogue."""
    from pykotor.resource.formats.lip import LIP, LIPShape

    length = float(seconds) if seconds else estimate_length(text)
    wanted = max(2, int(length * SHAPES_PER_SECOND))
    shapes = shapes_for(text)

    # Spread whatever the text gave us across the whole line rather than
    # running out early and leaving the mouth open for the rest of it.
    picked = [shapes[int(i * len(shapes) / wanted)] for i in range(wanted)]

    lip = LIP()
    lip.length = length
    step = length / (len(picked) + 1)
    lip.add(0.0, LIPShape.NEUTRAL)
    for i, shape in enumerate(picked, start=1):
        lip.add(round(i * step, 3), getattr(LIPShape, shape))
    # Ending anywhere else leaves the mouth hanging open when the line stops.
    lip.add(round(length, 3), LIPShape.NEUTRAL)
    return lip


def write(text: str, path, *, seconds: float | None = None) -> int:
    """Write a lip file for `text`. Returns its length in bytes."""
    from pathlib import Path

    from pykotor.resource.formats.lip import bytes_lip

    data = bytes_lip(build(text, seconds=seconds))
    Path(path).write_bytes(data)
    return len(data)
