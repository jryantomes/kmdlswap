"""Where to hang the weapon hooks so a rifle sits in the new palm as it sits in vanilla's fist.

The hooks are children of the hands, so the answer is worked out entirely in
the hand's own frame and holds in every pose. The weapon runs along its model's
longest axis through the hook's origin. In vanilla that line passes at some
offset from the centroid of the hand and its fingers; the new hook is moved so
the same line keeps the same offset from the new hand's centroid. The hook's
orientation is not touched, so the weapon still points where the animations
point it.

usage: grip_fit.py <build folder> <weapon model>
writes grip_fit.json beside this script: per hook, a position delta in the
hand's frame, ready for _shift_position_controller.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, r"C:\Users\jryan\mdl swap\src")
from kmdlfun import library as klib, parts as kparts, space as ksp
from kmdlswap import edit as kedit, layout as kl

KOTOR = r"E:\SteamLibrary\steamapps\common\swkotor"
HERE = Path(__file__).parent

HANDS = {
    "rhand": ("L_hand01", ("F-06", "F_06", "F-07", "F_07", "RTrgrFngr", "F-08", "F_08",
                           "F-09", "F_09", "F-10", "F_10")),
    "lhand": ("L_hand", ("F-1", "F_1", "LTrgrFngr", "F-2", "F_2", "F-3", "F_3",
                         "F-4", "F_4", "F-5", "F_5")),
}


def drawn_points(lay, rest, names):
    pts = []
    for name in names:
        try:
            n = lay.node_by_name(name)
        except KeyError:
            continue
        if not n.is_mesh or not n.vertex_count or not kparts.renders(lay, n):
            continue
        r = rest[n.index]
        p = np.array(kedit.extract(lay, n).positions)
        pts.append(p @ np.array(r.rotation).T + np.array(r.position))
    return np.vstack(pts)


def weapon_axis(lib, weapon):
    lay = kl.parse(*lib.read(weapon))
    rest = ksp.rest_pose(lay)
    pts = drawn_points(lay, rest, [n.name for n in kparts.mesh_nodes(lay)])
    centred = pts - pts.mean(axis=0)
    _, _, vt = np.linalg.svd(centred, full_matrices=False)
    return vt[0]


def closest_on_line(origin, direction, point):
    d = direction / np.linalg.norm(direction)
    return origin + d * float((point - origin) @ d)


def main(folder, weapon):
    folder = Path(folder)
    lib = klib.ModelLibrary(KOTOR)
    axis_hook = weapon_axis(lib, weapon)

    van = kl.parse(*lib.read("p_hk47"))
    built = kl.parse((folder / "p_hk47.mdl").read_bytes(), (folder / "p_hk47.mdx").read_bytes())
    vrest, brest = ksp.rest_pose(van), ksp.rest_pose(built)

    out = {}
    for hook, (hand, fingers) in HANDS.items():
        rows = {}
        for tag, lay, rest in (("vanilla", van, vrest), ("build", built, brest)):
            h = lay.node_by_name(hook)
            hand_node = lay.node_by_name(hand)
            hand_rot = np.array(rest[hand_node.index].rotation)
            hook_rot = np.array(rest[h.index].rotation)
            hook_pos = np.array(rest[h.index].position)
            centre = drawn_points(lay, rest, (hand,) + fingers).mean(axis=0)
            line_dir = hook_rot @ axis_hook
            near = closest_on_line(hook_pos, line_dir, centre)
            rows[tag] = dict(hand_rot=hand_rot, hook_pos=hook_pos, centre=centre,
                             line_dir=line_dir, near=near)

        v, b = rows["vanilla"], rows["build"]
        # vanilla's gap from the weapon line to the hand centre, in the hand's frame
        gap_local = v["hand_rot"].T @ (v["centre"] - v["near"])
        wanted_near = b["centre"] - b["hand_rot"] @ gap_local
        # sliding the hook along the weapon line changes nothing; remove that part
        shift = wanted_near - b["near"]
        d = b["line_dir"] / np.linalg.norm(b["line_dir"])
        shift = shift - d * float(shift @ d)
        local = b["hand_rot"].T @ shift

        before = np.linalg.norm(b["centre"] - b["near"])
        print(f"{hook}: vanilla weapon line passes {np.linalg.norm(gap_local)*100:.1f} cm from the hand centre; "
              f"the build's passes {before*100:.1f} cm")
        print(f"       move the hook {np.linalg.norm(shift)*100:.1f} cm, world {shift.round(3)}, hand frame {local.round(3)}")
        out[hook] = [float(x) for x in local]

    (HERE / "grip_fit.json").write_text(json.dumps(out, indent=2))
    print(f"wrote {HERE / 'grip_fit.json'}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
