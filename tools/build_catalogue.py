"""Build the character-model catalogue and the interchangeability report.

    python tools/build_catalogue.py --install "<K1 root>"
    python tools/build_catalogue.py --install "<K1 root>" --family S_Female02
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pykotor.extract.installation import Installation  # noqa: E402
from pykotor.resource.type import ResourceType  # noqa: E402

from kmdlfun import catalogue as kc  # noqa: E402
from kmdlswap import layout as kl  # noqa: E402
from kmdlswap import validate as kv  # noqa: E402

CHARACTER_PREFIXES = ("p_", "n_", "c_")


def collect(install: str, progress=True) -> list[kc.ModelEntry]:
    inst = Installation(install)
    index: dict[str, dict] = {}
    for r in inst.chitin_resources():
        if r.restype() in (ResourceType.MDL, ResourceType.MDX):
            index.setdefault(r.resname().lower(), {})[r.restype()] = r
    names = sorted(
        k
        for k, v in index.items()
        if len(v) == 2 and k.startswith(CHARACTER_PREFIXES)
    )

    entries = []
    for i, name in enumerate(names):
        e = index[name]
        try:
            layout = kl.parse(e[ResourceType.MDL].data(), e[ResourceType.MDX].data())
            if not kv.check(layout).ok:
                continue
            entries.append(kc.describe(layout, name))
        except Exception as exc:  # noqa: BLE001
            print(f"  skipped {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
        if progress and (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(names)} ...", file=sys.stderr)
    return entries


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", required=True)
    ap.add_argument("--family", help="print the parts bin for one supermodel")
    ap.add_argument("--out", default="reports/catalogue.json")
    args = ap.parse_args(argv)

    entries = collect(args.install)
    families = kc.group_by_supermodel(entries)

    payload = {
        "models": [asdict(e) for e in entries],
        "families": {
            name: {
                "models": [m.name for m in fam.models],
                "shared_nodes": fam.swappable_nodes(),
            }
            for name, fam in families.items()
        },
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=2))

    print(f"catalogued {len(entries)} character models into {args.out}\n")
    print(f"{'supermodel':<18}{'models':>7}{'shared nodes':>14}   biggest members")
    ranked = sorted(families.items(), key=lambda kv: -len(kv[1].models))
    for name, fam in ranked[:12]:
        shared = fam.swappable_nodes()
        members = sorted(fam.models, key=lambda m: -m.triangles)[:3]
        who = ", ".join(f"{m.name}({m.triangles}t)" for m in members)
        print(f"{name:<18}{len(fam.models):>7}{len(shared):>14}   {who}")

    if args.family:
        fam = families.get(args.family)
        if not fam:
            print(f"\nno such supermodel: {args.family}", file=sys.stderr)
            return 1
        shared = fam.swappable_nodes()
        print(f"\n=== parts bin for {args.family}: {len(fam.models)} models")
        print(f"{'node':<18}{'models':>7}   example donors")
        for node, models in sorted(shared.items(), key=lambda kv: -len(kv[1]))[:30]:
            print(f"{node:<18}{len(models):>7}   {', '.join(models[:4])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
