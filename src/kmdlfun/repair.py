"""Making a foreign mesh consistent enough for the engine to draw.

Generated and scanned meshes routinely arrive with triangles wound at random.
Nothing complains: most viewers light both sides, so the model looks fine right
up until it is in the game, where a back-facing triangle is simply not drawn and
the head reads as full of holes. Measured on a scanned head, **22.5% of faces
were wound against their neighbours**.

`unify_winding` walks the surface and makes every triangle agree with its
neighbours, then checks the whole thing is facing outwards rather than inwards -
a consistently wound mesh can still be uniformly inside out, and that looks
identical from inside the renderer.
"""

from __future__ import annotations

from collections import defaultdict, deque

import numpy as np

from kmdlswap.obj import ObjMesh


def outward_fraction(positions, faces) -> float:
    """How much of the surface faces away from the mesh's centre, by area.

    The test that replaced signed volume, which only means anything on a closed
    surface. Cropping a bust opens it along the cut, and the volume integral
    then returns whatever the open boundary happens to contribute - so a head
    that was cropped could be judged outward-facing while being entirely inside
    out, which is what put a hollow head in game.

    Comparing each face's normal against the direction from the centre works
    open or closed. A head is not convex, so this is never 100%; it only has to
    be a clear majority, weighted by area so a swarm of tiny crumpled faces
    cannot outvote the skull.
    """
    p = np.asarray([q[:3] for q in positions], dtype=np.float64)
    f = np.asarray(faces, dtype=np.int64)
    if len(f) == 0:
        return 1.0
    a, b, c = p[f[:, 0]], p[f[:, 1]], p[f[:, 2]]
    normals = np.cross(b - a, c - a)
    area = np.linalg.norm(normals, axis=1)
    # Bounding-box centre, not the mean of the vertices: a scan puts most of its
    # vertices wherever the detail is - all through the hair, on this one - and
    # the mean would sit inside that mass rather than inside the skull.
    centre = (p.min(axis=0) + p.max(axis=0)) / 2.0
    outward = np.einsum("ij,ij->i", normals, (a + b + c) / 3.0 - centre)
    total = area.sum()
    if total <= 0.0:
        return 1.0
    return float(area[outward > 0].sum() / total)


def signed_volume(positions, faces) -> float:
    """Six times the enclosed volume. Meaningful only on a closed surface."""
    p = np.asarray([q[:3] for q in positions], dtype=np.float64)
    f = np.asarray(faces, dtype=np.int64)
    if len(f) == 0:
        return 0.0
    a, b, c = p[f[:, 0]], p[f[:, 1]], p[f[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum())


def unify_winding(mesh: ObjMesh) -> tuple[ObjMesh, int]:
    """Wind every triangle the same way round, outward. Returns (mesh, flipped).

    Two vertices shared by two triangles should be traversed in *opposite*
    order by each of them - that is what "consistently wound" means. So the
    walk visits neighbours across shared edges and flips any that agree rather
    than oppose.

    Positions are welded first, because a mesh whose vertices are split at UV
    seams has no shared indices along those seams and the walk would stop at
    every one, leaving the mesh as inconsistent as it started.
    """
    if not mesh.faces:
        return mesh, 0

    lookup: dict = {}
    weld = []
    for p in mesh.positions:
        key = tuple(round(c, 7) for c in p[:3])
        weld.append(lookup.setdefault(key, len(lookup)))

    faces = [list(f) for f in mesh.faces]
    # Every directed edge, and which faces traverse it that way round.
    edges: dict = defaultdict(list)
    for i, f in enumerate(faces):
        w = [weld[v] for v in f]
        for k in range(3):
            edges[(w[k], w[(k + 1) % 3])].append(i)

    flipped = 0
    seen = [False] * len(faces)
    for start in range(len(faces)):
        if seen[start]:
            continue
        seen[start] = True
        queue = deque([start])
        while queue:
            i = queue.popleft()
            w = [weld[v] for v in faces[i]]
            for k in range(3):
                a, b = w[k], w[(k + 1) % 3]
                # A neighbour traversing (a, b) the *same* way is wound against
                # us; one traversing (b, a) agrees.
                for j in [*edges.get((a, b), ()), *edges.get((b, a), ())]:
                    if j == i or seen[j]:
                        continue
                    seen[j] = True
                    jw = [weld[v] for v in faces[j]]
                    same = any(
                        jw[m] == a and jw[(m + 1) % 3] == b for m in range(3)
                    )
                    if same:
                        faces[j] = [faces[j][0], faces[j][2], faces[j][1]]
                        flipped += 1
                    queue.append(j)

    # Consistent, but possibly consistently inside out.
    if outward_fraction(mesh.positions, faces) < 0.5:
        faces = [[f[0], f[2], f[1]] for f in faces]
        flipped = len(faces) - flipped

    out = ObjMesh(name=mesh.name)
    out.positions = list(mesh.positions)
    out.uvs = list(mesh.uvs)
    out.faces = [tuple(f) for f in faces]
    out.materials = list(mesh.materials)
    out.normals = _vertex_normals(out.positions, out.faces)
    return out, flipped


def facing_report(mesh: ObjMesh) -> str:
    return (f"{outward_fraction(mesh.positions, mesh.faces):.0%} of the surface "
            f"faces outward")


def _vertex_normals(positions, faces):
    """Smooth normals averaged per position, so seams do not shade faceted."""
    groups: dict = {}
    of_vertex = []
    for p in positions:
        of_vertex.append(groups.setdefault(tuple(round(c, 7) for c in p[:3]), len(groups)))

    acc = np.zeros((len(groups), 3))
    p = np.asarray([q[:3] for q in positions], dtype=np.float64)
    f = np.asarray(faces, dtype=np.int64)
    n = np.cross(p[f[:, 1]] - p[f[:, 0]], p[f[:, 2]] - p[f[:, 0]])
    idx = np.asarray(of_vertex, dtype=np.int64)
    for k in range(3):
        np.add.at(acc, idx[f[:, k]], n)

    lengths = np.linalg.norm(acc, axis=1)
    lengths[lengths < 1e-12] = 1.0
    unit = acc / lengths[:, None]
    return [tuple(float(c) for c in unit[g]) for g in of_vertex]


def crop_below(mesh: ObjMesh, fraction: float, axis: int = 2) -> tuple[ObjMesh, int]:
    """Drop everything below `fraction` of the mesh's height. Returns (mesh, cut).

    Asset sites sell busts, not heads: the scanned head this was written for is
    1.9 tall against 1.07 wide, nearly all of it hair hanging past the chin.
    Fitting that whole shape into a head node shrinks the actual face to a third
    of the space and spends the triangle budget on hair that would hang inside
    the character's chest anyway.

    Cropping leaves the mesh open along the cut, which is fine and is what
    vanilla does: a KOTOR head is not a closed surface either - the median has
    1.8% open edges, because the neck opening is hidden inside the body.
    """
    if not mesh.faces:
        return mesh, 0
    values = [p[axis] for p in mesh.positions]
    lo, hi = min(values), max(values)
    threshold = lo + (hi - lo) * fraction

    keep = [i for i, f in enumerate(mesh.faces)
            if max(mesh.positions[v][axis] for v in f) >= threshold]
    if len(keep) == len(mesh.faces):
        return mesh, 0

    remap: dict = {}
    out = ObjMesh(name=mesh.name)
    has_uvs = mesh.has_uvs and len(mesh.uvs) == len(mesh.positions)
    has_normals = bool(mesh.normals) and len(mesh.normals) == len(mesh.positions)
    for i in keep:
        tri = []
        for v in mesh.faces[i]:
            if v not in remap:
                remap[v] = len(out.positions)
                out.positions.append(mesh.positions[v])
                if has_uvs:
                    out.uvs.append(mesh.uvs[v])
                if has_normals:
                    out.normals.append(mesh.normals[v])
            tri.append(remap[v])
        out.faces.append(tuple(tri))
    return out, len(mesh.faces) - len(keep)
