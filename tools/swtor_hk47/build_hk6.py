"""p_hk47 from The Old Republic's HK-47: build_hk5, with the hands closed into a grip.

The Old Republic models HK-47's hands open and flat, and this build carries each
finger as one whole piece riding on the hand, so a two-handed rifle rested
against open palms. Vanilla does not close its hands by animation either: its
right-hand finger nodes hold exactly the same angles in every one of its
animations, and the left hand moves 10 to 20 degrees in the rifle stances. The
grip is a fixed curl.

So the curl is baked into the donor's own skinned fingers before they are
written. The Old Republic skins each finger across its three bones with smooth
blend weights at the knuckles, and every knuckle's joint is measured, so each
finger bone is rotated about its own joint, down the chain, and every vertex
takes the weighted blend of its bones' rotations - linear blend skinning with
the artist's own weights. The finger bends; nothing tears.

Axes are vanilla's, measured from the rifle stance: fingers curl about the
front-to-back axis so the tips swing in toward the body, which wraps them round
a bar pointing forward; thumbs turn about vanilla's thumb axes. Angles:

    right  index 10 15 10   the trigger finger stays nearly straight, as vanilla's does
           middle 55 50 40  vanilla's own 55 and 50
           thumb 33         vanilla's own
    left   index 40 40 30   a firmer grip than vanilla's small left-hand keys,
           middle 50 45 35  because these fingers start out flat
           thumb 25

Joints and piece assignment are measured on the unbent mesh; only the written
geometry is bent. Everything else is build_hk5: whole pieces by vanilla region,
the skeleton on the donor's joints, the neck straightened, the grip hooks, the
weak reflection texture.

usage: build_hk6.py <out folder>
"""
import collections
import json
import os
import shutil
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, r"C:\Users\jryan\mdl swap\src")
sys.path.insert(0, str(Path(__file__).parent))

import build_hk2 as B
from build_hk4 import vanilla_boxes
from build_hk5 import NECK_AXIS, NECK_CHAIN, move_to
from pieces_probe import pieces
from kmdlfun import library as klib, space as ksp, visibility as kvis, swtor
from kmdlfun.mouthparts import _shift_position_controller
from kmdlswap import layout as kl, edit as kedit, obj as kobj, swap as kswap

HERE = Path(__file__).parent

# Curl axes, from vanilla's rifle stance (world frame, rest pose).
FINGER_AXIS = {"Right": np.array([-0.08, 1.00, -0.02]), "Left": np.array([-0.08, -1.00, 0.04])}
THUMB_AXIS = {"Right": np.array([-0.55, -0.82, -0.17]), "Left": np.array([0.52, -0.82, -0.25])}

ANGLES = {
    "Right": {"Index": (10, 15, 10), "Middle": (55, 50, 40), "Thumb": (33,)},
    "Left": {"Index": (40, 40, 30), "Middle": (50, 45, 35), "Thumb": (25,)},
}
SCALE = float(os.environ.get("CURL_SCALE", "1.0"))


def rotation(axis, deg):
    axis = axis / np.linalg.norm(axis)
    a = np.radians(deg)
    x, y, z = axis
    c, s, C = np.cos(a), np.sin(a), 1 - np.cos(a)
    return np.array([[c + x*x*C, x*y*C - z*s, x*z*C + y*s],
                     [y*x*C + z*s, c + y*y*C, y*z*C - x*s],
                     [z*x*C - y*s, z*y*C + x*s, c + z*z*C]])


def finger_transforms(joint):
    """World transform (R, t: p -> R p + t) for every finger bone, composed down each chain."""
    out = {}
    for side, fingers in ANGLES.items():
        for finger, angles in fingers.items():
            bones = [f"{side}{finger}Finger"] + [f"{side}{finger}Finger{i}" for i in range(1, len(angles))]
            axis = THUMB_AXIS[side] if finger == "Thumb" else FINGER_AXIS[side]
            R_acc, t_acc = np.eye(3), np.zeros(3)
            for bone, deg in zip(bones, angles):
                if bone not in joint:
                    break
                # the joint has already been carried by the rotations above it
                j = R_acc @ joint[bone] + t_acc
                R_local = rotation(R_acc @ axis, deg * SCALE)
                R_acc = R_local @ R_acc
                t_acc = R_local @ (t_acc - j) + j
                out[bone] = (R_acc.copy(), t_acc.copy())
    return out


def curl(pos, nrm, weights, bone_ids, names, joint):
    """Linear blend skinning of the fingers with the donor's own weights."""
    xf = finger_transforms(joint)
    if not xf:
        return pos, nrm, 0
    idx_of = {b: i for i, b in enumerate(names)}
    mats = np.tile(np.eye(3), (len(names), 1, 1))
    offs = np.zeros((len(names), 3))
    for bone, (R, t) in xf.items():
        mats[idx_of[bone]] = R
        offs[idx_of[bone]] = t
    wsum = weights.sum(axis=1, keepdims=True)
    wn = np.where(wsum > 0, weights / np.maximum(wsum, 1e-9), 0.0)
    new_pos = np.zeros_like(pos)
    new_nrm = np.zeros_like(nrm) if nrm is not None else None
    for k in range(4):
        R = mats[bone_ids[:, k]]
        t = offs[bone_ids[:, k]]
        new_pos += wn[:, k:k+1] * (np.einsum("nij,nj->ni", R, pos) + t)
        if nrm is not None:
            new_nrm += wn[:, k:k+1] * np.einsum("nij,nj->ni", R, nrm)
    if nrm is not None:
        new_nrm /= np.maximum(np.linalg.norm(new_nrm, axis=1, keepdims=True), 1e-9)
    moved = int((np.linalg.norm(new_pos - pos, axis=1) > 1e-6).sum())
    return new_pos, new_nrm, moved


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

    # the bent geometry, written below; everything measured stays on `pos`
    geo_pos, geo_nrm, moved = curl(pos, nrm, weights, bone_ids, names, joint)

    want = []
    for tri in faces:
        votes = collections.Counter(B.MAP.get(names[dominant[v]]) for v in tri)
        votes.pop(None, None)
        want.append(votes.most_common(1)[0][0] if votes else None)

    lib = klib.ModelLibrary(B.KOTOR)
    mdl, mdx = lib.read(B.HOST)
    host = kl.parse(mdl, mdx)
    have = {n.name for n in host.nodes if n.in_animation is None and n.is_mesh}

    boxes = vanilla_boxes(host, sorted({w for w in want if w is not None}))
    for tris in pieces(pos, faces):
        verts_ids = np.unique(faces[tris])
        bones_here = {names[dominant[v]] for v in verts_ids}
        share = collections.Counter(want[t] for t in tris)
        share.pop(None, None)
        if bones_here & {"Neck", "Neck1"} and "Neck" in share:
            chosen = "Neck"
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

    targets = {}
    for node_name in set(B.MAP.values()) & have:
        _anchor, place = B.anchor_of(bones_per_node[node_name], joint)
        if place is not None:
            targets[node_name] = np.asarray(place, dtype=float)
    for node_name in [n.name for n in host.nodes if n.in_animation is None and n.name in targets]:
        mdl = move_to(mdl, mdx, node_name, targets[node_name])

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
    for name in sorted(NECK_CHAIN, key=lambda k: lay.node_by_name(k).index):
        mdl = move_to(mdl, mdx, name, chain_targets[name])

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
                    p_local.append(r.to_local(tuple(geo_pos[v])))
                    if geo_nrm is not None:
                        n_local.append(tuple(rot.T @ geo_nrm[v]))
                    if uvs is not None:
                        uv_local.append(tuple(uvs[v]))
                face.append(seen[v])
            tri_local.append(tuple(face))
        mesh = kobj.ObjMesh(name=node_name, positions=p_local, faces=tri_local,
                            uvs=uv_local, normals=n_local)
        geo, _report = kswap.build_replacement(layout, node, mesh, facial_rig=False)
        mdl, mdx = kedit.replace_geometry(layout, node, geo, texture=B.TEXTURE)

    layout = kl.parse(mdl, mdx)
    mdl, _hidden = kvis.hide_nodes(layout, mdl, sorted(have - set(by_node)))
    mdl, _grown = B.widen_bounds(mdl, mdx)

    work = bytearray(mdl)
    lay = kl.parse(mdl, mdx)
    for hook, delta in json.loads((HERE / "grip_fit.json").read_text()).items():
        _shift_position_controller(work, lay.node_by_name(hook), tuple(delta))
    mdl = bytes(work)

    (out_dir / f"{B.HOST}.mdl").write_bytes(mdl)
    (out_dir / f"{B.HOST}.mdx").write_bytes(mdx)
    for name in ("tor_hk47.tga", "tor_hk47.txi"):
        shutil.copy2(HERE / "hk_tex" / name, out_dir / name)

    spans = []
    for side in ("Right", "Left"):
        fingers = [i for i, b in enumerate(names) if b.startswith(side) and "Finger" in b]
        sel = np.isin(dominant, fingers)
        d = np.linalg.norm(geo_pos[sel] - pos[sel], axis=1)
        spans.append(f"{side.lower()} fingertips moved up to {d.max()*100:.1f} cm")
    print(f"curl scale {SCALE}: {moved} vertices bent; " + "; ".join(spans))


if __name__ == "__main__":
    main(sys.argv[1])
