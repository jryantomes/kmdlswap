"""Do the parts still touch? Minimum distance between every connected pair."""
import sys
import numpy as np
from pathlib import Path
sys.path.insert(0, r"C:\Users\jryan\mdl swap\src")
from kmdlfun import space as ksp, render as krender
from kmdlswap import layout as kl, edit as kedit

S = Path(sys.argv[1])


def world_parts(folder):
    b = S / folder
    lay = kl.parse((b / "p_hk47.mdl").read_bytes(), (b / "p_hk47.mdx").read_bytes())
    rest = ksp.rest_pose(lay)
    out = {}
    for n in lay.nodes:
        if n.in_animation is not None or not n.is_mesh or not n.vertex_count:
            continue
        if not krender.parts.renders(lay, n):
            continue
        r = rest[n.index]
        p = np.array(kedit.extract(lay, n).positions)
        out[n.name] = p @ np.array(r.rotation).T + np.array(r.position)
    return lay, out


def nearest_drawn(lay, node, drawn):
    """Walk up until a parent that is actually drawn."""
    at = node.parent
    while at is not None:
        up = lay.nodes[at]
        if up.name in drawn:
            return up.name
        at = up.parent
    return None


rows = {}
for folder in ("hk_out", "hk_joint"):
    lay, parts = world_parts(folder)
    for n in lay.nodes:
        if n.name not in parts or n.in_animation is not None:
            continue
        up = nearest_drawn(lay, n, parts)
        if up is None:
            continue
        a, b = parts[n.name], parts[up]
        d = float(np.linalg.norm(a[:, None, :] - b[None, :, :], axis=2).min())
        rows.setdefault((up, n.name), {})[folder] = d

print(f"{'joint':32s} {'donor placed':>13s} {'hung on host':>14s}")
worst = {"hk_out": [], "hk_joint": []}
for (up, name), got in sorted(rows.items(), key=lambda kv: -max(kv[1].values())):
    a, b = got.get("hk_out", float("nan")), got.get("hk_joint", float("nan"))
    worst["hk_out"].append(a); worst["hk_joint"].append(b)
    flag = "  <-- opens" if b > a + 0.005 else ("  <-- closes" if a > b + 0.005 else "")
    print(f"{up + ' -> ' + name:32s} {a*100:11.1f} cm {b*100:12.1f} cm{flag}")
for k, v in worst.items():
    v = np.array(v)
    print(f"\n{k}: {int((v > 0.005).sum())} of {len(v)} joins are open by more than 5 mm, "
          f"worst {v.max()*100:.1f} cm")
