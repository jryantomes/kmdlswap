"""Draw a weapon in HK-47's right hand the way the engine hangs it.

The engine attaches a weapon model's root to the `rhand` hook, so its geometry
goes through the hook's posed transform. Vanilla above, the build below, both
posed at the same animation frame and framed on the hook.

usage: grip_render.py <build folder> <animation> <weapon model> <output png>
"""
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, r"C:\Users\jryan\mdl swap\src")
sys.path.insert(0, str(Path(__file__).parent))
from pose_render import BASE, ORIENTATION, controllers, header_order
from kmdlfun import library as klib, parts as kparts, render as krender, space as ksp, textures as ktex
from kmdlswap import edit as kedit, layout as kl
from PIL import Image

KOTOR = r"E:\SteamLibrary\steamapps\common\swkotor"
WEAPON_COLOUR = (0.95, 0.85, 0.25)


def posed(mdl, mdx, anim, moment=0.0):
    lay = kl.parse(mdl, mdx)
    order = header_order(mdl, lay)
    geometry = {n.name: n for n in lay.nodes if n.in_animation is None}
    out = bytearray(mdl)
    for n in lay.nodes:
        if n.in_animation != anim or n.name not in geometry:
            continue
        for typ, times, vals, ncol in controllers(mdl, n):
            if typ != ORIENTATION or ncol != 4:
                continue
            j = int(np.argmin(np.abs(times - moment)))
            q = vals[j] / np.linalg.norm(vals[j])
            x, y, z, w = (float(v) for v in q)
            values = (x, y, z, w) if order == "xyzw" else (w, x, y, z)
            struct.pack_into("<4f", out, BASE + geometry[n.name].offset + 28, *values)
    return kl.parse(bytes(out), mdx)


def weapon_scene(lib, weapon, hook_rot, hook_pos):
    lay = kl.parse(*lib.read(weapon))
    rest = ksp.rest_pose(lay)
    points, tris, base = [], [], 0
    for node in kparts.mesh_nodes(lay):
        geo = kedit.extract(lay, node)
        if not geo.positions or not geo.faces:
            continue
        r = rest[node.index]
        p = np.array(geo.positions) @ np.array(r.rotation).T + np.array(r.position)
        p = p @ hook_rot.T + hook_pos
        points.append(p)
        tris.append(np.array([f.vertices for f in geo.faces]) + base)
        base += len(p)
    return krender.from_mesh(np.vstack(points), np.vstack(tris), colour=WEAPON_COLOUR)


def main(folder, anim, weapon, out):
    folder = Path(folder)
    lib = klib.ModelLibrary(KOTOR)
    cache = ktex.TextureCache(KOTOR)
    tor = np.asarray(Image.open(folder / "tor_hk47.tga").convert("RGB"))

    rows = []
    for tag, mdl, mdx, look in (
            ("vanilla", *lib.read("p_hk47"), lambda n: cache.get(n)),
            ("build", (folder / "p_hk47.mdl").read_bytes(), (folder / "p_hk47.mdx").read_bytes(),
             lambda n: tor if n.lower() == "tor_hk47" else None)):
        lay = posed(mdl, mdx, anim)
        rest = ksp.rest_pose(lay)
        hook = lay.node_by_name("rhand")
        hr = np.array(rest[hook.index].rotation)
        hp = np.array(rest[hook.index].position)
        body = krender.from_layout(lay, texture_lookup=look)
        scene = krender.join([body, weapon_scene(lib, weapon, hr, hp)])
        frame = (hp, 0.30)
        rows.append(np.concatenate([krender.render(scene, yaw=y, size=360, bounds=frame)
                                    for y in (0, 60, 120, 180)], axis=1))
        print(f"{tag}: rhand hook at {hp.round(3)}")
    Image.fromarray(np.concatenate(rows, axis=0)).save(out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
