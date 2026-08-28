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
    p_inspect.add_argument("model", help="path to <model>.mdl")

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
    return _not_yet(args.cmd)


if __name__ == "__main__":
    raise SystemExit(main())
