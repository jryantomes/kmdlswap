"""Move a leftover fitting onto a replaced head's face.

A head swap leaves the old head's fittings - HK-47's eye bar, a visor, an
antenna - wherever the old geometry put them. They cannot be removed without
touching the hierarchy, and hiding them loses detail that often still reads
well. Moving the geometry inside the node puts them back on the new face.

    python tools/place_fitting.py --mdl out/p_hk47.mdl --face head \
        --node Mesh01 --height 0.45 --out out2/
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kmdlfun import placement as kp
from kmdlswap import edit as ke, layout as kl, validate as kv


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mdl", required=True)
    ap.add_argument("--face", required=True, help="the head mesh to place against")
    ap.add_argument("--node", required=True, help="the fitting to move")
    ap.add_argument("--height", type=float, default=0.45,
                    help="height up the head, 0 = chin, 1 = crown")
    ap.add_argument("--proud", type=float, default=0.004,
                    help="how far to stand off the surface")
    ap.add_argument("--width", type=float, default=0.30,
                    help="how far off the centre line to sample the surface")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    mdl_path = Path(a.mdl)
    mdl = mdl_path.read_bytes()
    mdx = mdl_path.with_suffix(".mdx").read_bytes()
    lay = kl.parse(mdl, mdx)
    face = lay.node_by_name(a.face)
    node = lay.node_by_name(a.node)

    cx, surface, z = kp.face_surface(lay, face, a.height, facing=+1, axis=1,
                                     width=a.width)
    lo, hi = kp.model_bounds(lay, node)
    centre = [(lo[i] + hi[i]) / 2 for i in range(3)]
    depth = hi[1] - lo[1]
    target_y = surface + a.proud - depth / 2 + depth  # front face just proud
    delta = (cx - centre[0], target_y - centre[1], z - centre[2])

    geo = kp.translate_geometry(lay, node, delta)
    new_mdl, new_mdx = ke.replace_geometry(lay, node, geo)
    after = kl.parse(new_mdl, new_mdx)
    if not kv.check(after).ok:
        print("result failed validation; not written", file=sys.stderr)
        return 1

    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    (out / mdl_path.name).write_bytes(new_mdl)
    (out / mdl_path.with_suffix(".mdx").name).write_bytes(new_mdx)

    nlo, nhi = kp.model_bounds(after, after.node_by_name(a.node))
    flo, fhi = kp.model_bounds(after, after.node_by_name(a.face))
    h = fhi[2] - flo[2]
    print(f"{a.node} -> {a.height:.0%} of {a.face} height")
    print(f"  moved {tuple(round(v, 3) for v in delta)}")
    print(f"  now Z {nlo[2]:+.3f}..{nhi[2]:+.3f}  "
          f"({((nlo[2]+nhi[2])/2 - flo[2]) / h:.0%} height)  Y {nlo[1]:+.3f}..{nhi[1]:+.3f}")
    print(f"  wrote {out / mdl_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
