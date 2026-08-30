"""Applying an effect to a model.

Every edit goes through ``kmdlswap.edit.replace_geometry``, so the same coverage,
offset-closure and identity validators that guard a real geometry swap guard
these joke transforms too. A model that fails validation is not written.

The one thing an effect has to get right beyond "make it bigger" is *where* each
node grows from. A part made of several nodes - a human head is ten visible ones
- only holds together if every node grows about the same point in model space.
See :mod:`kmdlfun.space` for the arithmetic and for what goes wrong without it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from kmdlswap import edit as ke
from kmdlswap import layout as kl
from kmdlswap import validate as kv

from . import parts, space

# How the pivot each node grows from is chosen.
#
#   joint   the part's own joint, shared by every node in the part: a head grows
#           out of the neck it is attached to, and its eyes, teeth and skullcap
#           travel with the face skin instead of being left inside it.
#   node    each node about its own origin - the joint it hangs from, with no
#           group correction. What ``joint`` degrades to for a one-node part.
#   bounds  each node about the centre of its own bounding box. Keeps a single
#           mesh visually in place, and pulls a multi-node part apart; kept
#           because it is what the first version of this tool did.
PIVOTS = ("joint", "node", "bounds")


@dataclass
class NodeChange:
    node: str
    part: str
    factor: float
    vertices: int


@dataclass
class ModelResult:
    model: str
    changes: list[NodeChange] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    written: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def is_head_model(layout: kl.Layout) -> bool:
    """A head model is a whole model that *is* a head - it has facial meshes but
    no torso or limbs. Human companions keep their head in one of these.

    It matters because such a model holds hair, teeth, eyes, brows and tongue as
    separate nodes; scaling only the node literally called "head" would leave
    the hair and eyes at their original size.
    """
    survey = parts.survey(layout)
    return not survey["torso"] and not survey["limb"]


def targets(layout: kl.Layout, part_key: str) -> list[int]:
    """Node indices this part should scale, for this particular model."""
    if part_key == "head" and is_head_model(layout):
        # The entire model is the head; scale all of it except the neck, which
        # joins the body and would tear away from it.
        return [
            n.index
            for n in parts.mesh_nodes(layout)
            if parts.classify(n.name) != "neck"
        ]
    return [n.index for n in parts.find(layout, part_key)]


def head_joint(layout: kl.Layout, pose: dict[int, space.Rest]) -> space.Vec3 | None:
    """Where a head model's head meets the body, in model space.

    Every human head model in K1 carries the same two dummies at that joint -
    `head_g`, the bone the head hangs from, and its parent `Hturn_g`, the head
    turn - so the joint is read from the skeleton rather than guessed from the
    geometry.
    """
    for want in ("head_g", "hturn_g"):
        for node in layout.nodes:
            if node.in_animation is None and node.name.lower() == want:
                return pose[node.index].position
    return None


def pivot_local(
    layout: kl.Layout,
    pose: dict[int, space.Rest],
    node: kl.NodeInfo,
    geo: ke.MeshGeometry,
    mode: str,
    group_pivot: space.Vec3 | None,
) -> space.Vec3:
    """The point this node grows from, in the node's own space."""
    if mode == "bounds":
        ps = geo.positions
        return tuple(
            (max(p[i] for p in ps) + min(p[i] for p in ps)) / 2 for i in range(3)
        )
    if mode == "joint" and group_pivot is not None:
        return pose[node.index].to_local(group_pivot)
    return (0.0, 0.0, 0.0)  # the node's own origin


def scale_geometry(
    geo: ke.MeshGeometry, factor: float, pivot: space.Vec3 = (0.0, 0.0, 0.0)
) -> ke.MeshGeometry:
    """Uniformly scale a mesh's positions about ``pivot``, in node space."""
    geo.columns["vertex"] = [
        tuple(pivot[i] + (p[i] - pivot[i]) * factor for i in range(3))
        for p in geo.positions
    ]
    return geo


def apply_to_model(
    mdl: bytes,
    mdx: bytes,
    scales: dict[str, float],
    *,
    pivot: str = "joint",
    model_name: str = "",
) -> tuple[bytes, bytes, ModelResult]:
    """Apply per-part scale factors to one model. Returns new bytes + a report."""
    if pivot not in PIVOTS:
        raise ValueError(f"unknown pivot {pivot!r}. Known: {', '.join(PIVOTS)}")
    result = ModelResult(model=model_name)
    layout = kl.parse(mdl, mdx)
    if not kv.check(layout).ok:
        result.error = "model does not validate; refusing to edit it"
        return mdl, mdx, result

    plan: dict[int, tuple[str, float]] = {}
    for part_key, factor in scales.items():
        if abs(factor - 1.0) < 1e-6:
            continue
        for index in targets(layout, part_key):
            plan.setdefault(index, (part_key, factor))

    # One pivot for the whole head group, fixed before any splice moves bytes.
    group_pivot = None
    if "head" in scales and is_head_model(layout):
        group_pivot = head_joint(layout, space.rest_pose(layout))

    for index, (part_key, factor) in sorted(plan.items()):
        # Re-parse after each splice: offsets move, but node indices are stable
        # because parse order is deterministic. Names are NOT usable here - some
        # models have two nodes with the same name (T3-M4 has two "FootL").
        layout = kl.parse(mdl, mdx)
        pose = space.rest_pose(layout)
        node = layout.nodes[index]
        try:
            geo = ke.extract(layout, node)
        except ValueError as exc:
            result.skipped.append(f"{node.name}: {exc}")
            continue
        centre = pivot_local(layout, pose, node, geo, pivot, group_pivot)
        scale_geometry(geo, factor, centre)
        # The stored per-mesh bounding box, radius and average describe geometry
        # that just changed size; hand the engine the same map so they follow.
        moved = ke.UniformScale(factor, tuple((1.0 - factor) * c for c in centre))
        try:
            mdl, mdx = ke.replace_geometry(layout, node, geo, moved=moved)
        except Exception as exc:  # noqa: BLE001
            result.skipped.append(f"{node.name}: {type(exc).__name__}: {exc}")
            continue
        result.changes.append(
            NodeChange(node.name, part_key, factor, node.vertex_count)
        )

    final = kv.check(kl.parse(mdl, mdx))
    if not final.ok:
        result.error = (
            f"result failed validation (gaps={len(final.gaps)} "
            f"overlaps={len(final.overlaps)} dangling={len(final.dangling)})"
        )
    return mdl, mdx, result


def write_pair(out_dir: str | Path, name: str, mdl: bytes, mdx: bytes) -> Path:
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.mdl").write_bytes(mdl)
    (d / f"{name}.mdx").write_bytes(mdx)
    return d / f"{name}.mdl"
