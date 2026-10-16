"""Read a Steam depot manifest (depotcache/<depot>_<manifest>.manifest).

Only the file list is decoded: name, size, flags and the SHA-1 of the
content. The payload is a protobuf (ContentManifestPayload); a hand-rolled
varint reader is enough, so no protobuf dependency.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

MAGIC_PAYLOAD = 0x71F617D0
MAGIC_METADATA = 0x1F4812BE
MAGIC_SIGNATURE = 0x1B81B817
MAGIC_END = 0x32C415AB

FLAG_DIRECTORY = 64


@dataclass(frozen=True)
class DepotFile:
    name: str      # relative path, backslashes as Steam stores them
    size: int
    flags: int
    sha1: str      # hex, empty for directories

    @property
    def is_dir(self) -> bool:
        return bool(self.flags & FLAG_DIRECTORY)


def _varint(buf: bytes, i: int) -> tuple[int, int]:
    shift = value = 0
    while True:
        b = buf[i]
        i += 1
        value |= (b & 0x7F) << shift
        if not b & 0x80:
            return value, i
        shift += 7


def _fields(buf: bytes):
    """Yield (field_number, wire_type, value) for one protobuf message."""
    i = 0
    while i < len(buf):
        key, i = _varint(buf, i)
        num, wt = key >> 3, key & 7
        if wt == 0:
            val, i = _varint(buf, i)
        elif wt == 1:
            val, i = buf[i:i + 8], i + 8
        elif wt == 2:
            n, i = _varint(buf, i)
            val, i = buf[i:i + n], i + n
        elif wt == 5:
            val, i = buf[i:i + 4], i + 4
        else:
            raise ValueError(f"unsupported wire type {wt}")
        yield num, wt, val


def read_manifest(path: Path) -> list[DepotFile]:
    data = path.read_bytes()
    if data[:2] == b"PK":
        raise ValueError("zipped manifest (download cache format) not supported")
    payload = None
    i = 0
    while i + 4 <= len(data):
        magic = struct.unpack_from("<I", data, i)[0]
        if magic == MAGIC_END:
            break
        length = struct.unpack_from("<I", data, i + 4)[0]
        body = data[i + 8:i + 8 + length]
        i += 8 + length
        if magic == MAGIC_PAYLOAD:
            payload = body
        elif magic == MAGIC_METADATA:
            for num, _, val in _fields(body):
                if num == 4 and val:  # filenames_encrypted
                    raise ValueError("manifest filenames are encrypted")
    if payload is None:
        raise ValueError("no payload section")

    files = []
    for num, _, val in _fields(payload):
        if num != 1:
            continue
        name, size, flags, sha = "", 0, 0, b""
        for fnum, _, fval in _fields(val):
            if fnum == 1:
                name = fval.decode("utf-8")
            elif fnum == 2:
                size = fval
            elif fnum == 3:
                flags = fval
            elif fnum == 5:
                sha = fval
        files.append(DepotFile(name.rstrip("\0"), size, flags, sha.hex()))
    return files


if __name__ == "__main__":
    import sys
    fs = read_manifest(Path(sys.argv[1]))
    real = [f for f in fs if not f.is_dir]
    print(f"{len(real)} files, {sum(f.size for f in real):,} bytes")
    for f in real[:20]:
        print(f.sha1, f.size, f.name)
