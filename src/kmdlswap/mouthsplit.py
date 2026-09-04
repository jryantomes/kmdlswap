"""Parting a closed face along its lip line, without removing anything.

A head converted from another game arrives with its mouth modelled shut. Jade
Empire's ``h_common01_`` is a closed shell with the head's own teeth and mouth
interior behind it - the two 14-vertex pieces sample the teeth strip of its
atlas (u 0.012-0.182, v 0.015-0.071) and the 11-vertex bag samples the interior
patch (u 0.879-0.982, v 0.831-0.972). None of it can be seen, because the face
in front is continuous: the welded shell has no boundary edge anywhere near the
mouth.

Weighting that shell to stretch is necessary and not sufficient. A KOTOR mouth
opens by stretching *because the skin that stretches is UV-mapped to the mouth
interior painted there*; this one is mapped to skin, so it smears.

**Cutting faces away is not the answer either.** Triangles near the mouth
average 0.0067 tall and a mouth line wants to be a fraction of that. Deleting
whole faces leaves a hole several times too big and shaped like a triangle - in
game, a top lip cut into triangles with teeth showing through.

So the face is **split**, and nothing is deleted. The vertices along the lip
line are duplicated, the faces above are pointed at the copies, and the two
halves sit on identical coordinates: invisible at rest, no gap, no jagged edge.
Weighted apart they part, and the teeth and interior behind become visible.

**The line is cut first, because the mesh has no line to split along.** Splitting
only at existing vertices gave twelve points across the whole mouth, and twelve
points on geometry this coarse open into a row of triangles rather than a mouth
- reported from the game as "two little triangles you can see through to the
teeth", visible only while talking, which is exactly what an opening seam of
twelve points looks like. So every edge crossing the lip line inside the mouth
is subdivided at the crossing, putting a vertex exactly on the line, and the
split then follows a continuous polyline.

**Cut by edge, not by face**, or the subdivision leaves T-junctions where a cut
face meets an uncut neighbour, and a T-junction is a crack. Every face using a
subdivided edge is retriangulated, whether or not it was inside the mouth box.

**The corners stay joined.** Only a vertex whose every face lies inside the mouth
box is duplicated. One that also touches a face outside anchors the end of the
slit, which keeps the split from running away across the cheek - the failure
that tore a seam right around the skull once already. The box is 1.0x the
teeth's own half-width; at 1.6x the split ran past the lips and parted the
cheek, rendering as a dark slash out to either side of the face.
"""

from __future__ import annotations

import collections

import numpy as np

# How far above and below the lip line to look, as a multiple of the distance
# between the teeth pieces.
BAND = 1.2

# How wide the split may run, as a multiple of the teeth's own half-width. The
# mouth ends where the teeth end; reaching past them parts the cheek instead.
WIDTH = 1.0


def _box(positions, upper_piece, lower_piece, *, band: float = BAND):
    """(centre_x, centre_z, half_x, half_z) around the mouth, from the teeth."""
    P = np.asarray([p[:3] for p in positions], dtype=np.float64)
    rim = P[sorted(set(upper_piece) | set(lower_piece))]
    return (
        float(rim[:, 0].min() + rim[:, 0].max()) / 2,
        float(rim[:, 2].min() + rim[:, 2].max()) / 2,
        float(rim[:, 0].max() - rim[:, 0].min()) / 2 * WIDTH,
        float(rim[:, 2].max() - rim[:, 2].min()) / 2 * band,
    )


def _lerp(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(len(a)))


def cut_along_line(mesh, box) -> int:
    """Put a vertex exactly on the lip line wherever an edge crosses it.

    Returns how many were added. Works edge-first: an edge is subdivided only if
    its crossing point falls inside the mouth, and then *every* face using that
    edge is retriangulated, so a cut face never meets an uncut neighbour.
    """
    centre_x, centre_z, half_x, half_z = box
    P = [tuple(p[:3]) for p in mesh.positions]
    faces = [tuple(f)[:3] for f in mesh.faces]
    if not faces:
        return 0
    lo = np.asarray(P, dtype=np.float64).min(axis=0)
    hi = np.asarray(P, dtype=np.float64).max(axis=0)
    mid_y = (lo[1] + hi[1]) / 2
    eps = max(half_z * 0.02, 1e-7)

    has_uvs = mesh.has_uvs
    has_normals = mesh.has_normals
    materials = list(mesh.materials) if mesh.materials else []

    def side(v):
        z = P[v][2]
        if z > centre_z + eps:
            return 1
        if z < centre_z - eps:
            return -1
        return 0

    # Which edges to cut: crossing the line, and crossing it inside the mouth.
    cut_at: dict[tuple[int, int], int] = {}
    for f in faces:
        for a, b in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])):
            key = (a, b) if a < b else (b, a)
            if key in cut_at or side(a) * side(b) >= 0:
                continue
            za, zb = P[a][2], P[b][2]
            t = (centre_z - za) / (zb - za)
            point = _lerp(P[a], P[b], t)
            if abs(point[0] - centre_x) > half_x or point[1] <= mid_y:
                continue
            index = len(mesh.positions)
            mesh.positions.append(point)
            if has_uvs:
                mesh.uvs.append(_lerp(mesh.uvs[a], mesh.uvs[b], t))
            if has_normals:
                mesh.normals.append(_lerp(mesh.normals[a], mesh.normals[b], t))
            P.append(point)
            cut_at[key] = index

    if not cut_at:
        return 0

    out_faces: list[tuple[int, int, int]] = []
    out_materials: list[int] = []
    for index, f in enumerate(faces):
        material = materials[index] if index < len(materials) else None
        edges = [(f[0], f[1]), (f[1], f[2]), (f[2], f[0])]
        marks = [cut_at.get((a, b) if a < b else (b, a)) for a, b in edges]
        pieces = []
        if sum(m is not None for m in marks) == 2:
            # The lone corner is the one whose two edges are both cut.
            k = next(i for i in range(3) if marks[i] is not None
                     and marks[(i + 2) % 3] is not None)
            apex = f[k]
            m_in, m_out = marks[(i_out := (k + 2) % 3)], marks[k]
            other_a, other_b = f[(k + 1) % 3], f[(k + 2) % 3]
            pieces = [
                (apex, m_out, m_in),
                (m_out, other_a, other_b),
                (m_out, other_b, m_in),
            ]
        elif sum(m is not None for m in marks) == 1:
            # One edge cut: the opposite corner joins the new point.
            k = next(i for i in range(3) if marks[i] is not None)
            a, b = edges[k]
            c = f[(k + 2) % 3]
            pieces = [(a, marks[k], c), (marks[k], b, c)]
        else:
            pieces = [f]
        for piece in pieces:
            if len(set(piece)) == 3:
                out_faces.append(piece)
                if materials:
                    out_materials.append(material if material is not None else 0)

    mesh.faces = out_faces
    if materials:
        mesh.materials = out_materials
    return len(cut_at)


def split(mesh, upper_piece, lower_piece) -> tuple[list[int], list[int], list[str]]:
    """Part ``mesh`` along its lip line, in place. Returns (upper, lower, lines).

    ``upper_piece`` and ``lower_piece`` are the head's own teeth, which say
    where the mouth is. Nothing is removed and no existing position changes, so
    the result renders identically until the two sides are weighted apart.
    """
    P0 = np.asarray([p[:3] for p in mesh.positions], dtype=np.float64)
    if len(P0) < 8 or not mesh.faces:
        return [], [], []

    box = _box(mesh.positions, upper_piece, lower_piece)
    added = cut_along_line(mesh, box)

    centre_x, centre_z, half_x, half_z = box
    P = np.asarray([p[:3] for p in mesh.positions], dtype=np.float64)
    faces = [tuple(f)[:3] for f in mesh.faces]
    lo, hi = P.min(axis=0), P.max(axis=0)
    mid_y = (lo[1] + hi[1]) / 2

    centres = np.array([P[list(f)].mean(axis=0) for f in faces])
    inside = [
        i
        for i, c in enumerate(centres)
        if c[1] > mid_y
        and abs(c[0] - centre_x) <= half_x
        and abs(c[2] - centre_z) <= half_z
    ]
    if not inside:
        return [], [], []
    above = {i for i in inside if centres[i][2] > centre_z}
    below = {i for i in inside if centres[i][2] <= centre_z}
    if not above or not below:
        return [], [], []

    touches: dict[int, list[int]] = collections.defaultdict(list)
    for i, f in enumerate(faces):
        for v in f:
            touches[v].append(i)

    inside_set = set(inside)
    seam = [
        v
        for v, fs in touches.items()
        if any(i in above for i in fs)
        and any(i in below for i in fs)
        and all(i in inside_set for i in fs)
    ]
    if not seam:
        return [], [], []

    has_uvs = mesh.has_uvs
    has_normals = mesh.has_normals
    copy_of: dict[int, int] = {}
    for v in sorted(seam):
        copy_of[v] = len(mesh.positions)
        mesh.positions.append(tuple(mesh.positions[v]))
        if has_uvs:
            mesh.uvs.append(tuple(mesh.uvs[v]))
        if has_normals:
            mesh.normals.append(tuple(mesh.normals[v]))

    for i in above:
        mesh.faces[i] = tuple(copy_of.get(v, v) for v in faces[i])

    upper = sorted(copy_of.values())
    lower = sorted(copy_of)
    return upper, lower, [
        f"mouth split: cut {added} new points onto the lip line and parted the "
        f"face along it, {len(upper)} vertices duplicated (nothing removed)"
    ]
