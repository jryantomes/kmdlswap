"""Write a no-op swap of a model to a directory, for in-game verification.

Milestone 2's acceptance has two halves. The file-side half - output is
byte-identical - is proven by tools/noop_swap_sweep.py. This produces the actual
files for the other half: load them in KOTOR 1 and confirm the model renders and
animates. A successful file build is not proof.

    python tools/write_noop.py --install "<K1 root>" --model p_hk47 --node head --out out/

Never writes into the game install. Copy the output into Override yourself.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kmdlswap import edit as ke  # noqa: E402
from kmdlswap import layout as kl  # noqa: E402
from kmdlswap import validate as kv  # noqa: E402
from kmdlswap.loader import load  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", help="game install to read the model from")
    ap.add_argument("--model", required=True, help="resname, or path to a .mdl")
    ap.add_argument("--node", help="mesh node to round-trip (default: every mesh node)")
    ap.add_argument("--out", required=True, help="output directory")
    args = ap.parse_args(argv)

    layout = load(args.model, args.install)
    rep = kv.check(layout)
    if not rep.ok:
        print(
            f"refusing {args.model}: does not fully validate "
            f"(gaps={len(rep.gaps)} overlaps={len(rep.overlaps)} dangling={len(rep.dangling)})",
            file=sys.stderr,
        )
        return 1

    if args.node:
        targets = [layout.node_by_name(args.node)]
    else:
        targets = [
            n
            for n in layout.nodes
            if n.is_mesh and n.in_animation is None and n.vertex_count and "saber" not in n.flags
        ]

    mdl, mdx = layout.mdl, layout.mdx
    current = layout
    for node in targets:
        node = current.node_by_name(node.name)
        mdl, mdx = ke.replace_geometry(current, node, ke.extract(current, node))
        current = kl.parse(mdl, mdx)

    identical = mdl == layout.mdl and mdx == layout.mdx
    final = kv.check(current)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = layout.model_name.lower() or Path(args.model).stem
    (out_dir / f"{stem}.mdl").write_bytes(mdl)
    (out_dir / f"{stem}.mdx").write_bytes(mdx)

    print(f"wrote {out_dir / stem}.mdl / .mdx")
    print(f"  nodes rewritten : {len(targets)}")
    print(f"  byte-identical  : {'yes' if identical else 'NO'}")
    print(f"  validates       : {'yes' if final.ok else 'NO'}")
    print("\nNext: copy both files into the game's Override directory and load the model")
    print("in-game. A successful file build is not proof.")
    return 0 if identical and final.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
