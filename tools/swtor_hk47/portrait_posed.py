"""HK-47's portraits in his own poses: rifle stance for the icon, idle for the party screen.

The icon is posed from the first frame of `g7r1`, the rifle-ready stance, with a
textured blaster rifle hung from `rhand` the way the engine hangs it. The head
is then turned further toward the camera by an extra yaw about the vertical
through its pivot, applied on top of the animation's own head orientation.

The party image is posed from the first frame of `pause1`, the idle.

usage:
    portrait_posed.py <build> <out> sheet            candidates for several head turns
    portrait_posed.py <build> <out> final <head deg> write the three TGAs
"""
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, r"C:\Users\jryan\mdl swap\src")
sys.path.insert(0, str(Path(__file__).parent))
import portrait_render as P
from grip_render import posed
from pose_render import BASE, header_order
from kmdlfun import library as klib, parts as kparts, render as krender, space as ksp, textures as ktex
from kmdlswap import layout as kl
from PIL import Image

KOTOR = r"E:\SteamLibrary\steamapps\common\swkotor"
WEAPON = "w_blstrrfl_001"
CAMERA_YAW = -35.0
CAMERA_PITCH = -6.0


def rot_z(deg):
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])


def quat_xyzw(m):
    w = np.sqrt(max(0.0, 1 + m[0, 0] + m[1, 1] + m[2, 2])) / 2
    x = np.copysign(np.sqrt(max(0.0, 1 + m[0, 0] - m[1, 1] - m[2, 2])) / 2, m[2, 1] - m[1, 2])
    y = np.copysign(np.sqrt(max(0.0, 1 - m[0, 0] + m[1, 1] - m[2, 2])) / 2, m[0, 2] - m[2, 0])
    z = np.copysign(np.sqrt(max(0.0, 1 - m[0, 0] - m[1, 1] + m[2, 2])) / 2, m[1, 0] - m[0, 1])
    q = np.array([x, y, z, w])
    return q / np.linalg.norm(q)


def turn_head(lay, mdx, extra_deg):
    """The head node's posed orientation, turned about the world vertical."""
    if not extra_deg:
        return lay
    mdl = bytearray(lay.mdl)
    order = header_order(bytes(mdl), lay)
    rest = ksp.rest_pose(lay)
    head = lay.node_by_name("head")
    parent_rot = np.array(rest[head.parent].rotation)
    world = np.array(rest[head.index].rotation)
    local = parent_rot.T @ rot_z(extra_deg) @ world
    x, y, z, w = quat_xyzw(local)
    values = (x, y, z, w) if order == "xyzw" else (w, x, y, z)
    struct.pack_into("<4f", mdl, BASE + head.offset + 28, *values)
    return kl.parse(bytes(mdl), mdx)


def textured_weapon(lib, cache, hook_rot, hook_pos):
    wlay = kl.parse(*lib.read(WEAPON))
    scene = krender.from_layout(wlay, texture_lookup=lambda n: cache.get(n))
    scene.positions = scene.positions @ hook_rot.T + hook_pos
    return scene


def body_scene(lay, tex):
    return krender.from_layout(lay, texture_lookup=lambda n: tex if n.lower() == "tor_hk47" else None)


def icon_images(folder, lib, cache, tex, head_deg):
    mdl = (folder / "p_hk47.mdl").read_bytes()
    mdx = (folder / "p_hk47.mdx").read_bytes()
    lay = turn_head(posed(mdl, mdx, "g7r1", 0.0), mdx, head_deg)
    rest = ksp.rest_pose(lay)
    hook = lay.node_by_name("rhand")
    scene = krender.join([body_scene(lay, tex),
                          textured_weapon(lib, cache, np.array(rest[hook.index].rotation),
                                          np.array(rest[hook.index].position))])
    head = lay.node_by_name("head")
    head_pos = np.array(rest[head.index].position)
    radius = float(__import__("os").environ.get("ICON_RADIUS", "0.36"))
    drop = float(__import__("os").environ.get("ICON_DROP", "0.10"))
    bounds = (head_pos + np.array([0.0, 0.0, -drop]), radius)
    colour, alpha = P.render_rgba(scene, yaw=np.radians(CAMERA_YAW), pitch=np.radians(CAMERA_PITCH),
                                  size=256, bounds=bounds)
    icon_big = P.over(P.slate(256), colour, alpha)
    icon = np.asarray(Image.fromarray(P.to_u8(icon_big)).resize((64, 64), Image.LANCZOS))
    mask = P.from_u8(Image.fromarray(P.to_u8(alpha)).resize((64, 64), Image.LANCZOS))
    bg, figure = P.scanlines(64)
    sil = P.to_u8(P.over(bg, np.broadcast_to(figure, bg.shape), mask))
    return icon, sil


def party_image(folder, tex):
    mdl = (folder / "p_hk47.mdl").read_bytes()
    mdx = (folder / "p_hk47.mdx").read_bytes()
    lay = posed(mdl, mdx, "pause1", 0.0)
    scene = body_scene(lay, tex)
    z = scene.positions[:, 2]
    top, bottom = float(z.max()), float(z.min())
    height = top - bottom
    bounds = (np.array([0.0, 0.0, bottom + height * 0.49]), height * 0.52)
    colour, alpha = P.render_rgba(scene, yaw=0.0, pitch=0.0, size=256, bounds=bounds)
    red_light = np.array([1.0, 0.62, 0.55])
    colour = np.clip(colour * 1.15 * (0.65 + 0.35 * red_light), 0, 1)
    fade = np.clip((np.linspace(0, 1, 256) - 0.62) / 0.38, 0, 1)
    alpha = alpha * (1 - 0.75 * fade)[:, None]
    return P.to_u8(P.over(P.red_haze(256), colour, alpha))


def up256(a):
    im = Image.fromarray(a)
    return np.asarray(im.resize((256, 256), Image.NEAREST if im.size[0] < 256 else Image.LANCZOS))


def main(folder, out, mode, head="0"):
    folder, out = Path(folder), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    lib = klib.ModelLibrary(KOTOR)
    cache = ktex.TextureCache(KOTOR)
    tex = np.asarray(Image.open(folder / "tor_hk47.tga").convert("RGB"))
    gap = np.full((256, 8, 3), 20, np.uint8)

    if mode == "sheet":
        turns = (-40, -20, 0, 20, 40)
        icons = [up256(icon_images(folder, lib, cache, tex, d)[0]) for d in turns]
        row = np.concatenate(sum(([im, gap] for im in icons), [])[:-1], axis=1)
        party = up256(party_image(folder, tex))
        vanilla = up256(P.to_u8(P.upright("po_phk47")))
        bottom = np.concatenate([vanilla, gap, party], axis=1)
        pad = np.full((256, row.shape[1] - bottom.shape[1], 3), 20, np.uint8)
        sheet = np.concatenate([row, np.full((8, row.shape[1], 3), 20, np.uint8),
                                np.concatenate([bottom, pad], axis=1)], axis=0)
        Image.fromarray(sheet).save(out / "posed_sheet.png")
        print(f"icons with extra head turn {turns} deg; below: vanilla icon, idle party image")
    else:
        icon, sil = icon_images(folder, lib, cache, tex, float(head))
        party = party_image(folder, tex)
        P.write_tga(out / "po_phk47.tga", icon)
        P.write_tga(out / "po_phk472.tga", sil)
        P.write_tga(out / "po_phk473.tga", party)
        vanilla = [up256(P.to_u8(P.upright(n))) for n in ("po_phk47", "po_phk472", "po_phk473")]
        new = [up256(icon), up256(sil), party]
        row = lambda ims: np.concatenate([ims[0], gap, ims[1], gap, ims[2]], axis=1)
        sheet = np.concatenate([row(vanilla), np.full((8, 784, 3), 20, np.uint8), row(new)], axis=0)
        Image.fromarray(sheet).save(out / "portrait_sheet.png")
        print(f"wrote the three TGAs with head turn {head} deg, and portrait_sheet.png")


if __name__ == "__main__":
    main(*sys.argv[1:5])
