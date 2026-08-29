"""Milestone 2 acceptance harness: extract every mesh node's geometry and put
the SAME geometry straight back, then byte-diff the whole model.

Zero new variables. If the output is not identical, the rewrite mechanism is
wrong - independent of any question about the replacement content.

    python tools/noop_swap_sweep.py --install "<K1 root>" --filter p_
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pykotor.extract.installation import Installation  # noqa: E402
from pykotor.resource.type import ResourceType  # noqa: E402

from kmdlswap import edit as ke  # noqa: E402
from kmdlswap import layout as kl  # noqa: E402
from kmdlswap import validate as kv  # noqa: E402


def first_diff(a: bytes, b: bytes) -> int:
    if a == b:
        return -1
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            return i
    return min(len(a), len(b))


def sweep_model(mdl: bytes, mdx: bytes) -> tuple[int, int, list[str]]:
    lay = kl.parse(mdl, mdx)
    meshes = [
        n
        for n in lay.nodes
        if n.is_mesh and n.in_animation is None and n.vertex_count and "saber" not in n.flags
    ]
    ok = 0
    problems: list[str] = []
    for n in meshes:
        try:
            geo = ke.extract(lay, n)
            out_mdl, out_mdx = ke.replace_geometry(lay, n, geo)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{n.name}: {type(exc).__name__}: {exc}")
            continue
        if out_mdl == mdl and out_mdx == mdx:
            # The result must also still parse and validate, not merely match.
            rep = kv.check(kl.parse(out_mdl, out_mdx))
            if rep.ok:
                ok += 1
            else:
                problems.append(f"{n.name}: identical bytes but re-parse failed validation")
        else:
            problems.append(
                f"{n.name}: mdl@{first_diff(mdl, out_mdl)} mdx@{first_diff(mdx, out_mdx)} "
                f"sizes {len(mdl)}->{len(out_mdl)} / {len(mdx)}->{len(out_mdx)}"
            )
    return ok, len(meshes), problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", required=True)
    ap.add_argument("--filter", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--report", default="reports/noop_swap.json")
    args = ap.parse_args(argv)

    inst = Installation(args.install)
    res = inst.chitin_resources()
    index = {(r.resname().lower(), r.restype()): r for r in res}
    mdls = sorted(
        (r for r in res if r.restype() == ResourceType.MDL), key=lambda r: r.resname().lower()
    )
    if args.filter:
        mdls = [r for r in mdls if r.resname().lower().startswith(args.filter.lower())]
    if args.limit:
        mdls = mdls[: args.limit]

    total_ok = total_meshes = 0
    failures: list[dict] = []
    counts: Counter[str] = Counter()
    t0 = time.time()
    for i, r in enumerate(mdls):
        name = r.resname().lower()
        mdx = index.get((name, ResourceType.MDX))
        if mdx is None:
            continue
        try:
            ok, n, problems = sweep_model(r.data(), mdx.data())
        except Exception as exc:  # noqa: BLE001
            counts["model_error"] += 1
            failures.append(
                {"model": name, "error": f"{type(exc).__name__}: {exc}",
                 "trace": traceback.format_exc(limit=4)}
            )
            continue
        total_ok += ok
        total_meshes += n
        counts["clean_models" if not problems else "models_with_failures"] += 1
        if problems:
            failures.append({"model": name, "problems": problems[:5]})
        if (i + 1) % 250 == 0:
            print(f"  {i + 1}/{len(mdls)} ...", file=sys.stderr)

    summary = {
        "models": len(mdls),
        "mesh_nodes_swapped": total_meshes,
        "identical": total_ok,
        "pass_rate": round(total_ok / total_meshes, 5) if total_meshes else 0.0,
        "counts": dict(counts),
        "elapsed_sec": round(time.time() - t0, 1),
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps({"summary": summary, "failures": failures}, indent=2))
    print(json.dumps(summary, indent=2))
    for f in failures[:10]:
        print(f"\n  {f['model']}: {f.get('error') or f['problems']}")
    return 0 if total_ok == total_meshes else 1


if __name__ == "__main__":
    raise SystemExit(main())
