"""Classifying mesh nodes into body parts by name.

Node naming is inconsistent across vanilla models - `head`, `Head`, `headnew`,
`head_g` all appear, and casing varies by character - so parts are matched by
case-insensitive substring rather than an exact list. The match is always shown
to the user before anything is written, because a bad classification silently
scales the wrong thing.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from kmdlswap.layout import Layout, NodeInfo

# Byte in the trimesh subheader that decides whether the engine draws the mesh.
# It matters more than it sounds: a human body model draws exactly three meshes
# (torso, LArm, RArm) and carries forty-odd invisible `_g` boxes that are the
# skeleton. Scaling those changes nothing anyone can see, so an effect that
# reports "42 nodes changed" while nothing looks different is lying to the user.
# Corpus-wide the flag is clean - only ever 0 or 1, across all 76,767 vanilla
# mesh nodes, of which 18,058 are invisible.
RENDER_FLAG_AT = 313


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


def renders(layout: Layout, node: NodeInfo) -> bool:
    """Does the engine draw this mesh, or is it skeleton scaffolding?"""
    if not node.is_mesh or not node.trimesh_at:
        return False
    return struct.unpack_from("<B", layout.mdl, node.trimesh_at + RENDER_FLAG_AT)[0] == 1


def mesh_nodes(layout: Layout, *, visible_only: bool = True) -> list[NodeInfo]:
    """Geometry mesh nodes we are allowed to rewrite.

    Invisible meshes are excluded by default: they are the skeleton's `_g`
    boxes, and scaling them is work with no visible result.
    """
    return [
        n
        for n in layout.nodes
        if n.is_mesh
        and n.in_animation is None
        and n.vertex_count
        and "saber" not in n.flags
        and (not visible_only or renders(layout, n))
    ]


def find(layout: Layout, part_key: str, *, visible_only: bool = True) -> list[NodeInfo]:
    return [
        n
        for n in mesh_nodes(layout, visible_only=visible_only)
        if classify(n.name) == part_key
    ]


def survey(layout: Layout, *, visible_only: bool = True) -> dict[str, list[NodeInfo]]:
    """Every mesh node grouped by part, plus 'other' for the unmatched."""
    out: dict[str, list[NodeInfo]] = {p.key: [] for p in PARTS}
    out["other"] = []
    for n in mesh_nodes(layout, visible_only=visible_only):
        out[classify(n.name) or "other"].append(n)
    return out
