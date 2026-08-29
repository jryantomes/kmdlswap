"""Turning an OBJ into a replacement for one mesh node.

This is where the pieces meet: OBJ geometry, weights inherited from the mesh
being replaced, and rebuilt face adjacency.

Columns this tool cannot author from an OBJ - a second UV set, vertex colours,
tangent frames - are a hard refusal rather than a zero-fill. Inventing values
for data the engine reads is exactly what the brief rules out, and a silently
wrong model is worse than a hard error at write time.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import mdx as kmdx
from . import topology, weights
from .edit import Face, MeshGeometry, extract
from .layout import Layout, NodeInfo
from .obj import ObjMesh

# Columns we can produce from an OBJ.
AUTHORABLE = {"vertex", "normal", "uv1"}


@dataclass
class SwapReport:
    """What the swap did, so a user can sanity-check before loading in-game."""

    node: str
    old_vertices: int
    new_vertices: int
    old_triangles: int
    new_triangles: int
    skinned: bool
    max_influences: int = 0
    influence_histogram: dict[int, int] = field(default_factory=dict)
    bones_used: int = 0
    normals_source: str = "obj"
    uv_source: str = "obj"
    warnings: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        out = [
            f"node        {self.node}",
            f"vertices    {self.old_vertices} -> {self.new_vertices}",
            f"triangles   {self.old_triangles} -> {self.new_triangles}",
            f"normals     from {self.normals_source}",
            f"texcoords   from {self.uv_source}",
        ]
        if self.skinned:
            out.append(
                f"skinning    transferred; max {self.max_influences} influences/vertex, "
                f"{self.bones_used} bones, histogram {self.influence_histogram}"
            )
        else:
            out.append("skinning    none (mesh is not skinned)")
        for w in self.warnings:
            out.append(f"WARNING     {w}")
        return out


def _face_normals(positions, faces):
    """Area-weighted vertex normals, for when the OBJ carries none."""
    acc = [[0.0, 0.0, 0.0] for _ in positions]
    for (i0, i1, i2) in faces:
        p0, p1, p2 = positions[i0], positions[i1], positions[i2]
        ux, uy, uz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
        vx, vy, vz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        for i in (i0, i1, i2):
            acc[i][0] += nx
            acc[i][1] += ny
            acc[i][2] += nz
    out = []
    for n in acc:
        length = (n[0] ** 2 + n[1] ** 2 + n[2] ** 2) ** 0.5
        out.append((n[0] / length, n[1] / length, n[2] / length) if length > 1e-12 else (0.0, 0.0, 1.0))
    return out


def _plane_coefficient(positions, face, normal) -> float:
    p = positions[face[0]]
    return -(normal[0] * p[0] + normal[1] * p[1] + normal[2] * p[2])


def build_replacement(
    layout: Layout,
    node: NodeInfo,
    mesh: ObjMesh,
    *,
    max_influences: int = weights.MAX_INFLUENCES,
    material: int | None = None,
) -> tuple[MeshGeometry, SwapReport]:
    """Build a MeshGeometry replacing ``node``'s geometry with ``mesh``."""
    original = extract(layout, node)
    stride = kmdx.stride_layout(layout, node)

    unauthorable = sorted(set(stride.columns) - AUTHORABLE)
    if unauthorable:
        raise ValueError(
            f"{node.name!r} carries MDX columns this tool cannot author from an OBJ: "
            f"{', '.join(unauthorable)}. Refusing rather than writing invented values."
        )

    report = SwapReport(
        node=node.name,
        old_vertices=original.vertex_count,
        new_vertices=mesh.vertex_count,
        old_triangles=original.triangle_count,
        new_triangles=len(mesh.faces),
        skinned=node.is_skin,
    )

    columns: dict[str, list[tuple[float, ...]]] = {}
    if "vertex" in stride.columns:
        columns["vertex"] = [tuple(p) for p in mesh.positions]

    if "normal" in stride.columns:
        if mesh.has_normals:
            columns["normal"] = [tuple(n) for n in mesh.normals]
        else:
            columns["normal"] = _face_normals(mesh.positions, mesh.faces)
            report.normals_source = "computed from faces"

    if "uv1" in stride.columns:
        if mesh.has_uvs:
            columns["uv1"] = [tuple(t) for t in mesh.uvs]
        else:
            columns["uv1"] = [(0.0, 0.0)] * mesh.vertex_count
            report.uv_source = "none in OBJ - zeroed"
            report.warnings.append(
                "the OBJ has no texture coordinates; the mesh will render untextured"
            )

    normals = columns.get("normal") or _face_normals(mesh.positions, mesh.faces)
    adjacency = topology.build_adjacency(mesh.faces, mesh.positions)

    default_material = material
    if default_material is None:
        default_material = original.faces[0].material if original.faces else 1

    faces = []
    for i, tri in enumerate(mesh.faces):
        n = normals[tri[0]]
        fn = (
            (n[0] + normals[tri[1]][0] + normals[tri[2]][0]) / 3.0,
            (n[1] + normals[tri[1]][1] + normals[tri[2]][1]) / 3.0,
            (n[2] + normals[tri[1]][2] + normals[tri[2]][2]) / 3.0,
        )
        length = (fn[0] ** 2 + fn[1] ** 2 + fn[2] ** 2) ** 0.5
        if length > 1e-12:
            fn = (fn[0] / length, fn[1] / length, fn[2] / length)
        faces.append(
            Face(
                normal=fn,
                plane=_plane_coefficient(mesh.positions, tri, fn),
                material=default_material,
                adjacent=adjacency[i],
                vertices=tuple(tri),
            )
        )

    influences: list[list[kmdx.Influence]] = []
    if node.is_skin:
        if not original.influences:
            raise ValueError(f"{node.name!r} is skinned but has no source weights to transfer")
        influences = weights.transfer(
            original.positions,
            [f.vertices for f in original.faces],
            original.influences,
            mesh.positions,
            max_influences=max_influences,
        )
        problems = weights.check(influences)
        if problems:
            raise ValueError(
                f"{node.name!r}: weight transfer produced {len(problems)} bad vertices; "
                f"first: {problems[0]}"
            )
        hist: dict[int, int] = {}
        used = set()
        for infl in influences:
            hist[len(infl)] = hist.get(len(infl), 0) + 1
            used.update(x.bone_slot for x in infl)
        report.max_influences = max(hist) if hist else 0
        report.influence_histogram = dict(sorted(hist.items()))
        report.bones_used = len(used)

    geo = MeshGeometry(
        vertex_count=mesh.vertex_count,
        columns=columns,
        influences=influences,
        faces=faces,
        trailing=original.trailing,
    )

    budget = 4000
    if len(mesh.faces) > budget:
        report.warnings.append(
            f"{len(mesh.faces)} triangles: vanilla K1 character models run roughly "
            f"2,000-4,000 triangles across ALL nodes, so this is over the practical budget"
        )
    return geo, report


def geometry_to_obj_arrays(geo: MeshGeometry):
    """Split a MeshGeometry into the arrays ``obj.write_obj`` wants."""
    return (
        geo.positions,
        [f.vertices for f in geo.faces],
        geo.columns.get("uv1"),
        geo.columns.get("normal"),
    )
