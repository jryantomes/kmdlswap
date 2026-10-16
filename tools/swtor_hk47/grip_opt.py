"""Search for the rhand hook adjustment that best seats both hands on the rifle.

The right hand carries the rifle, so the only free parameters are where the
rifle sits in that hand: how far it slides along its own line, and a small tilt
about the grip. The left hand is placed by the animation alone, so the hook is
chosen to bring the rifle to wherever the new left arm actually puts that hand.

Frames: every sampled key of every rifle animation (`g7*`, `b7*`) where
vanilla's left hand is within 12 cm of the rifle line - the two-handed moments.
For each, vanilla gives three numbers: right hand off the line, left hand off
the line, left hand along it. The search minimises the squared difference of the
build's three from vanilla's.

The hook is shared with pistols, so the tilt is capped by the caller: a pistol
held in one hand takes the same tilt.

usage: grip_opt.py <build folder> <weapon> [max tilt deg, default 12] [tag]
writes grip_opt<tag>.json: slide (m), tilt (deg about the hook's two cross
axes), the hook position delta in its hand's frame, and the new local
quaternion (xyzw).
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, r"C:\Users\jryan\mdl swap\src")
sys.path.insert(0, str(Path(__file__).parent))
from grip_fit import HANDS, drawn_points, weapon_axis
from grip_render import posed
from two_hand_probe import key_times
from kmdlfun import library as klib, space as ksp
from kmdlswap import layout as kl

KOTOR = r"E:\SteamLibrary\steamapps\common\swkotor"
HERE = Path(__file__).parent
MAX_FRAMES = 12
TWO_HANDED = 0.12


def rot(axis, deg):
    axis = axis / np.linalg.norm(axis)
    a = np.radians(deg)
    x, y, z = axis
    c, s, C = np.cos(a), np.sin(a), 1 - np.cos(a)
    return np.array([[c + x*x*C, x*y*C - z*s, x*z*C + y*s],
                     [y*x*C + z*s, c + y*y*C, y*z*C - x*s],
                     [z*x*C - y*s, z*y*C + x*s, c + z*z*C]])


def quat_xyzw(m):
    w = np.sqrt(max(0.0, 1 + m[0, 0] + m[1, 1] + m[2, 2])) / 2
    x = np.sqrt(max(0.0, 1 + m[0, 0] - m[1, 1] - m[2, 2])) / 2
    y = np.sqrt(max(0.0, 1 - m[0, 0] + m[1, 1] - m[2, 2])) / 2
    z = np.sqrt(max(0.0, 1 - m[0, 0] - m[1, 1] + m[2, 2])) / 2
    x = np.copysign(x, m[2, 1] - m[1, 2])
    y = np.copysign(y, m[0, 2] - m[2, 0])
    z = np.copysign(z, m[1, 0] - m[0, 1])
    q = np.array([x, y, z, w])
    return q / np.linalg.norm(q)


def frame_data(mdl, mdx, anim, t):
    lay = posed(mdl, mdx, anim, t)
    rest = ksp.rest_pose(lay)
    hook = lay.node_by_name("rhand")
    right = drawn_points(lay, rest, (HANDS["rhand"][0],) + HANDS["rhand"][1]).mean(axis=0)
    left = drawn_points(lay, rest, (HANDS["lhand"][0],) + HANDS["lhand"][1]).mean(axis=0)
    return (np.array(rest[hook.index].position), np.array(rest[hook.index].rotation), right, left)


def numbers(origin, direction, right, left):
    d = direction / np.linalg.norm(direction)

    def off_along(p):
        along = float((p - origin) @ d)
        return float(np.linalg.norm(p - (origin + d * along))), along

    r_off, _ = off_along(right)
    l_off, l_along = off_along(left)
    return np.array([r_off, l_off, l_along])


def main(folder, weapon, max_tilt="12", tag=""):
    max_tilt = float(max_tilt)
    folder = Path(folder)
    lib = klib.ModelLibrary(KOTOR)
    axis = weapon_axis(lib, weapon)
    axis = axis / np.linalg.norm(axis)
    cross1 = np.cross(axis, [0, 0, 1.0] if abs(axis[2]) < 0.9 else [1.0, 0, 0])
    cross1 /= np.linalg.norm(cross1)
    cross2 = np.cross(axis, cross1)

    van = lib.read("p_hk47")
    built = ((folder / "p_hk47.mdl").read_bytes(), (folder / "p_hk47.mdx").read_bytes())
    anims = [a for a in kl.parse(*van).animation_names if a[:2] in ("g7", "b7")]

    frames = []
    for anim in anims:
        times = key_times(*van, anim)
        if not times:
            continue
        pick = [times[i] for i in np.linspace(0, len(times) - 1, min(MAX_FRAMES, len(times))).astype(int)]
        for t in pick:
            vo, vr, vright, vleft = frame_data(*van, anim, t)
            target = numbers(vo, vr @ axis, vright, vleft)
            if target[1] > TWO_HANDED:
                continue
            frames.append((anim, t, target, frame_data(*built, anim, t)))
    used = sorted({f[0] for f in frames})
    print(f"max tilt {max_tilt:g} deg: {len(frames)} two-handed frames across {used}")

    def error(slide, a, b):
        tilt = rot(cross1, a) @ rot(cross2, b)
        total = np.zeros(3)
        for _anim, _t, target, (bo, br, bright, bleft) in frames:
            d = br @ (tilt @ axis)
            origin = bo + d * slide
            total += (numbers(origin, d, bright, bleft) - target) ** 2
        return total / len(frames)

    def span(centre, half, step):
        vals = np.arange(centre - half, centre + half + step / 2, step)
        return np.unique(np.clip(vals, -max_tilt, max_tilt))

    before = error(0.0, 0.0, 0.0)
    coarse = span(0.0, max_tilt, max(max_tilt / 4, 1.0)) if max_tilt > 0 else np.array([0.0])
    best = (np.inf, None)
    for slide in np.arange(-0.10, 0.041, 0.01):
        for a in coarse:
            for b in coarse:
                e = error(slide, a, b)
                if e.sum() < best[0]:
                    best = (e.sum(), (slide, a, b))
    s0, a0, b0 = best[1]
    fine = (lambda c: span(c, 3.0, 0.5)) if max_tilt > 0 else (lambda c: np.array([0.0]))
    for slide in np.arange(s0 - 0.01, s0 + 0.0101, 0.0025):
        for a in fine(a0):
            for b in fine(b0):
                e = error(slide, a, b)
                if e.sum() < best[0]:
                    best = (e.sum(), (slide, a, b))
    slide, a, b = best[1]
    after = error(slide, a, b)
    names = ("right hand off the line", "left hand off the line", "left hand along the line")
    print(f"best: slide {slide*100:+.1f} cm along the rifle, tilt {a:+.1f} and {b:+.1f} deg "
          f"(total {np.hypot(a, b):.1f} deg)")
    for i, name in enumerate(names):
        print(f"   {name:26s} rms error {np.sqrt(before[i])*100:5.1f} cm -> {np.sqrt(after[i])*100:5.1f} cm")

    lay = kl.parse(*built)
    rest = ksp.rest_pose(lay)
    hook = lay.node_by_name("rhand")
    hand = lay.nodes[hook.parent]
    tilt = rot(cross1, a) @ rot(cross2, b)
    hook_rot = np.array(rest[hook.index].rotation)
    hand_rot = np.array(rest[hand.index].rotation)
    delta_world = hook_rot @ (tilt @ axis) * slide
    local_old = hand_rot.T @ hook_rot
    local_new = local_old @ tilt
    out = {
        "slide_m": float(slide), "tilt_deg": [float(a), float(b)],
        "rms_cm_before": [float(np.sqrt(x) * 100) for x in before],
        "rms_cm_after": [float(np.sqrt(x) * 100) for x in after],
        "position_delta_in_hand_frame": [float(x) for x in hand_rot.T @ delta_world],
        "local_quaternion_xyzw": [float(x) for x in quat_xyzw(local_new)],
        "old_local_quaternion_xyzw": [float(x) for x in quat_xyzw(local_old)],
    }
    path = HERE / f"grip_opt{tag}.json"
    path.write_text(json.dumps(out, indent=2))
    print(f"wrote {path.name}")


if __name__ == "__main__":
    main(*sys.argv[1:5])
