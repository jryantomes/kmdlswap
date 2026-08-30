"""Effect presets: which body parts get scaled, and by how much.

Everything here is a uniform scale of the geometry *inside* a node. Node
positions live in node headers that kmdlswap never touches, so a node cannot be
moved - only its geometry can grow or shrink. A part made of several nodes is
still scaled as one piece, about the joint it hangs from (see
:mod:`kmdlfun.space`), so a head stays a head.

What that cannot reach is the skeleton. A part that is *smaller* leaves the
bones that drive it where they were, so shrinking a whole body neither shortens
the character nor keeps its limbs on their joints once it animates. Heads and
extremities work well; whole-body proportions need the rig to move with them.
Every preset says up front which side of that line it is on -
``reports/KMDLFUN_PIVOT_FINDINGS.md`` has the measurements.
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
        "Every visible head mesh scaled up together, growing out of the neck "
        "joint - eyes, teeth, hair and skullcap travel with the face.",
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
        caution=(
            "Only the droids have a neck of their own: on a human the visible "
            "neck belongs to the body's torso mesh, so the thinning finds "
            "nothing and you get a plain big head."
        ),
    ),
    Effect(
        "chibi", "Chibi",
        "Big head, small body and limbs.",
        {"head": 1.7, "torso": 0.75, "limb": 0.7, "hand": 0.8, "foot": 0.8},
        caution=(
            "The weakest preset, and honestly so. Shrinking a body cannot "
            "shorten the character - height is where the bones are, and they "
            "stay - and the shrunken skin still swings about joints it is no "
            "longer near, so limbs pull away from the body in motion. It needs "
            "the rig to scale with the mesh, which this tool cannot do yet."
        ),
    ),
    Effect(
        "bigmitts", "Big Hands & Feet",
        "Oversized hands and feet, everything else untouched.",
        {"hand": 2.0, "foot": 1.8},
        caution=(
            "Droids only. A human body draws its hands and feet as part of one "
            "torso mesh and two arm meshes - there is no hand node to scale, "
            "only invisible finger bones."
        ),
    ),
)

BY_KEY = {e.key: e for e in EFFECTS}


def resolve(key: str) -> Effect:
    if key not in BY_KEY:
        raise KeyError(f"unknown effect {key!r}. Known: {', '.join(sorted(BY_KEY))}")
    return BY_KEY[key]
