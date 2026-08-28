"""Little-endian struct primitives over an immutable ``bytes`` buffer.

Everything here reads. Nothing here writes: the byte-surgical design never
regenerates a region it did not deliberately edit, so a general-purpose writer
would be a liability.
"""

from __future__ import annotations

import struct

# All offsets stored inside an MDL are relative to byte 12 of the file (the
# 12-byte wrapper of {0, mdl_data_size, mdx_size} is not counted).
MDL_BASE = 12

_U8 = struct.Struct("<B")
_U16 = struct.Struct("<H")
_U32 = struct.Struct("<I")
_I16 = struct.Struct("<h")
_I32 = struct.Struct("<i")
_F32 = struct.Struct("<f")
_VEC3 = struct.Struct("<3f")
_VEC4 = struct.Struct("<4f")


class Reader:
    """Cursor over a bytes buffer. Absolute file positions throughout."""

    __slots__ = ("data", "pos")

    def __init__(self, data: bytes, pos: int = 0):
        self.data = data
        self.pos = pos

    def seek(self, pos: int) -> Reader:
        self.pos = pos
        return self

    def seek_mdl(self, offset: int) -> Reader:
        """Seek to an MDL-internal offset (relative to :data:`MDL_BASE`)."""
        self.pos = MDL_BASE + offset
        return self

    def _take(self, s: struct.Struct):
        v = s.unpack_from(self.data, self.pos)
        self.pos += s.size
        return v

    def u8(self) -> int:
        return self._take(_U8)[0]

    def u16(self) -> int:
        return self._take(_U16)[0]

    def u32(self) -> int:
        return self._take(_U32)[0]

    def i16(self) -> int:
        return self._take(_I16)[0]

    def i32(self) -> int:
        return self._take(_I32)[0]

    def f32(self) -> float:
        return self._take(_F32)[0]

    def vec3(self) -> tuple[float, float, float]:
        return self._take(_VEC3)

    def vec4(self) -> tuple[float, float, float, float]:
        return self._take(_VEC4)

    def raw(self, n: int) -> bytes:
        b = self.data[self.pos : self.pos + n]
        self.pos += n
        return b

    def cstr(self, n: int) -> str:
        """Fixed-width NUL-padded string. Trailing garbage after the NUL is
        common in vanilla files and is deliberately discarded here - the raw
        bytes still live in the span, so identity is unaffected."""
        return self.raw(n).split(b"\0", 1)[0].decode("ascii", "replace")

    def skip(self, n: int) -> Reader:
        self.pos += n
        return self


def u32_at(data: bytes, pos: int) -> int:
    return _U32.unpack_from(data, pos)[0]


def u16_at(data: bytes, pos: int) -> int:
    return _U16.unpack_from(data, pos)[0]


def cstr_at(data: bytes, pos: int) -> str:
    """NUL-terminated string of unbounded length."""
    end = data.index(b"\0", pos)
    return data[pos:end].decode("ascii", "replace")
