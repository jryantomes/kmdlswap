"""Generating a head parametrically.

A UV sphere is the right starting point for exactly the reasons the acceptance
criteria list: it is closed, it is one piece, its winding is consistent, and it
carries a natural UV layout. Shaping is then purely radial - it moves vertices
and never touches topology - so a shaped sphere cannot fail those checks however
the numbers are tuned.

The head is built in a canonical space: +Z up, face along -Y, which is where a
KOTOR head node looks in its own node space.

This lives in the package rather than in tools/ so the test suite can generate a
known-good head on demand instead of committing one.
"""

from __future__ import annotations

import json
import math
from pathlib import Path


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

    # Wound outward. This was inward until 2026-08-30, which means every head
    # this module ever generated was inside out: the engine draws front faces
    # only, so it would have rendered hollow. Nothing caught it because the
    # previewer is two-sided by design and the topology checks - one piece,
    # closed, degenerate - are all blind to which way a surface faces. The
    # `solid` check in headspec exists now, and found this on its first run.
    faces: list[tuple[int, int, int]] = []
    for s in range(segments):
        n = (s + 1) % segments
        faces.append((top, grid[0][s], grid[0][n]))
        faces.append((bottom, grid[-1][n], grid[-1][s]))
    for r in range(len(grid) - 1):
        for s in range(segments):
            n = (s + 1) % segments
            a, b = grid[r][s], grid[r][n]
            c, d = grid[r + 1][n], grid[r + 1][s]
            faces.append((a, c, b))
            faces.append((a, d, c))
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


def place_at(positions, size, centre, anchor="chin"):
    """Move a mesh onto the node without changing its size.

    Placing and resizing are different jobs and were one function, which meant
    a head could not be put where it belongs without also being rescaled to the
    node's box. That rescale is by the *tightest* axis, so a head fractionally
    wider than the host's loses height everywhere: measured on a Jade head onto
    Carth, the width ratio of 0.980 bound and cost 9% of the height - visible in
    game as a head that sits slightly too small.

    Anything converted from a game with a known scale already arrives the right
    size, and resizing it can only make it wrong.
    """
    lo = [min(p[i] for p in positions) for i in range(3)]
    hi = [max(p[i] for p in positions) for i in range(3)]
    mid = [(hi[i] + lo[i]) / 2 for i in range(3)]

    moved = [tuple(centre[i] + (p[i] - mid[i]) for i in range(3))
             for p in positions]
    if anchor == "chin":
        bottom = min(p[2] for p in moved)
        want = centre[2] - size[2] / 2
        moved = [(p[0], p[1], p[2] + (want - bottom)) for p in moved]
    return moved


def fit_to(positions, size, centre, anchor="chin"):
    """Scale uniformly into `size` and place at `centre`, chin-anchored.

    The scale is by the tightest axis, which keeps the head inside the node's
    box at the cost of shrinking it whenever the proportions differ. Right for
    a sculpt or a scan arriving at an arbitrary size; wrong for anything that
    already knows how big it should be - see `place_at`.
    """
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


def build_pack(
    out: str | Path,
    *,
    name: str = "Moldy One",
    rings: int = 13,
    segments: int = 22,
    texture: str = "moldyone",
    size: tuple[float, float, float] | None = None,
    centre: tuple[float, float, float] | None = None,
) -> Path:
    """Write a complete head pack: mesh, texture and manifest."""
    directions, faces, uvs = uv_sphere(rings, segments)
    positions = [shape(d) for d in directions]
    if size and centre:
        positions = fit_to(positions, size, centre)
    normals = vertex_normals(positions, faces)

    root = Path(out)
    root.mkdir(parents=True, exist_ok=True)
    write_obj(root / "head.obj", positions, faces, uvs, normals, name)
    write_texture(root / f"{texture}.tga")
    (root / "head.json").write_text(
        json.dumps(
            {
                "name": name,
                "author": "kmdlfun.headgen",
                "notes": "parametric head: a UV sphere shaped by radial falloffs, "
                         "so it is closed and one piece by construction",
                "target": "head",
                "facing": "-y",
                "scale": 1.0,
                "anchor": "chin",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return root


# Rotation about Z that brings a mesh's stated facing round to -Y, which is
# where a KOTOR head node looks in its own space.
# Which way a mesh must turn about Z to face the game's forward.
#
# KOTOR characters face +Y (reports/FACING_FINDINGS.md). This table used to make
# "-y" the identity, which quietly asserted the opposite: a pack that correctly
# declared "+y" was spun 180 degrees to face backwards. Default is now "+y",
# which is still a zero rotation, so a mesh already authored facing the camera
# behaves exactly as before - only the labels now mean what they say.
FACING_TO_DEGREES = {"+y": 0.0, "-y": 180.0, "+x": 90.0, "-x": -90.0}


def orient(positions, facing: str = "+y", up: str = "z"):
    """Rotate a mesh from its own convention into the node's.

    `up` handles the other common mismatch: many tools export Y-up, where KOTOR
    is Z-up, and a head exported that way arrives lying on its back.

    All three axes are handled. `x` used to fall through silently, so a pack
    declaring it was quietly treated as already Z-up - the manifest accepted a
    value the code ignored, which is worse than rejecting it, because the head
    then merely comes out the wrong size and nothing says why.

    Both rotations have determinant +1. A reflection would map the axis just as
    well and turn the head inside out.
    """
    out = list(positions)
    axis = up.lower()
    if axis == "y":
        out = [(x, -z, y) for (x, y, z) in out]
    elif axis == "x":
        out = [(-z, y, x) for (x, y, z) in out]
    degrees = FACING_TO_DEGREES.get(facing.lower(), 0.0)
    if degrees:
        a = math.radians(degrees)
        ca, sa = math.cos(a), math.sin(a)
        out = [(x * ca - y * sa, x * sa + y * ca, z) for (x, y, z) in out]
    return out
