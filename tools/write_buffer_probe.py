"""Probe P1b: grow the MDX block without changing the declared vertex count.

The engine reads `vertex_count` from the MDL and vertex data from the MDX. Every
probe so far changed both together, so nothing has separated *the number the
engine is told* from *the size of the buffer it is told about*.

This changes only the second. Three duplicate vertex rows are inserted into the
target mesh's MDX block, immediately before its sentinel row, and the two MDX
size fields are updated. `vertex_count` stays at its vanilla value, the MDL-side
vertex and face arrays are untouched, and the MDL does not change length at all.
The engine is then told to read 565 vertices out of a block holding 568.

Safe by construction: the buffer is over-provisioned, never short, so nothing
reads past the end of anything.

* **Skinning survives** - the declared count is the trigger, and the cause lies
  in whatever changes *because* the count changed.
* **Skinning breaks** - the engine is sensitive to the block's size or layout
  rather than to the count, which is a different search entirely.

Requires the target to own the **last** MDX block, so that growing it shifts no
other block and no offset anywhere needs rewriting. Refuses otherwise.

    python tools/write_buffer_probe.py --install "<K1 root>" --model p_carthh \\
        --node Head --extra 3 --out out_probe/

Never writes into the game install.
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kmdlswap import layout as kl  # noqa: E402
from kmdlswap import validate as kv  # noqa: E402
from kmdlswap.loader import load  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install")
    ap.add_argument("--model", required=True)
    ap.add_argument("--node", required=True)
    ap.add_argument("--extra", type=int, default=3)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    layout = load(args.model, args.install)
    if not kv.check(layout).ok:
        print(f"refusing {args.model}: does not fully validate", file=sys.stderr)
        return 1

    node = layout.node_by_name(args.node)
    span = next((s for s in layout.mdx_spans if s.owner == node.index), None)
    if span is None:
        print(f"{args.node} has no MDX block", file=sys.stderr)
        return 1
    if span.end != len(layout.mdx):
        print(f"{args.node} does not own the last MDX block (ends at {span.end} of "
              f"{len(layout.mdx)}); this probe would have to shift other blocks",
              file=sys.stderr)
        return 1

    stride = node.mdx_stride
    used = node.vertex_count * stride
    if span.size - used != stride:
        print("expected exactly one spare sentinel row", file=sys.stderr)
        return 1

    # [ real vertices | NEW duplicate rows | sentinel ]
    cut = span.start + used
    filler = layout.mdx[span.start : span.start + args.extra * stride]
    mdx = layout.mdx[:cut] + filler + layout.mdx[cut:]
    added = len(mdx) - len(layout.mdx)

    # Only the two MDX size fields move. The MDL keeps its length.
    mdl = bytearray(layout.mdl)
    touched = []
    for c in layout.counts:
        if c.array_id in ("mdx_size", "model_mdx_size"):
            struct.pack_into("<I", mdl, c.loc, c.value + added)
            touched.append(f"{c.array_id}@0x{c.loc:05x} {c.value} -> {c.value + added}")
    if len(touched) != 2:
        print(f"expected 2 MDX size fields, found {len(touched)}", file=sys.stderr)
        return 1
    mdl = bytes(mdl)

    after = kl.parse(mdl, mdx)
    rep = kv.check(after)
    if not rep.ok:
        print(f"produced model does not validate: gaps={len(rep.gaps)} "
              f"overlaps={len(rep.overlaps)} dangling={len(rep.dangling)}", file=sys.stderr)
        return 1
    if after.node_by_name(args.node).vertex_count != node.vertex_count:
        print("vertex_count moved; it must not", file=sys.stderr)
        return 1
    if len(mdl) != len(layout.mdl):
        print("MDL length changed; it must not", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{args.model}.mdl").write_bytes(mdl)
    (out / f"{args.model}.mdx").write_bytes(mdx)

    print(f"wrote {out / args.model}.mdl / .mdx")
    print(f"  node             : {node.name}, "
          f"{'skinned' if node.is_skin else 'unskinned'}")
    print(f"  vertex_count     : {node.vertex_count}  (UNCHANGED - this is the point)")
    print(f"  MDX block        : {span.size} -> {span.size + added} bytes "
          f"({args.extra} spare rows inserted before the sentinel)")
    for line in touched:
        print(f"  {line}")
    print(f"  MDL length       : {len(mdl)} (unchanged)")
    print(f"  MDX length       : {len(layout.mdx)} -> {len(mdx)}")
    print("\nThe engine is told to read "
          f"{node.vertex_count} vertices from a block holding "
          f"{node.vertex_count + args.extra}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
