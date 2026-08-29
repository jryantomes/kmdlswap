"""Milestone 1: a readable report of a model's node tree.

The point is to let a human choose a target node for a geometry swap, so the
things that matter are exact names, parent paths, and which nodes actually carry
skinned geometry.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from . import mdx as kmdx
from .layout import Layout, NodeInfo


@dataclass
class MeshFacts:
    node: NodeInfo
    triangles: int
    max_influences: int
    influence_histogram: dict[int, int]
    bone_names: list[str]
    weight_sum_range: tuple[float, float]


def mesh_facts(layout: Layout, node: NodeInfo) -> MeshFacts:
    hist: Counter[int] = Counter()
    bone_names: list[str] = []
    lo, hi = 1.0, 1.0
    if node.is_skin:
        per_vertex = kmdx.influences(layout, node)
        slot_nodes = kmdx.bone_slot_nodes(layout, node)
        used: set[int] = set()
        sums = []
        for infl in per_vertex:
            hist[len(infl)] += 1
            sums.append(sum(i.weight for i in infl))
            used.update(i.bone_slot for i in infl)
        bone_names = [
            slot_nodes[s].name if s in slot_nodes else f"<slot {s}>" for s in sorted(used)
        ]
        if sums:
            lo, hi = min(sums), max(sums)
    return MeshFacts(
        node=node,
        triangles=node.face_count,
        max_influences=max(hist) if hist else 0,
        influence_histogram=dict(sorted(hist.items())),
        bone_names=bone_names,
        weight_sum_range=(lo, hi),
    )


def report(layout: Layout, *, show_animations: bool = False) -> str:
    geometry = [n for n in layout.nodes if n.in_animation is None]
    meshes = [n for n in geometry if n.is_mesh]
    skinned = [n for n in meshes if n.is_skin]
    bx = layout.bbox

    out: list[str] = []
    out.append(f"model        {layout.model_name}")
    out.append(f"supermodel   {layout.supermodel}")
    out.append(f"nodes        {len(geometry)} geometry  ({len(meshes)} mesh, {len(skinned)} skinned)")
    out.append(f"animations   {len(layout.animation_names)}")
    if len(bx) == 6:
        out.append(
            f"bounding box ({bx[0]:.3f}, {bx[1]:.3f}, {bx[2]:.3f}) .. "
            f"({bx[3]:.3f}, {bx[4]:.3f}, {bx[5]:.3f})   radius {layout.radius:.3f}"
        )
    total_tris = sum(n.face_count for n in meshes)
    total_verts = sum(n.vertex_count for n in meshes)
    out.append(f"totals       {total_verts} vertices, {total_tris} triangles across all mesh nodes")

    out.append("")
    out.append("node tree (names shown with exact casing)")
    out.append("")
    _tree(layout, geometry, out)

    if meshes:
        out.append("")
        out.append("mesh nodes")
        out.append("")
        out.append(f"  {'node':<24} {'verts':>6} {'tris':>6} {'skin':>5}  {'stride':>6}  texture")
        out.append(f"  {'-' * 24} {'-' * 6} {'-' * 6} {'-' * 5}  {'-' * 6}  {'-' * 20}")
        for n in meshes:
            out.append(
                f"  {n.name:<24} {n.vertex_count:>6} {n.face_count:>6} "
                f"{('yes' if n.is_skin else '-'):>5}  {n.mdx_stride:>6}  {n.textures[0]}"
            )

    if skinned:
        out.append("")
        out.append("skinning")
        for n in skinned:
            f = mesh_facts(layout, n)
            out.append("")
            out.append(f"  {n.name}  ({n.path(layout.nodes)})")
            out.append(
                f"    max influences/vertex observed: {f.max_influences}"
                f"   histogram: {f.influence_histogram}"
            )
            out.append(
                f"    weight sums: {f.weight_sum_range[0]:.4f} .. {f.weight_sum_range[1]:.4f}"
            )
            out.append(f"    bones referenced ({len(f.bone_names)}): {', '.join(f.bone_names)}")

    if show_animations and layout.animation_names:
        out.append("")
        out.append("animations")
        for a in layout.animation_names:
            out.append(f"  {a}")

    return "\n".join(out)


def _tree(layout: Layout, geometry: list[NodeInfo], out: list[str]) -> None:
    roots = [n for n in geometry if n.parent is None]
    for r in roots:
        _branch(layout, r, "", True, out)


def _branch(layout: Layout, node: NodeInfo, prefix: str, last: bool, out: list[str]) -> None:
    connector = "" if not prefix and last else ("`-- " if last else "|-- ")
    tags = []
    if node.is_mesh:
        tags.append(f"mesh {node.vertex_count}v/{node.face_count}t")
    if node.is_skin:
        tags.append("skin")
    for extra in ("light", "emitter", "reference", "dangly", "aabb", "saber"):
        if extra in node.flags:
            tags.append(extra)
    suffix = f"   [{', '.join(tags)}]" if tags else ""
    out.append(f"  {prefix}{connector}{node.name}{suffix}")

    kids = [layout.nodes[i] for i in node.children]
    child_prefix = prefix + ("" if not connector else ("    " if last else "|   "))
    for i, k in enumerate(kids):
        _branch(layout, k, child_prefix, i == len(kids) - 1, out)
