"""The neck: where its geometry sits, where the pivots above it sit, and how the
animations turn them.

A head turn spins the head about a pivot. If that pivot is not over the middle
of the neck column, the column's base sweeps sideways off the chest.
"""
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, r"C:\Users\jryan\mdl swap\src")
sys.path.insert(0, str(Path(__file__).parent))
from pose_render import BASE, ORIENTATION, controllers
from kmdlfun import library as klib, parts as kparts, space as ksp
from kmdlswap import edit as kedit, layout as kl

S = Path(__file__).parent
KOTOR = r"E:\SteamLibrary\steamapps\common\swkotor"


def world(lay, rest, name):
    n = lay.node_by_name(name)
    r = rest[n.index]
    return np.array(kedit.extract(lay, n).positions) @ np.array(r.rotation).T + np.array(r.position)


for tag, (mdl, mdx) in (("vanilla", klib.ModelLibrary(KOTOR).read("p_hk47")),
                        ("build", ((S / "hk_final" / "p_hk47.mdl").read_bytes(),
                                   (S / "hk_final" / "p_hk47.mdx").read_bytes()))):
    lay = kl.parse(mdl, mdx)
    rest = ksp.rest_pose(lay)
    print(f"== {tag} ==")
    for name in ("Fore_body", "Neck", "Hturn_g", "talkdummy", "head"):
        n = lay.node_by_name(name)
        drawn = n.is_mesh and n.vertex_count and kparts.renders(lay, n)
        line = f"  {name:10s} pivot {np.round(rest[n.index].position, 3)}"
        if drawn:
            p = world(lay, rest, name)
            line += f"  drawn, z {p[:,2].min():.3f}..{p[:,2].max():.3f}"
        print(line)
    head = world(lay, rest, "head")
    band = head[(head[:, 2] < head[:, 2].min() + 0.06)]
    print(f"  bottom 6 cm of what the head node draws: centre x {band[:,0].mean():+.3f} y {band[:,1].mean():+.3f}, "
          f"spans y {band[:,1].min():+.3f}..{band[:,1].max():+.3f}")
    chest = world(lay, rest, "Fore_body")
    top = chest[chest[:, 2] > chest[:, 2].max() - 0.06]
    print(f"  top 6 cm of the chest: centre x {top[:,0].mean():+.3f} y {top[:,1].mean():+.3f}")

print("\n== how the animations turn the neck and head (largest swing, degrees, and mean axis) ==")
mdl, mdx = klib.ModelLibrary(KOTOR).read("p_hk47")
lay = kl.parse(mdl, mdx)
found = {}
for n in lay.nodes:
    if n.in_animation is None or n.name not in ("Neck", "Hturn_g", "head"):
        continue
    for typ, times, vals, ncol in controllers(mdl, n):
        if typ != ORIENTATION or ncol != 4 or len(vals) < 2:
            continue
        q = vals / np.linalg.norm(vals, axis=1, keepdims=True)
        k = int(np.argmin(np.abs(q @ q[0])))
        rel = q[k]
        ang = float(2 * np.degrees(np.arccos(min(1.0, abs(float(rel @ q[0]))))))
        # axis of the key furthest from identity, in the node's parent frame
        axis = rel[:3] / (np.linalg.norm(rel[:3]) + 1e-9)
        found.setdefault(n.name, []).append((ang, n.in_animation, np.round(axis, 2)))
for name, rows in found.items():
    rows.sort(key=lambda r: -r[0])
    print(f"  {name:8s} turned in {len(rows)} animations; biggest:")
    for ang, anim, axis in rows[:6]:
        print(f"      {anim:10s} {ang:5.1f} deg  axis {axis}")
