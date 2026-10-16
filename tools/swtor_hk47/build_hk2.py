"""Build KOTOR's p_hk47 out of The Old Republic's HK-47.

One skinned donor mesh becomes the host's rigid nodes: each vertex goes to the
bone that pulls hardest on it, each triangle to the node most of its corners
agree on.

With ``align="joint"`` each part is then moved so the donor's own joint lands
on the host's, which is what makes it turn about the right point when the
engine animates it. Left at ``align="none"`` the parts keep the donor's own
positions: the standing model is then the donor's silhouette exactly, and every
joint rotates about a pivot up to 14 cm from where the part actually hinges,
which pulls the arms off the shoulders as soon as HK-47 walks.
"""
import sys
import collections
import itertools
import struct
import numpy as np
from pathlib import Path

sys.path.insert(0, r"C:\Users\jryan\mdl swap\src")
from kmdlfun import swtor, library as klib, space as ksp, visibility as kvis
from kmdlswap import layout as kl, edit as kedit, obj as kobj, swap as kswap

KOTOR = r"E:\SteamLibrary\steamapps\common\swkotor"
ASSETS = Path(r"E:/SteamLibrary/steamapps/common/Star Wars - The Old Republic/Assets")
ARCHIVE = "swtor_main_art_creature_a_1.tor"
DONOR = "assassin_hk47_a01"
HOST = "p_hk47"
TEXTURE = "tor_hk47"

# The donor's skeleton, read off its bone names: a pelvis, a spine of four, a
# neck of two, four bones to a limb. Needed to know which end of a part is the
# end it hangs from.
PARENT = {
    "Pelvis": "Root", "LowerBack": "Root", "Chest": "LowerBack",
    "Chest1": "Chest", "Chest2": "Chest1", "Neck": "Chest2",
    "Neck1": "Neck", "Head": "Neck1",
}
for _s in ("Left", "Right"):
    PARENT.update({
        f"{_s}Hip": "Root", f"{_s}Knee": f"{_s}Hip",
        f"{_s}Ankle": f"{_s}Knee", f"{_s}Toe": f"{_s}Ankle",
        f"{_s}Collar": "Chest2", f"{_s}Shoulder": f"{_s}Collar",
        f"{_s}Elbow": f"{_s}Shoulder", f"{_s}Wrist": f"{_s}Elbow",
        f"{_s}ThumbFinger": f"{_s}Wrist",
        f"{_s}IndexFinger": f"{_s}Wrist",
        f"{_s}IndexFinger1": f"{_s}IndexFinger",
        f"{_s}IndexFinger2": f"{_s}IndexFinger1",
        f"{_s}MiddleFinger": f"{_s}Wrist",
        f"{_s}MiddleFinger1": f"{_s}MiddleFinger",
        f"{_s}MiddleFinger2": f"{_s}MiddleFinger1",
    })

# Donor bone -> host node. The 180 degree yaw that turns the donor to face the
# way KOTOR faces also swaps its sides, so the donor's Left lands on L_.
MAP = {
    "Head": "head",
    "Neck": "Neck", "Neck1": "Neck",
    "Chest2": "Fore_body", "Chest1": "Fore_body",
    "Chest": "InnerTorso", "LowerBack": "InnerTorso",
    "Root": "Pelvis", "Pelvis": "Pelvis",
}
for _t, _h in (("Left", "L"), ("Right", "R")):
    _hand = "L_hand" if _t == "Left" else "L_hand01"   # the host misnames its right hand
    _trigger = "LTrgrFngr" if _t == "Left" else "RTrgrFngr"
    _index0, _index1 = ("F-1", "F_1") if _t == "Left" else ("F-07", "F_07")
    _middle0, _middle1 = ("F-2", "F_2") if _t == "Left" else ("F-08", "F_08")
    _thumb = "F-5" if _t == "Left" else "F-10"
    MAP.update({
        f"{_t}Collar": f"{_h}_upper_arm", f"{_t}Shoulder": f"{_h}_upper_arm",
        f"{_t}Elbow": f"{_h}_lower_arm",
        f"{_t}Wrist": _hand,
        f"{_t}ThumbFinger": _thumb,
        f"{_t}IndexFinger": _index0, f"{_t}IndexFinger1": _index1,
        f"{_t}IndexFinger2": _trigger,
        # the host's other fingers are two joints deep and the donor's three,
        # so the last segment rides with the second
        f"{_t}MiddleFinger": _middle0, f"{_t}MiddleFinger1": _middle1,
        f"{_t}MiddleFinger2": _middle1,
        f"{_t}Hip": f"{_h}_thigh", f"{_t}Knee": f"{_h}_calf",
        f"{_t}Ankle": f"{_h}_foot", f"{_t}Toe": f"{_h}_Toe",
    })


def donor():
    arc = ASSETS / ARCHIVE
    with arc.open("rb") as fh:
        for src in swtor.entries(arc):
            try:
                raw = swtor.read_block(fh, src)
            except Exception:
                continue
            if not swtor.is_model(raw):
                continue
            try:
                model = swtor.parse(raw)
            except Exception:
                continue
            if model.meshes and model.meshes[0].name == DONOR:
                return raw, model
    raise SystemExit(f"{DONOR} not found in {ARCHIVE}")


def ancestors(bone):
    seen = []
    while bone in PARENT:
        bone = PARENT[bone]
        seen.append(bone)
    return seen


def joints(pos, weights, bone_ids, names, chunk):
    """Every joint of the donor, measured two ways and preferring the surer one.

    Where the artist blended, the vertices carrying weight from a bone and one
    of its forebears sit on the joint between them, and that is the answer.
    Most of this droid is rigid armour with no blend at all, and there the
    joint is where the two shells come closest, taken as the mean of the
    nearest tenth. Checked against each other on the 20 joints that have both,
    the two agree to 42 mm on average.
    """
    shared = collections.defaultdict(list)
    for v in range(len(pos)):
        live = [bone_ids[v, k] for k in range(4) if weights[v, k] > 0.15]
        for a, b in itertools.combinations(live, 2):
            shared[frozenset((names[a], names[b]))].append(v)
    blended = {k: pos[v].mean(axis=0) for k, v in shared.items() if len(v) >= 6}

    out, how = {}, {}
    for bone in chunk:
        place = None
        for older in ancestors(bone):
            place = blended.get(frozenset((bone, older)))
            if place is not None:
                how[bone] = "blend"
                break
        if place is None:
            parent = PARENT.get(bone)
            if parent in chunk:
                child, other = chunk[bone], chunk[parent]
                gap = np.linalg.norm(child[:, None, :] - other[None, :, :], axis=2).min(axis=1)
                place = child[gap <= np.quantile(gap, 0.15)].mean(axis=0)
                how[bone] = "contact"
        if place is not None:
            out[bone] = place
    return out, how


def anchor_of(bones_here, joint):
    """The joint a whole host node hangs from: the highest one in the chain.

    A node can take several donor bones, the shoulder cap and the upper arm
    both going into `L_upper_arm`, and the part has to hang from the top of
    that run rather than from whichever bone carries the most geometry.
    """
    tops = [b for b in bones_here if PARENT.get(b) not in bones_here]
    for bone in sorted(tops, key=lambda b: len(ancestors(b))):
        if bone in joint:
            return bone, joint[bone]
    for bone in sorted(bones_here, key=lambda b: len(ancestors(b))):
        if bone in joint:
            return bone, joint[bone]
    return None, None


def widen_bounds(mdl, mdx):
    """Grow each mesh's stored box and radius to cover the geometry now in it.

    The engine culls and sorts by these, and vanilla never stores a box its own
    geometry leaves. A part rebuilt from a donor does, so the box is widened
    rather than recomputed: vanilla's own slack is deliberate and is kept, and
    nothing is ever made smaller.
    """
    out = bytearray(mdl)
    grown = []
    layout = kl.parse(bytes(out), mdx)
    for node in layout.nodes:
        if node.in_animation is not None or not node.is_mesh or not node.vertex_count:
            continue
        lo, hi, radius, average = kedit.bounds(layout, node)
        p = np.array(kedit.extract(layout, node).positions, dtype=float)
        new_lo = np.minimum(np.array(lo), p.min(axis=0))
        new_hi = np.maximum(np.array(hi), p.max(axis=0))
        new_r = max(radius, float(np.linalg.norm(p - np.array(average), axis=1).max()))
        if np.allclose(new_lo, lo) and np.allclose(new_hi, hi) and new_r <= radius:
            continue
        at = node.trimesh_at
        struct.pack_into("<3f", out, at + kedit.BBOX_MIN_AT, *new_lo)
        struct.pack_into("<3f", out, at + kedit.BBOX_MAX_AT, *new_hi)
        struct.pack_into("<f", out, at + kedit.RADIUS_AT, new_r)
        grown.append(node.name)
    return bytes(out), grown


def main(out_dir, align="joint"):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw, model = donor()
    info = model.meshes[0]
    found = swtor.mesh(raw, index=0, model=model)
    pos = np.array(found.positions)
    nrm = np.array(found.normals) if found.normals else None
    uvs = np.array(found.uvs) if found.uvs else None
    faces = np.array(found.faces)
    # A 180 degree yaw: the donor faces -y and KOTOR faces +y. A rotation, not
    # a mirror, so the winding and the authored normals survive it.
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
    joint, how = joints(pos, weights, bone_ids, names, chunk)

    want = []
    for tri in faces:
        votes = collections.Counter(MAP.get(names[dominant[v]]) for v in tri)
        votes.pop(None, None)
        want.append(votes.most_common(1)[0][0] if votes else None)
    by_node = collections.defaultdict(list)
    for i, node_name in enumerate(want):
        if node_name is not None:
            by_node[node_name].append(i)
    bones_per_node = collections.defaultdict(set)
    for bone, node_name in MAP.items():
        if bone in chunk:
            bones_per_node[node_name].add(bone)

    lib = klib.ModelLibrary(KOTOR)
    mdl, mdx = lib.read(HOST)
    host_layout = kl.parse(mdl, mdx)
    have = {n.name for n in host_layout.nodes if n.in_animation is None and n.is_mesh}
    missing = sorted(set(by_node) - have)
    if missing:
        raise SystemExit(f"the host has no node named {missing}")

    lines, moves = [], []
    for node_name in sorted(by_node, key=lambda k: -len(by_node[k])):
        tris = by_node[node_name]
        layout = kl.parse(mdl, mdx)
        node = layout.node_by_name(node_name)
        rest = ksp.rest_pose(layout)[node.index]
        rot = np.array(rest.rotation)

        shift = np.zeros(3)
        if align == "joint":
            anchor, place = anchor_of(bones_per_node[node_name], joint)
            if place is not None:
                shift = np.array(rest.position) - place
                moves.append((node_name, anchor, how.get(anchor, "-"),
                              float(np.linalg.norm(shift))))

        # One part's own vertices, renumbered from zero. A vertex on a seam is
        # written into both parts, which is how the host's own body is built.
        seen, p_local, n_local, uv_local, tri_local = {}, [], [], [], []
        for i in tris:
            face = []
            for v in faces[i]:
                if v not in seen:
                    seen[v] = len(p_local)
                    p_local.append(rest.to_local(tuple(pos[v] + shift)))
                    if nrm is not None:
                        n_local.append(tuple(rot.T @ nrm[v]))
                    if uvs is not None:
                        uv_local.append(tuple(uvs[v]))
                face.append(seen[v])
            tri_local.append(tuple(face))

        mesh = kobj.ObjMesh(name=node_name, positions=p_local, faces=tri_local,
                            uvs=uv_local, normals=n_local)
        geo, report = kswap.build_replacement(layout, node, mesh, facial_rig=False)
        mdl, mdx = kedit.replace_geometry(layout, node, geo, texture=TEXTURE)
        lines.append(f"{node_name:14s} {report.old_vertices:4d}v {report.old_triangles:4d}t "
                     f"-> {report.new_vertices:4d}v {report.new_triangles:4d}t")

    layout = kl.parse(mdl, mdx)
    leftover = sorted(have - set(by_node))
    mdl, hidden = kvis.hide_nodes(layout, mdl, leftover)
    mdl, grown = widen_bounds(mdl, mdx)

    (out_dir / f"{HOST}.mdl").write_bytes(mdl)
    (out_dir / f"{HOST}.mdx").write_bytes(mdx)
    print("\n".join(lines))
    print(f"\nnodes rebuilt: {len(by_node)}   triangles placed: "
          f"{sum(len(v) for v in by_node.values())} of {len(faces)}")
    print(f"hidden: {', '.join(hidden)}")
    print(f"bounds widened on {len(grown)} nodes")
    if moves:
        print(f"\nalign=joint moved {len(moves)} parts onto the host's own joints:")
        for node_name, anchor, source, far in sorted(moves, key=lambda m: -m[3]):
            print(f"   {node_name:14s} hangs from {anchor:18s} ({source:7s}) {far*100:5.1f} cm")


if __name__ == "__main__":
    main(sys.argv[1], align=sys.argv[2] if len(sys.argv) > 2 else "joint")
