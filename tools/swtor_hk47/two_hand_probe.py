"""Both hands against the rifle, through a whole animation.

The weapon hangs from `rhand`, so the right hand carries it wherever the arm
goes. The left hand is placed only by the animation, which was authored for
vanilla HK-47's arm lengths and pivots. On a two-handed stance it reaches for a
fore-grip at vanilla's distance, and on the new arms that may be somewhere else.

For every key time of the animation this measures, in vanilla and in the build,
how far each hand's centre sits from the rifle's centre line, and where along
that line it sits. It also draws the frame where the build's left hand is
furthest off, vanilla above and the build below.

usage: two_hand_probe.py <build folder> <animation> <weapon> <output png>
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, r"C:\Users\jryan\mdl swap\src")
sys.path.insert(0, str(Path(__file__).parent))
from grip_fit import HANDS, drawn_points, weapon_axis
from grip_render import posed, weapon_scene
from pose_render import ORIENTATION, controllers
from kmdlfun import library as klib, render as krender, space as ksp, textures as ktex
from kmdlswap import layout as kl
from PIL import Image

KOTOR = r"E:\SteamLibrary\steamapps\common\swkotor"


def key_times(mdl, mdx, anim):
    lay = kl.parse(mdl, mdx)
    times = set()
    for n in lay.nodes:
        if n.in_animation != anim:
            continue
        for typ, t, _v, ncol in controllers(mdl, n):
            if typ == ORIENTATION and ncol == 4:
                times.update(round(float(x), 4) for x in t)
    return sorted(times)


def measure(mdl, mdx, anim, moment, axis_hook):
    lay = posed(mdl, mdx, anim, moment)
    rest = ksp.rest_pose(lay)
    hook = lay.node_by_name("rhand")
    origin = np.array(rest[hook.index].position)
    direction = np.array(rest[hook.index].rotation) @ axis_hook
    direction /= np.linalg.norm(direction)
    out = {}
    for side, (hand, fingers) in (("right", HANDS["rhand"]), ("left", HANDS["lhand"])):
        centre = drawn_points(lay, rest, (hand,) + fingers).mean(axis=0)
        along = float((centre - origin) @ direction)
        off = float(np.linalg.norm(centre - (origin + direction * along)))
        out[side] = (off, along)
    return lay, out


def main(folder, anim, weapon, out_png):
    folder = Path(folder)
    lib = klib.ModelLibrary(KOTOR)
    axis_hook = weapon_axis(lib, weapon)
    van = lib.read("p_hk47")
    built = ((folder / "p_hk47.mdl").read_bytes(), (folder / "p_hk47.mdx").read_bytes())

    times = key_times(*van, anim)
    print(f"{anim}: {len(times)} key times")
    print(f"{'t':>6s} | {'vanilla R off':>13s} {'L off':>7s} {'L along':>8s} | {'build R off':>11s} {'L off':>7s} {'L along':>8s}")
    worst_t, worst = None, -1.0
    for t in times:
        _, v = measure(*van, anim, t, axis_hook)
        _, b = measure(*built, anim, t, axis_hook)
        print(f"{t:6.3f} | {v['right'][0]*100:11.1f}cm {v['left'][0]*100:5.1f}cm {v['left'][1]*100:6.1f}cm | "
              f"{b['right'][0]*100:9.1f}cm {b['left'][0]*100:5.1f}cm {b['left'][1]*100:6.1f}cm")
        gap = abs(b["left"][0] - v["left"][0]) + abs(b["left"][1] - v["left"][1])
        if gap > worst:
            worst, worst_t = gap, t

    cache = ktex.TextureCache(KOTOR)
    tor = np.asarray(Image.open(folder / "tor_hk47.tga").convert("RGB"))
    rows = []
    for (mdl, mdx), look in ((van, lambda n: cache.get(n)),
                             (built, lambda n: tor if n.lower() == "tor_hk47" else None)):
        lay = posed(mdl, mdx, anim, worst_t)
        rest = ksp.rest_pose(lay)
        hook = lay.node_by_name("rhand")
        hr = np.array(rest[hook.index].rotation)
        hp = np.array(rest[hook.index].position)
        scene = krender.join([krender.from_layout(lay, texture_lookup=look),
                              weapon_scene(lib, weapon, hr, hp)])
        frame = (hp + hr @ axis_hook * 0.15, 0.45)
        rows.append(np.concatenate([krender.render(scene, yaw=y, size=360, bounds=frame)
                                    for y in (0, 45, 90, 135)], axis=1))
    Image.fromarray(np.concatenate(rows, axis=0)).save(out_png)
    print(f"drew t={worst_t:.3f}, where the build's left hand differs most from vanilla's")


if __name__ == "__main__":
    main(*sys.argv[1:5])
