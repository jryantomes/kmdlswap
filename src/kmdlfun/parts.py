"""Classifying mesh nodes into body parts by name.

Node naming is inconsistent across vanilla models - `head`, `Head`, `headnew`,
`head_g` all appear, and casing varies by character - so parts are matched by
case-insensitive substring rather than an exact list. The match is always shown
to the user before anything is written, because a bad classification silently
scales the wrong thing.
"""

from __future__ import annotations

from dataclasses import dataclass

from kmdlswap.layout import Layout, NodeInfo


@dataclass(frozen=True)
class Part:
    key: str
    label: str
    include: tuple[str, ...]
    exclude: tuple[str, ...] = ()


PARTS: tuple[Part, ...] = (
    Part("head", "Head", ("head", "face", "skull")),
    Part("neck", "Neck", ("neck",)),
    # "hand" also matches handconjure/handdummy, which are hooks, not meshes;
    # only mesh nodes are ever considered, so those drop out anyway.
    Part("hand", "Hands", ("hand", "fngr", "finger", "thumb", "trgrfngr")),
    Part("foot", "Feet", ("foot", "toe")),
    Part("torso", "Torso", ("torso", "body", "chest", "pelvis", "waist", "stomach")),
    Part("limb", "Arms & legs",
         ("arm", "leg", "thigh", "calf", "shin", "bicep", "forearm", "collar")),
)

BY_KEY = {p.key: p for p in PARTS}


def classify(name: str) -> str | None:
    """Return the part key a node name belongs to, or None."""
    low = name.lower()
    for part in PARTS:
        if any(x in low for x in part.exclude):
            continue
        if any(x in low for x in part.include):
            return part.key
    return None


def mesh_nodes(layout: Layout) -> list[NodeInfo]:
    """Geometry mesh nodes we are allowed to rewrite."""
    return [
        n
        for n in layout.nodes
        if n.is_mesh
        and n.in_animation is None
        and n.vertex_count
        and "saber" not in n.flags
    ]


def find(layout: Layout, part_key: str) -> list[NodeInfo]:
    return [n for n in mesh_nodes(layout) if classify(n.name) == part_key]


def survey(layout: Layout) -> dict[str, list[NodeInfo]]:
    """Every mesh node grouped by part, plus 'other' for the unmatched."""
    out: dict[str, list[NodeInfo]] = {p.key: [] for p in PARTS}
    out["other"] = []
    for n in mesh_nodes(layout):
        out[classify(n.name) or "other"].append(n)
    return out
