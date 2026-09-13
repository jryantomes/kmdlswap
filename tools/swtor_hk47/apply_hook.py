"""Apply a grip_opt result to a copy of a build: move and turn the rhand hook.

A node's rest position and orientation each live twice, in the node header and
in a single-key controller, and the engine reads the controller. Both are
written, position through mouthparts' helper and orientation here. The header
stores its quaternion w first; the controller stores x, y, z, w.

usage: apply_hook.py <source build> <out build> <grip_opt json>
"""
import json
import shutil
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, r"C:\Users\jryan\mdl swap\src")
sys.path.insert(0, str(Path(__file__).parent))
from pose_render import BASE, ORIENTATION, header_order
from kmdlfun.mouthparts import _shift_position_controller
from kmdlswap import layout as kl, validate as kval
from kmdlswap.nodes import CONTROLLER_SIZE


def set_orientation(mdl, lay, node, q_xyzw):
    order = header_order(bytes(mdl), lay)
    x, y, z, w = (float(v) for v in q_xyzw)
    head = (x, y, z, w) if order == "xyzw" else (w, x, y, z)
    at = BASE + node.offset
    struct.pack_into("<4f", mdl, at + 28, *head)
    carr, ccount = struct.unpack_from("<II", mdl, at + 56)
    dat, dlen = struct.unpack_from("<II", mdl, at + 68)
    written = False
    for i in range(ccount if dlen else 0):
        entry = BASE + carr + i * CONTROLLER_SIZE
        typ, _u, rows, tix, dix, cols = struct.unpack_from("<IHHHHB", mdl, entry)
        if typ != ORIENTATION or (cols & 0x0F) != 4:
            continue
        for r in range(rows):
            struct.pack_into("<4f", mdl, BASE + dat + (dix + r * 4) * 4, x, y, z, w)
        written = True
    return written


def main(src, dst, spec):
    src, dst = Path(src), Path(dst)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    fit = json.loads(Path(spec).read_text())
    mdl = bytearray((dst / "p_hk47.mdl").read_bytes())
    mdx = (dst / "p_hk47.mdx").read_bytes()
    lay = kl.parse(bytes(mdl), mdx)
    hook = lay.node_by_name("rhand")
    _shift_position_controller(mdl, hook, tuple(fit["position_delta_in_hand_frame"]))
    had_controller = set_orientation(mdl, lay, hook, fit["local_quaternion_xyzw"])
    (dst / "p_hk47.mdl").write_bytes(bytes(mdl))
    report = kval.check(kl.parse(bytes(mdl), mdx))
    ok = report.identity_mdl and report.identity_mdx and not report.gaps and not report.overlaps and not report.dangling
    print(f"rhand: slide {fit['slide_m']*100:+.1f} cm, tilt {fit['tilt_deg']} deg; "
          f"orientation controller {'written' if had_controller else 'absent, header only'}; valid {ok}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
