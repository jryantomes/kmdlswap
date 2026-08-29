"""Face topology: adjacency rebuilding.

Each face stores three neighbour face indices, one per edge. Vanilla always
holds either a valid face index or ``NO_NEIGHBOUR``. Replacement geometry
invalidates the original values, so they must be recomputed.

The convention was recovered by testing candidate rules against 16,031 vanilla
faces (see reports/MILESTONE_3_FINDINGS.md):

* edges are taken in the order (v0,v1), (v1,v2), (v2,v0);
* vertices are welded **by position** first - meshes split vertices at UV seams,
  and vanilla's adjacency crosses those seams;
* matching is **directed**: the neighbour across edge (a,b) is the face holding
  the opposite half-edge (b,a). This handles double-sided surfaces, where an
  undirected edge is shared by four faces rather than two.

That reproduces 96.3% of vanilla adjacency exactly. The residual is most likely
a weld tolerance in the original compiler; we weld on exact position equality.
"""

from __future__ import annotations

from collections.abc import Sequence

NO_NEIGHBOUR = 0xFFFF

_EDGES = ((0, 1), (1, 2), (2, 0))


def weld_by_position(positions: Sequence[tuple[float, ...]]) -> list[int]:
    """Map each vertex index to the first index sharing its exact position."""
    first: dict[tuple[float, ...], int] = {}
    return [first.setdefault(p, i) for i, p in enumerate(positions)]


def build_adjacency(
    face_vertices: Sequence[tuple[int, int, int]],
    positions: Sequence[tuple[float, ...]],
) -> list[tuple[int, int, int]]:
    """Recompute per-face edge adjacency for a mesh."""
    weld = weld_by_position(positions)
    half: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for fi, verts in enumerate(face_vertices):
        v = [weld[x] for x in verts]
        for ei, (a, b) in enumerate(_EDGES):
            half.setdefault((v[a], v[b]), []).append((fi, ei))

    adjacency = [[NO_NEIGHBOUR] * 3 for _ in face_vertices]
    for (a, b), uses in half.items():
        opposite = half.get((b, a))
        if not opposite:
            continue
        for (fi, ei), (fj, _) in zip(uses, opposite):
            adjacency[fi][ei] = fj
    return [tuple(a) for a in adjacency]


def check_adjacency(
    adjacency: Sequence[tuple[int, int, int]], face_count: int
) -> list[str]:
    """Every entry must be a valid face index or NO_NEIGHBOUR - vanilla never
    stores anything else."""
    problems = []
    for fi, adj in enumerate(adjacency):
        for ei, a in enumerate(adj):
            if a != NO_NEIGHBOUR and not (0 <= a < face_count):
                problems.append(f"face {fi} edge {ei}: neighbour {a} out of range")
    return problems
