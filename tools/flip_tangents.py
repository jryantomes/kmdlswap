"""Negate the tangent slot of a built model, to test it against itself.

The tangent basis was reverse-engineered and its *sign* measured against
vanilla rather than derived. `compute` now agrees positively with BioWare's own
tangents - better than +0.8 across every mesh that carries them - so the
convention is anchored. What that cannot show is whether the engine renders a
basis computed for *new* geometry correctly, and a flipped tangent looks
identical in every viewer.

So: build once, flip the sign, and install each in turn. Judging one head on
its own asks "does this look right", which is a matter of opinion about a face
you have never seen lit. Judging two identical heads that differ in exactly one
sign asks "which of these is wrong", which is a matter of observation.

    python tools/flip_tangents.py <folder with the built .mdl/.mdx> --out <dir>

If they look the same, tangents are not doing much on that model and the test
says nothing. If one looks inverted - highlights opposite the light, detail
reading inside-out - then the sign matters and the other one is right.
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# Nine floats: (bitangent, tangent, normal). The middle three are the ones the
# sign convention is about.
TANGENT_FLOATS = slice(3, 6)


def flip(mdl_path: Path, mdx_path: Path, out_dir: Path, mode: str = "flip") -> dict:
    """Write a copy with the tangent column disturbed.

    `flip` negates it, which is the question the sign convention asks.

    `wreck` replaces every tangent with the same fixed direction, which asks a
    blunter question: does the engine read this column *at all*? A negated
    tangent is a symmetric change and can be genuinely hard to see; a constant
    one destroys the basis everywhere, and if the lighting still does not move
    then the column is not being used and the sign cannot matter.

    That escalation is the point. A null result from `flip` on its own means
    either "the sign does not matter" or "the column is ignored", and those are
    very different answers.
    """
    from kmdlfun import parts as kparts
    from kmdlswap import layout as kl
    from kmdlswap import mdx as kmdx

    mdl = mdl_path.read_bytes()
    mdx = bytearray(mdx_path.read_bytes())
    layout = kl.parse(mdl, bytes(mdx))

    touched = {}
    for node in kparts.mesh_nodes(layout):
        stride = kmdx.stride_layout(layout, node)
        offset = stride.columns.get("tangent")
        if offset is None:
            continue
        # The column's stride offset, from the node's own block. The 288 in
        # `mdx.py` is where the *header* keeps this number, not the data.
        base = node.mdx_data_offset + offset
        for i in range(node.vertex_count):
            at = base + i * node.mdx_stride
            values = list(struct.unpack_from("<9f", mdx, at))
            if mode == "wreck":
                values[3:6] = [1.0, 0.0, 0.0]
            else:
                for j in range(*TANGENT_FLOATS.indices(9)):
                    values[j] = -values[j]
            struct.pack_into("<9f", mdx, at, *values)
        touched[node.name] = node.vertex_count

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / mdl_path.name).write_bytes(mdl)
    (out_dir / mdx_path.name).write_bytes(bytes(mdx))
    return touched


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("folder", help="a build folder holding one .mdl and .mdx")
    p.add_argument("--out", required=True)
    p.add_argument("--mode", choices=["flip", "wreck"], default="flip",
                   help="flip negates the tangents; wreck replaces them all "
                        "with one fixed direction, to ask whether the engine "
                        "reads the column at all")
    args = p.parse_args()

    folder = Path(args.folder)
    mdls = sorted(folder.glob("*.mdl"))
    if len(mdls) != 1:
        print(f"expected one .mdl in {folder}, found {len(mdls)}",
              file=sys.stderr)
        return 1
    mdl = mdls[0]
    mdx = mdl.with_suffix(".mdx")
    if not mdx.is_file():
        print(f"no {mdx.name} beside it", file=sys.stderr)
        return 1

    touched = flip(mdl, mdx, Path(args.out), args.mode)
    if not touched:
        print("no mesh in this model carries a tangent column - "
              "there is nothing for this test to measure", file=sys.stderr)
        return 1
    for name, count in touched.items():
        print(f"  {args.mode}ed {count} tangents on {name!r}")
    print(f"\nwrote {args.out}")
    print("Install this and the original in turn. They differ in exactly one "
          "sign, so any visible difference is the tangent basis.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
