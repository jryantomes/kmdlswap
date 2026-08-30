"""Reducing a mesh to a triangle budget, without breaking what we check for.

Quadric error edge collapse (Garland & Heckbert). Each vertex carries a matrix
summarising the planes of the faces around it; collapsing an edge costs the
squared distance from the new point to all those planes, so the cheapest
collapses are the ones that change the surface least. Flat regions simplify
first and silhouettes survive, which is what you want on a head.

Edge collapse is the right operation here specifically because of the acceptance
criteria: it cannot disconnect a mesh, and on a closed surface it cannot open
one. So a mesh that passed `one piece` and `closed` before decimating still
passes after, which a naive triangle-dropping simplifier could not promise.

Two collapses are refused rather than allowed to make a mess:

* one that would **flip a face**, which is what produces the pinched dark
  creases you see in bad automatic reductions;
* one that would make the mesh **non-manifold**, checked with the standard link
  condition - the two endpoints must share exactly the two neighbours opposite
  the edge, or the collapse pinches the surface together.

UVs are carried **per face corner**, not per vertex, and not resampled.

That is the second design here that had to be measured rather than reasoned
about. Resampling by closest point looks principled - it ties the mapping to the
shape rather than to whichever vertex survived - but it ignores UV seams. A
photogrammetry atlas is mostly seam: the Tripo head carries 2,941 vertices for
3,312 faces, so roughly 1,300 of them are seam duplicates sharing a position
with a different UV. Welding by position (which the collapses need, or the mesh
tears) merges those, and closest-point resampling then hands back whichever side
of the seam it happened to hit. Measured on that head, one face in five ended up
with a UV area more than twenty times the median, and the texture rendered as
concentric garbage.

Carrying corner UVs cannot cross a seam, because a corner keeps the UV it was
authored with. Vertices are re-split on output wherever corners disagree, which
is how the seam survives into the MDX.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass

import numpy as np

from kmdlswap.obj import ObjMesh


# Above this, run a clustering pass first. Chosen so ordinary head meshes - a
# few thousand triangles - never touch it and go straight to quadric collapse.
CLUSTER_ABOVE = 40_000


@dataclass
class Result:
    mesh: ObjMesh
    before: int
    after: int
    collapses: int
    refused_flip: int
    refused_manifold: int
    clustered: int = 0

    def summary(self) -> str:
        pre = (f"clustered away {self.clustered} triangles first, then "
               if self.clustered else "")
        return (
            f"{self.before} -> {self.after} triangles, " + pre
            + f"{self.collapses} collapses "
            f"({self.refused_flip} refused for face flips, "
            f"{self.refused_manifold} for non-manifold)"
        )


def _weld(positions, tolerance: float = 0.0):
    """Merge vertices that share a position, so seams do not tear apart."""
    lookup: dict = {}
    mapping = []
    unique: list = []
    for p in positions:
        key = tuple(p[:3]) if tolerance <= 0 else tuple(
            round(c / tolerance) for c in p[:3]
        )
        if key not in lookup:
            lookup[key] = len(unique)
            unique.append(tuple(p[:3]))
        mapping.append(lookup[key])
    return unique, mapping


def _face_quadric(p0, p1, p2):
    n = np.cross(np.subtract(p1, p0), np.subtract(p2, p0))
    length = np.linalg.norm(n)
    if length < 1e-14:
        return None
    n = n / length
    d = -float(np.dot(n, p0))
    plane = np.array([n[0], n[1], n[2], d], dtype=np.float64)
    return np.outer(plane, plane)


def cluster(mesh: ObjMesh, target_faces: int) -> ObjMesh:
    """Collapse a mesh onto a grid, as a first pass for very dense input.

    Edge collapse is O(edges log edges) with a Python-level loop, which is fine
    for a few thousand triangles and hopeless for a scan: a 1.2-million-triangle
    head would need well over a million collapses. Vertex clustering is a single
    vectorised pass - snap every vertex to a grid cell, keep one representative
    per cell, drop faces whose corners collapse together - so it gets within
    reach quickly and the quadric pass then does the shape-aware work.

    Clustering alone would be a poor decimator: it ignores curvature and can
    weld across a thin gap. That is exactly why it is only ever a first pass,
    stopping well above the target so the quadric stage still has room to work.

    Seams are preserved the same way the quadric pass preserves them, and for
    the same reason: taking one representative vertex's UV per cell hands back
    whichever side of a seam happened to be first, and on a scan atlas that
    scrambles the texture. Output vertices are keyed by (cell, UV), so a cell
    straddling a seam becomes several vertices sharing a position - which is
    exactly what the quadric pass then welds for topology and re-splits on
    output.
    """
    positions = np.asarray([p[:3] for p in mesh.positions], dtype=np.float64)
    lo, hi = positions.min(axis=0), positions.max(axis=0)
    extent = np.maximum(hi - lo, 1e-9)

    # Aim for a few times the target so the quadric pass still has choices.
    wanted_cells = max(target_faces * 4, 64)
    divisions = max(2, int(round(wanted_cells ** (1.0 / 3.0) * 2)))
    step = extent / divisions

    cell = np.floor((positions - lo) / step).astype(np.int64)
    _, first, inverse = np.unique(cell, axis=0, return_index=True, return_inverse=True)
    inverse = inverse.reshape(-1)

    has_uvs = mesh.has_uvs and len(mesh.uvs) == len(mesh.positions)
    representative = [tuple(float(c) for c in positions[i]) for i in first]

    out = ObjMesh(name=mesh.name)
    remap: dict = {}
    seen = set()

    def vertex_for(original: int) -> int:
        cell_index = int(inverse[original])
        uv = tuple(round(c, 6) for c in mesh.uvs[original]) if has_uvs else None
        key = (cell_index, uv)
        if key not in remap:
            remap[key] = len(out.positions)
            out.positions.append(representative[cell_index])
            if uv is not None:
                out.uvs.append(uv)
        return remap[key]

    for a, b, c in mesh.faces:
        cells = (int(inverse[a]), int(inverse[b]), int(inverse[c]))
        if len({*cells}) != 3:
            continue
        key = tuple(sorted(cells))
        if key in seen:
            continue
        seen.add(key)
        out.faces.append((vertex_for(a), vertex_for(b), vertex_for(c)))
    return out


def simplify(mesh: ObjMesh, target_faces: int) -> Result:
    """Reduce a mesh towards `target_faces`, preserving its topology class."""
    # A scan can arrive with a million triangles. Cluster down to something the
    # quadric pass can chew through, then let it do the shape-aware work.
    clustered = 0
    if len(mesh.faces) > CLUSTER_ABOVE and len(mesh.faces) > target_faces * 8:
        before_cluster = len(mesh.faces)
        mesh = cluster(mesh, target_faces)
        clustered = before_cluster - len(mesh.faces)

    verts, mapping = _weld(mesh.positions)
    faces = []
    corner_uv: list[list[tuple]] = []
    has_uvs = mesh.has_uvs and len(mesh.uvs) == len(mesh.positions)
    for a, b, c in mesh.faces:
        t = (mapping[a], mapping[b], mapping[c])
        if len({*t}) == 3:
            faces.append(list(t))
            if has_uvs:
                corner_uv.append(
                    [tuple(mesh.uvs[a]), tuple(mesh.uvs[b]), tuple(mesh.uvs[c])]
                )
    before = len(faces)
    if before <= target_faces or before == 0:
        return Result(mesh, before, before, 0, 0, 0)

    positions = [np.array(v, dtype=np.float64) for v in verts]
    alive_face = [True] * len(faces)
    vertex_faces: list[set] = [set() for _ in positions]
    for fi, f in enumerate(faces):
        for v in f:
            vertex_faces[v].add(fi)

    quadrics = [np.zeros((4, 4)) for _ in positions]
    for fi, f in enumerate(faces):
        q = _face_quadric(*(positions[v] for v in f))
        if q is None:
            alive_face[fi] = False
            continue
        for v in f:
            quadrics[v] += q

    def neighbours(v):
        out = set()
        for fi in vertex_faces[v]:
            if alive_face[fi]:
                out.update(faces[fi])
        out.discard(v)
        return out

    def cost(i, j):
        q = quadrics[i] + quadrics[j]
        target = (positions[i] + positions[j]) / 2.0
        # The optimal point solves the 3x3 system; fall back to the midpoint
        # when the quadric is degenerate, which happens on flat regions.
        a = q[:3, :3]
        try:
            best = np.linalg.solve(a, -q[:3, 3])
            if np.all(np.isfinite(best)):
                target = best
        except np.linalg.LinAlgError:
            pass
        v4 = np.array([target[0], target[1], target[2], 1.0])
        return float(v4 @ q @ v4), target

    heap: list = []
    for fi, f in enumerate(faces):
        for a, b in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])):
            if a < b:
                c, t = cost(a, b)
                heapq.heappush(heap, (c, a, b, tuple(t)))

    alive_vertex = [True] * len(positions)
    version = [0] * len(positions)
    live_faces = before
    collapses = refused_flip = refused_manifold = 0

    def face_normal(f, override=None, at=None):
        pts = [override if (at is not None and v == at) else positions[v] for v in f]
        return np.cross(np.subtract(pts[1], pts[0]), np.subtract(pts[2], pts[0]))

    while live_faces > target_faces and heap:
        _, i, j, target = heapq.heappop(heap)
        if not (alive_vertex[i] and alive_vertex[j]):
            continue
        ni, nj = neighbours(i), neighbours(j)
        if j not in ni:
            continue

        # Link condition: the endpoints must share exactly the vertices opposite
        # the edge. More, and collapsing pinches the surface into itself.
        shared = ni & nj
        opposite = {
            v
            for fi in (vertex_faces[i] & vertex_faces[j])
            if alive_face[fi]
            for v in faces[fi]
            if v not in (i, j)
        }
        if shared != opposite:
            refused_manifold += 1
            continue

        new_point = np.array(target, dtype=np.float64)
        flipped = False
        for fi in (vertex_faces[i] | vertex_faces[j]):
            if not alive_face[fi]:
                continue
            f = faces[fi]
            if i in f and j in f:
                continue          # this face disappears in the collapse
            at = i if i in f else j
            before_n = face_normal(f)
            after_n = face_normal(f, override=new_point, at=at)
            if np.dot(before_n, after_n) <= 0:
                flipped = True
                break
        if flipped:
            refused_flip += 1
            continue

        # Commit: j folds into i.
        for fi in list(vertex_faces[i] & vertex_faces[j]):
            if alive_face[fi]:
                alive_face[fi] = False
                live_faces -= 1
        positions[i] = new_point
        quadrics[i] = quadrics[i] + quadrics[j]
        for fi in list(vertex_faces[j]):
            if not alive_face[fi]:
                continue
            faces[fi] = [i if v == j else v for v in faces[fi]]
            vertex_faces[i].add(fi)
        alive_vertex[j] = False
        version[i] += 1
        collapses += 1

        for k in neighbours(i):
            c, t = cost(i, k)
            heapq.heappush(heap, (c, min(i, k), max(i, k), tuple(t)))

    # Rebuild a compact mesh, splitting a vertex wherever its corners carry
    # different UVs - that is what puts the seams back.
    remap: dict = {}
    out = ObjMesh(name=mesh.name)
    for fi, f in enumerate(faces):
        if not alive_face[fi]:
            continue
        tri = []
        for k, v in enumerate(f):
            uv = corner_uv[fi][k] if has_uvs else None
            key = (v, uv)
            if key not in remap:
                remap[key] = len(out.positions)
                out.positions.append(tuple(float(c) for c in positions[v]))
                if uv is not None:
                    out.uvs.append(uv)
            tri.append(remap[key])
        if len({*tri}) == 3:
            out.faces.append(tuple(tri))

    out.normals = _normals(out.positions, out.faces)
    return Result(
        out, before, len(out.faces), collapses, refused_flip, refused_manifold, clustered
    )


def resample_uvs(points, source: ObjMesh):
    """Closest-point UV resampling. **Not used by `simplify` any more.**

    Kept because it is the right tool when the target genuinely has no UVs of
    its own - a reshape, where the host's vertices move onto a donor surface and
    must pick up the donor's mapping. It is the wrong tool for decimation, where
    the mesh already has UVs and seams to preserve; see the module docstring.
    """
    from .reshape import snap_to_surface

    _, uvs = snap_to_surface(
        points, source.positions, source.faces, target_uvs=source.uvs
    )
    return uvs


def _normals(positions, faces):
    """Smooth normals, averaged across every vertex sharing a position.

    Splitting vertices at UV seams means one point on the surface can be several
    vertices. Averaging per vertex would then give each side of a seam its own
    normal, and the mesh shades faceted along every seam - which on a
    photogrammetry atlas is most of the mesh. Averaging per *position* keeps the
    shading smooth across seams, which is what the seam is for.
    """
    groups: dict = {}
    of_vertex = []
    for pos in positions:
        key = tuple(round(c, 7) for c in pos[:3])
        of_vertex.append(groups.setdefault(key, len(groups)))

    acc = [[0.0, 0.0, 0.0] for _ in groups]
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
                acc[of_vertex[i]][k] += n[k]

    unit = []
    for n in acc:
        length = (n[0] ** 2 + n[1] ** 2 + n[2] ** 2) ** 0.5
        unit.append(
            tuple(c / length for c in n) if length > 1e-12 else (0.0, 0.0, 1.0)
        )
    return [unit[g] for g in of_vertex]
