# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounds-checked binary helpers used by the Jade Empire readers."""

from __future__ import annotations

import struct
from dataclasses import dataclass


class BinaryBoundsError(ValueError):
    """Raised when a parser attempts to read outside a binary resource."""


@dataclass(frozen=True)
class ArrayDefinition:
    offset: int
    count: int
    capacity: int


class BinaryView:
    """Immutable, bounds-checked view over a byte buffer."""

    def __init__(self, data: bytes | bytearray | memoryview, label: str = "resource"):
        self.data = memoryview(data)
        self.label = label

    def __len__(self) -> int:
        return len(self.data)

    def check(self, offset: int, size: int, context: str = "read") -> None:
        if offset < 0 or size < 0 or offset + size > len(self.data):
            raise BinaryBoundsError(
                f"{self.label}: {context} outside resource "
                f"(offset=0x{offset:X}, size=0x{size:X}, resource=0x{len(self.data):X})"
            )

    def bytes(self, offset: int, size: int, context: str = "bytes") -> bytes:
        self.check(offset, size, context)
        return self.data[offset : offset + size].tobytes()

    def u8(self, offset: int, context: str = "u8") -> int:
        self.check(offset, 1, context)
        return self.data[offset]

    def u16(self, offset: int, context: str = "u16") -> int:
        self.check(offset, 2, context)
        return struct.unpack_from("<H", self.data, offset)[0]

    def i16(self, offset: int, context: str = "i16") -> int:
        self.check(offset, 2, context)
        return struct.unpack_from("<h", self.data, offset)[0]

    def u32(self, offset: int, context: str = "u32") -> int:
        self.check(offset, 4, context)
        return struct.unpack_from("<I", self.data, offset)[0]

    def u32_be(self, offset: int, context: str = "u32be") -> int:
        self.check(offset, 4, context)
        return struct.unpack_from(">I", self.data, offset)[0]

    def i32(self, offset: int, context: str = "i32") -> int:
        self.check(offset, 4, context)
        return struct.unpack_from("<i", self.data, offset)[0]

    def f32(self, offset: int, context: str = "f32") -> float:
        self.check(offset, 4, context)
        return struct.unpack_from("<f", self.data, offset)[0]

    def u64(self, offset: int, context: str = "u64") -> int:
        self.check(offset, 8, context)
        return struct.unpack_from("<Q", self.data, offset)[0]

    def c_string_fixed(self, offset: int, size: int, context: str = "string") -> str:
        raw = self.bytes(offset, size, context)
        raw = raw.split(b"\0", 1)[0]
        return raw.decode("ascii", errors="replace")

    def c_string(self, offset: int, max_size: int | None = None, context: str = "string") -> str:
        if offset < 0 or offset >= len(self.data):
            self.check(offset, 1, context)
        end_limit = len(self.data) if max_size is None else min(len(self.data), offset + max_size)
        end = offset
        while end < end_limit and self.data[end] != 0:
            end += 1
        return self.data[offset:end].tobytes().decode("ascii", errors="replace")

    def f32_tuple(self, offset: int, count: int, context: str = "float tuple") -> tuple[float, ...]:
        self.check(offset, 4 * count, context)
        return struct.unpack_from("<" + "f" * count, self.data, offset)

    def array_definition(self, offset: int, context: str = "array definition") -> ArrayDefinition:
        self.check(offset, 12, context)
        return ArrayDefinition(
            self.u32(offset, context),
            self.u32(offset + 4, context),
            self.u32(offset + 8, context),
        )
