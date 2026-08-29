"""The splice engine: the only place bytes are allowed to change.

An edit is expressed as a set of byte-range replacements. Everything outside
those ranges is copied from the original, and every stored pointer that would be
displaced is shifted by the exact amount the bytes before it moved. With no
replacements the output is the input, byte for byte.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from ._io import MDL_BASE
from .layout import Layout

_U16 = struct.Struct("<H")
_U32 = struct.Struct("<I")


class RewriteError(Exception):
    """Refuse rather than emit a model we cannot vouch for."""


@dataclass(slots=True)
class _Edit:
    start: int
    end: int
    data: bytes

    @property
    def delta(self) -> int:
        return len(self.data) - (self.end - self.start)


@dataclass
class Rewriter:
    layout: Layout
    _mdl_edits: list[_Edit] = field(default_factory=list)
    _mdx_edits: list[_Edit] = field(default_factory=list)
    _patches: dict[int, tuple[struct.Struct, int]] = field(default_factory=dict)

    # ---- staging ----------------------------------------------------------

    def replace_mdl(self, start: int, end: int, data: bytes) -> None:
        self._mdl_edits.append(_Edit(start, end, data))

    def replace_mdx(self, start: int, end: int, data: bytes) -> None:
        self._mdx_edits.append(_Edit(start, end, data))

    def set_u32(self, loc: int, value: int) -> None:
        """Patch a u32 at an ORIGINAL-file position."""
        self._patches[loc] = (_U32, value)

    def set_u16(self, loc: int, value: int) -> None:
        self._patches[loc] = (_U16, value)

    # ---- machinery --------------------------------------------------------

    @staticmethod
    def _validate(edits: list[_Edit], stream: str) -> list[_Edit]:
        ordered = sorted(edits, key=lambda e: e.start)
        for a, b in zip(ordered, ordered[1:]):
            if b.start < a.end:
                raise RewriteError(
                    f"{stream} edits overlap: [{a.start},{a.end}) and [{b.start},{b.end})"
                )
        return ordered

    @staticmethod
    def _shift(ordered: list[_Edit], pos: int, stream: str) -> int:
        """How far a byte at ``pos`` moves. Positions strictly inside a replaced
        range have no defined image, which is an error rather than a guess."""
        delta = 0
        for e in ordered:
            if e.end <= pos:
                delta += e.delta
            elif e.start < pos < e.end:
                raise RewriteError(
                    f"{stream} position {pos} falls inside replaced range "
                    f"[{e.start},{e.end}); it has no image in the output"
                )
            else:
                break
        return delta

    @staticmethod
    def _splice(data: bytes, ordered: list[_Edit]) -> bytes:
        out = bytearray()
        cursor = 0
        for e in ordered:
            out += data[cursor : e.start]
            out += e.data
            cursor = e.end
        out += data[cursor:]
        return bytes(out)

    # ---- commit -----------------------------------------------------------

    def apply(self) -> tuple[bytes, bytes]:
        mdl_edits = self._validate(self._mdl_edits, "MDL")
        mdx_edits = self._validate(self._mdx_edits, "MDX")

        # Every stored pointer whose target moved must be rewritten. Offsets are
        # patched in ORIGINAL coordinates; the splice happens afterwards.
        for off in self.layout.offsets:
            edits = mdl_edits if off.space == "MDL" else mdx_edits
            stream = off.space
            moved = self._shift(edits, off.absolute, stream)
            if not moved:
                continue
            if self._shift(mdl_edits, off.loc, "MDL") != self._shift(
                mdl_edits, off.loc + 4, "MDL"
            ):
                raise RewriteError(f"pointer field at {off.loc} straddles an edit boundary")
            self.set_u32(off.loc, off.value + moved)

        mdl = bytearray(self.layout.mdl)
        mdx = bytearray(self.layout.mdx)
        for loc, (fmt, value) in self._patches.items():
            target = mdl if loc < len(mdl) else None
            if target is None:
                raise RewriteError(f"patch location {loc} is outside the MDL")
            for e in mdl_edits:
                if e.start <= loc < e.end:
                    raise RewriteError(
                        f"patch at {loc} lands inside replaced range [{e.start},{e.end})"
                    )
            fmt.pack_into(target, loc, value)

        mdl_out = self._splice(bytes(mdl), mdl_edits)
        mdx_out = self._splice(bytes(mdx), mdx_edits)

        # Sizes recorded in the wrapper and the model header must follow.
        mdl_out = bytearray(mdl_out)
        _U32.pack_into(mdl_out, 4, len(mdl_out) - MDL_BASE)
        _U32.pack_into(mdl_out, 8, len(mdx_out))
        _U32.pack_into(mdl_out, MDL_BASE + 176, len(mdx_out))
        return bytes(mdl_out), mdx_out
