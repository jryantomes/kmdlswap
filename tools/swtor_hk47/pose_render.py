"""Draw a built p_hk47 in a frame of one of its own animations.

Orientation keys replace a node's rest orientation. Every limb and torso
position key in this model is zero, so rest positions stand as they are. The
frame drawn is the one where the focus node has turned furthest from its first
key: InnerTorso by default, which is where a torn waist shows worst.

usage: pose_render.py <build folder> <animation> <output png> [focus node]
"""
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, r"C:\Users\jryan\mdl swap\src")
from kmdlfun import render as krender
from kmdlswap import layout as kl
from kmdlswap.nodes import CONTROLLER_SIZE
from PIL import Image

BASE = 12
POSITION, ORIENTATION = 8, 20

# Where to frame the close row, by focus node.
CLOSE_UPS = {
    "InnerTorso": (np.array([0.0, 0.0, 1.35]), 0.40),
    "Fore_body": (np.array([0.0, 0.0, 1.35]), 0.40),
    "Pelvis": (np.array([0.0, 0.0, 1.20]), 0.40),
    "Neck": (np.array([0.0, 0.0, 1.82]), 0.24),
    "head": (np.array([0.0, 0.0, 1.82]), 0.24),
}


def controllers(mdl, node):
    at = BASE + node.offset
    carr, ccount = struct.unpack_from("<II", mdl, at + 56)
    dat, dlen = struct.unpack_from("<II", mdl, at + 68)
    if not ccount or not dlen:
        return
    data = np.frombuffer(mdl, np.float32, dlen, BASE + dat)
    for i in range(ccount):
        typ, _u, rows, tix, dix, cols = struct.unpack_from("<IHHHHB", mdl, BASE + carr + i * CONTROLLER_SIZE)
        ncol = cols & 0x0F
        times = data[tix: tix + rows]
        values = data[dix: dix + rows * ncol].reshape(rows, ncol) if ncol else None
        yield typ, times, values, ncol


def header_order(mdl, lay):
    """Is the header quaternion stored w first, like the controller's last column?"""
    for n in lay.nodes:
        if n.in_animation is not None:
            continue
        head = np.array(struct.unpack_from("<4f", mdl, BASE + n.offset + 28))
        for typ, _t, vals, ncol in controllers(mdl, n):
            if typ != ORIENTATION or ncol != 4:
                continue
            c = vals[0]
            if abs(c[3]) > 0.999:
                break  # identity tells us nothing
            if np.allclose(head, c, atol=1e-4) or np.allclose(head, -c, atol=1e-4):
                return "xyzw"
            w_first = np.array([c[3], c[0], c[1], c[2]])
            if np.allclose(head, w_first, atol=1e-4) or np.allclose(head, -w_first, atol=1e-4):
                return "wxyz"
    raise SystemExit("could not tell the header's quaternion order")


def main(folder, anim, out, focus="InnerTorso"):
    folder = Path(folder)
    mdl = (folder / "p_hk47.mdl").read_bytes()
    mdx = (folder / "p_hk47.mdx").read_bytes()
    lay = kl.parse(mdl, mdx)
    order = header_order(mdl, lay)

    tracks = {}
    skipped = 0
    for n in lay.nodes:
        if n.in_animation != anim:
            continue
        for typ, times, vals, ncol in controllers(mdl, n):
            if typ != ORIENTATION:
                continue
            if ncol != 4:
                skipped += 1
                continue
            q = vals / np.linalg.norm(vals, axis=1, keepdims=True)
            tracks[n.name] = (times, q)
    if focus not in tracks:
        raise SystemExit(f"{anim} has no {focus} orientation track")
    t_in, q_in = tracks[focus]
    k = int(np.argmin(np.abs(q_in @ q_in[0])))
    moment = float(t_in[k])

    posed = bytearray(mdl)
    geometry = {n.name: n for n in lay.nodes if n.in_animation is None}
    for name, (times, q) in tracks.items():
        if name not in geometry:
            continue
        j = int(np.argmin(np.abs(times - moment)))
        x, y, z, w = (float(v) for v in q[j])
        values = (x, y, z, w) if order == "xyzw" else (w, x, y, z)
        struct.pack_into("<4f", posed, BASE + geometry[name].offset + 28, *values)

    posed_lay = kl.parse(bytes(posed), mdx)
    tex_path = folder / "tor_hk47.tga"
    tex = np.asarray(Image.open(tex_path).convert("RGB")) if tex_path.exists() else None
    look = (lambda n: tex if n.lower() == "tor_hk47" else None) if tex is not None else None
    textured = krender.from_layout(posed_lay, texture_lookup=look)
    flat = krender.from_layout(posed_lay)

    whole = krender.shared_bounds([flat])
    close = CLOSE_UPS.get(focus, CLOSE_UPS["InnerTorso"])
    rows = [
        np.concatenate([krender.render(textured, yaw=y, size=380, bounds=whole) for y in (0, 90, 180, 270)], axis=1),
        np.concatenate([krender.render(flat, yaw=y, size=380, bounds=close) for y in (0, 90, 180, 270)], axis=1),
    ]
    Image.fromarray(np.concatenate(rows, axis=0)).save(out)
    swing = 2 * np.degrees(np.arccos(min(1, abs(float(q_in[k] @ q_in[0])))))
    print(f"{anim}: frame at t={moment:.3f}, {focus} {swing:.1f} deg from its first key; "
          f"{len(tracks)} nodes posed, {skipped} compressed tracks skipped; header order {order}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], *(sys.argv[4:5]))
