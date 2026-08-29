"""Effect presets: which body parts get scaled, and by how much.

Everything here is a per-node uniform scale of geometry *within* a node. Node
positions live in node headers that kmdlswap never touches, so a node cannot be
moved - only its geometry can grow or shrink in place. That is why heads and
extremities work well and why aggressive whole-body effects can show seams at
joints, which each preset says up front.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Effect:
    key: str
    label: str
    description: str
    scales: dict[str, float] = field(default_factory=dict)
    caution: str = ""

    def scaled(self, intensity: float) -> dict[str, float]:
        """Blend each factor towards 1.0 by ``intensity`` (0 = no change)."""
        return {p: 1.0 + (f - 1.0) * intensity for p, f in self.scales.items()}


EFFECTS: tuple[Effect, ...] = (
    Effect(
        "bighead", "Big Head",
        "Every head mesh scaled up. The proven effect - this is the transform "
        "already verified in-game.",
        {"head": 1.6},
    ),
    Effect(
        "smallhead", "Pinhead",
        "Heads scaled down.",
        {"head": 0.55},
    ),
    Effect(
        "bobblehead", "Bobblehead",
        "Big head on a thinned neck.",
        {"head": 1.8, "neck": 0.55},
        caution="Head and neck are separate nodes, so a seam may show at the join.",
    ),
    Effect(
        "chibi", "Chibi",
        "Big head, small body and limbs.",
        {"head": 1.7, "torso": 0.75, "limb": 0.7, "hand": 0.8, "foot": 0.8},
        caution=(
            "Shrinking torso and limbs leaves gaps at joints: node positions "
            "cannot move, so the meshes pull away from each other."
        ),
    ),
    Effect(
        "bigmitts", "Big Hands & Feet",
        "Oversized hands and feet, everything else untouched.",
        {"hand": 2.0, "foot": 1.8},
    ),
)

BY_KEY = {e.key: e for e in EFFECTS}


def resolve(key: str) -> Effect:
    if key not in BY_KEY:
        raise KeyError(f"unknown effect {key!r}. Known: {', '.join(sorted(BY_KEY))}")
    return BY_KEY[key]
