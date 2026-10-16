"""Build KOTOR's p_hk47 with The Old Republic's HK-47 on a skeleton fitted to it.

The earlier builds kept one of the two things fixed and bent the other to fit:
either the geometry stayed where the donor put it and hinged about the old
HK-47's joints, or it was moved onto those joints and stood like the old
HK-47 in new plating. This build keeps the donor's geometry exactly where it
is and moves the *skeleton* instead: every rebuilt node's rest position goes to
the donor's own joint for that part, so each piece hinges where The Old
Republic hinges it.

That is safe because of how this model animates. p_hk47 has no supermodel; its
75 animations live in the file, and across all of them every position key on
every limb and torso node is zero. Only `rootdummy` carries real positions, and
it is not touched. The animations turn the limbs and never place them, so a
limb's rest position is the only thing that decides where it hangs.

The engine reads a node's rest position from its position controller over the
header field, so both are moved together, with `mouthparts`'s helper for
exactly that. Orientations are left alone: the host's rotation keys are what
drive the parts, and they are authored against the host's own frames.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, r"C:\Users\jryan\mdl swap\src")
sys.path.insert(0, str(Path(__file__).parent))

import build_hk2 as B  # the map, the skeleton, the joints, the donor reader
from kmdlfun import library as klib, space as ksp, visibility as kvis, swtor
from kmdlfun.mouthparts import _shift_position_controller
from kmdlswap import layout as kl, edit as kedit, obj as kobj, swap as kswap


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
    pos[:, :2] *= -1          # the same 180 degree yaw as every build before
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

    import collections
    want = []
    for tri in faces:
        votes = collections.Counter(B.MAP.get(names[dominant[v]]) for v in tri)
        votes.pop(None, None)
        want.append(votes.most_common(1)[0][0] if votes else None)
    by_node = collections.defaultdict(list)
    for i, node_name in enumerate(want):
        if node_name is not None:
            by_node[node_name].append(i)
    bones_per_node = collections.defaultdict(set)
    for bone, node_name in B.MAP.items():
        if bone in chunk:
            bones_per_node[node_name].add(bone)

    lib = klib.ModelLibrary(B.KOTOR)
    mdl, mdx = lib.read(B.HOST)
    layout = kl.parse(mdl, mdx)
    have = {n.name for n in layout.nodes if n.in_animation is None and n.is_mesh}
    missing = sorted(set(by_node) - have)
    if missing:
        raise SystemExit(f"the host has no node named {missing}")

    # --- the skeleton, parents before children -------------------------------
    # A node's position is stored in its parent's frame, and moving a parent
    # carries its children with it. Walking the tree top down and re-reading the
    # rest pose after every move means each child is placed against where its
    # parent actually ended up, not where it started.
    targets = {}
    for node_name in by_node:
        anchor, place = B.anchor_of(bones_per_node[node_name], joint)
        if place is not None:
            targets[node_name] = (anchor, place)

    order = [n.name for n in layout.nodes
             if n.in_animation is None and n.name in targets]
    moved = []
    work = bytearray(mdl)
    for node_name in order:
        current = kl.parse(bytes(work), mdx)
        rest = ksp.rest_pose(current)
        node = current.node_by_name(node_name)
        anchor, place = targets[node_name]
        world_delta = np.asarray(place) - np.asarray(rest[node.index].position)
        if node.parent is not None and node.parent in rest:
            frame = np.asarray(rest[node.parent].rotation)
            local_delta = frame.T @ world_delta
        else:
            local_delta = world_delta
        _shift_position_controller(work, node, tuple(float(x) for x in local_delta))
        moved.append((node_name, anchor, how.get(anchor, "-"),
                      float(np.linalg.norm(world_delta))))
    mdl = bytes(work)

    # --- the geometry, in the donor's own positions ----------------------------
    lines = []
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
        geo, report = kswap.build_replacement(layout, node, mesh, facial_rig=False)
        mdl, mdx = kedit.replace_geometry(layout, node, geo, texture=B.TEXTURE)
        lines.append(f"{node_name:14s} {report.old_vertices:4d}v {report.old_triangles:4d}t "
                     f"-> {report.new_vertices:4d}v {report.new_triangles:4d}t")

    layout = kl.parse(mdl, mdx)
    leftover = sorted(have - set(by_node))
    mdl, hidden = kvis.hide_nodes(layout, mdl, leftover)
    mdl, grown = B.widen_bounds(mdl, mdx)

    (out_dir / f"{B.HOST}.mdl").write_bytes(mdl)
    (out_dir / f"{B.HOST}.mdx").write_bytes(mdx)

    # --- proof: pivots on the donor's joints, geometry on the donor's vertices --
    final = kl.parse(mdl, mdx)
    rest = ksp.rest_pose(final)
    pivot_err, geo_err = [], []
    for node_name, (anchor, place) in targets.items():
        n = final.node_by_name(node_name)
        pivot_err.append(float(np.linalg.norm(np.asarray(rest[n.index].position) - place)))
        r = rest[n.index]
        local = np.array(kedit.extract(final, n).positions)
        world = local @ np.array(r.rotation).T + np.array(r.position)
        expected = pos[np.unique(faces[by_node[node_name]])]
        # every rebuilt vertex should be a donor vertex, to float precision
        d = np.linalg.norm(world[:, None, :] - expected[None, :, :], axis=2).min(axis=1)
        geo_err.append(float(d.max()))

    print("\n".join(lines))
    print(f"\nnodes rebuilt: {len(by_node)}   triangles placed: "
          f"{sum(len(v) for v in by_node.values())} of {len(faces)}")
    print(f"hidden: {', '.join(hidden)}")
    print(f"bounds widened on {len(grown)} nodes")
    print(f"\npivots moved onto the donor's joints ({len(moved)} nodes):")
    for node_name, anchor, source, far in sorted(moved, key=lambda m: -m[3]):
        print(f"   {node_name:14s} to {anchor:18s} ({source:7s}) {far*100:5.1f} cm")
    print(f"\nworst pivot left off its donor joint: {max(pivot_err)*1000:.3f} mm")
    print(f"worst vertex left off its donor position: {max(geo_err)*1000:.3f} mm")


if __name__ == "__main__":
    main(sys.argv[1])
