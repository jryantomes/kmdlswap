"""Parting a closed face along its lip line, without removing anything.

A head converted from another game arrives with its mouth modelled shut. Jade
Empire's ``h_common01_`` is a closed shell with the head's own teeth and mouth
interior sitting behind it - the two 14-vertex pieces sample the teeth strip of
its atlas (u 0.012-0.182, v 0.015-0.071) and the 11-vertex bag samples the
interior patch (u 0.879-0.982, v 0.831-0.972). None of it can be seen, because
the face in front is continuous: the welded shell has no boundary edge anywhere
near the mouth.

Weighting that shell to stretch is necessary and not sufficient. A KOTOR mouth
opens by stretching *because the skin that stretches is UV-mapped to the mouth
interior painted there*; this one is mapped to skin, so it smears.

**Cutting is not the answer either.** Triangles near the mouth average 0.0067
tall and a mouth line wants to be a fraction of that. Deleting whole faces
leaves a hole several times too big and shaped like a triangle - in game, a top
lip cut into triangles with teeth showing through.

So the face is **split** instead, and nothing is deleted. The vertices along the
lip line are duplicated, the faces above the line are pointed at the copies, and
the two halves then sit on identical coordinates: invisible at rest, no gap, no
jagged edge. Weighted apart - the upper copies lifting, the lower dropping -
they part, and the teeth and interior behind become visible. That is the
zero-width aperture an earlier pass wrongly believed was already in the mesh.

**Splitting by plane rather than by row.** The rows of vertices near the lip
line are ragged - scattered over 0.008 in z with two to twelve vertices apiece -
so there is no clean loop to walk. Classifying *faces* against a plane and
duplicating the vertices that end up on both sides follows the existing edges
wherever they happen to run, and needs no such loop.

**The corners stay joined.** Only a vertex whose every face lies inside the
mouth box is duplicated. One that also touches a face outside it anchors the end
of the slit, which is what keeps the split from running away across the cheek -
the failure that tore a seam right around the skull once already.
"""

from __future__ import annotations

import collections

import numpy as np

# How far above and below the lip line to look, as a multiple of the distance
# between the teeth pieces. The split only needs the faces that meet at the
# line; reaching further just risks the cheeks.
BAND = 1.2

# How wide the split may run, as a multiple of the teeth's own half-width. The
# mouth ends where the teeth end; reaching past them parts the cheek instead,
# which renders as a dark slash running out to either side of the face.
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


def split(mesh, upper_piece, lower_piece) -> tuple[list[int], list[int], list[str]]:
    """Part ``mesh`` along its lip line, in place. Returns (upper, lower, lines).

    ``upper_piece`` and ``lower_piece`` are the head's own teeth, which say
    where the mouth is. The mesh gains one vertex per split point; nothing is
    removed and no position changes, so the result renders identically until the
    two sides are weighted apart.
    """
    P = np.asarray([p[:3] for p in mesh.positions], dtype=np.float64)
    faces = [tuple(f)[:3] for f in mesh.faces]
    if len(P) < 8 or not faces:
        return [], [], []

    centre_x, centre_z, half_x, half_z = _box(mesh.positions, upper_piece, lower_piece)
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
        # On the line: pulled at from both sides...
        if any(i in above for i in fs)
        and any(i in below for i in fs)
        # ...and wholly inside the mouth, so the corners stay joined.
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
        f = faces[i]
        mesh.faces[i] = tuple(copy_of.get(v, v) for v in f)

    upper = sorted(copy_of.values())
    lower = sorted(copy_of)
    return upper, lower, [
        f"mouth split: parted the face along its lip line, {len(upper)} vertices "
        f"duplicated so the two halves can move apart (nothing removed)"
    ]
