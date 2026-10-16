"""Which of the donor's armour pieces were torn across two host nodes.

A rigid node can only carry whole pieces. A piece whose triangles were voted
into two nodes will rip at that seam the moment the two nodes turn by
different amounts, which the host's walk does to Pelvis and InnerTorso.
"""
import sys
import collections
from pathlib import Path

import numpy as np

sys.path.insert(0, r"C:\Users\jryan\mdl swap\src")
sys.path.insert(0, str(Path(__file__).parent))
import build_hk2 as B
from kmdlfun import swtor


def pieces(pos, faces):
    """Triangle groups joined by shared vertices or by coincident positions.

    Coincident positions matter: a hard edge or a UV seam splits one vertex
    into several with the same position, and the surface is still one piece.
    """
    n = len(pos)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for a, b, c in faces:
        union(int(a), int(b))
        union(int(b), int(c))
    same = collections.defaultdict(list)
    for v in range(n):
        same[tuple(np.round(pos[v], 4))].append(v)
    for group in same.values():
        for a, b in zip(group, group[1:]):
            union(a, b)
    by_root = collections.defaultdict(list)
    for t, tri in enumerate(faces):
        by_root[find(int(tri[0]))].append(t)
    return list(by_root.values())


def main():
    raw, model = B.donor()
    info = model.meshes[0]
    found = swtor.mesh(raw, index=0, model=model)
    pos = np.array(found.positions)
    pos[:, :2] *= -1
    faces = np.array(found.faces)
    buf = np.frombuffer(raw, np.uint8, info.vertices * info.vertex_size,
                        info.vertices_at).reshape(info.vertices, info.vertex_size)
    weights = buf[:, 12:16].astype(float) / 255.0
    bone_ids = buf[:, 16:20].astype(int)
    dominant = np.take_along_axis(bone_ids, weights.argmax(axis=1)[:, None], 1).ravel()
    names = np.array(info.bones, dtype=object)

    want = []
    for tri in faces:
        votes = collections.Counter(B.MAP.get(names[dominant[v]]) for v in tri)
        votes.pop(None, None)
        want.append(votes.most_common(1)[0][0] if votes else None)

    groups = pieces(pos, faces)
    torn = []
    for tris in groups:
        nodes = collections.Counter(want[t] for t in tris)
        if len(nodes) > 1:
            verts = np.unique(faces[tris])
            p = pos[verts]
            torn.append((len(tris), nodes, p[:, 2].min(), p[:, 2].max(), p[:, 0].mean()))
    torn.sort(key=lambda r: -r[0])

    print(f"{len(groups)} pieces in the donor, {len(torn)} of them split across more than one node\n")
    print(f"{'tris':>5s} {'z range':>15s} {'x mean':>7s}  nodes and their share")
    for count, nodes, z0, z1, xm in torn:
        share = ", ".join(f"{k} {v}" for k, v in nodes.most_common())
        print(f"{count:5d} {z0:7.3f}..{z1:.3f} {xm:+7.3f}  {share}")

    np.save(Path(__file__).parent / "pieces.npy",
            np.array([np.array(t) for t in groups], dtype=object), allow_pickle=True)


if __name__ == "__main__":
    main()
