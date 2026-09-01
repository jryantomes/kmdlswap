"""Walking a conversation and giving every line a mouth.

The pieces this stands on were settled in game rather than argued about:
a `.lip` plays with no recording behind it, the engine finds it by the line's
`VO_ResRef`, and 26 generated files drove the broker's whole conversation. What
is left is the bookkeeping - which lines are spoken, which already name a VO,
and which have a recording whose real length should win over a guess.

Two rules the job never breaks:

**The original dialogue is not edited.** Lines that need a `VO_ResRef` get one
in a copy written beside the lips. Installing that copy is a separate decision,
made by somebody who can see what changed.

**A length is measured or admitted.** A lip built on a wrong duration looks
worse than one built on an honest guess, because it drifts against audio that
is actually playing. Where a recording is unreadable - shipped voice is MP3
behind a WAV header - it says so and estimates instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

ENTRIES = "EntryList"
REPLIES = "ReplyList"
RESREF_MAX = 16          # the field is 16 bytes; the suffix takes three


class DialogueError(RuntimeError):
    pass


@dataclass
class Line:
    """One spoken line and the lip written for it."""

    vo: str
    text: str
    seconds: float
    size: int
    timing: str          # "estimated", "given", or the recording's name
    assigned: bool = False

    @property
    def opening(self) -> str:
        return " ".join(self.text.split())[:40]


@dataclass
class LipJob:
    """What was written, and what still needs a decision."""

    out_dir: Path
    lines: list[Line] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)
    skipped: int = 0
    unreadable: list[str] = field(default_factory=list)
    dialogue_copy: Path | None = None

    @property
    def written(self) -> int:
        return len(self.lines)

    @property
    def assigned(self) -> int:
        return sum(1 for line in self.lines if line.assigned)

    @property
    def timed(self) -> int:
        return sum(1 for line in self.lines
                   if line.timing not in ("estimated", "given"))

    @property
    def estimated(self) -> int:
        return sum(1 for line in self.lines if line.timing == "estimated")


def spoken(root, lists) -> int:
    """How many lines have something to say.

    A dialogue entry with no `Text` is structure - a branch, a condition, an
    end - and gets no lip, so counting the lists is not the same as counting
    the work.
    """
    found = 0
    for listname in lists:
        if not root.exists(listname):
            continue
        items = root.get_list(listname)
        for i in range(len(items)):
            item = items.at(i)
            if item.exists("Text") and str(item.value("Text")).strip():
                found += 1
    return found


def run(dialogue, out_dir, *, prefix: str | None = None, assign: bool = False,
        replies: bool = False, audio=None, seconds: float | None = None,
        progress=None) -> LipJob:
    """Write a `.lip` for every spoken line in `dialogue`.

    `assign` gives a `VO_ResRef` to lines that have none - without it those
    lines are counted and skipped, because a lip with nothing to hang on is a
    file the engine will never look for. `audio` is a folder of recordings,
    matched to a line by its `VO_ResRef`. `seconds` overrides everything, for
    when the timing is known but the files are elsewhere.
    """
    from pykotor.resource.formats.gff import bytes_gff, read_gff

    from . import lipsync

    source = Path(dialogue)
    if not source.is_file():
        raise DialogueError(f"no such dialogue: {source}")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    job = LipJob(out_dir=out_dir)

    gff = read_gff(source.read_bytes())
    root = gff.root
    stem = (prefix or source.stem)[:RESREF_MAX - 3]
    resref_type = None

    wanted = [ENTRIES] + ([REPLIES] if replies else [])
    # Counted before anything is written so a caller drawing a progress bar has
    # a denominator. Walking the lists twice costs nothing next to writing the
    # files, and a bar that does not know where it ends is worse than none.
    total = spoken(root, wanted)
    for listname in wanted:
        if not root.exists(listname):
            continue
        items = root.get_list(listname)
        for i in range(len(items)):
            item = items.at(i)
            if not item.exists("Text"):
                continue
            text = str(item.value("Text")).strip()
            if not text:
                continue

            vo = str(item.value("VO_ResRef")) if item.exists("VO_ResRef") else ""
            fresh = False
            if not vo:
                if not assign:
                    job.skipped += 1
                    continue
                if resref_type is None:
                    resref_type = type(item.value("VO_ResRef"))
                vo = f"{stem}{'r' if listname == REPLIES else 'e'}{i:02d}"
                item.set_resref("VO_ResRef", resref_type(vo))
                fresh = True

            length, timing = seconds, "given"
            if length is None and audio:
                recording = lipsync.find_audio(audio, vo)
                if recording is not None:
                    length = lipsync.duration_of(recording)
                    if length:
                        timing = recording.name
                    else:
                        job.unreadable.append(recording.name)
            if length is None:
                timing = "estimated"

            path = out_dir / f"{vo}.lip"
            size = lipsync.write(text, path, seconds=length)
            job.lines.append(Line(
                vo=vo, text=text, size=size, timing=timing, assigned=fresh,
                seconds=length if length else lipsync.estimate_length(text),
            ))
            job.files.append(path)
            if progress is not None:
                progress(len(job.lines), total, vo)

    # Named after the dialogue, not after anything in the loop above - an
    # earlier version reused one variable for both and crashed here, after
    # writing every lip, on exactly the path this feature exists for.
    if job.assigned:
        job.dialogue_copy = out_dir / source.name
        job.dialogue_copy.write_bytes(bytes_gff(gff))
        job.files.append(job.dialogue_copy)

    return job


def summarise(job: LipJob, *, audio=None, detail: int = 4) -> list[str]:
    """The same account for the terminal and the window."""
    out = []
    for line in job.lines[:detail]:
        out.append(f"  {line.vo}.lip  {line.size:>4}B  {line.seconds:5.2f}s  "
                   f"{line.timing:<18} {line.opening}")
    if job.written > detail:
        out.append(f"  ... and {job.written - detail} more")

    out.append(f"\n{job.written} lip file(s) written to {job.out_dir}")
    if job.timed:
        out.append(f"{job.timed} lip(s) matched to a recording's real length")
    if job.estimated:
        out.append(f"{job.estimated} estimated from the word count"
                   + (" - no recording found for those" if audio else
                      " (point it at your recordings to use them)"))
    if job.unreadable:
        shown = ", ".join(job.unreadable[:4])
        out.append(f"could not read a length from: {shown}"
                   + (" ..." if len(job.unreadable) > 4 else ""))
    if job.skipped:
        out.append(f"{job.skipped} line(s) have no VO_ResRef and were skipped; "
                   f"assigning gives them one")
    if job.dialogue_copy:
        out.append(f"{job.assigned} line(s) given a VO_ResRef; updated dialogue "
                   f"written to {job.dialogue_copy}")
        out.append("The original was not touched. Install the copy to use it.")
    return out
