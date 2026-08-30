"""CLI for kmdlfun. The GUI drives exactly this logic.

    kmdlfun effects
    kmdlfun companions
    kmdlfun preview --install <K1> --companion hk47 --effect bighead
    kmdlfun build --install <K1> --effect bighead --companion all --out out/
"""

from __future__ import annotations

import argparse
import sys

from . import apply as kapply
from . import effects as keffects
from . import roster


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="kmdlfun")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("effects", help="list available effects")
    sub.add_parser("companions", help="list companions and their models")

    prev = sub.add_parser("preview", help="show what would change, without writing")
    prev.add_argument("--install", required=True)
    prev.add_argument("--companion", nargs="*", default=["all"])
    prev.add_argument("--effect", required=True)
    prev.add_argument("--intensity", type=float, default=1.0)

    b = sub.add_parser("build", help="write modified models to a directory")
    b.add_argument("--install", required=True)
    b.add_argument("--companion", nargs="*", default=["all"])
    b.add_argument("--effect", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--intensity", type=float, default=1.0)
    b.add_argument(
        "--pivot", choices=list(kapply.PIVOTS), default="joint",
        help="where each node grows from: joint (default, keeps a multi-node "
             "part registered), node (its own origin), bounds (its own bbox centre)",
    )

    tp = sub.add_parser("transplant", help="move one model's geometry into another")
    tp.add_argument("--install", required=True)
    tp.add_argument("--host", required=True, help="model that keeps its hierarchy and animations")
    tp.add_argument("--donor", required=True, help="model to take geometry from")
    tp.add_argument("--node", nargs="*", help="host node(s); default every matching node")
    tp.add_argument("--out", required=True)
    tp.add_argument("--fit", action="store_true", help="scale the donor part to the host part's size")
    tp.add_argument("--max-influences", type=int, default=4)
    tp.add_argument("--reshape", action="store_true",
                    help="keep the host's vertices and move them onto the donor's surface; "
                         "required for heads, whose facial animation breaks if the vertex "
                         "count changes")
    tp.add_argument("--dry-run", action="store_true", help="report matches and fit, write nothing")

    sub.add_parser("gui", help="launch the desktop app")

    args = p.parse_args(argv)
    try:
        if args.cmd == "effects":
            return _effects()
        if args.cmd == "companions":
            return _companions()
        if args.cmd == "preview":
            return _preview(args)
        if args.cmd == "build":
            return _build(args)
        if args.cmd == "transplant":
            return _transplant(args)
        if args.cmd == "gui":
            from .gui import run

            return run()
    except KeyError as exc:
        print(f"kmdlfun: {exc}", file=sys.stderr)
        return 1
    return 2


def _effects() -> int:
    for e in keffects.EFFECTS:
        scales = ", ".join(f"{k} x{v:g}" for k, v in e.scales.items())
        print(f"{e.key:<12} {e.label}")
        print(f"             {e.description}")
        print(f"             scales: {scales}")
        if e.caution:
            print(f"             CAUTION: {e.caution}")
    return 0


def _companions() -> int:
    for c in roster.COMPANIONS:
        note = f"   ({c.note})" if c.note else ""
        print(f"{c.key:<11} {c.name:<18} {', '.join(c.models)}{note}")
    return 0


def _preview(args) -> int:
    from kmdlswap import layout as kl

    from .library import ModelLibrary

    effect = keffects.resolve(args.effect)
    scales = effect.scaled(args.intensity)
    lib = ModelLibrary(args.install)

    print(f"effect: {effect.label}  ({', '.join(f'{k} x{v:.2f}' for k, v in scales.items())})")
    if effect.caution:
        print(f"CAUTION: {effect.caution}")
    for c in roster.resolve(args.companion):
        print(f"\n{c.name}")
        for model in c.models:
            if not lib.has(model):
                print(f"  {model:<16} not in this install")
                continue
            layout = kl.parse(*lib.read(model))
            hits = []
            for part_key in scales:
                for index in kapply.targets(layout, part_key):
                    hits.append((layout.nodes[index].name, part_key))
            kind = "head model" if kapply.is_head_model(layout) else "body model"
            if not hits:
                print(f"  {model:<16} {kind}: nothing matches")
                continue
            names = ", ".join(n for n, _ in hits[:8])
            more = f" (+{len(hits) - 8} more)" if len(hits) > 8 else ""
            print(f"  {model:<16} {kind}: {len(hits)} nodes -> {names}{more}")
    return 0


def _build(args) -> int:
    from .library import build

    def progress(i, total, label):
        if i < total:
            print(f"  [{i + 1}/{total}] {label}", file=sys.stderr)

    report = build(
        args.install, args.effect, args.companion, args.out,
        intensity=args.intensity, pivot=args.pivot, progress=progress,
    )
    effect = keffects.resolve(args.effect)
    print(f"\n{effect.label} @ {args.intensity:g}x -> {args.out}")
    print(f"  models written : {report.written}")
    print(f"  nodes changed  : {report.total_nodes}")
    if report.missing:
        print(f"  not in install : {', '.join(report.missing)}")
    for m in report.failed:
        print(f"  FAILED {m.model}: {m.error}", file=sys.stderr)
    skipped = [(m.model, s) for m in report.models for s in m.skipped]
    for model, s in skipped[:10]:
        print(f"  skipped {model}: {s}", file=sys.stderr)
    print("\nCopy the .mdl/.mdx files into the game's Override directory to use them.")
    print("A successful build is not proof; verify in-game.")
    return 0 if not report.failed else 1


if __name__ == "__main__":
    raise SystemExit(main())


def _transplant(args) -> int:
    from pathlib import Path

    from kmdlswap import layout as kl
    from kmdlswap import validate as kv

    from . import transplant as ktp
    from .library import ModelLibrary

    lib = ModelLibrary(args.install)
    for name in (args.host, args.donor):
        if not lib.has(name):
            print(f"kmdlfun: no model {name!r} in that install", file=sys.stderr)
            return 1

    mdl, mdx = lib.read(args.host)
    donor_layout = kl.parse(*lib.read(args.donor))
    host_layout = kl.parse(mdl, mdx)

    if args.node:
        donors = {n.name.lower(): n.name for n in ktp.kparts.mesh_nodes(donor_layout)}
        pairs = []
        for wanted in args.node:
            match = donors.get(wanted.lower())
            if not match:
                print(f"kmdlfun: {args.donor} has no node matching {wanted!r}", file=sys.stderr)
                return 1
            pairs.append((wanted, match))
    else:
        pairs = ktp.match_nodes(host_layout, donor_layout)

    if not pairs:
        print(
            f"kmdlfun: {args.host} and {args.donor} share no mesh node names, "
            f"so there is nothing to move between them",
            file=sys.stderr,
        )
        return 1

    print(f"{args.host}  <-  {args.donor}   ({len(pairs)} node(s))")
    print()
    results = []
    for host_node, donor_node in pairs:
        mdl2, mdx2, r = ktp.transplant_node(
            mdl, mdx, donor_layout, args.donor, host_node, donor_node,
            fit=args.fit, max_influences=args.max_influences, reshape=args.reshape,
        )
        results.append(r)
        if r.ok and not args.dry_run:
            mdl, mdx = mdl2, mdx2
        line = f"  {host_node:<16} <- {donor_node:<16}"
        if not r.ok:
            print(f"{line} REFUSED: {r.error}")
            continue
        a = r.alignment
        s = r.swap
        print(
            f"{line} {s.old_vertices:>5} -> {s.new_vertices:<5} verts"
            f"   fit {a.worst_ratio:.2f}x   drift {a.drift:.3f}"
        )
        for w in r.warnings:
            print(f"      ! {w}")

    done = [r for r in results if r.ok]
    if args.dry_run:
        print(f"dry run: {len(done)}/{len(pairs)} node(s) would transfer")
        return 0
    if not done:
        print("nothing transferred", file=sys.stderr)
        return 1

    final = kv.check(kl.parse(mdl, mdx))
    if not final.ok:
        print("kmdlfun: result failed validation; refusing to write it", file=sys.stderr)
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{args.host}.mdl").write_bytes(mdl)
    (out_dir / f"{args.host}.mdx").write_bytes(mdx)
    print()
    print(f"{len(done)}/{len(pairs)} node(s) transferred")
    print(f"wrote {out_dir / args.host}.mdl and .mdx")
    print("Copy both into the game's Override directory. Verify in-game.")
    return 0
