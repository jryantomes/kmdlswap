"""Where every joint of the donor sits, by two independent measurements.

A joint shows up twice in a skinned mesh. Where the artist blended, the
vertices carrying weight from both bones sit on it. Where the armour is rigid,
and on this droid most of it is, there is no blend at all, and the joint is
instead where the two shells come closest to touching.

The second method is checked against the first on every joint that has both.
"""
import sys, collections, itertools
import numpy as np
sys.path.insert(0, r"C:\Users\jryan\mdl swap\src")
from kmdlfun import swtor
from pathlib import Path

A = Path(r"E:/SteamLibrary/steamapps/common/Star Wars - The Old Republic/Assets")

# The chain, read off the bone names. Standard biped: a pelvis, a spine of
# four, a neck of two, and four bones per limb.
PARENT = {
    "Pelvis": "Root", "LowerBack": "Root", "Chest": "LowerBack",
    "Chest1": "Chest", "Chest2": "Chest1", "Neck": "Chest2",
    "Neck1": "Neck", "Head": "Neck1",
}
for side in ("Left", "Right"):
    PARENT.update({
        f"{side}Hip": "Root", f"{side}Knee": f"{side}Hip",
        f"{side}Ankle": f"{side}Knee", f"{side}Toe": f"{side}Ankle",
        f"{side}Collar": "Chest2", f"{side}Shoulder": f"{side}Collar",
        f"{side}Elbow": f"{side}Shoulder", f"{side}Wrist": f"{side}Elbow",
        f"{side}ThumbFinger": f"{side}Wrist",
        f"{side}IndexFinger": f"{side}Wrist",
        f"{side}IndexFinger1": f"{side}IndexFinger",
        f"{side}IndexFinger2": f"{side}IndexFinger1",
        f"{side}MiddleFinger": f"{side}Wrist",
        f"{side}MiddleFinger1": f"{side}MiddleFinger",
        f"{side}MiddleFinger2": f"{side}MiddleFinger1",
    })


def load(name, archive="swtor_main_art_creature_a_1.tor"):
    arc = A / archive
    with arc.open("rb") as fh:
        for src in swtor.entries(arc):
            try: raw = swtor.read_block(fh, src)
            except Exception: continue
            if not swtor.is_model(raw): continue
            try: model = swtor.parse(raw)
            except Exception: continue
            if model.meshes and model.meshes[0].name == name:
                return raw, model
    raise SystemExit(name)


def blended_joints(pos, weights, bones, names, floor=0.15):
    """Joints the artist blended across, from vertices two bones share."""
    out = collections.defaultdict(list)
    for v in range(len(pos)):
        live = [(bones[v, k], weights[v, k]) for k in range(4) if weights[v, k] > floor]
        for (a, _), (b, _) in itertools.combinations(live, 2):
            out[frozenset((names[a], names[b]))].append(v)
    return {k: pos[v].mean(axis=0) for k, v in out.items() if len(v) >= 6}


def contact_joint(child, parent, keep=0.15):
    """Where two rigid shells come closest, as the mean of the closest tenth."""
    d = np.linalg.norm(child[:, None, :] - parent[None, :, :], axis=2).min(axis=1)
    cut = np.quantile(d, keep)
    return child[d <= cut].mean(axis=0), float(d.min())


def main():
    raw, model = load("assassin_hk47_a01")
    info = model.meshes[0]
    found = swtor.mesh(raw, index=0, model=model)
    pos = np.array(found.positions); pos[:, :2] *= -1
    buf = np.frombuffer(raw, np.uint8, info.vertices * info.vertex_size,
                        info.vertices_at).reshape(info.vertices, info.vertex_size)
    weights = buf[:, 12:16].astype(float) / 255.0
    bones = buf[:, 16:20].astype(int)
    names = np.array(info.bones, dtype=object)
    dominant = np.take_along_axis(bones, weights.argmax(axis=1)[:, None], 1).ravel()

    blended = blended_joints(pos, weights, bones, names)
    chunk = {b: pos[dominant == i] for i, b in enumerate(names) if (dominant == i).any()}

    print(f"{'joint':24s} {'contact estimate':>24s} {'blend truth':>24s} {'apart':>7s}")
    agree = []
    out = {}
    for child, parent in PARENT.items():
        if child not in chunk or parent not in chunk:
            continue
        c, gap = contact_joint(chunk[child], chunk[parent])
        out[child] = c
        truth = blended.get(frozenset((child, parent)))
        if truth is not None:
            d = float(np.linalg.norm(c - truth))
            agree.append(d)
            print(f"{child:24s} {str(c.round(3)):>24s} {str(truth.round(3)):>24s} {d:7.3f}")
        else:
            print(f"{child:24s} {str(c.round(3)):>24s} {'-':>24s} {'':>7s}")
    if agree:
        print(f"\nthe two agree to {np.mean(agree):.3f} m on average over "
              f"{len(agree)} joints, worst {max(agree):.3f}")
    np.save(sys.argv[1], out, allow_pickle=True)


main()
