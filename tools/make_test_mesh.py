"""Generate deliberately-visible replacement geometry, for in-game testing.

Milestone 3's acceptance is a model that loads, renders and animates with
geometry it did not ship with. A round-tripped mesh cannot demonstrate that -
if it renders, you have learned nothing, because it is the original shape. The
replacement has to be obviously different, so that "it looks right" means the
new data is genuinely in use.

Modes:
  scale   uniformly scale the node's vertices about their centroid. Same vertex
          count and topology; isolates whether new positions are used.
  bulge   push vertices out along their normals. Same count; a smooth, obvious
          deformation that also shows normals are being read.
  box     replace the node with an 8-vertex box spanning its bounding volume.
          Completely new topology; on a skinned node this is the real test of
          weight transfer, since nothing is inherited by index.

    python tools/make_test_mesh.py --install "<K1 root>" --model p_hk47 \
        --node head --mode scale --factor 1.3 --out out_m3/head.obj
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kmdlswap import edit as ke  # noqa: E402
from kmdlswap import obj as kobj  # noqa: E402
from kmdlswap import swap as ks  # noqa: E402
from kmdlswap.loader import load  # noqa: E402


def centroid(points):
    n = len(points)
    return tuple(sum(p[i] for p in points) / n for i in range(3))


def mode_scale(positions, normals, faces, factor):
    c = centroid(positions)
    moved = [
        tuple(c[i] + (p[i] - c[i]) * factor for i in range(3)) for p in positions
    ]
    return moved, normals, faces


def mode_bulge(positions, normals, faces, factor):
    if not normals:
        raise SystemExit("bulge needs vertex normals, which this mesh does not carry")
    c = centroid(positions)
    extent = max(
        max(abs(p[i] - c[i]) for i in range(3)) for p in positions
    )
    amount = extent * (factor - 1.0)
    moved = [
        tuple(p[i] + normals[v][i] * amount for i in range(3))
        for v, p in enumerate(positions)
    ]
    return moved, normals, faces


def mode_box(positions, normals, faces, factor):
    lo = tuple(min(p[i] for p in positions) for i in range(3))
    hi = tuple(max(p[i] for p in positions) for i in range(3))
    c = centroid(positions)
    lo = tuple(c[i] + (lo[i] - c[i]) * factor for i in range(3))
    hi = tuple(c[i] + (hi[i] - c[i]) * factor for i in range(3))
    corners = [
        (lo[0], lo[1], lo[2]), (hi[0], lo[1], lo[2]),
        (hi[0], hi[1], lo[2]), (lo[0], hi[1], lo[2]),
        (lo[0], lo[1], hi[2]), (hi[0], lo[1], hi[2]),
        (hi[0], hi[1], hi[2]), (lo[0], hi[1], hi[2]),
    ]
    quads = [
        (0, 1, 2, 3), (5, 4, 7, 6), (4, 0, 3, 7),
        (1, 5, 6, 2), (3, 2, 6, 7), (4, 5, 1, 0),
    ]
    out_pos, out_faces = [], []
    for q in quads:
        base = len(out_pos)
        out_pos.extend(corners[i] for i in q)
        out_faces.append((base, base + 1, base + 2))
        out_faces.append((base, base + 2, base + 3))
    return out_pos, None, out_faces


MODES = {"scale": mode_scale, "bulge": mode_bulge, "box": mode_box}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install")
    ap.add_argument("--model", required=True)
    ap.add_argument("--node", required=True)
    ap.add_argument("--mode", choices=sorted(MODES), default="scale")
    ap.add_argument("--factor", type=float, default=1.3)
    ap.add_argument("--out", required=True, help="output .obj path")
    args = ap.parse_args(argv)

    layout = load(args.model, args.install)
    node = layout.node_by_name(args.node)
    geo = ke.extract(layout, node)
    positions, faces, uvs, normals = ks.geometry_to_obj_arrays(geo)

    new_pos, new_normals, new_faces = MODES[args.mode](
        positions, normals, faces, args.factor
    )
    new_uvs = uvs if new_faces is faces else None
    if new_faces is not faces:
        new_uvs = [(0.0, 0.0)] * len(new_pos)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    kobj.write_obj(out, new_pos, new_faces, new_uvs, new_normals, name=node.name)

    print(f"wrote {out}")
    print(f"  source     {args.model}:{node.name}  skinned={node.is_skin}")
    print(f"  mode       {args.mode} (factor {args.factor})")
    print(f"  vertices   {len(positions)} -> {len(new_pos)}")
    print(f"  triangles  {len(faces)} -> {len(new_faces)}")
    if new_uvs is None or new_faces is not faces:
        print("  NOTE       texture coordinates are zeroed; the mesh will look untextured")
    print("\nNext: kmdlswap replace ... --mesh " + str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
