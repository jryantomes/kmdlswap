"""Generate a custom head that satisfies docs/CUSTOM_HEAD_SPEC.md by construction.

A UV sphere is the right starting point precisely because of what the spec asks
for: it is closed, it is one piece, its winding is consistent, and it carries a
natural UV layout. Every hard criterion is then satisfied before any shaping
happens, and shaping only moves vertices - it never changes topology, so it
cannot break those properties.

The head is built in a canonical space (+Z up, face along -Y, which is where
KOTOR head nodes look in their own node space) and then mapped onto the target
node's extents, anchored at the chin. Anchoring the chin rather than the centre
matters: a taller head centred on the old one hangs into the shoulders.

    python tools/make_head.py --out packs/moldy_one --rings 13 --segments 22
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


# --- shaping ----------------------------------------------------------------


def smoothstep(edge0: float, edge1: float, x: float) -> float:
    """A 0-to-1 ramp between the edges, smooth at both ends.

    edge1 may be LESS than edge0, which gives a descending ramp - the snout,
    the jaw taper and the eye sockets are all written that way. An earlier
    version guarded `edge1 <= edge0` and returned 0, which silently disabled
    every one of them and produced a plain egg.
    """
    if edge0 == edge1:
        return 0.0
    t = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)


def shape(direction: tuple[float, float, float]) -> tuple[float, float, float]:
    """Turn a point on the unit sphere into a point on a head.

    Everything here is a radial scale of a sphere direction, so the result stays
    a closed single-piece surface no matter how the numbers are tuned.
    """
    x, y, z = direction
    front = -y                      # the face looks along -Y
    up = z
    centre = 1.0 - min(1.0, abs(x) / 0.55)   # 1 on the centre line, 0 at the sides

    # Narrow and deep rather than round - a sphere reads as an egg however it
    # is dented, so the base proportions have to do most of the work.
    rx, ry, rz = 0.68, 0.95, 1.0

    # Cranium swells above the eyes; the jaw draws in below them.
    taper = 1.0 - 0.34 * smoothstep(-0.05, -0.95, up)
    crown = 1.0 + 0.10 * smoothstep(0.10, 0.95, up)

    # A muzzle, not a bulge: pushed forward, and only near the centre line.
    snout = (
        0.46
        * smoothstep(0.10, 0.95, front)
        * smoothstep(0.50, -0.45, up)
        * (0.35 + 0.65 * centre)
    )

    # Chin, under the muzzle.
    chin = 0.12 * smoothstep(-0.35, -0.80, up) * smoothstep(0.25, 0.85, front) * centre

    # Brow ridge, a band above the sockets.
    brow = (
        0.09
        * smoothstep(0.40, 0.95, front)
        * smoothstep(0.08, 0.34, up)
        * (1.0 - smoothstep(0.34, 0.66, up))
    )

    # Two recessed eye sockets either side of the centre line.
    socket = 0.0
    for side in (-1.0, 1.0):
        d = math.dist((x, y, z), (side * 0.42, -0.78, 0.26))
        socket -= 0.17 * smoothstep(0.55, 0.0, d)

    # Cheek hollows, below and outside the sockets.
    for side in (-1.0, 1.0):
        d = math.dist((x, y, z), (side * 0.62, -0.55, -0.30))
        socket -= 0.07 * smoothstep(0.50, 0.0, d)

    # The back of the skull is flatter than a sphere.
    flat = -0.10 * smoothstep(0.30, 1.0, -front)

    r = taper * crown + snout + chin + brow + socket + flat
    return (x * rx * r, y * ry * r, z * rz * r)


def uv_sphere(rings: int, segments: int):
    """Positions, triangles and UVs for a closed sphere.

    Poles are single vertices, so there are no coincident duplicates and no
    boundary edges - the mesh is watertight by construction.
    """
    positions: list[tuple[float, float, float]] = []
    uvs: list[tuple[float, float]] = []

    def spherical_uv(x, y, z):
        # Put the face (-Y) in the middle of the texture.
        u = 0.5 + math.atan2(x, -y) / (2.0 * math.pi)
        v = 0.5 + math.asin(max(-1.0, min(1.0, z))) / math.pi
        return (u, v)

    top = len(positions)
    positions.append((0.0, 0.0, 1.0))
    uvs.append((0.5, 1.0))

    grid: list[list[int]] = []
    for r in range(1, rings):
        phi = math.pi * r / rings
        row = []
        for s in range(segments):
            theta = 2.0 * math.pi * s / segments
            d = (
                math.sin(phi) * math.sin(theta),
                -math.sin(phi) * math.cos(theta),
                math.cos(phi),
            )
            row.append(len(positions))
            positions.append(d)
            uvs.append(spherical_uv(*d))
        grid.append(row)

    bottom = len(positions)
    positions.append((0.0, 0.0, -1.0))
    uvs.append((0.5, 0.0))

    faces: list[tuple[int, int, int]] = []
    for s in range(segments):
        n = (s + 1) % segments
        faces.append((top, grid[0][n], grid[0][s]))
        faces.append((bottom, grid[-1][s], grid[-1][n]))
    for r in range(len(grid) - 1):
        for s in range(segments):
            n = (s + 1) % segments
            a, b = grid[r][s], grid[r][n]
            c, d = grid[r + 1][n], grid[r + 1][s]
            faces.append((a, b, c))
            faces.append((a, c, d))
    return positions, faces, uvs


def vertex_normals(positions, faces):
    acc = [[0.0, 0.0, 0.0] for _ in positions]
    for i0, i1, i2 in faces:
        p0, p1, p2 = positions[i0], positions[i1], positions[i2]
        u = [p1[i] - p0[i] for i in range(3)]
        v = [p2[i] - p0[i] for i in range(3)]
        n = (
            u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0],
        )
        for i in (i0, i1, i2):
            for k in range(3):
                acc[i][k] += n[k]
    out = []
    for n in acc:
        length = math.sqrt(sum(c * c for c in n))
        out.append(tuple(c / length for c in n) if length > 1e-12 else (0.0, 0.0, 1.0))
    return out


def fit_to(positions, size, centre, anchor="chin"):
    """Scale uniformly into `size` and place at `centre`, chin-anchored."""
    lo = [min(p[i] for p in positions) for i in range(3)]
    hi = [max(p[i] for p in positions) for i in range(3)]
    span = [hi[i] - lo[i] for i in range(3)]
    factor = min(size[i] / span[i] for i in range(3) if span[i] > 1e-9)
    mid = [(hi[i] + lo[i]) / 2 for i in range(3)]

    moved = [
        tuple(centre[i] + (p[i] - mid[i]) * factor for i in range(3)) for p in positions
    ]
    if anchor == "chin":
        bottom = min(p[2] for p in moved)
        want = centre[2] - size[2] / 2
        moved = [(p[0], p[1], p[2] + (want - bottom)) for p in moved]
    return moved


# --- texture ----------------------------------------------------------------


def write_texture(path: Path, size: int = 256) -> None:
    """A face painted where the UVs put it: eyes at the eyeline, mouth below."""
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (size, size), (150, 143, 122))
    d = ImageDraw.Draw(im)

    for y in range(size):
        # v runs 0 at the chin to 1 at the crown; darken towards the top.
        t = y / (size - 1)
        shade = int(150 - 26 * (1.0 - t))
        d.line([(0, y), (size, y)], fill=(shade, shade - 6, shade - 24))

    cx = size // 2                      # the face sits at u = 0.5
    eye_y = int(size * (1.0 - 0.66))    # v ~ 0.66 is the eyeline
    for side in (-1, 1):
        ex = cx + side * int(size * 0.085)
        d.ellipse([ex - 20, eye_y - 15, ex + 20, eye_y + 15], fill=(38, 34, 30))
        d.ellipse([ex - 12, eye_y - 9, ex + 12, eye_y + 9], fill=(196, 158, 62))
        d.ellipse([ex - 5, eye_y - 5, ex + 5, eye_y + 5], fill=(20, 18, 16))

    mouth_y = int(size * (1.0 - 0.40))
    d.line([(cx - 34, mouth_y), (cx + 34, mouth_y)], fill=(58, 46, 40), width=5)
    for i in range(-3, 4):
        x = cx + i * 11
        d.line([(x, mouth_y - 6), (x, mouth_y + 6)], fill=(58, 46, 40), width=2)

    brow_y = eye_y - 30
    for side in (-1, 1):
        ex = cx + side * int(size * 0.085)
        d.line([(ex - 24, brow_y + side * 2), (ex + 24, brow_y - side * 2)],
               fill=(96, 88, 74), width=6)

    im.save(path, format="TGA", compression=None)


# --- output -----------------------------------------------------------------


def write_obj(path: Path, positions, faces, uvs, normals, name: str) -> None:
    lines = [f"# {name} - generated by tools/make_head.py", f"o {name}"]
    lines += [f"v {p[0]:.9g} {p[1]:.9g} {p[2]:.9g}" for p in positions]
    lines += [f"vt {t[0]:.9g} {t[1]:.9g}" for t in uvs]
    lines += [f"vn {n[0]:.9g} {n[1]:.9g} {n[2]:.9g}" for n in normals]
    for a, b, c in faces:
        lines.append(f"f {a+1}/{a+1}/{a+1} {b+1}/{b+1}/{b+1} {c+1}/{c+1}/{c+1}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="pack folder to create")
    ap.add_argument("--name", default="Moldy One")
    ap.add_argument("--rings", type=int, default=13)
    ap.add_argument("--segments", type=int, default=22)
    ap.add_argument("--install", help="fit to a node in this install")
    ap.add_argument("--host", default="p_hk47")
    ap.add_argument("--node", default="head")
    ap.add_argument("--texture", default="moldyone")
    args = ap.parse_args(argv)

    directions, faces, uvs = uv_sphere(args.rings, args.segments)
    positions = [shape(d) for d in directions]

    size = centre = None
    if args.install:
        from kmdlfun.library import ModelLibrary
        from kmdlswap import edit as ke
        from kmdlswap import layout as kl

        lib = ModelLibrary(args.install)
        layout = kl.parse(*lib.read(args.host))
        node = layout.node_by_name(args.node)
        geo = ke.extract(layout, node)
        lo = [min(p[i] for p in geo.positions) for i in range(3)]
        hi = [max(p[i] for p in geo.positions) for i in range(3)]
        size = [hi[i] - lo[i] for i in range(3)]
        centre = [(hi[i] + lo[i]) / 2 for i in range(3)]
        positions = fit_to(positions, size, centre)

    normals = vertex_normals(positions, faces)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    write_obj(out / "head.obj", positions, faces, uvs, normals, args.name)
    write_texture(out / f"{args.texture}.tga")
    (out / "head.json").write_text(
        json.dumps(
            {
                "name": args.name,
                "author": "tools/make_head.py",
                "notes": "parametric head: a UV sphere shaped by radial falloffs, "
                         "so it is closed and one piece by construction",
                "target": args.node,
                "facing": "-y",
                "scale": 1.0,
                "anchor": "chin",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    lo = [min(p[i] for p in positions) for i in range(3)]
    hi = [max(p[i] for p in positions) for i in range(3)]
    print(f"{args.name} -> {out}")
    print(f"  {len(positions)} vertices, {len(faces)} triangles")
    print(f"  size {hi[0]-lo[0]:.3f} x {hi[1]-lo[1]:.3f} x {hi[2]-lo[2]:.3f}")
    if size:
        print(f"  target {size[0]:.3f} x {size[1]:.3f} x {size[2]:.3f}"
              f" ({args.host}:{args.node})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
