"""p_hk47 from The Old Republic's HK-47: build_hk4's region build, with the neck
straightened and a very weak reflection.

The neck. The ribbed neck column is one piece of the donor's armour, and the
region rule gave it to `head`, so every nod swung its base across the chest.
It now belongs to `Neck`. And the pivots above the chest were scattered: Neck
6.6 cm behind centre, Hturn_g 5.6 cm behind and 5 cm higher than the head,
the head itself 0.7 cm in front. The animations turn Neck up to 66 degrees,
almost all of it about the vertical, which spun the column about a line 5 cm
behind it. Vanilla stacks all four on one vertical line. So does this: Neck,
Hturn_g, talkdummy and head all go onto the column's own axis, measured slice
by slice at x 0, y -0.095. Heights are kept, except that Hturn_g and
talkdummy sit at the head's height, as they do in vanilla.

The grip hooks from grip_fit.json are carried over, and the texture comes from
hk_tex: a gloss-derived reflection mask at 0.3 strength, alpha mean 242.

usage: build_hk5.py <out folder>
"""
import collections
import json
import shutil
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, r"C:\Users\jryan\mdl swap\src")
sys.path.insert(0, str(Path(__file__).parent))

import build_hk2 as B
from build_hk4 import vanilla_boxes
from pieces_probe import pieces
from kmdlfun import library as klib, space as ksp, visibility as kvis, swtor
from kmdlfun.mouthparts import _shift_position_controller
from kmdlswap import layout as kl, edit as kedit, obj as kobj, swap as kswap

HERE = Path(__file__).parent
NECK_AXIS = (0.0, -0.095)          # x, y of the neck column, measured
NECK_CHAIN = ("Neck", "Hturn_g", "talkdummy", "head")


def move_to(mdl, mdx, name, target):
    """Move one node's rest position, header and controller, to a world point."""
    lay = kl.parse(mdl, mdx)
    rest = ksp.rest_pose(lay)
    node = lay.node_by_name(name)
    delta = np.asarray(target) - np.asarray(rest[node.index].position)
    if node.parent is not None and node.parent in rest:
        delta = np.asarray(rest[node.parent].rotation).T @ delta
    work = bytearray(mdl)
    _shift_position_controller(work, node, tuple(float(x) for x in delta))
    return bytes(work)


def main(out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    raw, model = B.donor()
    info = model.meshes[0]
    found = swtor.mesh(raw, index=0, model=model)
    pos = np.array(found.positions)
    nrm = np.array(found.normals) if found.normals else None
    uvs = np.array(found.uvs) if found.uvs else None
    faces = np.array(found.faces)
    pos[:, :2] *= -1
    if nrm is not None:
        nrm[:, :2] *= -1

    buf = np.frombuffer(raw, np.uint8, info.vertices * info.vertex_size,
                        info.vertices_at).reshape(info.vertices, info.vertex_size)
    weights = buf[:, 12:16].astype(float) / 255.0
    bone_ids = buf[:, 16:20].astype(int)
    dominant = np.take_along_axis(bone_ids, weights.argmax(axis=1)[:, None], 1).ravel()
    names = np.array(info.bones, dtype=object)
    chunk = {b: pos[dominant == i] for i, b in enumerate(names) if (dominant == i).any()}
    joint, _how = B.joints(pos, weights, bone_ids, names, chunk)

    want = []
    for tri in faces:
        votes = collections.Counter(B.MAP.get(names[dominant[v]]) for v in tri)
        votes.pop(None, None)
        want.append(votes.most_common(1)[0][0] if votes else None)

    lib = klib.ModelLibrary(B.KOTOR)
    mdl, mdx = lib.read(B.HOST)
    host = kl.parse(mdl, mdx)
    have = {n.name for n in host.nodes if n.in_animation is None and n.is_mesh}

    # --- whole pieces, by vanilla region; the neck column goes to Neck --------
    boxes = vanilla_boxes(host, sorted({w for w in want if w is not None}))
    neck_tris = 0
    for tris in pieces(pos, faces):
        verts_ids = np.unique(faces[tris])
        bones_here = {names[dominant[v]] for v in verts_ids}
        share = collections.Counter(want[t] for t in tris)
        share.pop(None, None)
        if bones_here & {"Neck", "Neck1"} and "Neck" in share:
            chosen = "Neck"
            neck_tris = len(tris)
        elif len(share) < 2:
            continue
        else:
            verts = pos[verts_ids]
            inside = {n: int(np.all((verts >= boxes[n][0]) & (verts <= boxes[n][1]), axis=1).sum())
                      for n in share}
            best = max(inside.values())
            tied = [n for n in share if inside[n] == best]
            chosen = max(tied, key=lambda n: share[n])
        for t in tris:
            want[t] = chosen

    by_node = collections.defaultdict(list)
    for i, node_name in enumerate(want):
        if node_name is not None:
            by_node[node_name].append(i)
    bones_per_node = collections.defaultdict(set)
    for bone, node_name in B.MAP.items():
        if bone in chunk:
            bones_per_node[node_name].add(bone)

    # --- skeleton on the donor's joints, parents first ------------------------
    targets = {}
    for node_name in set(B.MAP.values()) & have:
        _anchor, place = B.anchor_of(bones_per_node[node_name], joint)
        if place is not None:
            targets[node_name] = np.asarray(place, dtype=float)
    order = [n.name for n in host.nodes if n.in_animation is None and n.name in targets]
    for node_name in order:
        mdl = move_to(mdl, mdx, node_name, targets[node_name])

    # --- the neck chain onto one vertical line --------------------------------
    rest = ksp.rest_pose(kl.parse(mdl, mdx))
    lay = kl.parse(mdl, mdx)
    head_z = float(rest[lay.node_by_name("head").index].position[2])
    neck_z = float(rest[lay.node_by_name("Neck").index].position[2])
    chain_targets = {
        "Neck": (NECK_AXIS[0], NECK_AXIS[1], neck_z),
        "Hturn_g": (NECK_AXIS[0], NECK_AXIS[1], head_z),
        "talkdummy": (NECK_AXIS[0], NECK_AXIS[1], head_z),
        "head": (NECK_AXIS[0], NECK_AXIS[1], head_z),
    }
    chain_order = sorted(NECK_CHAIN, key=lambda k: kl.parse(mdl, mdx).node_by_name(k).index)
    for name in chain_order:           # parents before children, by the file's own order
        mdl = move_to(mdl, mdx, name, chain_targets[name])

    # --- geometry in the donor's own positions --------------------------------
    for node_name in sorted(by_node, key=lambda k: -len(by_node[k])):
        layout = kl.parse(mdl, mdx)
        node = layout.node_by_name(node_name)
        r = ksp.rest_pose(layout)[node.index]
        rot = np.array(r.rotation)
        seen, p_local, n_local, uv_local, tri_local = {}, [], [], [], []
        for i in by_node[node_name]:
            face = []
            for v in faces[i]:
                if v not in seen:
                    seen[v] = len(p_local)
                    p_local.append(r.to_local(tuple(pos[v])))
                    if nrm is not None:
                        n_local.append(tuple(rot.T @ nrm[v]))
                    if uvs is not None:
                        uv_local.append(tuple(uvs[v]))
                face.append(seen[v])
            tri_local.append(tuple(face))
        mesh = kobj.ObjMesh(name=node_name, positions=p_local, faces=tri_local,
                            uvs=uv_local, normals=n_local)
        geo, _report = kswap.build_replacement(layout, node, mesh, facial_rig=False)
        mdl, mdx = kedit.replace_geometry(layout, node, geo, texture=B.TEXTURE)

    layout = kl.parse(mdl, mdx)
    mdl, hidden = kvis.hide_nodes(layout, mdl, sorted(have - set(by_node)))
    mdl, _grown = B.widen_bounds(mdl, mdx)

    # --- the grip hooks, in their hands' frames -------------------------------
    work = bytearray(mdl)
    lay = kl.parse(mdl, mdx)
    for hook, delta in json.loads((HERE / "grip_fit.json").read_text()).items():
        _shift_position_controller(work, lay.node_by_name(hook), tuple(delta))
    mdl = bytes(work)

    (out_dir / f"{B.HOST}.mdl").write_bytes(mdl)
    (out_dir / f"{B.HOST}.mdx").write_bytes(mdx)
    for name in ("tor_hk47.tga", "tor_hk47.txi"):
        shutil.copy2(HERE / "hk_tex" / name, out_dir / name)

    final = kl.parse(mdl, mdx)
    rest = ksp.rest_pose(final)
    print(f"neck column: {neck_tris} tris now on Neck; nodes drawn {len(by_node)}")
    for name in NECK_CHAIN:
        print(f"   {name:10s} pivot {np.round(rest[final.node_by_name(name).index].position, 3)}")
    print(f"hidden: {', '.join(hidden)}")


if __name__ == "__main__":
    main(sys.argv[1])
