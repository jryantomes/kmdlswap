"""p_hk47 from The Old Republic's HK-47, skeleton fitted, armour pieces kept whole.

`build_hk3` voted every triangle into a node by its bones. The Old Republic
skins some single pieces of armour across several bones - the waist's ring
stack across five spine bones, each finger across its three joints, the knee
cap across thigh and shin - so the vote cut those pieces into several rigid
nodes, and they tore the moment the host's animations turned those nodes by
different amounts. A rigid node can only carry whole pieces.

This build finds every connected piece and gives the whole piece to one node.
Which node is the rule:

    majority  the node that won most of the piece's triangles
    rootmost  the node nearest the root of the host's hierarchy, so the piece
              rides with the part everything else hangs from; ties by majority
    region    the node whose vanilla geometry the piece overlaps most, which
              is how the host itself divides that stretch of the body; ties by
              majority

Pivots are unchanged from build_hk3: every rebuilt node still hinges on the
donor's own joint for the bones that name it.

usage: build_hk4.py <out folder> <majority|rootmost|region>
"""
import collections
import shutil
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, r"C:\Users\jryan\mdl swap\src")
sys.path.insert(0, str(Path(__file__).parent))

import build_hk2 as B
from pieces_probe import pieces
from kmdlfun import library as klib, space as ksp, visibility as kvis, swtor
from kmdlfun.mouthparts import _shift_position_controller
from kmdlswap import layout as kl, edit as kedit, obj as kobj, swap as kswap

HERE = Path(__file__).parent


def depth(lay, name):
    n = lay.node_by_name(name)
    d, at = 0, n.parent
    while at is not None:
        d += 1
        at = lay.nodes[at].parent
    return d


def vanilla_boxes(lay, names):
    rest = ksp.rest_pose(lay)
    out = {}
    for name in names:
        n = lay.node_by_name(name)
        r = rest[n.index]
        p = np.array(kedit.extract(lay, n).positions) @ np.array(r.rotation).T + np.array(r.position)
        out[name] = (p.min(axis=0) - 0.01, p.max(axis=0) + 0.01)
    return out


def main(out_dir, rule):
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
    joint, how = B.joints(pos, weights, bone_ids, names, chunk)

    want = []
    for tri in faces:
        votes = collections.Counter(B.MAP.get(names[dominant[v]]) for v in tri)
        votes.pop(None, None)
        want.append(votes.most_common(1)[0][0] if votes else None)

    lib = klib.ModelLibrary(B.KOTOR)
    mdl, mdx = lib.read(B.HOST)
    host = kl.parse(mdl, mdx)
    have = {n.name for n in host.nodes if n.in_animation is None and n.is_mesh}

    # --- whole pieces ----------------------------------------------------------
    candidates = sorted({w for w in want if w is not None})
    boxes = vanilla_boxes(host, candidates) if rule == "region" else {}
    moved_tris, decisions = 0, []
    for tris in pieces(pos, faces):
        share = collections.Counter(want[t] for t in tris)
        share.pop(None, None)
        if len(share) < 2:
            continue
        majority = share.most_common(1)[0][0]
        if rule == "majority":
            chosen = majority
        elif rule == "rootmost":
            shallowest = min(depth(host, n) for n in share)
            tied = [n for n in share if depth(host, n) == shallowest]
            chosen = max(tied, key=lambda n: share[n])
        elif rule == "region":
            verts = pos[np.unique(faces[tris])]
            inside = {n: int(np.all((verts >= boxes[n][0]) & (verts <= boxes[n][1]), axis=1).sum())
                      for n in share}
            best = max(inside.values())
            tied = [n for n in share if inside[n] == best]
            chosen = max(tied, key=lambda n: share[n])
        else:
            raise SystemExit(f"unknown rule {rule!r}")
        for t in tris:
            if want[t] != chosen:
                moved_tris += 1
                want[t] = chosen
        z = pos[np.unique(faces[tris])][:, 2]
        decisions.append((len(tris), z.min(), z.max(), dict(share), chosen))

    by_node = collections.defaultdict(list)
    for i, node_name in enumerate(want):
        if node_name is not None:
            by_node[node_name].append(i)
    bones_per_node = collections.defaultdict(set)
    for bone, node_name in B.MAP.items():
        if bone in chunk:
            bones_per_node[node_name].add(bone)

    # --- skeleton, parents first (as build_hk3) -------------------------------
    targets = {}
    for node_name in set(B.MAP.values()) & have:
        anchor, place = B.anchor_of(bones_per_node[node_name], joint)
        if place is not None:
            targets[node_name] = (anchor, place)
    order = [n.name for n in host.nodes if n.in_animation is None and n.name in targets]
    work = bytearray(mdl)
    for node_name in order:
        current = kl.parse(bytes(work), mdx)
        rest = ksp.rest_pose(current)
        node = current.node_by_name(node_name)
        world_delta = np.asarray(targets[node_name][1]) - np.asarray(rest[node.index].position)
        if node.parent is not None and node.parent in rest:
            local_delta = np.asarray(rest[node.parent].rotation).T @ world_delta
        else:
            local_delta = world_delta
        _shift_position_controller(work, node, tuple(float(x) for x in local_delta))
    mdl = bytes(work)

    # --- geometry in the donor's own positions --------------------------------
    for node_name in sorted(by_node, key=lambda k: -len(by_node[k])):
        layout = kl.parse(mdl, mdx)
        node = layout.node_by_name(node_name)
        rest = ksp.rest_pose(layout)[node.index]
        rot = np.array(rest.rotation)
        seen, p_local, n_local, uv_local, tri_local = {}, [], [], [], []
        for i in by_node[node_name]:
            face = []
            for v in faces[i]:
                if v not in seen:
                    seen[v] = len(p_local)
                    p_local.append(rest.to_local(tuple(pos[v])))
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

    # A node the donor gave pivots to but no whole piece: nothing to draw.
    layout = kl.parse(mdl, mdx)
    leftover = sorted(have - set(by_node))
    mdl, hidden = kvis.hide_nodes(layout, mdl, leftover)
    mdl, grown = B.widen_bounds(mdl, mdx)

    (out_dir / f"{B.HOST}.mdl").write_bytes(mdl)
    (out_dir / f"{B.HOST}.mdx").write_bytes(mdx)
    for name in ("tor_hk47.tga", "tor_hk47.txi"):
        shutil.copy2(HERE / "hk_skel" / name, out_dir / name)

    print(f"rule {rule}: {len(decisions)} split pieces made whole, {moved_tris} triangles changed node")
    for count, z0, z1, share, chosen in sorted(decisions, key=lambda d: -d[0]):
        print(f"   {count:4d} tris z {z0:.3f}..{z1:.3f}  {share}  -> {chosen}")
    print(f"nodes drawn: {len(by_node)}   hidden: {', '.join(hidden)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
