"""Where the torso should be cut, and where the hand actually grips.

Torso: the donor's waist armour went to the host's Pelvis and its chest to
Fore_body, which hangs off InnerTorso. Pelvis and InnerTorso are siblings the
animations turn independently, so anything bridging them tears. This measures
how the host itself cuts that region, how the donor's pieces are shaped, and
how hard the common animations twist the spine.

Hand: a weapon hangs from the `rhand` and `lhand` hooks. Their position was
carried across by keeping vanilla's offset from the wrist, not by looking at
where the new fingers close.
"""
import sys, struct, collections
import numpy as np
from pathlib import Path

sys.path.insert(0, r"C:\Users\jryan\mdl swap\src")
sys.path.insert(0, str(Path(__file__).parent))
import build_hk2 as B
from kmdlfun import library as klib, space as ksp, swtor
from kmdlswap import layout as kl, edit as kedit
from kmdlswap.nodes import CONTROLLER_SIZE

BASE = 12
S = Path(__file__).parent

van_mdl, van_mdx = klib.ModelLibrary(B.KOTOR).read(B.HOST)
van = kl.parse(van_mdl, van_mdx)
vrest = ksp.rest_pose(van)


def world(lay, rest, name):
    n = lay.node_by_name(name)
    r = rest[n.index]
    geo = kedit.extract(lay, n)
    p = np.array(geo.positions) @ np.array(r.rotation).T + np.array(r.position)
    return p, np.array([f.vertices for f in geo.faces])


print("== vanilla's own torso cut ==")
for name in ("Pelvis", "InnerTorso", "Fore_body", "TorsoHoses"):
    p, _ = world(van, vrest, name)
    n = van.node_by_name(name)
    print(f"  {name:11s} pivot z {vrest[n.index].position[2]:.3f}  geometry z {p[:,2].min():.3f}..{p[:,2].max():.3f}  "
          f"x {p[:,0].min():.3f}..{p[:,0].max():.3f}")

print("\n== how hard the everyday animations twist the spine (degrees of swing) ==")
def swing(anim, node):
    for n in van.nodes:
        if n.in_animation != anim or n.name != node:
            continue
        at = BASE + n.offset
        carr, ccount = struct.unpack_from("<II", van_mdl, at + 56)
        dat, dlen = struct.unpack_from("<II", van_mdl, at + 68)
        if not ccount or not dlen:
            return 0.0
        data = np.frombuffer(van_mdl, np.float32, dlen, BASE + dat)
        for i in range(ccount):
            typ, _u, rows, tix, dix, cols = struct.unpack_from("<IHHHHB", van_mdl, BASE + carr + i * CONTROLLER_SIZE)
            if typ != 20 or (cols & 0x0F) != 4:
                continue
            q = data[dix: dix + rows * 4].reshape(rows, 4)
            q = q / np.linalg.norm(q, axis=1, keepdims=True)
            # largest angle between any key and the first key
            dots = np.abs(q @ q[0])
            return float(2 * np.degrees(np.arccos(np.clip(dots.min(), 0, 1))))
    return 0.0
for anim in ("pause1", "pause2", "walk", "run", "g5r1", "g5a1" if False else "b5a1", "tlknorm"):
    row = {node: swing(anim, node) for node in ("Pelvis", "InnerTorso", "Fore_body")}
    print(f"  {anim:8s} Pelvis {row['Pelvis']:5.1f}  InnerTorso {row['InnerTorso']:5.1f}  Fore_body {row['Fore_body']:5.1f}")

print("\n== the donor's torso, piece by piece ==")
raw, model = B.donor()
info = model.meshes[0]
found = swtor.mesh(raw, index=0, model=model)
pos = np.array(found.positions); pos[:, :2] *= -1
faces = np.array(found.faces)
buf = np.frombuffer(raw, np.uint8, info.vertices * info.vertex_size, info.vertices_at).reshape(info.vertices, info.vertex_size)
w = buf[:, 12:16].astype(float) / 255.0
bi = buf[:, 16:20].astype(int)
dom = np.take_along_axis(bi, w.argmax(axis=1)[:, None], 1).ravel()
names = np.array(info.bones, dtype=object)


def components(vertex_ids):
    """Connected pieces among these vertices, joined by shared triangles and by
    coincident positions (a hard edge splits a vertex but not the surface)."""
    ids = set(int(v) for v in vertex_ids)
    parent = {v: v for v in ids}
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb: parent[ra] = rb
    for tri in faces:
        inside = [int(v) for v in tri if int(v) in ids]
        for a, b in zip(inside, inside[1:]):
            union(a, b)
    key = collections.defaultdict(list)
    for v in ids:
        key[tuple(np.round(pos[v], 4))].append(v)
    for group in key.values():
        for a, b in zip(group, group[1:]):
            union(a, b)
    out = collections.defaultdict(list)
    for v in ids:
        out[find(v)].append(v)
    return sorted(out.values(), key=len, reverse=True)


for bone in ("Root", "Pelvis", "LowerBack", "Chest", "Chest2"):
    ids = np.where(names[dom] == bone)[0]
    parts = components(ids)
    print(f"  {bone:9s} {len(ids):4d} verts in {len(parts)} pieces")
    for piece in parts[:8]:
        p = pos[piece]
        print(f"      {len(piece):4d} verts  z {p[:,2].min():.3f}..{p[:,2].max():.3f}  "
              f"x {p[:,0].min():+.3f}..{p[:,0].max():+.3f}  y {p[:,1].min():+.3f}..{p[:,1].max():+.3f}")

spine = ["Root", "Pelvis", "LowerBack", "Chest", "Chest1", "Chest2"]
print("\n  vertices the artist blended across two spine bones:")
pairs = collections.Counter(); where = collections.defaultdict(list)
for v in range(len(pos)):
    live = sorted({names[bi[v, k]] for k in range(4) if w[v, k] > 0.15} & set(spine))
    if len(live) >= 2:
        pairs[tuple(live)] += 1; where[tuple(live)].append(v)
for pair, n in pairs.most_common():
    p = pos[where[pair]]
    print(f"      {' + '.join(pair):22s} {n:3d} verts  z {p[:,2].min():.3f}..{p[:,2].max():.3f}")

print("\n== the grip ==")
built = kl.parse((S / "hk_skel" / "p_hk47.mdl").read_bytes(), (S / "hk_skel" / "p_hk47.mdx").read_bytes())
brest = ksp.rest_pose(built)
for side, hook, hand, fingers in (
        ("right", "rhand", "L_hand01", ("RightThumbFinger", "RightIndexFinger", "RightMiddleFinger",
                                         "RightIndexFinger1", "RightMiddleFinger1")),
        ("left", "lhand", "L_hand", ("LeftThumbFinger", "LeftIndexFinger", "LeftMiddleFinger",
                                      "LeftIndexFinger1", "LeftMiddleFinger1"))):
    vh = van.node_by_name(hook)
    vp, _ = world(van, vrest, hand)
    vhook = np.array(vrest[vh.index].position)
    vlo, vhi = vp.min(0), vp.max(0)
    frac = (vhook - vlo) / (vhi - vlo)
    bh = built.node_by_name(hook)
    bp, _ = world(built, brest, hand)
    blo, bhi = bp.min(0), bp.max(0)
    bhook = np.array(brest[bh.index].position)
    mapped = blo + frac * (bhi - blo)
    # where the donor's fingers close: the mean of thumb and the base finger joints
    tips = [pos[names[dom] == f] for f in fingers if (names[dom] == f).any()]
    grip = np.vstack(tips).mean(axis=0)
    print(f"  {side}: hook now {bhook.round(3)}")
    print(f"         vanilla hook sits at {frac.round(2)} of vanilla's hand box; the same fraction of the new hand is {mapped.round(3)}")
    print(f"         centroid of the new thumb and finger bases {grip.round(3)}")
    print(f"         hook orientation vanilla {np.round(vrest[vh.index].rotation, 2).tolist()}")
    print(f"         hand node orientation vanilla {np.round(vrest[van.node_by_name(hand).index].rotation, 2).tolist()}")
