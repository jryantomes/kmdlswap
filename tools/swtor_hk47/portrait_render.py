"""New party portraits for HK-47, rendered from the built model.

Three textures, matched to the vanilla ones in size and in look:

    po_phk47    64x64    colour icon: head and shoulders, three-quarter view,
                         slate-blue backdrop
    po_phk472   64x64    silhouette of the same framing: black figure on the
                         vanilla image's own blue scanline background
    po_phk473   256x256  party selection: full body, front-on, standing, in red
                         haze, lower legs fading into the fog

Every figure is rendered twice, on black and on white, so its edge coverage is
known exactly and it can be laid over a background with a clean, antialiased
edge. Backgrounds are built from the vanilla images themselves where that is
possible, so the new portraits sit in the same GUI without looking pasted in.

The TGAs are written with their rows stored top down and the header saying so,
the order the engine reads - see tex_out.py.

usage: portrait_render.py <build folder> <out folder>
"""
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, r"C:\Users\jryan\mdl swap\src")
from kmdlfun import render as krender
from kmdlswap import layout as kl
from PIL import Image, ImageFilter

HERE = Path(__file__).parent
GUI = HERE / "gui"
ICON_YAW = float(__import__("os").environ.get("ICON_YAW", "35"))


def write_tga(path, rgb):
    """A GUI texture: rows stored bottom first, as every vanilla portrait TPC is.

    Not the model texture's order. The party screens draw the first row in the
    file at the bottom, and the engine ignores the origin flag, so a portrait
    stored top first shows upside down there - which is what the first silhouette
    did in game.
    """
    h, w = rgb.shape[:2]
    rgba = np.dstack([rgb, np.full((h, w), 255, np.uint8)])
    with open(path, "wb") as fh:
        fh.write(struct.pack("<BBBHHBHHHHBB", 0, 0, 2, 0, 0, 0, 0, 0, w, h, 32, 0x08))
        fh.write(rgba[::-1][:, :, [2, 1, 0, 3]].astype(np.uint8).tobytes())


def to_u8(a):
    return (np.clip(a, 0, 1) * 255).astype(np.uint8)


def from_u8(im):
    return np.asarray(im).astype(float) / 255


def blur(a, radius):
    return from_u8(Image.fromarray(to_u8(a)).filter(ImageFilter.GaussianBlur(radius)))


def render_rgba(scene, *, yaw, pitch, size, bounds):
    """Colour and coverage, from one render on black and one on white."""
    black = krender.render(scene, yaw=yaw, pitch=pitch, size=size, bounds=bounds,
                           background=(0.0, 0.0, 0.0), supersample=3).astype(float) / 255
    white = krender.render(scene, yaw=yaw, pitch=pitch, size=size, bounds=bounds,
                           background=(1.0, 1.0, 1.0), supersample=3).astype(float) / 255
    alpha = np.clip(1.0 - (white - black).mean(axis=2), 0.0, 1.0)
    colour = np.where(alpha[..., None] > 1e-3, black / np.maximum(alpha[..., None], 1e-3), 0.0)
    return np.clip(colour, 0, 1), alpha


def over(background, colour, alpha):
    a = alpha[..., None]
    return background * (1 - a) + colour * a


def upright(name):
    return from_u8(Image.open(GUI / f"{name}_up.png").convert("RGB"))


def red_haze(size):
    """The vanilla party image's red nebula, with the old HK-47 taken out.

    The figure stands in the middle third, so the haze there is unknown. It is
    filled by a weighted blur that only counts the outer thirds - each pixel is
    the blurred colour of the haze around it, divided by how much haze the blur
    actually saw - which gives a smooth field with no seam and no streaks. The
    grain is lifted from the outer thirds as it is and scattered over the middle
    in blocks, so the fill has the same texture as the edges.
    """
    van = upright("po_phk473")
    h, w, _ = van.shape
    lo, hi = int(w * 0.30), int(w * 0.70)
    known = np.ones((h, w))
    known[:, lo:hi] = 0.0
    radius = 24
    summed = blur(van * known[..., None], radius)
    weight = blur(np.repeat(known[..., None], 3, axis=2), radius)
    smooth = summed / np.maximum(weight, 1e-3)
    smooth[:, :lo] = blur(van, 4)[:, :lo] * 0.5 + smooth[:, :lo] * 0.5
    smooth[:, hi:] = blur(van, 4)[:, hi:] * 0.5 + smooth[:, hi:] * 0.5
    smooth = blur(smooth, 6)

    grain_src = van - blur(van, 6)
    rng = np.random.default_rng(47)
    grain = grain_src.copy()
    block = 24
    edge_cols = list(range(0, lo - block)) + list(range(hi, w - block))
    for y in range(0, h, block):
        for x in range(lo, hi, block):
            sx = int(rng.choice(edge_cols))
            sy = int(rng.integers(0, h - block))
            bh, bw = min(block, h - y), min(block, hi - x)
            grain[y:y + bh, x:x + bw] = grain_src[sy:sy + bh, sx:sx + bw]
    haze = np.clip(smooth + blur(grain, 1) * 0.7, 0, 1)
    if (h, w) != (size, size):
        haze = from_u8(Image.fromarray(to_u8(haze)).resize((size, size), Image.LANCZOS))
    return haze


def slate(size):
    """The icon's slate-blue backdrop: a smooth gradient from the vanilla icon's
    clear corner, darker to the lower left."""
    van = upright("po_phk47")
    h, w, _ = van.shape
    top_right = van[: h // 5, -w // 5:].reshape(-1, 3).mean(axis=0)
    lum = van.mean(axis=2)
    dark = van[lum < np.quantile(lum, 0.25)].mean(axis=0)
    bottom_left = 0.55 * top_right + 0.45 * dark
    ys, xs = np.mgrid[0:size, 0:size] / (size - 1)
    t = np.clip((ys + (1 - xs)) / 2, 0, 1)[..., None]
    return top_right * (1 - t) + bottom_left * t


def scanlines(size):
    """The silhouette's background: each row's own colour from the vanilla image,
    where the old silhouette leaves some of that row showing."""
    van = upright("po_phk472")
    h, w, _ = van.shape
    lum = van.mean(axis=2)
    rows = np.zeros((h, 3))
    have = np.zeros(h, bool)
    for y in range(h):
        clear = lum[y] > 0.10
        if clear.sum() >= 3:
            rows[y] = np.median(van[y][clear], axis=0)
            have[y] = True
    last = np.where(have)[0].max()
    for y in range(h):
        if not have[y]:
            src = last - ((last - y) % 2) if y > last else y
            rows[y] = rows[src] if have[src] else rows[last]
    img = np.repeat(rows[:, None, :], w, axis=1)
    figure = np.median(van[lum < 0.03], axis=0) if (lum < 0.03).any() else np.zeros(3)
    if size != h:
        img = from_u8(Image.fromarray(to_u8(img)).resize((size, size), Image.NEAREST))
    return img, figure


def main(folder, out_dir):
    folder, out_dir = Path(folder), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    lay = kl.parse((folder / "p_hk47.mdl").read_bytes(), (folder / "p_hk47.mdx").read_bytes())
    tex = np.asarray(Image.open(folder / "tor_hk47.tga").convert("RGB"))
    scene = krender.from_layout(lay, texture_lookup=lambda n: tex if n.lower() == "tor_hk47" else None)
    z = scene.positions[:, 2]
    top, bottom = float(z.max()), float(z.min())

    # --- party selection, full body ------------------------------------------
    size = 256
    height = top - bottom
    bounds = (np.array([0.0, 0.0, bottom + height * 0.49]), height * 0.52)
    colour, alpha = render_rgba(scene, yaw=0.0, pitch=0.0, size=size, bounds=bounds)
    red_light = np.array([1.0, 0.62, 0.55])
    colour = np.clip(colour * 1.15 * (0.65 + 0.35 * red_light), 0, 1)
    fade = np.clip((np.linspace(0, 1, size) - 0.62) / 0.38, 0, 1)
    alpha = alpha * (1 - 0.75 * fade)[:, None]
    party_u8 = to_u8(over(red_haze(size), colour, alpha))

    # --- icon, head and shoulders ---------------------------------------------
    big = 256
    head_bounds = (np.array([0.0, 0.0, top - 0.22]), 0.25)
    icolour, ialpha = render_rgba(scene, yaw=np.radians(ICON_YAW), pitch=np.radians(-6.0), size=big, bounds=head_bounds)
    icon_big = over(slate(big), icolour, ialpha)
    icon = np.asarray(Image.fromarray(to_u8(icon_big)).resize((64, 64), Image.LANCZOS))

    # --- silhouette of the icon -----------------------------------------------
    mask = from_u8(Image.fromarray(to_u8(ialpha)).resize((64, 64), Image.LANCZOS))
    bg, figure = scanlines(64)
    sil_u8 = to_u8(over(bg, np.broadcast_to(figure, bg.shape), mask))

    write_tga(out_dir / "po_phk473.tga", party_u8)
    write_tga(out_dir / "po_phk47.tga", icon)
    write_tga(out_dir / "po_phk472.tga", sil_u8)

    # --- a sheet to look at: vanilla above, new below, all at 256 ------------
    def at256(a):
        im = Image.fromarray(a if a.dtype == np.uint8 else to_u8(a))
        return np.asarray(im.resize((256, 256), Image.NEAREST if im.size[0] < 256 else Image.LANCZOS))

    vanilla = [at256(upright(n)) for n in ("po_phk47", "po_phk472", "po_phk473")]
    new = [at256(icon), at256(sil_u8), at256(party_u8)]
    gap = np.full((256, 8, 3), 20, np.uint8)

    def row(ims):
        return np.concatenate([ims[0], gap, ims[1], gap, ims[2]], axis=1)

    sheet = np.concatenate([row(vanilla), np.full((8, 256 * 3 + 16, 3), 20, np.uint8), row(new)], axis=0)
    Image.fromarray(sheet).save(out_dir / "portrait_sheet.png")
    print(f"wrote {', '.join(p.name for p in sorted(out_dir.glob('*.tga')))} and portrait_sheet.png")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
