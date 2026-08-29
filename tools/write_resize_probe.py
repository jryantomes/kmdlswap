"""Write a model whose bytes changed but whose appearance must not.

The no-op swap comes out byte-identical, which makes loading it in-game a test
of the Override mechanism rather than of this tool. This produces the test that
actually carries information: a model where a mesh's vertex array has been grown
with inert duplicate vertices that no face references.

Nothing visible changes - same faces, same positions, same bounding box - but
the MDL and MDX both grow, every array after the edit moves, and every stored
pointer past the splice had to be rewritten. If the model renders and animates
correctly in-game, the splice and offset-fixup logic is sound in the engine, not
just against the validators.

    python tools/write_resize_probe.py --install "<K1 root>" --model p_hk47 \
        --node head --out out/

Never writes into the game install.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kmdlswap import edit as ke  # noqa: E402
from kmdlswap import layout as kl  # noqa: E402
from kmdlswap import validate as kv  # noqa: E402
from kmdlswap.loader import load  # noqa: E402


def pad_mesh(geo: ke.MeshGeometry, extra: int) -> ke.MeshGeometry:
    """Append ``extra`` duplicate vertices that no face references."""
    if extra > geo.vertex_count:
        extra = geo.vertex_count
    return ke.MeshGeometry(
        vertex_count=geo.vertex_count + extra,
        columns={name: values + values[:extra] for name, values in geo.columns.items()},
        influences=geo.influences + geo.influences[:extra] if geo.influences else [],
        faces=list(geo.faces),  # unchanged - the copies stay unreferenced
        trailing=geo.trailing,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install")
    ap.add_argument("--model", required=True)
    ap.add_argument("--node", required=True, help="mesh node to pad")
    ap.add_argument("--extra", type=int, default=64, help="duplicate vertices to append")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    layout = load(args.model, args.install)
    if not kv.check(layout).ok:
        print(f"refusing {args.model}: does not fully validate", file=sys.stderr)
        return 1

    node = layout.node_by_name(args.node)
    geo = ke.extract(layout, node)
    padded = pad_mesh(geo, args.extra)
    mdl, mdx = ke.replace_geometry(layout, node, padded)

    after = kl.parse(mdl, mdx)
    rep = kv.check(after)
    if not rep.ok:
        print(
            f"produced model does not validate: gaps={len(rep.gaps)} "
            f"overlaps={len(rep.overlaps)} dangling={len(rep.dangling)}",
            file=sys.stderr,
        )
        return 1

    # Everything except the padded node must be untouched.
    for old in layout.nodes:
        if not old.is_mesh or old.index == node.index or not old.vertex_count:
            continue
        if "saber" in old.flags or old.in_animation is not None:
            continue
        new = next(n for n in after.nodes if n.index == old.index)
        if ke.extract(after, new).columns != ke.extract(layout, old).columns:
            print(f"regression: {old.name} geometry changed", file=sys.stderr)
            return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = layout.model_name.lower()
    (out_dir / f"{stem}.mdl").write_bytes(mdl)
    (out_dir / f"{stem}.mdx").write_bytes(mdx)

    shifted = sum(
        1
        for o in layout.offsets
        if o.space == "MDL" and o.absolute > min(s.start for s in layout.spans_of(node.index))
    )
    print(f"wrote {out_dir / stem}.mdl / .mdx")
    print(f"  node padded        : {node.name}  {geo.vertex_count} -> {padded.vertex_count} vertices")
    print(f"  faces              : {len(padded.faces)} (unchanged - copies are unreferenced)")
    print(f"  MDL size           : {len(layout.mdl)} -> {len(mdl)}  ({len(mdl) - len(layout.mdl):+d})")
    print(f"  MDX size           : {len(layout.mdx)} -> {len(mdx)}  ({len(mdx) - len(layout.mdx):+d})")
    print(f"  pointers past edit : ~{shifted} required rewriting")
    print(f"  validates          : yes")
    print("\nExpected in-game: visually and behaviourally IDENTICAL to vanilla.")
    print("Any difference - missing mesh, scrambled geometry, broken animation,")
    print("crash on load - means the splice or offset fixup is wrong.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
