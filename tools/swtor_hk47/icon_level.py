"""Lower the icon crop until the top of HK-47's head sits on the same row as vanilla's.

Measured on the silhouettes, where the figure is unambiguous: the first row, in
the columns the head occupies, that the dark figure reaches. The renderer is
orthographic, so moving the frame centre moves the figure by a fixed number of
pixels per metre; one render with the head clear of the edge gives the row, and
the offset that lands it on vanilla's row follows directly. A final render
checks it.

usage: icon_level.py <build> <out>
"""
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
os.environ["ICON_RADIUS"] = "0.25"
import portrait_posed as PP
import portrait_render as P
from kmdlfun import library as klib, textures as ktex
from PIL import Image

HEAD_COLUMNS = slice(26, 45)
RADIUS = 0.25
PX_PER_M = 64 * 0.46 / RADIUS      # the renderer fills 92% of the frame with 2 * radius


def top_row(sil_rgb):
    lum = np.asarray(sil_rgb).astype(float).mean(axis=2) / 255
    dark = (lum[:, HEAD_COLUMNS] < 0.06).any(axis=1)
    return int(np.argmax(dark)) if dark.any() else None


def main(build, out):
    build, out = Path(build), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    lib = klib.ModelLibrary(PP.KOTOR)
    cache = ktex.TextureCache(PP.KOTOR)
    tex = np.asarray(Image.open(build / "tor_hk47.tga").convert("RGB"))

    vanilla = top_row(P.to_u8(P.upright("po_phk472")))

    def render(drop):
        os.environ["ICON_DROP"] = f"{drop:.4f}"
        return PP.icon_images(build, lib, cache, tex, float(os.environ.get("HEAD_TURN", "35")))

    probe_drop = -0.03
    _, sil = render(probe_drop)
    probe = top_row(sil)
    drop = probe_drop - (vanilla - probe) / PX_PER_M
    icon, sil = render(drop)
    got = top_row(sil)
    print(f"vanilla head top at row {vanilla}; probe drop {probe_drop} put it at row {probe}; "
          f"drop {drop:.4f} puts it at row {got}")

    P.write_tga(out / "po_phk47.tga", icon)
    P.write_tga(out / "po_phk472.tga", sil)
    up = lambda a: np.asarray(Image.fromarray(a).resize((256, 256), Image.NEAREST))
    gap = np.full((256, 8, 3), 20, np.uint8)
    top = np.concatenate([up(P.to_u8(P.upright("po_phk47"))), gap, up(P.to_u8(P.upright("po_phk472")))], axis=1)
    bottom = np.concatenate([up(icon), gap, up(sil)], axis=1)
    line = int(vanilla * 4)
    for img in (top, bottom):
        img[line, :, :] = (0, 255, 120)
    Image.fromarray(np.concatenate([top, np.full((8, top.shape[1], 3), 20, np.uint8), bottom], axis=0)).save(out / "level_sheet.png")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
