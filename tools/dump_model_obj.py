"""Dump a model's visible meshes to one OBJ, in model space.

For looking at what an edit actually did, in Blender or any viewer, without
launching the game. Rest pose only: node transforms are applied, skinning is
not, which is exactly the pose the geometry is authored in.

    python tools/dump_model_obj.py --install "<K1 root>" --model p_missionh --out head.obj
    python tools/dump_model_obj.py --mdl out_fun/p_missionh.mdl --out big.obj
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kmdlfun import parts, space  # noqa: E402
from kmdlswap import edit as ke  # noqa: E402
from kmdlswap import layout as kl  # noqa: E402


def read_pair(args) -> tuple[bytes, bytes]:
    if args.mdl:
        mdl_path = Path(args.mdl)
        return mdl_path.read_bytes(), mdl_path.with_suffix(".mdx").read_bytes()
    from kmdlfun.library import ModelLibrary

    return ModelLibrary(args.install).read(args.model)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install")
    ap.add_argument("--model")
    ap.add_argument("--mdl", help="read a written .mdl/.mdx pair instead")
    ap.add_argument("--out", required=True)
    ap.add_argument("--all-nodes", action="store_true", help="include invisible `_g` boxes")
    args = ap.parse_args()

    layout = kl.parse(*read_pair(args))
    pose = space.rest_pose(layout)
    lines: list[str] = []
    written = 0
    base = 1
    for node in parts.mesh_nodes(layout, visible_only=not args.all_nodes):
        rest = pose[node.index]
        geo = ke.extract(layout, node)
        lines.append(f"o {node.name}")
        for v in geo.positions:
            w = tuple(
                rest.position[i] + sum(rest.rotation[i][k] * v[k] for k in range(3))
                for i in range(3)
            )
            lines.append(f"v {w[0]:.6f} {w[1]:.6f} {w[2]:.6f}")
        for f in geo.faces:
            a, b, c = (i + base for i in f.vertices)
            lines.append(f"f {a} {b} {c}")
        base += len(geo.positions)
        written += 1
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="ascii")
    print(f"{written} meshes, {base - 1} vertices -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
