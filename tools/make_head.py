"""Generate a custom head pack. The shaping lives in kmdlfun.headgen.

    python tools/make_head.py --out packs/moldy_one --install "<K1 root>"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kmdlfun import headgen  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="pack folder to create")
    ap.add_argument("--name", default="Moldy One")
    ap.add_argument("--rings", type=int, default=13)
    ap.add_argument("--segments", type=int, default=22)
    ap.add_argument("--texture", default="moldyone")
    ap.add_argument("--install", help="fit to a node in this install")
    ap.add_argument("--host", default="p_hk47")
    ap.add_argument("--node", default="head")
    args = ap.parse_args(argv)

    size = centre = None
    if args.install:
        from kmdlfun.library import ModelLibrary
        from kmdlswap import edit as ke
        from kmdlswap import layout as kl

        layout = kl.parse(*ModelLibrary(args.install).read(args.host))
        geo = ke.extract(layout, layout.node_by_name(args.node))
        lo = [min(p[i] for p in geo.positions) for i in range(3)]
        hi = [max(p[i] for p in geo.positions) for i in range(3)]
        size = tuple(hi[i] - lo[i] for i in range(3))
        centre = tuple((hi[i] + lo[i]) / 2 for i in range(3))

    root = headgen.build_pack(
        args.out, name=args.name, rings=args.rings, segments=args.segments,
        texture=args.texture, size=size, centre=centre,
    )
    from kmdlswap import obj as kobj

    mesh = kobj.read_obj(root / "head.obj")
    lo = [min(p[i] for p in mesh.positions) for i in range(3)]
    hi = [max(p[i] for p in mesh.positions) for i in range(3)]
    print(f"{args.name} -> {root}")
    print(f"  {mesh.vertex_count} vertices, {len(mesh.faces)} triangles")
    print(f"  size {hi[0]-lo[0]:.3f} x {hi[1]-lo[1]:.3f} x {hi[2]-lo[2]:.3f}")
    if size:
        print(f"  target {size[0]:.3f} x {size[1]:.3f} x {size[2]:.3f}"
              f"  ({args.host}:{args.node})")
    print(f"  check it: kmdlfun head {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
