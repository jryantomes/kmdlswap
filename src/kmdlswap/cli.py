"""Thin CLI.

    kmdlswap inspect <model.mdl>
    kmdlswap extract <model.mdl> --node <name> --out mesh.obj
    kmdlswap replace <model.mdl> --node <name> --mesh new.obj --out <dir>

Models may also be named by resref with --install, which reads out of the game's
BIFs. Nothing here ever writes into the game install.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kmdlswap")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_source(p):
        p.add_argument("model", help="path to <model>.mdl, or a resref with --install")
        p.add_argument("--install", help="game install to read the model out of")

    p_inspect = sub.add_parser("inspect", help="dump the node tree for a model")
    add_source(p_inspect)
    p_inspect.add_argument("--animations", action="store_true", help="list animation names")

    p_extract = sub.add_parser("extract", help="extract one mesh node to OBJ")
    add_source(p_extract)
    p_extract.add_argument("--node", required=True)
    p_extract.add_argument("--out", required=True, help="output .obj path")

    p_replace = sub.add_parser("replace", help="replace one mesh node's geometry")
    add_source(p_replace)
    p_replace.add_argument("--node", required=True)
    p_replace.add_argument("--mesh", required=True, help="replacement geometry, .obj")
    p_replace.add_argument("--out", required=True, help="output directory")
    p_replace.add_argument(
        "--max-influences", type=int, default=4,
        help="cap bone influences per vertex (1-4; vanilla never exceeds 4)",
    )
    p_replace.add_argument(
        "--texture", default=None,
        help="point the node at a different texture (resref, max 16 chars); the file "
             "itself must be in Override as .tga or .tpc",
    )
    p_replace.add_argument(
        "--hide", nargs="*", default=None,
        help="stop drawing these mesh nodes; for leftovers the new geometry does "
             "not account for, which cannot be removed without touching the hierarchy",
    )
    p_replace.add_argument(
        "--material", type=int, default=None,
        help="face material value (default: inherit from the node being replaced)",
    )

    args = parser.parse_args(argv)
    try:
        if args.cmd == "inspect":
            return _inspect(args)
        if args.cmd == "extract":
            return _extract(args)
        if args.cmd == "replace":
            return _replace(args)
    except (FileNotFoundError, KeyError, ValueError) as exc:
        print(f"kmdlswap: {exc}", file=sys.stderr)
        return 1
    return 2


def _load(args):
    from .layout import ParseError
    from .loader import load
    from .validate import check

    try:
        layout = load(args.model, args.install)
    except ParseError as exc:
        raise ValueError(f"refusing {args.model}: {exc}") from exc
    return layout, check(layout)


def _warn_unvalidated(rep) -> None:
    print(
        f"\nWARNING: this model does not fully validate "
        f"(gaps={len(rep.gaps)}/{rep.gap_bytes}B, overlaps={len(rep.overlaps)}, "
        f"unresolved pointers={len(rep.dangling)}). It is not safe to edit.",
        file=sys.stderr,
    )


def _inspect(args) -> int:
    from . import inspect as kinspect

    layout, rep = _load(args)
    print(kinspect.report(layout, show_animations=args.animations))
    if not rep.ok:
        _warn_unvalidated(rep)
        return 1
    return 0


def _extract(args) -> int:
    from .edit import extract
    from .obj import write_obj
    from .swap import geometry_to_obj_arrays

    layout, rep = _load(args)
    if not rep.ok:
        _warn_unvalidated(rep)
        return 1

    node = layout.node_by_name(args.node)
    geo = extract(layout, node)
    positions, faces, uvs, normals = geometry_to_obj_arrays(geo)
    write_obj(args.out, positions, faces, uvs, normals, name=node.name)
    print(
        f"wrote {args.out}: {len(positions)} vertices, {len(faces)} triangles"
        f"{'' if uvs else ' (no texcoords)'}{'' if normals else ' (no normals)'}"
    )
    return 0


def _replace(args) -> int:
    from . import layout as kl
    from . import validate as kv
    from .edit import replace_geometry
    from .obj import read_obj
    from .swap import build_replacement

    layout, rep = _load(args)
    if not rep.ok:
        _warn_unvalidated(rep)
        return 1

    node = layout.node_by_name(args.node)
    mesh = read_obj(args.mesh)
    geo, report = build_replacement(
        layout, node, mesh,
        max_influences=args.max_influences,
        material=args.material,
    )
    mdl, mdx = replace_geometry(layout, node, geo, texture=args.texture)

    if args.hide:
        import struct

        RENDER_FLAG_AT = 313
        staged = kl.parse(mdl, mdx)
        buf = bytearray(mdl)
        hidden = []
        for n in staged.nodes:
            if n.is_mesh and n.in_animation is None and n.name in args.hide:
                struct.pack_into("<B", buf, n.trimesh_at + RENDER_FLAG_AT, 0)
                hidden.append(n.name)
        missing = sorted(set(args.hide) - set(hidden))
        if missing:
            print(f"kmdlswap: no mesh node named {', '.join(missing)}", file=sys.stderr)
            return 1
        mdl = bytes(buf)
        print(f"hidden      {', '.join(hidden)}")

    after = kl.parse(mdl, mdx)
    final = kv.check(after)
    if not final.ok:
        print(
            f"kmdlswap: produced model failed validation "
            f"(gaps={len(final.gaps)} overlaps={len(final.overlaps)} "
            f"dangling={len(final.dangling)}); refusing to write it",
            file=sys.stderr,
        )
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = (layout.model_name or Path(args.model).stem).lower()
    (out_dir / f"{stem}.mdl").write_bytes(mdl)
    (out_dir / f"{stem}.mdx").write_bytes(mdx)

    for line in report.lines():
        print(line)
    print(f"MDL         {len(layout.mdl)} -> {len(mdl)} bytes")
    print(f"MDX         {len(layout.mdx)} -> {len(mdx)} bytes")
    print(f"\nwrote {out_dir / stem}.mdl and .mdx")
    print("Copy both into the game's Override directory to test.")
    print("A successful file build is not proof; verify in-game.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
