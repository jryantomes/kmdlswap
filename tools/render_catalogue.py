"""Render a preview image for every character model in an install.

This used to export each model to OBJ and hand the batch to Blender. That was
right when there was no renderer here; there is one now, it is the one the app
draws with, and it has the corrected camera. Every image the old tool produced
showed the **back** of the character's head, because the whole project had the
facing wrong until `reports/FACING_FINDINGS.md` - so those images have to be
thrown away regardless, and regenerating them through Blender would mean
trusting a second camera convention that no test covers.

Using our own renderer means the catalogue is drawn by the same code the
Preview tab uses, with the same tests behind it, and needs nothing installed.

    python tools/render_catalogue.py --install "<K1 root>"
    python tools/render_catalogue.py --install "<K1 root>" --limit 8
    python tools/render_catalogue.py --install "<K2 root>" --out catalogue_k2
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kmdlfun import render as krender  # noqa: E402
from kmdlfun import textures as ktextures  # noqa: E402
from kmdlfun.library import ModelLibrary, character_models  # noqa: E402
from kmdlswap import layout as kl  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--install", required=True)
    ap.add_argument("--out", default="catalogue")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--untextured", action="store_true",
                    help="draw flat shaded, which is faster and shows shape")
    ap.add_argument("--yaw", type=float, default=0.0,
                    help="degrees to turn from front-on")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    lib = ModelLibrary(args.install)
    names = character_models(args.install, lib)
    if args.limit:
        names = names[: args.limit]

    lookup = None
    if not args.untextured:
        lookup = ktextures.lookup_across([Path(args.install)])

    index = []
    started = time.time()
    for i, name in enumerate(names, 1):
        print(f"[{i}/{len(names)}] {name}", flush=True)
        try:
            layout = kl.parse(*lib.read(name))
            scene = krender.from_layout(layout, texture_lookup=lookup)
            if not len(scene.faces):
                index.append({"name": name, "skipped": "nothing visible to draw"})
                continue
            # Backface culling, because a two-sided draw hides exactly the
            # fault this catalogue is most useful for spotting.
            pixels = krender.render(
                scene, yaw=args.yaw * 3.14159265 / 180.0,
                size=args.size, cull=True,
            )
            krender.to_png(pixels, out / f"{name}.png")
            index.append({
                "name": name,
                "image": f"{name}.png",
                "textured": bool(scene.textured),
                "faces": int(len(scene.faces)),
            })
        except Exception as exc:  # noqa: BLE001
            print(f"    failed: {type(exc).__name__}: {exc}")
            index.append({"name": name, "skipped": f"{type(exc).__name__}: {exc}"})

    (out / "index.json").write_text(
        json.dumps({"install": str(args.install), "models": index}, indent=1),
        encoding="utf-8",
    )
    drawn = sum(1 for e in index if "image" in e)
    print(f"\n{drawn} of {len(names)} rendered into {out} "
          f"in {time.time() - started:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
