"""Applying an effect to a model.

Every edit goes through ``kmdlswap.edit.replace_geometry``, so the same coverage,
offset-closure and identity validators that guard a real geometry swap guard
these joke transforms too. A model that fails validation is not written.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from kmdlswap import edit as ke
from kmdlswap import layout as kl
from kmdlswap import validate as kv

from . import parts


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


def scale_geometry(geo: ke.MeshGeometry, factor: float, pivot: str = "bounds"):
    """Uniformly scale a mesh's positions.

    ``bounds`` grows the mesh about the centre of its bounding box, so it stays
    visually in place. Note this is deliberately NOT the average vertex
    position: that is pulled towards dense regions of the mesh (a face has far
    more vertices than the back of a skull), so scaling about it makes the part
    drift as it grows.

    ``origin`` grows it away from the node's own origin, which for a head is
    roughly the neck joint - closer to how a classic big-head mode looks.
    """
    positions = geo.positions
    if pivot == "bounds":
        c = tuple(
            (max(p[i] for p in positions) + min(p[i] for p in positions)) / 2
            for i in range(3)
        )
    else:
        c = (0.0, 0.0, 0.0)
    geo.columns["vertex"] = [
        tuple(c[i] + (p[i] - c[i]) * factor for i in range(3)) for p in positions
    ]
    return geo


def apply_to_model(
    mdl: bytes,
    mdx: bytes,
    scales: dict[str, float],
    *,
    pivot: str = "bounds",
    model_name: str = "",
) -> tuple[bytes, bytes, ModelResult]:
    """Apply per-part scale factors to one model. Returns new bytes + a report."""
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

    for index, (part_key, factor) in sorted(plan.items()):
        # Re-parse after each splice: offsets move, but node indices are stable
        # because parse order is deterministic. Names are NOT usable here - some
        # models have two nodes with the same name (T3-M4 has two "FootL").
        layout = kl.parse(mdl, mdx)
        node = layout.nodes[index]
        try:
            geo = ke.extract(layout, node)
        except ValueError as exc:
            result.skipped.append(f"{node.name}: {exc}")
            continue
        scale_geometry(geo, factor, pivot)
        try:
            mdl, mdx = ke.replace_geometry(layout, node, geo)
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
