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

import re
from dataclasses import dataclass, field

from kmdlswap import layout as kl

from . import parts as kparts
from . import space as kspace
from . import transplant as ktrans
from . import who as kwho

# How a donor part is placed relative to the host part it fills.
#   "joint" - the donor node's own origin is moved onto the host node's origin,
#             so the part hangs from the same articulation point. A short donor's
#             head still lands at the tall host's neck; the part keeps its own
#             size (which is the "goofy" the caller signed up for - `scale` and
#             `fit` are the knobs for that).
#   "none"  - the raw transplant, donor geometry carried at its own model-space
#             height. A T3-M4 head on HK-47 ends up ~1 unit low.
ALIGN_JOINT = "joint"
ALIGN_NONE = "none"


def split_donor(spec: str) -> tuple[str, str]:
    """Pull an optional game off a donor name: ``"k2/c_condrdl"`` gives
    ``("K2", "c_condrdl")``, a bare ``"c_drdwar"`` gives ``("", "c_drdwar")``.

    A namespace rather than a flag because the choice is per part - the whole
    point of naming the game here is that one build can take a head from one
    game and an arm from the other. `/` is safe as the separator: a resref is
    letters, digits and underscores, so no existing `--part` can contain one.
    """
    game, sep, model = spec.partition("/")
    if not sep:
        return "", spec.strip()
    return game.strip().upper(), model.strip()


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


def fillable_slots(layout: kl.Layout) -> list[tuple[str, str, list]]:
    """The standard part groups a droid offers as mix points, in part order,
    each as ``(part key, label, [nodes])``.

    `slot_groups` keeps every mesh, "Other" included; this drops it. HK-47's
    hoses and finger plates, T3-M4's probe arm, a war droid's blaster - none
    of that is geometry anyone swaps between droids, and offering it is only
    more ways to pick a node that will not pair. A guided picker wants the
    six real slots (head, neck, hands, feet, torso, arms & legs); the command
    line still lists everything.
    """
    survey = kparts.survey(layout)
    return [(k, kparts.BY_KEY[k].label, survey[k])
            for k in kparts.BY_KEY if survey.get(k)]


def part_categories(layout: kl.Layout) -> set[str]:
    """The standard `parts.py` keys this model actually carries geometry in -
    'other' excluded. `{"head", "torso", "limb", ...}`."""
    return {k for k, _label, nodes in fillable_slots(layout) if nodes}


# What a droid needs before it is worth offering as a base to build on: a
# head and a torso. A turret (`c_drdsentry`), a spider walker (`c_drdspyder`)
# or a bare astromech dome (`l_astro02`) has one or neither, and every part
# of it lands in "other" - picking it as a base produces a slot list with
# nothing mixable in it.
BASE_MINIMUM = frozenset({"head", "torso"})


def catalogue(install, *, library=None) -> dict[str, set[str]]:
    """Every droid model in the install mapped to the part categories it has.

    Built once and read for both the base list (which droids are complete
    enough to build on) and the per-slot donor lists (which droids can fill
    a head, an arm, ...). One parse per droid, on top of the structural scan
    `droid_models` already does.
    """
    from .library import ModelLibrary

    lib = library or ModelLibrary(install)
    out: dict[str, set[str]] = {}
    for name in droid_models(install, library=lib):
        try:
            out[name] = part_categories(kl.parse(*lib.read(name)))
        except Exception:  # noqa: BLE001
            out[name] = set()
    return out


def buildable_bases(cat: dict[str, set[str]]) -> list[str]:
    """The droids from `catalogue` complete enough to be a base - `BASE_MINIMUM`
    met."""
    return sorted(name for name, cats in cat.items() if BASE_MINIMUM <= cats)


def donors_for(cat: dict[str, set[str]], part_key: str, *, exclude: str = "") -> list[str]:
    """The droids from `catalogue` that carry `part_key`, so a slot only ever
    offers a donor that can actually fill it."""
    return sorted(name for name, cats in cat.items()
                  if part_key in cats and name != exclude)


def _squash(name: str) -> str:
    """A node name with case and separators taken out: `R_upper_arm` and
    `R_UpperArm` both become `rupperarm`."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def auto_donor_node(host_node_name: str, donor_layout: kl.Layout) -> str | None:
    """The donor node that would fill a given host node, worked out the same
    way `transplant.match_nodes` pairs a whole model: the same name first,
    case-insensitive, then the same name ignoring separators, then the
    canonical alias (`arm.l`, `torso`, ...) if the literal name differs.
    `None` means the caller has to say which donor node they mean.

    The separator pass is what pairs HK-47's `R_upper_arm` with a war droid's
    `R_UpperArm` - the same word, punctuated differently by two modellers, and
    the single most common reason a droid mix silently skipped a part. It only
    counts when exactly one donor node squashes to that form: HK-47 itself has
    both `F-1` and `F_1`, and guessing between two nodes is worse than saying
    so.
    """
    nodes = kparts.mesh_nodes(donor_layout)
    for n in nodes:
        if n.name.lower() == host_node_name.lower():
            return n.name
    wanted = _squash(host_node_name)
    same = [n.name for n in nodes if _squash(n.name) == wanted]
    if len(same) == 1:
        return same[0]
    key = ktrans.canonical(host_node_name)
    if key is None:
        return None
    for n in nodes:
        if ktrans.canonical(n.name) == key:
            return n.name
    return None


def joint_offset(
    host_layout: kl.Layout, host_node_name: str,
    donor_layout: kl.Layout, donor_node_name: str,
) -> tuple[float, float, float]:
    """The model-space shift that puts the donor node's origin on the host's.

    Droid parts are rigid nodes (only HK-47's hoses are skinned), so a part's
    node *is* its joint: its rest-pose origin sits at the articulation point it
    swings about. Matching those origins hangs the donor part off the host's
    equivalent joint - the donor keeps its own shape and size, it just attaches
    in the right place. Rotation is left to `transplant.to_host_space`, which
    already re-expresses the donor's frame in the host's.
    """
    h = kspace.rest_pose(host_layout)[host_layout.node_by_name(host_node_name).index]
    d = kspace.rest_pose(donor_layout)[donor_layout.node_by_name(donor_node_name).index]
    return tuple(h.position[i] - d.position[i] for i in range(3))


@dataclass
class SlotChoice:
    """One part of the build: fill `host_node` from `donor_model`.

    `donor_node` may be left as ``None`` to let `auto_donor_node` work it
    out; a droid whose parts are named unlike the base needs it spelled out,
    the same way the Transplant tab's donor-node box does for a single node.

    `donor_game` names which install the donor comes from - ``""`` for the
    base's own, `"K2"` for a second game passed in `build`'s
    `donor_libraries`. It is part of the choice rather than a setting for the
    whole build because the two games ship fourteen droids under the *same
    name*: a build can take a head from K1's `c_drdwar` and an arm from K2's,
    and only the pair (game, model) says which file that is.
    """

    host_node: str
    donor_model: str
    donor_node: str | None = None
    donor_game: str = ""

    @property
    def donor_label(self) -> str:
        """The donor as a person would write it: `c_drdwar`, or `K2/c_drdwar`."""
        return f"{self.donor_game}/{self.donor_model}" if self.donor_game else self.donor_model


@dataclass
class SlotResult:
    host_node: str
    donor_model: str
    donor_node: str | None
    transplant: ktrans.TransplantResult | None = None
    note: str | None = None
    donor_game: str = ""

    @property
    def ok(self) -> bool:
        return self.note is None and self.transplant is not None and self.transplant.ok

    @property
    def donor_label(self) -> str:
        return f"{self.donor_game}/{self.donor_model}" if self.donor_game else self.donor_model


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
    donor_libraries: dict[str, object] | None = None,
    align: str = ALIGN_JOINT,
    fit: bool = False,
    scale: float = 1.0,
    reshape: bool = False,
    with_texture: bool = True,
    max_influences: int = 4,
) -> DroidBuildResult:
    """Apply one donor part per slot, each onto the result of the last.

    A part left with no matching donor node - none given and none inferable, or
    an explicit one that the donor does not have - is skipped rather than
    refused, so one bad `--part` does not sink the ones that were fine. A skip
    is the only thing done silently on success; every applied or refused part is
    reported through `SlotResult`.

    With ``align="joint"`` (the default) each donor part is moved so its own
    node origin lands on the host node's, hanging it off the same joint; see
    `joint_offset`. ``align="none"`` is the raw transplant. `fit` re-centres on
    its own, so it takes over the placing when set.

    `library` reads the base's own game; `donor_libraries` maps a game tag to
    another one, which is what lets a single build take its head from KOTOR and
    its arm from KOTOR II. Each donor is cached under `(game, model)` rather
    than model alone: both games ship a `c_drdwar`, and they are not the same
    file.
    """
    result = DroidBuildResult(base=base_name)
    mdl, mdx = base_mdl, base_mdx
    donor_layouts: dict[tuple[str, str], kl.Layout] = {}
    libraries = dict(donor_libraries or {})
    libraries.setdefault("", library)
    # Node headers are never rewritten, so every slot's host joint is read from
    # the untouched base rather than from the part-by-part result.
    host_layout = kl.parse(base_mdl, base_mdx)

    for choice in choices:
        key = (choice.donor_game, choice.donor_model)
        if key not in donor_layouts:
            donor_lib = libraries.get(choice.donor_game)
            if donor_lib is None:
                result.slots.append(SlotResult(
                    choice.host_node, choice.donor_model, choice.donor_node,
                    donor_game=choice.donor_game,
                    note=f"no {choice.donor_game} install is set, so "
                         f"{choice.donor_label} cannot be read",
                ))
                continue
            try:
                donor_layouts[key] = kl.parse(*donor_lib.read(choice.donor_model))
            except Exception as exc:  # noqa: BLE001
                result.slots.append(SlotResult(
                    choice.host_node, choice.donor_model, choice.donor_node,
                    donor_game=choice.donor_game,
                    note=f"could not read {choice.donor_label}: {exc}",
                ))
                continue
        donor_layout = donor_layouts[key]

        donor_node = choice.donor_node or auto_donor_node(choice.host_node, donor_layout)
        if donor_node is None:
            result.slots.append(SlotResult(
                choice.host_node, choice.donor_model, None,
                donor_game=choice.donor_game,
                note=f"no node on {choice.donor_label} matches {choice.host_node!r}; "
                     f"name one explicitly",
            ))
            continue
        try:
            donor_layout.node_by_name(donor_node)
        except KeyError as exc:
            result.slots.append(SlotResult(
                choice.host_node, choice.donor_model, donor_node,
                donor_game=choice.donor_game,
                note=f"{choice.donor_label} has no node {donor_node!r} ({exc})",
            ))
            continue

        offset = None
        if align == ALIGN_JOINT and not fit:
            try:
                offset = joint_offset(
                    host_layout, choice.host_node, donor_layout, donor_node
                )
            except KeyError:
                # A host node the base does not have: let `transplant_node`
                # report it, the same way every other bad pairing is reported.
                offset = None

        new_mdl, new_mdx, report = ktrans.transplant_node(
            mdl, mdx, donor_layout, choice.donor_model,
            choice.host_node, donor_node,
            fit=fit, scale=scale, reshape=reshape,
            place=offset is not None, model_offset=offset,
            with_texture=with_texture, max_influences=max_influences,
        )
        result.slots.append(SlotResult(
            choice.host_node, choice.donor_model, donor_node, transplant=report,
            donor_game=choice.donor_game,
        ))
        if report.ok:
            mdl, mdx = new_mdl, new_mdx

    result.mdl, result.mdx = mdl, mdx
    return result
