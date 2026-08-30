"""Diff two models semantically, to find what an edit failed to update.

Probes P0b and P0d from `reports/ANIMATION_PROBE_PLAN.md`.

A raw byte diff is useless here: growing a mesh shifts most of the file, so
almost every byte "differs" and the one that matters is buried. This compares by
**span identity** instead - each span is keyed by its kind, its owning node's
name, and its ordinal among that node's spans of the same kind - so a span that
merely moved compares equal, and only a span whose *content* changed is
reported.

Two questions are asked:

* **What changed that should not have?** Every field the parser can name, and
  the bytes of every span, for every node except the one deliberately edited.
* **What did not change that should have?** Any 16- or 32-bit value anywhere in
  the file that equals something derived from the old vertex count - the count
  itself, or it times the stride, times 12, and so on. If such a value is still
  the *old* one after the edit, it is a stale second copy of the count, and a
  direct candidate for why the engine mis-handles the mesh.

    python tools/probe_diff.py --install "<K1 root>" --model p_carthh \\
        --against out/p_carthh.mdl --node Head
"""

from __future__ import annotations

import argparse
import struct
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kmdlswap import layout as kl  # noqa: E402
from kmdlswap.loader import load  # noqa: E402

SCALAR_FIELDS = (
    "type_id", "node_id", "name_id", "name", "parent", "children", "in_animation",
    "vertex_count", "face_count", "mdx_stride", "mdx_bitmap",
    "bones", "textures", "mdx_weights_offset", "mdx_bones_offset", "bonemap",
)


def span_keys(layout: kl.Layout, spans, mdl: bytes):
    """Map each span to a stable identity and its bytes."""
    ordinal: dict = defaultdict(int)
    out: dict = {}
    for s in spans:
        owner = layout.nodes[s.owner].name if s.owner is not None else "-"
        base = (s.kind, owner)
        key = (*base, ordinal[base])
        ordinal[base] += 1
        out[key] = mdl[s.start : s.end]
    return out


def compare_nodes(a: kl.Layout, b: kl.Layout, skip: str) -> list[str]:
    notes = []
    if len(a.nodes) != len(b.nodes):
        return [f"node count {len(a.nodes)} -> {len(b.nodes)}"]
    for na, nb in zip(a.nodes, b.nodes):
        for f in SCALAR_FIELDS:
            va, vb = getattr(na, f), getattr(nb, f)
            if va != vb:
                tag = "  (the edited node)" if na.name == skip else "  <-- UNEXPECTED"
                notes.append(f"{na.name}.{f}: {va!r} -> {vb!r}{tag}")
    return notes


def compare_spans(a: kl.Layout, b: kl.Layout, skip: str) -> list[str]:
    notes = []
    for label, sa, sb, mdl_a, mdl_b in (
        ("MDL", a.spans, b.spans, a.mdl, b.mdl),
        ("MDX", a.mdx_spans, b.mdx_spans, a.mdx, b.mdx),
    ):
        ka = span_keys(a, sa, mdl_a)
        kb = span_keys(b, sb, mdl_b)
        for key in sorted(set(ka) | set(kb), key=repr):
            va, vb = ka.get(key), kb.get(key)
            kind, owner, ordinal = key
            if va is None or vb is None:
                notes.append(f"[{label}] {kind} of {owner}#{ordinal}: "
                             f"{'only in vanilla' if vb is None else 'only in probe'}")
            elif va != vb:
                where = next((i for i, (x, y) in enumerate(zip(va, vb)) if x != y), 0)
                tag = "  (the edited node)" if owner == skip else "  <-- UNEXPECTED"
                notes.append(
                    f"[{label}] {kind} of {owner}#{ordinal}: {len(va)} -> {len(vb)} bytes, "
                    f"first difference at +{where}{tag}"
                )
    return notes


def derived_values(count: int, stride: int, faces: int) -> dict[int, str]:
    """Numbers a stale copy of the vertex count could plausibly be stored as."""
    out: dict[int, str] = {}

    def add(value, how):
        if 0 < value < 2**32 and value not in out:
            out[value] = how

    add(count, "vertex count")
    add(count - 1, "count - 1")
    add(count + 1, "count + 1")
    add(count * stride, f"count x stride({stride})")
    for k in (2, 3, 4, 6, 8, 12, 16, 24, 32):
        add(count * k, f"count x {k}")
    add(faces, "face count")
    add(faces * 3, "face count x 3")
    add(faces * 32, "face count x 32")
    return out


def scan(data: bytes, wanted: dict[int, str]) -> dict[int, list[int]]:
    """Every offset holding one of `wanted`, as u32 or u16."""
    hits: dict[int, list[int]] = defaultdict(list)
    for at in range(0, len(data) - 3):
        v = struct.unpack_from("<I", data, at)[0]
        if v in wanted:
            hits[v].append(at)
    for at in range(0, len(data) - 1):
        v = struct.unpack_from("<H", data, at)[0]
        if v in wanted and v < 0x10000:
            hits[v].append(-at)  # negative marks a u16 hit
    return hits


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install")
    ap.add_argument("--model", required=True, help="vanilla model name")
    ap.add_argument("--against", required=True, help="path to the edited .mdl")
    ap.add_argument("--node", required=True, help="the node the edit targeted")
    ap.add_argument("--max", type=int, default=40, help="lines per section")
    args = ap.parse_args(argv)

    a = load(args.model, args.install)
    other = Path(args.against)
    b = kl.parse(other.read_bytes(), other.with_suffix(".mdx").read_bytes())

    node_a = a.node_by_name(args.node)
    node_b = b.node_by_name(args.node)
    print(f"vanilla {args.model}: {len(a.mdl)} MDL / {len(a.mdx)} MDX bytes")
    print(f"probe   {other.name}: {len(b.mdl)} MDL / {len(b.mdx)} MDX bytes")
    print(f"edited node {args.node}: {node_a.vertex_count} -> {node_b.vertex_count} "
          f"vertices, stride {node_a.mdx_stride}")

    print("\n=== P0b: named fields that differ ===")
    notes = compare_nodes(a, b, node_a.name)
    for line in notes[: args.max] or ["(none)"]:
        print("  " + line)
    if len(notes) > args.max:
        print(f"  ... and {len(notes) - args.max} more")

    print("\n=== P0b: spans whose CONTENT differs ===")
    notes = compare_spans(a, b, node_a.name)
    unexpected = [n for n in notes if "UNEXPECTED" in n]
    for line in notes[: args.max] or ["(none)"]:
        print("  " + line)
    if len(notes) > args.max:
        print(f"  ... and {len(notes) - args.max} more")
    print(f"  -> {len(unexpected)} change(s) outside the edited node")

    print("\n=== P0d: stale copies of the old vertex count ===")
    wanted = derived_values(node_a.vertex_count, node_a.mdx_stride, node_a.face_count)
    new_wanted = derived_values(node_b.vertex_count, node_b.mdx_stride, node_b.face_count)
    hits_a = scan(a.mdl, wanted)
    hits_b = scan(b.mdl, wanted)

    print(f"  looking for {len(wanted)} value(s) derived from {node_a.vertex_count}")
    stale = []
    for value, how in sorted(wanted.items()):
        n_a, n_b = len(hits_a.get(value, ())), len(hits_b.get(value, ()))
        if n_a == 0 and n_b == 0:
            continue
        # A value that survives the edit unchanged, and is not also a legitimate
        # value for the NEW count, is a candidate stale field.
        flag = ""
        if n_b >= n_a and n_a > 0 and value not in new_wanted:
            flag = "  <-- SURVIVED the edit"
            stale.append((value, how, n_a, n_b))
        print(f"    {value:>8}  {how:<22} vanilla x{n_a:<3} probe x{n_b:<3}{flag}")

    print(f"\n  {len(stale)} value(s) survived that should arguably have moved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
