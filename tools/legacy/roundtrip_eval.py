"""Milestone 0 oracle: load every MDL/MDX pair in a vanilla K1 install through
PyKotor and re-emit it, then byte-diff the result against the original.

A high pass rate here is the only real proof the reader/writer is correct.

Usage:
    python tools/roundtrip_eval.py --install "E:\\SteamLibrary\\steamapps\\common\\swkotor"
    python tools/roundtrip_eval.py --install ... --filter p_          # char models only
    python tools/roundtrip_eval.py --install ... --dump-bad reports/  # write mismatching pairs
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
import traceback
from pathlib import Path

from pykotor.common.misc import Game
from pykotor.extract.installation import Installation
from pykotor.resource.formats.mdl.io_mdl import MDLBinaryReader, MDLBinaryWriter
from pykotor.resource.type import ResourceType


def first_diff(a: bytes, b: bytes) -> int:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    if len(a) != len(b):
        return n
    return -1


def roundtrip_one(mdl_in: bytes, mdx_in: bytes) -> dict:
    """Return a result dict for one pair. Never raises."""
    rec: dict = {
        "mdl_in_size": len(mdl_in),
        "mdx_in_size": len(mdx_in),
    }
    try:
        mdl = MDLBinaryReader(
            bytes(mdl_in), 0, len(mdl_in),
            bytes(mdx_in), 0, len(mdx_in),
            game=Game.K1,
        ).load()
    except Exception as exc:  # noqa: BLE001 - we want every failure classified
        rec["status"] = "read_error"
        rec["error"] = f"{type(exc).__name__}: {exc}"
        rec["trace"] = traceback.format_exc(limit=6)
        return rec

    try:
        mdl_out_buf = bytearray()
        mdx_out_buf = bytearray()
        MDLBinaryWriter(mdl, mdl_out_buf, mdx_out_buf).write()
        mdl_out, mdx_out = bytes(mdl_out_buf), bytes(mdx_out_buf)
    except Exception as exc:  # noqa: BLE001
        rec["status"] = "write_error"
        rec["error"] = f"{type(exc).__name__}: {exc}"
        rec["trace"] = traceback.format_exc(limit=6)
        return rec

    rec["mdl_out_size"] = len(mdl_out)
    rec["mdx_out_size"] = len(mdx_out)
    mdl_d = first_diff(mdl_in, mdl_out)
    mdx_d = first_diff(mdx_in, mdx_out)
    rec["mdl_first_diff"] = mdl_d
    rec["mdx_first_diff"] = mdx_d
    rec["status"] = "exact" if (mdl_d == -1 and mdx_d == -1) else "mismatch"
    return rec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", required=True, help="path to a vanilla K1 install root")
    ap.add_argument("--filter", default="", help="only resnames starting with this prefix")
    ap.add_argument("--limit", type=int, default=0, help="stop after N pairs (0 = all)")
    ap.add_argument("--report", default="reports/roundtrip.json")
    ap.add_argument("--dump-bad", default="", help="dir to write mismatching in/out pairs")
    args = ap.parse_args(argv)

    inst = Installation(args.install)
    resources = inst.chitin_resources()
    by_name_type: dict[tuple[str, ResourceType], object] = {
        (r.resname().lower(), r.restype()): r for r in resources
    }
    mdl_res = sorted(
        (r for r in resources if r.restype() == ResourceType.MDL),
        key=lambda r: r.resname().lower(),
    )
    if args.filter:
        mdl_res = [r for r in mdl_res if r.resname().lower().startswith(args.filter.lower())]
    if args.limit:
        mdl_res = mdl_res[: args.limit]

    dump_dir = Path(args.dump_bad) if args.dump_bad else None
    if dump_dir:
        dump_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    counts: dict[str, int] = {}
    t0 = time.time()
    for i, r in enumerate(mdl_res):
        name = r.resname().lower()
        mdx = by_name_type.get((name, ResourceType.MDX))
        if mdx is None:
            rec = {"name": name, "status": "no_mdx"}
        else:
            rec = {"name": name}
            rec.update(roundtrip_one(r.data(), mdx.data()))
        results.append(rec)
        counts[rec["status"]] = counts.get(rec["status"], 0) + 1

        if dump_dir and rec["status"] in ("mismatch", "read_error", "write_error"):
            (dump_dir / f"{name}.in.mdl").write_bytes(r.data())
            if mdx is not None:
                (dump_dir / f"{name}.in.mdx").write_bytes(mdx.data())

        if (i + 1) % 200 == 0:
            print(f"  {i + 1}/{len(mdl_res)} ...", file=sys.stderr)

    elapsed = time.time() - t0
    total = len(results)
    exact = counts.get("exact", 0)
    summary = {
        "install": args.install,
        "filter": args.filter or None,
        "total": total,
        "exact": exact,
        "pass_rate": round(exact / total, 4) if total else 0.0,
        "counts": counts,
        "elapsed_sec": round(elapsed, 1),
    }

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({"summary": summary, "results": results}, indent=2))

    print(json.dumps(summary, indent=2))
    # Worst offenders for a quick eyeball
    bad = [r for r in results if r["status"] == "mismatch"][:15]
    if bad:
        print("\nfirst 15 mismatches (name: mdl_first_diff / mdx_first_diff, sizes in->out):")
        for r in bad:
            print(
                f"  {r['name']:<24} mdl@{r.get('mdl_first_diff')} mdx@{r.get('mdx_first_diff')}"
                f"  mdl {r.get('mdl_in_size')}->{r.get('mdl_out_size')}"
                f"  mdx {r.get('mdx_in_size')}->{r.get('mdx_out_size')}"
            )
    errs = [r for r in results if r["status"] in ("read_error", "write_error")][:10]
    if errs:
        print("\nfirst 10 errors:")
        for r in errs:
            print(f"  {r['name']:<24} {r['status']}: {r.get('error')}")

    return 0 if exact == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
