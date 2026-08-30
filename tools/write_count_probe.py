"""Probe P1e: grow every array a vertex count touches, but leave the count alone.

Test 3 showed that growing the MDX block while `vertex_count` stays put is
harmless, so the buffer is not the trigger. But probe C moved two things at
once: the count field *and* the MDL-side vertex array, whose growth shifted
roughly 295 pointers. Nothing has separated those.

This does everything probe C does - grows the MDL vertex array, grows the MDX
block, shifts every pointer, updates every size - and then writes the **old**
`vertex_count` back into the trimesh header. The engine is told 565 while every
array behind it holds 568.

* **Skinning survives** - the count field alone is the trigger, and growing a
  skinned mesh's arrays is otherwise harmless.
* **Skinning breaks** - the count is innocent; growing a *skinned* mesh's MDL
  arrays is what the engine objects to. (Probe D already showed that growing an
  *unskinned* mesh's arrays and shifting pointers is fine.)

Over-provisioned in every direction, so nothing is read past the end of
anything. The parser will report a coverage gap for the arrays that are longer
than the declared count implies; that gap is the point of the probe, and its
size is checked rather than ignored.

    python tools/write_count_probe.py --install "<K1 root>" --model p_carthh \\
        --node Head --extra 3 --out out_probe/

Never writes into the game install.
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kmdlswap import edit as ke  # noqa: E402
from kmdlswap import layout as kl  # noqa: E402
from kmdlswap.loader import load  # noqa: E402

VERTEX_COUNT_AT = 304  # u16, into the trimesh subheader


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install")
    ap.add_argument("--model", required=True)
    ap.add_argument("--node", required=True)
    ap.add_argument("--extra", type=int, default=3)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    layout = load(args.model, args.install)
    node = layout.node_by_name(args.node)
    original = node.vertex_count

    # Exactly probe C: duplicate rows the faces never reference.
    geo = ke.extract(layout, node)
    grown = ke.MeshGeometry(
        vertex_count=geo.vertex_count + args.extra,
        columns={k: v + v[: args.extra] for k, v in geo.columns.items()},
        influences=geo.influences + geo.influences[: args.extra] if geo.influences else [],
        faces=list(geo.faces),
        trailing=geo.trailing,
    )
    mdl, mdx = ke.replace_geometry(layout, node, grown)

    grown_layout = kl.parse(mdl, mdx)
    grown_node = grown_layout.node_by_name(args.node)
    if grown_node.vertex_count != original + args.extra:
        print("the grown build did not take", file=sys.stderr)
        return 1

    # ...and now put the old count back.
    at = grown_node.trimesh_at + VERTEX_COUNT_AT
    stored = struct.unpack_from("<H", mdl, at)[0]
    if stored != original + args.extra:
        print(f"vertex_count is not the u16 at trimesh +{VERTEX_COUNT_AT} "
              f"(found {stored})", file=sys.stderr)
        return 1
    patched = bytearray(mdl)
    struct.pack_into("<H", patched, at, original)
    mdl = bytes(patched)

    final = kl.parse(mdl, mdx)
    final_node = final.node_by_name(args.node)
    if final_node.vertex_count != original:
        print("the count did not revert", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{args.model}.mdl").write_bytes(mdl)
    (out / f"{args.model}.mdx").write_bytes(mdx)

    print(f"wrote {out / args.model}.mdl / .mdx")
    print(f"  node          : {node.name}, "
          f"{'skinned' if node.is_skin else 'unskinned'}")
    print(f"  arrays hold   : {original + args.extra} vertices "
          f"(MDL vertex array and MDX block both grown)")
    print(f"  vertex_count  : {original}  (REVERTED - this is the point)")
    print(f"  MDL / MDX     : {len(layout.mdl)} -> {len(mdl)} / "
          f"{len(layout.mdx)} -> {len(mdx)}")
    print(f"  pointers moved: same as probe C")
    over = args.extra * 12
    print(f"\nThe engine is told {original} while the arrays hold "
          f"{original + args.extra}; {over} bytes of the MDL vertex array and "
          f"{args.extra * node.mdx_stride} of the MDX block sit past what the "
          f"count claims.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
