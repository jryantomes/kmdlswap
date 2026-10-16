"""KOTOR I's original PC font under KMRP 1.5.1, sharp and wrapping right (user, 2026-10-16).

KMRP 1.5.1 draws a font it finds in Override instead of its own, enlarged to its own font's size
(its log: "Override's font fnt_d16x16b drawn 1.42 times its size, as KMRP's own is here"). Two
problems with the game's own sheets as they are:
  * soft: the 256/512 px sheets are blown up 1.4-2x on screen;
  * lines run off the screen: KMRP enlarges the letters when it draws them, but the game breaks
    lines at the font's own (smaller) size - at 1600x1200 the end of a long dialogue line was cut.

So each sheet is made SCALE times larger - coverage (alpha) enlarged smoothly, edges pulled back
to sharp with a curve around half coverage, the original letter shapes kept - and the TXI's size
fields are multiplied so the font already IS KMRP's size at the player's resolution: the game draws
and wraps at that size and KMRP has nothing left to enlarge. Letter boxes are fractions of the
sheet, so they stay as they are.

KMRP's own sizes depend on the resolution: its 1.5.1 fonts' heights at 1600x1200 (KMRP_HEIGHT, read
from its asset cache 2026-10-16) times RES_FACTOR - 1.19 at 2560x1440 (its log there). At another
resolution, a font sized for this one is enlarged or shrunk by KMRP again (harmless, but the line
breaks drift with it): build with --res-factor from KMRP's log at that resolution
("drawn N times its size" with these files in Override, times the factor they were built with).

Input: the game's own swpc_tex_gui.erf (TexturePacks) - the 18 font TPCs and their embedded TXI.
Output: <name>.tga (bottom-up rows, as KMRP's own; the engine ignores the TGA origin flag) and
<name>.txi, for Override.

usage: build.py <game folder> <out folder> [--scale 4] [--steep 7] [--res-factor 1.19]
"""
import re
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image
from pykotor.resource.formats.erf import read_erf
from pykotor.resource.formats.tpc import read_tpc, write_tpc
from pykotor.resource.type import ResourceType

SCALE = 4
STEEP = 7.0          # the edge curve: 1 = as enlarged (soft), higher = sharper
RES_FACTOR = 1.19    # KMRP's fonts at 2560x1440 against 1600x1200 (its log, 2026-10-16)
# KMRP 1.5.1's own fonts' fontheight at 1600x1200 (its asset cache, 2026-10-16)
KMRP_HEIGHT = {
    "dialogfont10x10": 0.17, "dialogfont10x10a": 0.17, "dialogfont10x10b": 0.27,
    "dialogfont12x16": 0.20, "dialogfont16x16": 0.27, "dialogfont16x16a": 0.17,
    "dialogfont16x16b": 0.27, "dialogfont32x32": 0.53, "fnt_console": 0.27,
    "fnt_credits": 0.32, "fnt_creditsa": 0.23, "fnt_creditsb": 0.32, "fnt_d10x10b": 0.17,
    "fnt_d16x16": 0.17, "fnt_d16x16a": 0.23, "fnt_d16x16b": 0.27, "fnt_dialog16x16": 0.23,
    "fnt_galahad14": 0.28,
}
SIZED = ("fontheight", "baselineheight", "texturewidth", "caretindent", "spacingr", "spacingb")


def fonts(game):
    """{name: TPC bytes} of the 18 fonts, from the game's own GUI texture pack."""
    erf = read_erf((Path(game) / "TexturePacks" / "swpc_tex_gui.erf").read_bytes())
    out = {str(r.resref).lower(): bytes(r.data) for r in erf
           if r.restype == ResourceType.TPC and str(r.resref).lower() in KMRP_HEIGHT}
    missing = sorted(set(KMRP_HEIGHT) - set(out))
    if missing:
        raise SystemExit(f"not in swpc_tex_gui.erf: {', '.join(missing)}")
    return out


def sheet(raw):
    """(the sheet as an upright RGBA image, its embedded TXI bytes)"""
    m = re.search(rb"[\x20-\x7e\r\n\t]{200,}$", raw)
    if not m:
        raise SystemExit("a font TPC without its TXI")
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "f.tga"
        write_tpc(read_tpc(raw), p, ResourceType.TGA)
        im = Image.open(p).convert("RGBA").transpose(Image.FLIP_TOP_BOTTOM)   # pykotor's TGA comes out flipped
        im.load()
    return im, m.group(0)


def sharpen_up(im, scale, steep):
    a = im.getchannel("A").resize((im.width * scale, im.height * scale), Image.LANCZOS)
    x = np.asarray(a, dtype=np.float32) / 255.0
    x = 1.0 / (1.0 + np.exp(-steep * 4.0 * (x - 0.5)))                 # a logistic curve around 0.5
    lo, hi = 1.0 / (1.0 + np.exp(2.0 * steep)), 1.0 / (1.0 + np.exp(-2.0 * steep))
    x = np.clip((x - lo) / (hi - lo), 0.0, 1.0)
    out = Image.new("RGBA", a.size, (255, 255, 255, 0))
    out.putalpha(Image.fromarray((x * 255.0 + 0.5).astype(np.uint8)))
    return out


def txi_value(txi, key):
    m = re.search(rb"(?im)^" + key.encode() + rb"\s+([-0-9.]+)", txi)
    return float(m.group(1)) if m else None


def resized(txi, factor):
    """The TXI with its size fields multiplied by factor (the letter boxes left alone)."""
    def one(m):
        return m.group(1) + (b"%.6f" % (float(m.group(2)) * factor))
    pat = rb"(?im)^(\s*(?:" + b"|".join(k.encode() for k in SIZED) + rb")\s+)([-0-9.]+)"
    return re.sub(pat, one, txi)


def main(argv):
    def opt(name, default, cast):
        return cast(argv[argv.index(name) + 1]) if name in argv else default
    scale, steep, res = opt("--scale", SCALE, int), opt("--steep", STEEP, float), opt("--res-factor", RES_FACTOR, float)
    game, out = Path(argv[0]), Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for name, raw in sorted(fonts(game).items()):
        im, txi = sheet(raw)
        big = sharpen_up(im, scale, steep)
        big.save(out / f"{name}.tga", orientation=-1)
        factor = KMRP_HEIGHT[name] * res / txi_value(txi, "fontheight")
        (out / f"{name}.txi").write_bytes(resized(txi, factor))
        print(f"{name}: {im.size} -> {big.size}, sizes x{factor:.3f}")


if __name__ == "__main__":
    main(sys.argv[1:])
