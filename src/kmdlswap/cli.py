"""Thin CLI entry point. Subcommands are stubbed until their milestones land."""

from __future__ import annotations

import argparse
import sys


def _not_yet(name: str) -> int:
    print(f"kmdlswap: '{name}' is not implemented yet", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kmdlswap")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_inspect = sub.add_parser("inspect", help="dump the node tree for a model")
    p_inspect.add_argument("model", help="path to <model>.mdl, or a resname with --install")
    p_inspect.add_argument("--install", help="game install to read the model out of")
    p_inspect.add_argument("--animations", action="store_true", help="list animation names")

    p_extract = sub.add_parser("extract", help="extract one mesh node to OBJ")
    p_extract.add_argument("model")
    p_extract.add_argument("--node", required=True)
    p_extract.add_argument("--out", required=True)

    p_replace = sub.add_parser("replace", help="replace one mesh node's geometry")
    p_replace.add_argument("model")
    p_replace.add_argument("--node", required=True)
    p_replace.add_argument("--mesh", required=True)
    p_replace.add_argument("--out", required=True)

    args = parser.parse_args(argv)
    if args.cmd == "inspect":
        return _inspect(args)
    return _not_yet(args.cmd)


def _inspect(args) -> int:
    from . import inspect as kinspect
    from .layout import ParseError
    from .loader import load
    from .validate import check

    try:
        layout = load(args.model, args.install)
    except (FileNotFoundError, KeyError) as exc:
        print(f"kmdlswap: {exc}", file=sys.stderr)
        return 1
    except ParseError as exc:
        print(f"kmdlswap: refusing {args.model}: {exc}", file=sys.stderr)
        return 1

    rep = check(layout)
    print(kinspect.report(layout, show_animations=args.animations))
    if not rep.ok:
        # Report, do not hide: a model we cannot fully account for is one we
        # must not edit later.
        print(
            f"\nWARNING: this model does not fully validate "
            f"(gaps={len(rep.gaps)}/{rep.gap_bytes}B, overlaps={len(rep.overlaps)}, "
            f"unresolved pointers={len(rep.dangling)}). It is not safe to edit.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
