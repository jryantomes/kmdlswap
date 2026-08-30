"""Render a preview image for every catalogued character model.

Exports each model's visible meshes to a model-space OBJ, then hands the whole
batch to one Blender process. Splitting it this way keeps all the KOTOR format
knowledge on this side and uses Blender only as a renderer.

    python tools/render_catalogue.py --install "<K1 root>"
    python tools/render_catalogue.py --install "<K1 root>" --limit 8   # smoke test
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kmdlfun import parts, space  # noqa: E402
from kmdlswap import edit as ke  # noqa: E402
from kmdlswap import layout as kl  # noqa: E402
from kmdlswap import validate as kv  # noqa: E402

BLENDER_CANDIDATES = [
    r"C:\Program Files\Blender Foundation\Blender 3.6\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe",
    "blender",
]


def find_blender(explicit: str | None) -> str:
    if explicit:
        return explicit
    for c in BLENDER_CANDIDATES:
        if c == "blender" or Path(c).is_file():
            return c
    raise SystemExit("Blender not found; pass --blender <path to blender.exe>")


def write_model_obj(layout: kl.Layout, path: Path) -> int:
    """Visible meshes, posed into model space. Same convention as
    tools/dump_model_obj.py, which this deliberately mirrors."""
    pose = space.rest_pose(layout)
    lines: list[str] = []
    base = 1
    written = 0
    for node in parts.mesh_nodes(layout):
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
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", required=True)
    ap.add_argument("--out", default="catalogue")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--blender")
    ap.add_argument("--keep-obj", action="store_true")
    args = ap.parse_args(argv)

    from pykotor.extract.installation import Installation
    from pykotor.resource.type import ResourceType

    blender = find_blender(args.blender)
    out = Path(args.out)
    obj_dir = out / "obj"
    png_dir = out / "png"
    obj_dir.mkdir(parents=True, exist_ok=True)
    png_dir.mkdir(parents=True, exist_ok=True)

    inst = Installation(args.install)
    index: dict[str, dict] = {}
    for r in inst.chitin_resources():
        if r.restype() in (ResourceType.MDL, ResourceType.MDX):
            index.setdefault(r.resname().lower(), {})[r.restype()] = r
    names = sorted(
        k for k, v in index.items() if len(v) == 2 and k.startswith(("p_", "n_", "c_"))
    )
    if args.limit:
        names = names[: args.limit]

    jobs = []
    for i, name in enumerate(names):
        e = index[name]
        try:
            layout = kl.parse(e[ResourceType.MDL].data(), e[ResourceType.MDX].data())
            if not kv.check(layout).ok:
                continue
            obj_path = obj_dir / f"{name}.obj"
            if write_model_obj(layout, obj_path) == 0:
                continue
        except Exception as exc:  # noqa: BLE001
            print(f"  skipped {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        jobs.append(
            {
                "name": name,
                "obj": str(obj_path.resolve()),
                "png": str((png_dir / f"{name}.png").resolve()),
            }
        )
        if (i + 1) % 40 == 0:
            print(f"  exported {i + 1}/{len(names)} ...", file=sys.stderr)

    manifest = out / "manifest.json"
    manifest.write_text(json.dumps(jobs, indent=1))
    print(f"exported {len(jobs)} OBJs; rendering with {blender} ...")

    proc = subprocess.run(
        [
            blender, "--background", "--python",
            str(Path(__file__).with_name("blender_render.py").resolve()),
            "--", "--manifest", str(manifest.resolve()),
        ],
        capture_output=True,
        text=True,
    )
    result = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT")]
    if not result:
        print(proc.stdout[-2000:], file=sys.stderr)
        print(proc.stderr[-2000:], file=sys.stderr)
        raise SystemExit("Blender produced no result line")
    payload = json.loads(result[0][7:])
    print(f"rendered {payload['rendered']} previews into {png_dir}")
    for f in payload["failed"]:
        print(f"  FAILED {f}", file=sys.stderr)

    if not args.keep_obj:
        for j in jobs:
            Path(j["obj"]).unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
