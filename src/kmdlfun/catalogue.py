"""A catalogue of the game's character models and the parts they are made of.

The point is to answer, from the data rather than from assumption: what models
exist, what each one is made of, and which of them are actually interchangeable.

Interchangeability is the interesting question. KOTOR models that share a
*supermodel* inherit its skeleton and animations, so their node names largely
agree - which is what makes geometry portable between them **without touching
the hierarchy**, the one constraint that keeps this whole tool safe.
"""

from __future__ import annotations

import struct
from collections import defaultdict
from dataclasses import dataclass, field

from kmdlswap.layout import Layout

from . import parts as kparts
from . import space


@dataclass
class PartEntry:
    """One mesh node, as a candidate donor or recipient."""

    node: str
    index: int
    part: str | None
    vertices: int
    triangles: int
    skinned: bool
    visible: bool
    texture: str
    swappable: bool
    refusal: str | None
    size: tuple[float, float, float]
    anchor: tuple[float, float, float]


@dataclass
class ModelEntry:
    name: str
    supermodel: str
    category: str
    node_count: int
    animations: int
    is_head_model: bool
    parts: list[PartEntry] = field(default_factory=list)

    @property
    def visible_parts(self) -> list[PartEntry]:
        return [p for p in self.parts if p.visible]

    @property
    def triangles(self) -> int:
        return sum(p.triangles for p in self.visible_parts)


CATEGORIES = (
    ("p_", "player/companion"),
    ("n_", "NPC"),
    ("c_", "creature"),
)


def categorise(name: str) -> str:
    for prefix, label in CATEGORIES:
        if name.startswith(prefix):
            return label
    return "other"


def describe(layout: Layout, name: str) -> ModelEntry:
    from kmdlswap import mdx as kmdx
    from kmdlswap.swap import AUTHORABLE

    from .apply import is_head_model

    geometry = [n for n in layout.nodes if n.in_animation is None]
    entry = ModelEntry(
        name=name,
        supermodel=layout.supermodel or "NULL",
        category=categorise(name),
        node_count=len(geometry),
        animations=len(layout.animation_names),
        is_head_model=is_head_model(layout),
    )

    rest = space.rest_pose(layout)
    for node in layout.nodes:
        if not node.is_mesh or node.in_animation is not None or not node.vertex_count:
            continue

        refusal = None
        if "saber" in node.flags:
            refusal = "saber"
        else:
            try:
                stride = kmdx.stride_layout(layout, node)
                extra = sorted(set(stride.columns) - AUTHORABLE)
                if extra:
                    refusal = "needs_" + extra[0]
            except ValueError:
                refusal = "stride_not_understood"

        vertices_offset = struct.unpack_from("<I", layout.mdl, node.trimesh_at + 328)[0]
        base = 12 + vertices_offset
        pts = [
            struct.unpack_from("<3f", layout.mdl, base + i * 12)
            for i in range(node.vertex_count)
        ]
        size = tuple(
            max(p[i] for p in pts) - min(p[i] for p in pts) for i in range(3)
        )
        r = rest.get(node.index)
        anchor = tuple(r.position) if r else (0.0, 0.0, 0.0)

        entry.parts.append(
            PartEntry(
                node=node.name,
                index=node.index,
                part=kparts.classify(node.name),
                vertices=node.vertex_count,
                triangles=node.face_count,
                skinned=node.is_skin,
                visible=kparts.renders(layout, node),
                texture=node.textures[0],
                swappable=refusal is None,
                refusal=refusal,
                size=size,
                anchor=anchor,
            )
        )
    return entry


# ---- interchangeability ----------------------------------------------------


@dataclass
class Family:
    """Models sharing a supermodel, and therefore a skeleton."""

    supermodel: str
    models: list[ModelEntry] = field(default_factory=list)

    def node_index(self) -> dict[str, list[str]]:
        """Node name -> the models that have it, among visible swappable meshes."""
        out: dict[str, list[str]] = defaultdict(list)
        for m in self.models:
            for p in m.visible_parts:
                if p.swappable:
                    out[p.node].append(m.name)
        return dict(out)

    def swappable_nodes(self, minimum: int = 2) -> dict[str, list[str]]:
        """Nodes present in at least ``minimum`` models - the actual parts bin."""
        return {
            node: models
            for node, models in sorted(self.node_index().items())
            if len(models) >= minimum
        }


def group_by_supermodel(entries: list[ModelEntry]) -> dict[str, Family]:
    families: dict[str, Family] = {}
    for e in entries:
        families.setdefault(e.supermodel, Family(e.supermodel)).models.append(e)
    return families


def donors_for(family: Family, node_name: str, exclude: str) -> list[ModelEntry]:
    """Which models could supply geometry for ``node_name``."""
    return [
        m
        for m in family.models
        if m.name != exclude
        and any(p.node == node_name and p.swappable and p.visible for p in m.parts)
    ]


# ---- compatibility ---------------------------------------------------------

# A swap only moves geometry into nodes the host already has, so two models are
# compatible to the extent their node names agree. Name overlap alone is too
# weak a test: c_dewback shares exactly one node name with p_carthh - a `head`
# of an entirely different shape - while a real donor head shares seven or eight.
# So coverage, model kind and skeleton are all taken into account.

MIN_COVERAGE = 0.5


@dataclass(frozen=True)
class Compatibility:
    tier: str            # "good" | "possible" | "poor"
    shared: int
    coverage: float
    same_supermodel: bool
    same_kind: bool
    host_is_head: bool = False
    donor_is_head: bool = False

    @property
    def usable(self) -> bool:
        return self.tier in ("good", "possible")

    def label(self, donor: str) -> str:
        return f"{donor}   {self.shared} parts" + ("" if self.tier == "good" else "  (?)")

    def why_not(self, host: str, donor: str) -> str:
        def kind(is_head: bool) -> str:
            return "a head model" if is_head else "a body model"

        if not self.same_kind:
            return (
                f"{host} is {kind(self.host_is_head)} and {donor} is "
                f"{kind(self.donor_is_head)}; their parts are not the same parts"
            )
        if self.shared == 0:
            return f"{donor} shares no mesh node names with {host}"
        return (
            f"{donor} has only {self.shared} of {host}'s {int(round(self.shared / max(self.coverage, 1e-9)))} "
            f"parts ({self.coverage:.0%}); they are built differently"
        )


@dataclass
class ModelIndex:
    """Just enough about every model to answer compatibility instantly."""

    nodes: dict[str, frozenset] = field(default_factory=dict)
    head_model: dict[str, bool] = field(default_factory=dict)
    supermodel: dict[str, str] = field(default_factory=dict)

    def add(self, entry: ModelEntry) -> None:
        # Through the same alias table the matcher uses, or the index would
        # report a Carth/Bastila body swap as sharing one node when the
        # transplant would actually move three. Head models are untouched:
        # none of their node names are in the table.
        from .transplant import canonical

        self.nodes[entry.name] = frozenset(
            canonical(p.node) or p.node.lower()
            for p in entry.visible_parts if p.swappable
        )
        self.head_model[entry.name] = entry.is_head_model
        self.supermodel[entry.name] = (entry.supermodel or "NULL").lower()

    @property
    def names(self) -> list[str]:
        return sorted(self.nodes)

    def compare(self, host: str, donor: str) -> Compatibility:
        h = self.nodes.get(host, frozenset())
        d = self.nodes.get(donor, frozenset())
        shared = len(h & d)
        coverage = shared / len(h) if h else 0.0
        same_kind = self.head_model.get(host) == self.head_model.get(donor)
        same_super = self.supermodel.get(host) == self.supermodel.get(donor)
        if not same_kind or coverage < MIN_COVERAGE:
            tier = "poor"
        elif same_super:
            tier = "good"
        else:
            tier = "possible"
        return Compatibility(
            tier, shared, coverage, same_super, same_kind,
            host_is_head=bool(self.head_model.get(host)),
            donor_is_head=bool(self.head_model.get(donor)),
        )

    def donors_for(self, host: str, *, usable_only: bool = True):
        """Candidate donors, best first."""
        out = []
        for donor in self.nodes:
            if donor == host:
                continue
            c = self.compare(host, donor)
            if usable_only and not c.usable:
                continue
            out.append((c, donor))
        out.sort(key=lambda t: (t[0].tier != "good", -t[0].shared, t[1]))
        return out
