"""Validators. These decide whether a model is safe to edit.

The rule from the brief - *when a behavior is unknown, preserve the vanilla
value exactly rather than inventing one* - has a corollary: if we cannot account
for every byte and resolve every pointer, we refuse the model rather than guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .layout import Layout, Span


@dataclass
class Gap:
    start: int
    end: int
    stream: str

    @property
    def size(self) -> int:
        return self.end - self.start


@dataclass
class Overlap:
    a: Span
    b: Span
    stream: str


@dataclass
class Report:
    identity_mdl: bool = False
    identity_mdx: bool = False
    gaps: list[Gap] = field(default_factory=list)
    overlaps: list[Overlap] = field(default_factory=list)
    dangling: list[str] = field(default_factory=list)

    @property
    def covered(self) -> bool:
        return not self.gaps and not self.overlaps

    @property
    def ok(self) -> bool:
        return self.identity_mdl and self.identity_mdx and self.covered and not self.dangling

    @property
    def gap_bytes(self) -> int:
        return sum(g.size for g in self.gaps)


def _scan(spans: list[Span], total: int, stream: str) -> tuple[list[Gap], list[Overlap]]:
    gaps: list[Gap] = []
    overlaps: list[Overlap] = []
    ordered = sorted(spans, key=lambda s: (s.start, s.end))
    cursor = 0
    prev: Span | None = None
    for s in ordered:
        if s.start > cursor:
            gaps.append(Gap(cursor, s.start, stream))
        elif s.start < cursor and prev is not None:
            overlaps.append(Overlap(prev, s, stream))
        cursor = max(cursor, s.end)
        prev = s
    if cursor < total:
        gaps.append(Gap(cursor, total, stream))
    return gaps, overlaps


def serialize(layout: Layout) -> tuple[bytes, bytes]:
    """Rebuild both streams from the span map. With full coverage this is the
    original bytes; that is the point - identity is not reconstructed, it is
    copied."""
    def build(spans: list[Span], data: bytes, total: int) -> bytes:
        out = bytearray(total)
        for s in sorted(spans, key=lambda s: s.start):
            out[s.start : s.end] = data[s.start : s.end]
        return bytes(out)

    return (
        build(layout.spans, layout.mdl, len(layout.mdl)),
        build(layout.mdx_spans, layout.mdx, len(layout.mdx)),
    )


def check(layout: Layout) -> Report:
    rep = Report()
    rep.gaps, rep.overlaps = _scan(layout.spans, len(layout.mdl), "MDL")
    mgaps, moverlaps = _scan(layout.mdx_spans, len(layout.mdx), "MDX")
    rep.gaps += mgaps
    rep.overlaps += moverlaps

    # Offset closure: every stored pointer must land on a span boundary of the
    # kind it claims to point at.
    mdl_starts: dict[int, set[str]] = {}
    for s in layout.spans:
        mdl_starts.setdefault(s.start, set()).add(s.kind)
    mdx_starts: dict[int, set[str]] = {}
    for s in layout.mdx_spans:
        mdx_starts.setdefault(s.start, set()).add(s.kind)

    # Both the model header and an animation header open with a geometry header,
    # so a node's offset_to_root may legitimately resolve to either.
    aliases = {"geometry_header": {"model_header", "anim_header"}}

    for o in layout.offsets:
        starts = mdl_starts if o.space == "MDL" else mdx_starts
        kinds = starts.get(o.absolute)
        acceptable = aliases.get(o.target_kind, {o.target_kind})
        if kinds is None:
            rep.dangling.append(
                f"{o.space} offset at {o.loc} -> {o.value} ({o.target_kind}) hits no span start"
            )
        elif not (kinds & acceptable):
            rep.dangling.append(
                f"{o.space} offset at {o.loc} -> {o.value} expected {o.target_kind}, "
                f"found {sorted(kinds)}"
            )

    mdl_out, mdx_out = serialize(layout)
    rep.identity_mdl = mdl_out == layout.mdl
    rep.identity_mdx = mdx_out == layout.mdx
    return rep
