"""Given one model name, round-trip it through PyKotor and characterise WHERE and
HOW the bytes differ - contiguous diff runs, with hex context. Helps decide
whether PyKotor is patchable or a byte-surgical approach is needed.
"""

from __future__ import annotations

import argparse

from pykotor.common.misc import Game
from pykotor.extract.installation import Installation
from pykotor.resource.formats.mdl.io_mdl import MDLBinaryReader, MDLBinaryWriter
from pykotor.resource.type import ResourceType


def diff_runs(a: bytes, b: bytes, ctx: int = 8, max_runs: int = 40):
    runs = []
    n = min(len(a), len(b))
    i = 0
    while i < n:
        if a[i] != b[i]:
            j = i
            while j < n and a[j] != b[j]:
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    if len(a) != len(b):
        runs.append((n, max(len(a), len(b))))
    return runs[:max_runs], len(runs)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", required=True)
    ap.add_argument("--name", required=True)
    args = ap.parse_args()

    inst = Installation(args.install)
    res = {(r.resname().lower(), r.restype()): r for r in inst.chitin_resources()}
    mdl_in = res[(args.name.lower(), ResourceType.MDL)].data()
    mdx_in = res[(args.name.lower(), ResourceType.MDX)].data()

    mdl = MDLBinaryReader(bytes(mdl_in), 0, len(mdl_in), bytes(mdx_in), 0, len(mdx_in), game=Game.K1).load()
    mo, xo = bytearray(), bytearray()
    MDLBinaryWriter(mdl, mo, xo).write()
    mo, xo = bytes(mo), bytes(xo)

    for tag, ai, bi in (("MDL", mdl_in, mo), ("MDX", mdx_in, xo)):
        runs, total = diff_runs(ai, bi)
        print(f"\n=== {tag}: in={len(ai)} out={len(bi)} delta={len(bi) - len(ai)}  diff_runs={total}")
        for (s, e) in runs:
            a_hex = ai[s:min(e, s + 16)].hex(" ")
            b_hex = bi[s:min(e, s + 16)].hex(" ")
            print(f"  @{s:>8} len {e - s:>6}   in: {a_hex}\n{'':>21}out: {b_hex}")


if __name__ == "__main__":
    main()
