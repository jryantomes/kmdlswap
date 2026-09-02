"""Put every Jade head through the whole path and see what survives.

Three heads were checked by hand and all three worked, which says almost
nothing about a hundred and fifty-eight. This converts each one, builds it onto
a KOTOR host, and records what happened - so the failures are counted and named
rather than discovered one at a time by whoever picks an unlucky face.

    python tools/jade_sweep.py [--kind head|body] [--limit N] [--host p_carthh]

Writes `reports/jade_sweep.json` and prints a summary.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import traceback
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def failure_reason(lines) -> str:
    """The first check that failed, named the way the report names it."""
    for line in lines:
        if "[FAIL]" in line:
            after = line.split("[FAIL]", 1)[1].strip()
            return after.split(":", 1)[0].strip() or "unnamed check"
    return "no failing check named"


def run(kind: str, limit: int | None, host: str, node: str, decimate):
    from kmdlfun import headbuild, installs, jade

    jade_root = installs.detect().get(installs.JADE)
    k1 = installs.detect().get(installs.K1)
    if not jade_root:
        raise SystemExit("no Jade Empire install found")
    if not k1:
        raise SystemExit("no KOTOR install found")

    entries = [e for e in jade.catalogue(jade_root) if e.kind == kind]
    if limit:
        entries = entries[:limit]
    print(f"{len(entries)} {kind}(s) from {jade_root}")
    print(f"building each onto {host}:{node}\n")

    scratch = Path(tempfile.mkdtemp())
    rows = []
    for i, entry in enumerate(entries, 1):
        row = {"resref": entry.resref, "kind": entry.kind}
        pack = scratch / entry.resref.strip("_").lower()
        try:
            made = jade.to_pack(entry, pack)
            row.update(triangles=made["triangles"], vertices=made["vertices"],
                       uvs=made["uvs"], texture=bool(made["texture"]),
                       notes=made["notes"])
        except Exception as exc:                        # noqa: BLE001
            row.update(stage="convert", ok=False,
                       why=f"{type(exc).__name__}: {exc}")
            rows.append(row)
            print(f"  [{i:>3}] {entry.resref:<20} CONVERT FAILED  {row['why'][:60]}")
            continue

        try:
            result = headbuild.run(str(pack), install=k1, host=host, node=node,
                                   decimate=decimate, repair=True, fit=True,
                                   reshape=False, hide=[], crop=None,
                                   build=True)
        except Exception as exc:                        # noqa: BLE001
            row.update(stage="build", ok=False,
                       why=f"{type(exc).__name__}: {exc}")
            rows.append(row)
            print(f"  [{i:>3}] {entry.resref:<20} BUILD RAISED    {row['why'][:60]}")
            continue

        row.update(stage="build", ok=bool(result.ok),
                   why="" if result.ok else failure_reason(result.lines),
                   warnings=[l.split("[warn]", 1)[1].strip().split(":", 1)[0]
                             for l in result.lines if "[warn]" in l])
        rows.append(row)
        mark = "ok  " if result.ok else "FAIL"
        print(f"  [{i:>3}] {entry.resref:<20} {mark}  "
              f"{row['triangles']:>5} tris  "
              f"{'tex' if row['texture'] else 'no tex':<6} {row['why'][:44]}")
    return rows


def summarise(rows):
    good = [r for r in rows if r.get("ok")]
    bad = [r for r in rows if not r.get("ok")]
    print(f"\n{len(good)}/{len(rows)} built  ({len(good) / max(len(rows), 1):.0%})")

    if bad:
        print("\nwhy the rest did not:")
        for why, n in Counter(r.get("why", "?") for r in bad).most_common():
            print(f"   {n:>4}  {why}")

    no_texture = [r for r in rows if not r.get("texture")]
    if no_texture:
        print(f"\n{len(no_texture)} carried no texture:")
        for r in no_texture[:8]:
            print(f"   {r['resref']}")

    warned = Counter(w for r in rows for w in r.get("warnings", []))
    if warned:
        print("\nwarnings seen:")
        for what, n in warned.most_common(6):
            print(f"   {n:>4}  {what}")

    tris = [r["triangles"] for r in rows if r.get("triangles")]
    if tris:
        tris.sort()
        print(f"\ntriangles: min {tris[0]}, median {tris[len(tris) // 2]}, "
              f"max {tris[-1]}")


def write_report(rows, path: Path, args) -> None:
    """A markdown summary, so the numbers survive the terminal."""
    good = [r for r in rows if r.get("ok")]
    bad = [r for r in rows if not r.get("ok")]
    reasons = Counter(r.get("why", "?") for r in bad)

    lines = [
        f"# Jade {args.kind}s through the whole path",
        "",
        f"Every {args.kind} converted and built onto `{args.host}:{args.node}`, "
        f"with decimation {'off' if not args.decimate else args.decimate}. "
        "Generated by `tools/jade_sweep.py`; re-run it rather than editing this.",
        "",
        f"**{len(good)} of {len(rows)} built** "
        f"({len(good) / max(len(rows), 1):.0%}).",
        "",
    ]
    if reasons:
        lines += ["| why the rest did not | how many |", "|---|---|"]
        lines += [f"| {why} | {n} |" for why, n in reasons.most_common()]
        lines.append("")
    if bad:
        lines += ["## The ones that did not build", ""]
        for r in sorted(bad, key=lambda r: (r.get("why", ""), r["resref"])):
            lines.append(f"- `{r['resref']}` — {r.get('why', '?')} "
                         f"({r.get('triangles', 0)} triangles)")
        lines.append("")

    no_texture = [r for r in rows if not r.get("texture")]
    lines += [
        "## Textures", "",
        f"{len(rows) - len(no_texture)} of {len(rows)} carried one.",
        "",
    ]
    if no_texture:
        lines += [f"- `{r['resref']}`" for r in no_texture[:20]] + [""]

    tris = sorted(r["triangles"] for r in rows if r.get("triangles"))
    if tris:
        lines += [
            "## Size", "",
            f"Triangles: min {tris[0]}, median {tris[len(tris) // 2]}, "
            f"max {tris[-1]}. Vanilla KOTOR heads run 440-796 and the check "
            f"allows 1500, so most of these are left undecimated.",
            "",
        ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {path}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--kind", choices=["head", "body", "mask"], default="head")
    p.add_argument("--limit", type=int)
    p.add_argument("--host", default="p_carthh")
    p.add_argument("--node", default="Head")
    p.add_argument("--decimate", type=int, default=0,
                   help="0 leaves the mesh alone, which is right for Jade")
    p.add_argument("--out", default="reports/jade_sweep.json")
    args = p.parse_args()

    try:
        rows = run(args.kind, args.limit, args.host, args.node,
                   args.decimate or None)
    except SystemExit:
        raise
    except Exception:                                   # noqa: BLE001
        traceback.print_exc()
        return 1

    summarise(rows)
    write_report(rows, ROOT / "reports" / "JADE_SWEEP.md", args)
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
