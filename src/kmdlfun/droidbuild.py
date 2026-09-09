"""Mixing one droid's parts into another - heads, arms, legs and torsos.

A droid is not built the way a human character is. A human's head is a
separate model attached at runtime (`p_carthh`), so "give Carth a different
head" is a choice between existing files and costs no geometry work at all.
Every droid the game ships is the opposite: one **unified body** model, with
its head as a node among forty-odd droid-named meshes (`roster.py`,
`who.is_droid`). There is no table row that swaps a droid's arm the way
`heads.2da` swaps a human's face - the only way to give HK-47 someone else's
arm is to move geometry, node by node, the way `transplant.py` already does
for a single head.

This module adds nothing to that engine. It only decides which node on the
model being built pairs with which node on which donor, and applies
`transplant.transplant_node` once per part, threading the result of each
transplant into the next - so "head from one droid, arms from a second, legs
from a third" is one build instead of four manual ones, each needing the
previous output renamed into the next command's `--host`.

Which nodes exist, and what they are called, is read off the model actually
being built rather than assumed: `p_hk47`'s chassis mesh is `TorsoHoses`, not
`torso`, and nothing here needs to know that in advance. `parts.survey`
already buckets a model's own visible meshes into head / torso / limb / hand
/ foot / other for exactly this kind of picker.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from kmdlswap import layout as kl

from . import parts as kparts
from . import transplant as ktrans
from . import who as kwho


def droid_models(install, names=None, *, library=None) -> list[str]:
    """Every model in the install that is structurally a droid.

    Reuses `who.looks`, which already runs this exact test - a rigid head
    with no facial bones - for the donor filters elsewhere in the app. Not
    limited to HK-47 and T3-M4: any droid NPC the install carries, including
    ones the roster does not name.
    """
    from .library import ModelLibrary

    lib = library or ModelLibrary(install)
    looked = kwho.looks(install, names=names, library=lib)
    return sorted(name for name, look in looked.items() if look == kwho.DROID)


def slot_groups(layout: kl.Layout) -> dict[str, list]:
    """This model's own fillable nodes, grouped the way `parts.py` already
    groups a model's visible meshes for the Effects tab.

    Not a fixed list of droid part names - there isn't a portable one - but
    whatever the model actually has, so a picker can offer HK-47's
    `TorsoHoses` and T3-M4's own names without either being hardcoded.
    """
    survey = kparts.survey(layout)
    return {kparts.BY_KEY[k].label if k in kparts.BY_KEY else "Other": v
            for k, v in survey.items() if v}


def auto_donor_node(host_node_name: str, donor_layout: kl.Layout) -> str | None:
    """The donor node that would fill a given host node, worked out the same
    way `transplant.match_nodes` pairs a whole model: the same name first,
    case-insensitive, then the canonical alias (`arm.l`, `torso`, ...) if the
    literal name differs. `None` means the caller has to say which donor node
    they mean.
    """
    nodes = kparts.mesh_nodes(donor_layout)
    for n in nodes:
        if n.name.lower() == host_node_name.lower():
            return n.name
    key = ktrans.canonical(host_node_name)
    if key is None:
        return None
    for n in nodes:
        if ktrans.canonical(n.name) == key:
            return n.name
    return None


@dataclass
class SlotChoice:
    """One part of the build: fill `host_node` from `donor_model`.

    `donor_node` may be left as ``None`` to let `auto_donor_node` work it
    out; a droid whose parts are named unlike the base needs it spelled out,
    the same way the Transplant tab's donor-node box does for a single node.
    """

    host_node: str
    donor_model: str
    donor_node: str | None = None


@dataclass
class SlotResult:
    host_node: str
    donor_model: str
    donor_node: str | None
    transplant: ktrans.TransplantResult | None = None
    note: str | None = None

    @property
    def ok(self) -> bool:
        return self.note is None and self.transplant is not None and self.transplant.ok


@dataclass
class DroidBuildResult:
    base: str
    slots: list[SlotResult] = field(default_factory=list)
    mdl: bytes = b""
    mdx: bytes = b""

    @property
    def ok(self) -> bool:
        return all(s.ok for s in self.slots)

    @property
    def applied(self) -> list[str]:
        return [s.host_node for s in self.slots if s.ok]


def build(
    base_mdl: bytes,
    base_mdx: bytes,
    base_name: str,
    choices: list[SlotChoice],
    library,
    *,
    fit: bool = False,
    scale: float = 1.0,
    reshape: bool = False,
    with_texture: bool = True,
    max_influences: int = 4,
) -> DroidBuildResult:
    """Apply one donor part per slot, each onto the result of the last.

    A part left with no matching donor node is skipped rather than refused -
    one bad `--part` should not sink the ones that were fine - and it is the
    only thing skipped silently on success; every applied or refused part is
    reported through `SlotResult`.
    """
    result = DroidBuildResult(base=base_name)
    mdl, mdx = base_mdl, base_mdx
    donor_layouts: dict[str, kl.Layout] = {}

    for choice in choices:
        if choice.donor_model not in donor_layouts:
            donor_layouts[choice.donor_model] = kl.parse(*library.read(choice.donor_model))
        donor_layout = donor_layouts[choice.donor_model]

        donor_node = choice.donor_node or auto_donor_node(choice.host_node, donor_layout)
        if donor_node is None:
            result.slots.append(SlotResult(
                choice.host_node, choice.donor_model, None,
                note=f"no node on {choice.donor_model} matches {choice.host_node!r}; "
                     f"name one explicitly",
            ))
            continue

        new_mdl, new_mdx, report = ktrans.transplant_node(
            mdl, mdx, donor_layout, choice.donor_model,
            choice.host_node, donor_node,
            fit=fit, scale=scale, reshape=reshape,
            with_texture=with_texture, max_influences=max_influences,
        )
        result.slots.append(SlotResult(
            choice.host_node, choice.donor_model, donor_node, transplant=report,
        ))
        if report.ok:
            mdl, mdx = new_mdl, new_mdx

    result.mdl, result.mdx = mdl, mdx
    return result
