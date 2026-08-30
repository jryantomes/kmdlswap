"""How does vanilla store a mesh's bounding box, radius and average point?

An edit that resizes a mesh has to decide what to do with those three fields.
Recomputing them is only safe if vanilla itself keeps them tight; this measures
whether it does.

    python tools/mesh_bounds_census.py --install "<K1 root>"
    python tools/mesh_bounds_census.py --install "<K1 root>" --filter p_
"""

from __future__ import annotations

import argparse
import math
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pykotor.extract.installation import Installation  # noqa: E402
from pykotor.resource.type import ResourceType  # noqa: E402

from kmdlswap import edit as ke  # noqa: E402
from kmdlswap import layout as kl  # noqa: E402

TOL = 1e-5


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", required=True)
    ap.add_argument("--filter", default="")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    inst = Installation(args.install)
    index: dict[str, dict] = {}
    for r in inst.chitin_resources():
        if r.restype() in (ResourceType.MDL, ResourceType.MDX):
            index.setdefault(r.resname().lower(), {})[r.restype()] = r
    names = sorted(n for n, e in index.items() if len(e) == 2 and args.filter in n)
    if args.limit:
        names = names[: args.limit]

    c = Counter()
    worst_pad = 0.0
    worst_pad_where = ""
    for name in names:
        mdl = index[name][ResourceType.MDL].data()
        mdx = index[name][ResourceType.MDX].data()
        try:
            layout = kl.parse(mdl, mdx)
        except Exception:  # noqa: BLE001
            c["models_unparsed"] += 1
            continue
        c["models"] += 1
        for node in layout.nodes:
            if node.in_animation is not None or not node.is_mesh or not node.vertex_count:
                continue
            if "saber" in node.flags:
                continue
            try:
                ps = ke.extract(layout, node).positions
            except Exception:  # noqa: BLE001
                continue
            if not ps:
                continue
            bmin, bmax, radius, average = ke.bounds(layout, node)
            lo = [min(p[i] for p in ps) for i in range(3)]
            hi = [max(p[i] for p in ps) for i in range(3)]
            c["meshes"] += 1

            if all(abs(bmin[i] - lo[i]) < TOL and abs(bmax[i] - hi[i]) < TOL for i in range(3)):
                c["bbox_tight"] += 1
            elif all(bmin[i] <= lo[i] + TOL and bmax[i] >= hi[i] - TOL for i in range(3)):
                c["bbox_padded"] += 1
                pad = max(max(lo[i] - bmin[i], bmax[i] - hi[i]) for i in range(3))
                if pad > worst_pad:
                    worst_pad, worst_pad_where = pad, f"{name}:{node.name}"
            else:
                c["bbox_too_small"] += 1

            centroid = [sum(p[i] for p in ps) / len(ps) for i in range(3)]
            if all(abs(average[i] - centroid[i]) < TOL for i in range(3)):
                c["average_is_centroid"] += 1
            else:
                c["average_is_something_else"] += 1

            if abs(radius - max(math.dist(p, average) for p in ps)) < TOL:
                c["radius_is_max_dist_from_average"] += 1
            else:
                c["radius_is_something_else"] += 1

    for k in sorted(c):
        print(f"{k:<34} {c[k]}")
    if worst_pad_where:
        print(f"largest padding: {worst_pad:.3f} on {worst_pad_where}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
