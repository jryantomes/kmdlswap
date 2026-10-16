"""Read KMRP 1.5's interface bank (resource 101, RT_RCDATA, in KMRP.kpatch's windows_x86.dll) the way
K1RuntimeAssets.cpp does, and write the named file of every resolution set out.

    kmrp_bank.py <dll> <out dir> [name ...]     default name: partyselection.gui
"""
import ctypes
import struct
import sys
from ctypes import wintypes
from pathlib import Path

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.LoadLibraryExW.restype = wintypes.HMODULE
k32.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
k32.FindResourceW.restype = wintypes.HANDLE
k32.FindResourceW.argtypes = [wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p]
k32.SizeofResource.argtypes = [wintypes.HMODULE, wintypes.HANDLE]
k32.LoadResource.restype = wintypes.HANDLE
k32.LoadResource.argtypes = [wintypes.HMODULE, wintypes.HANDLE]
k32.LockResource.restype = ctypes.c_void_p
k32.LockResource.argtypes = [wintypes.HANDLE]
cab = ctypes.WinDLL("cabinet")


def bank(dll):
    m = k32.LoadLibraryExW(str(dll), None, 0x2 | 0x20)       # AS_DATAFILE | AS_IMAGE_RESOURCE
    if not m:
        raise SystemExit(f"LoadLibraryEx: {ctypes.get_last_error()}")
    r = k32.FindResourceW(m, ctypes.c_void_p(101), ctypes.c_void_p(10))
    size = k32.SizeofResource(m, r)
    return ctypes.string_at(k32.LockResource(k32.LoadResource(m, r)), size)


def decompress(blob, size, lzms):
    h = ctypes.c_void_p()
    if not cab.CreateDecompressor(5 if lzms else 4, None, ctypes.byref(h)):
        raise SystemExit("CreateDecompressor")
    out = ctypes.create_string_buffer(size)
    got = ctypes.c_size_t()
    ok = cab.Decompress(h, blob, ctypes.c_size_t(len(blob)), out, ctypes.c_size_t(size), ctypes.byref(got))
    cab.CloseDecompressor(h)
    if not ok:
        raise SystemExit("Decompress failed")
    return out.raw[:got.value]


def parse(data):
    magic = data[:8]
    lzms = magic == b"KNASL002"
    assert lzms or magic == b"KNAST002", magic
    at = 8
    groups_n, objects_n = struct.unpack_from("<II", data, at); at += 8
    table_key = data[at:at + 32]; at += 32
    groups = []
    for _ in range(groups_n):
        w, h, n = struct.unpack_from("<III", data, at); at += 12
        entries = {}
        for _ in range(n):
            (ln,) = struct.unpack_from("<H", data, at); at += 2
            name = data[at:at + ln].decode(); at += ln
            entries[name] = data[at:at + 32]; at += 32
        groups.append((w, h, entries))
    objects = {}
    for _ in range(objects_n):
        key = data[at:at + 32]; at += 32
        size, comp = struct.unpack_from("<II", data, at); at += 8
        objects[key] = (size, data[at:at + comp]); at += comp
    assert at == len(data)
    return lzms, table_key, groups, objects


def main(dll, out, names):
    lzms, _table, groups, objects = parse(bank(dll))
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    have, blended = 0, []
    for w, h, entries in groups:
        for name in names:
            key = entries.get(name)
            if key is None:
                continue
            if key not in objects:
                blended.append(f"{w}x{h}")
                continue
            size, blob = objects[key]
            d = out / (f"{w}x{h}" if w else "common")
            d.mkdir(exist_ok=True)
            (d / name).write_bytes(decompress(blob, size, lzms))
            have += 1
    print(f"{len(groups)} groups; {have} files written; left to the blend helper: {blended}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3:] or ["partyselection.gui"])
