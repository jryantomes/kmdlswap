"""The brief's influence-cap experiment, measured over the whole vanilla corpus.

Milestone 3 asks for variants capped at 1, 2, 4 and 8 influences per vertex,
tested in-game, and says the finding is worth publishing regardless of whether
the tool ships.

Two of those arms are answerable from data alone and are answered here:

* how many vertices a given cap actually touches, and
* how much weight it discards when it does.

The second number is what matters. Capping drops a vertex's weakest influences
and renormalises the rest; if the discarded share is tiny, the cap is close to
free. This bounds the *data* loss precisely. It does not predict the *visual*
error, which depends on how far apart the dropped bone and its replacements move
during an animation - only in-game testing settles that.

The 8 arm is not reachable at all: the MDX vertex stride holds exactly four
(weight, bone) pairs, so a fifth influence cannot be expressed without widening
the stride, which this tool does not do.

    python tools/influence_cap_experiment.py --install "<K1 root>"
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pykotor.extract.installation import Installation  # noqa: E402
from pykotor.resource.type import ResourceType  # noqa: E402

from kmdlswap import layout as kl  # noqa: E402
from kmdlswap import mdx as kmdx  # noqa: E402

CAPS = (1, 2, 3)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", required=True)
    ap.add_argument("--report", default="reports/influence_caps.json")
    args = ap.parse_args(argv)

    inst = Installation(args.install)
    index: dict[str, dict] = {}
    for r in inst.chitin_resources():
        if r.restype() in (ResourceType.MDL, ResourceType.MDX):
            index.setdefault(r.resname().lower(), {})[r.restype()] = r
    names = sorted(k for k, v in index.items() if len(v) == 2)

    total_verts = 0
    affected: Counter[int] = Counter()
    discarded: dict[int, list[float]] = {c: [] for c in CAPS}
    worst: dict[int, tuple[float, str]] = {c: (0.0, "") for c in CAPS}

    for i, name in enumerate(names):
        e = index[name]
        try:
            lay = kl.parse(e[ResourceType.MDL].data(), e[ResourceType.MDX].data())
        except Exception:  # noqa: BLE001
            continue
        for node in lay.nodes:
            if not (node.is_skin and node.in_animation is None):
                continue
            for infl in kmdx.influences(lay, node):
                if not infl:
                    continue
                total_verts += 1
                weights = sorted((x.weight for x in infl), reverse=True)
                whole = sum(weights)
                for cap in CAPS:
                    if len(weights) <= cap:
                        continue
                    affected[cap] += 1
                    lost = sum(weights[cap:]) / whole if whole else 0.0
                    discarded[cap].append(lost)
                    if lost > worst[cap][0]:
                        worst[cap] = (lost, f"{name}:{node.name}")
        if (i + 1) % 500 == 0:
            print(f"  {i + 1}/{len(names)} ...", file=sys.stderr)

    summary = {
        "skinned_vertices": total_verts,
        "stride_limit": 4,
        "caps": {},
    }
    for cap in CAPS:
        vals = discarded[cap]
        summary["caps"][str(cap)] = {
            "vertices_affected": affected[cap],
            "percent_affected": round(100 * affected[cap] / total_verts, 3) if total_verts else 0,
            "weight_discarded_mean_pct": round(100 * statistics.fmean(vals), 3) if vals else 0.0,
            "weight_discarded_median_pct": round(100 * statistics.median(vals), 3) if vals else 0.0,
            "weight_discarded_p95_pct": (
                round(100 * sorted(vals)[int(0.95 * (len(vals) - 1))], 3) if vals else 0.0
            ),
            "weight_discarded_max_pct": round(100 * worst[cap][0], 3),
            "worst_case_mesh": worst[cap][1],
        }

    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
