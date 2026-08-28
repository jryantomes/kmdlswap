"""Milestone 0 acceptance harness for OUR parser.

Parses every MDL/MDX pair in a vanilla K1 install into a span map and runs the
coverage / offset-closure / identity validators. Reports per-model status and,
for failures, the largest unclaimed gaps - which is the iteration signal for
filling in the remaining span kinds.

    python tools/corpus_check.py --install "<K1 root>"
    python tools/corpus_check.py --install "<K1 root>" --filter p_ --verbose
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

from kmdlswap import layout as kl  # noqa: E402
from kmdlswap import validate as kv  # noqa: E402


def check_one(mdl: bytes, mdx: bytes) -> dict:
    try:
        lay = kl.parse(mdl, mdx)
    except kl.ParseError as exc:
        return {"status": "parse_refused", "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "parse_crash",
            "error": f"{type(exc).__name__}: {exc}",
            "trace": traceback.format_exc(limit=4),
        }

    rep = kv.check(lay)
    rec: dict = {
        "identity": rep.identity_mdl and rep.identity_mdx,
        "gap_bytes": rep.gap_bytes,
        "gap_count": len(rep.gaps),
        "overlaps": len(rep.overlaps),
        "dangling": len(rep.dangling),
        "nodes": len(lay.nodes),
        "anims": len(lay.animation_names),
    }
    rec["status"] = "ok" if rep.ok else "incomplete"
    if rep.gaps:
        biggest = sorted(rep.gaps, key=lambda g: -g.size)[:3]
        rec["top_gaps"] = [[g.stream, g.start, g.size] for g in biggest]
    if rep.overlaps:
        o = rep.overlaps[0]
        rec["first_overlap"] = f"{o.stream} {o.a.kind}[{o.a.start}:{o.a.end}] vs {o.b.kind}[{o.b.start}:{o.b.end}]"
    if rep.dangling:
        rec["first_dangling"] = rep.dangling[0]
    return rec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", required=True)
    ap.add_argument("--filter", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--report", default="reports/corpus_check.json")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    inst = Installation(args.install)
    res = inst.chitin_resources()
    index = {(r.resname().lower(), r.restype()): r for r in res}
    mdls = sorted(
        (r for r in res if r.restype() == ResourceType.MDL),
        key=lambda r: r.resname().lower(),
    )
    if args.filter:
        mdls = [r for r in mdls if r.resname().lower().startswith(args.filter.lower())]
    if args.limit:
        mdls = mdls[: args.limit]

    results = []
    counts: Counter[str] = Counter()
    gap_kinds: Counter[str] = Counter()
    t0 = time.time()
    for i, r in enumerate(mdls):
        name = r.resname().lower()
        mdx = index.get((name, ResourceType.MDX))
        rec = {"name": name}
        if mdx is None:
            rec["status"] = "no_mdx"
        else:
            rec.update(check_one(r.data(), mdx.data()))
        results.append(rec)
        counts[rec["status"]] += 1
        if rec.get("error"):
            gap_kinds[rec["error"][:90]] += 1
        if args.verbose and rec["status"] != "ok":
            print(f"  {name}: {json.dumps({k: v for k, v in rec.items() if k != 'trace'})}")
        if not args.verbose and (i + 1) % 250 == 0:
            print(f"  {i + 1}/{len(mdls)} ...", file=sys.stderr)

    total = len(results)
    ok = counts["ok"]
    summary = {
        "total": total,
        "ok": ok,
        "pass_rate": round(ok / total, 4) if total else 0.0,
        "counts": dict(counts),
        "elapsed_sec": round(time.time() - t0, 1),
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps({"summary": summary, "results": results}, indent=2))
    print(json.dumps(summary, indent=2))
    if gap_kinds:
        print("\ntop failure messages:")
        for msg, n in gap_kinds.most_common(10):
            print(f"  {n:>5}  {msg}")
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
