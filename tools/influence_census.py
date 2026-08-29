"""Empirical census: how many bone influences per vertex does vanilla K1 use?

The brief lists max-influences-per-vertex as a genuine unknown, to be answered
by experiment. This measures the ceiling the shipped game actually exercises,
across every skinned mesh in the install. That is not the same as the engine's
limit - only in-game testing settles that - but it is the strongest available
prior, and it bounds what a weight-transfer step needs to emit.

    python tools/influence_census.py --install "<K1 root>"
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pykotor.extract.installation import Installation  # noqa: E402
from pykotor.resource.type import ResourceType  # noqa: E402

from kmdlswap import layout as kl  # noqa: E402
from kmdlswap import mdx as kmdx  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", required=True)
    ap.add_argument("--report", default="reports/influence_census.json")
    args = ap.parse_args(argv)

    inst = Installation(args.install)
    res = inst.chitin_resources()
    index: dict[str, dict] = {}
    for r in res:
        if r.restype() in (ResourceType.MDL, ResourceType.MDX):
            index.setdefault(r.resname().lower(), {})[r.restype()] = r

    hist: Counter[int] = Counter()
    per_mesh_max: Counter[int] = Counter()
    weight_sum_min, weight_sum_max = 2.0, 0.0
    unnormalised = 0
    skinned_meshes = 0
    models_with_skin = 0
    bone_counts: Counter[int] = Counter()
    examples: dict[int, str] = {}

    names = sorted(k for k, v in index.items() if ResourceType.MDL in v and ResourceType.MDX in v)
    for i, name in enumerate(names):
        entry = index[name]
        try:
            lay = kl.parse(entry[ResourceType.MDL].data(), entry[ResourceType.MDX].data())
        except Exception:  # noqa: BLE001 - census, not validation; that is corpus_check's job
            continue
        skins = [n for n in lay.nodes if n.is_skin and n.in_animation is None]
        if skins:
            models_with_skin += 1
        for n in skins:
            skinned_meshes += 1
            per_vertex = kmdx.influences(lay, n)
            mesh_max = 0
            slots = set()
            for infl in per_vertex:
                k = len(infl)
                hist[k] += 1
                mesh_max = max(mesh_max, k)
                total = sum(x.weight for x in infl)
                weight_sum_min = min(weight_sum_min, total)
                weight_sum_max = max(weight_sum_max, total)
                if abs(total - 1.0) > 1e-4:
                    unnormalised += 1
                slots.update(x.bone_slot for x in infl)
            per_mesh_max[mesh_max] += 1
            bone_counts[len(slots)] += 1
            examples.setdefault(mesh_max, f"{name}:{n.name}")
        if (i + 1) % 500 == 0:
            print(f"  {i + 1}/{len(names)} ...", file=sys.stderr)

    total_verts = sum(hist.values())
    summary = {
        "models_with_skinning": models_with_skin,
        "skinned_meshes": skinned_meshes,
        "skinned_vertices": total_verts,
        "influences_per_vertex_histogram": dict(sorted(hist.items())),
        "influences_per_vertex_pct": {
            k: round(100 * v / total_verts, 3) for k, v in sorted(hist.items())
        }
        if total_verts
        else {},
        "max_influences_observed": max(hist) if hist else 0,
        "per_mesh_max_histogram": dict(sorted(per_mesh_max.items())),
        "bones_per_mesh_max": max(bone_counts) if bone_counts else 0,
        "weight_sum_range": [round(weight_sum_min, 6), round(weight_sum_max, 6)],
        "vertices_not_summing_to_1": unnormalised,
        "example_by_max": {str(k): v for k, v in sorted(examples.items())},
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
