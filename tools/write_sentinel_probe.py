"""Probe P1d: write the unskinned sentinel into a skinned mesh.

Every MDX mesh block carries one extra vertex row past `vertex_count x stride`,
and its parked position splits perfectly by mesh type across the whole corpus -
`10,000,000` on all 6,795 unskinned blocks, `1,000,000` on all 495 skinned ones,
with no exceptions either way. The engine therefore chooses it per mesh type,
which means something reads it, and it divides skinned from unskinned on exactly
the axis that discriminates the facial-animation failure.

This writes the *unskinned* value into a skinned head and changes nothing else.
Vertex count, faces, weights, every offset and both file sizes are untouched -
the edit is three floats, in place.

* If facial animation breaks, the sentinel is load-bearing and we finally have a
  mechanism to pull on.
* If nothing happens, it is bookkeeping and the split is a compiler artefact.

    python tools/write_sentinel_probe.py --install "<K1 root>" --model p_carthh \\
        --node Head --out out_probe/

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

SKINNED_SENTINEL = 1_000_000.0
UNSKINNED_SENTINEL = 10_000_000.0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install")
    ap.add_argument("--model", required=True)
    ap.add_argument("--node", required=True)
    ap.add_argument("--value", type=float, default=UNSKINNED_SENTINEL)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    layout = load(args.model, args.install)
    if not kv.check(layout).ok:
        print(f"refusing {args.model}: does not fully validate", file=sys.stderr)
        return 1

    node = layout.node_by_name(args.node)
    if not node.is_skin:
        print(f"{args.node} is not skinned; this probe only means something on a "
              f"skinned mesh", file=sys.stderr)
        return 1

    span = next((s for s in layout.mdx_spans if s.owner == node.index), None)
    if span is None:
        print(f"{args.node} has no MDX block", file=sys.stderr)
        return 1

    used = node.vertex_count * node.mdx_stride
    row_at = span.start + used
    spare = span.size - used
    if spare != node.mdx_stride:
        print(f"expected exactly one spare vertex row, found {spare} bytes "
              f"against a stride of {node.mdx_stride}", file=sys.stderr)
        return 1

    before = struct.unpack_from("<3f", layout.mdx, row_at)
    if before[0] != SKINNED_SENTINEL:
        print(f"unexpected sentinel {before}; refusing to guess", file=sys.stderr)
        return 1

    mdx = bytearray(layout.mdx)
    struct.pack_into("<3f", mdx, row_at, args.value, args.value, args.value)
    mdx = bytes(mdx)

    after = kl.parse(layout.mdl, mdx)
    rep = kv.check(after)
    if not rep.ok:
        print("produced model does not validate", file=sys.stderr)
        return 1

    # Nothing but those twelve bytes may have moved.
    assert len(mdx) == len(layout.mdx), "MDX size changed"
    differing = [i for i in range(len(mdx)) if mdx[i] != layout.mdx[i]]
    if differing and (min(differing) != row_at or max(differing) >= row_at + 12):
        print(f"unexpected byte changes at {differing[:8]}", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{args.model}.mdl").write_bytes(layout.mdl)
    (out / f"{args.model}.mdx").write_bytes(mdx)

    print(f"wrote {out / args.model}.mdl / .mdx")
    print(f"  node               : {node.name} ({node.vertex_count} vertices, "
          f"stride {node.mdx_stride}, skinned)")
    print(f"  sentinel row at    : MDX +{row_at}")
    print(f"  sentinel           : {before[0]:,.0f} -> {args.value:,.0f}")
    print(f"  bytes changed      : {len(differing)} (expected 12)")
    print(f"  MDL / MDX size     : unchanged ({len(layout.mdl)} / {len(mdx)})")
    print("\nExpected if the sentinel is inert: identical to vanilla in every way.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
