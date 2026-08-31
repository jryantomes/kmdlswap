"""Reading companion models out of a game install, and running a whole build.

Never writes into the install. Output goes to a directory the user then copies
into Override themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import apply as kapply
from . import effects as keffects
from . import roster


@dataclass
class BuildReport:
    effect: str
    intensity: float
    out_dir: str
    models: list[kapply.ModelResult] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def written(self) -> int:
        return sum(1 for m in self.models if m.written)

    @property
    def failed(self) -> list[kapply.ModelResult]:
        return [m for m in self.models if not m.ok]

    @property
    def total_nodes(self) -> int:
        return sum(len(m.changes) for m in self.models)


class ModelLibrary:
    """Lazy index of MDL/MDX pairs in an install."""

    def __init__(self, install: str | Path):
        from pykotor.extract.installation import Installation
        from pykotor.resource.type import ResourceType

        self._mdl_type = ResourceType.MDL
        self._mdx_type = ResourceType.MDX
        inst = Installation(str(install))
        self.index: dict[str, dict] = {}
        for r in inst.chitin_resources():
            if r.restype() in (ResourceType.MDL, ResourceType.MDX):
                self.index.setdefault(r.resname().lower(), {})[r.restype()] = r

    def has(self, name: str) -> bool:
        e = self.index.get(name.lower())
        return bool(e and self._mdl_type in e and self._mdx_type in e)

    def read(self, name: str) -> tuple[bytes, bytes]:
        e = self.index[name.lower()]
        return e[self._mdl_type].data(), e[self._mdx_type].data()


def build(
    install: str | Path,
    effect_key: str,
    companion_keys: list[str] | None,
    out_dir: str | Path,
    *,
    intensity: float = 1.0,
    pivot: str = "joint",
    progress=None,
) -> BuildReport:
    """Apply one effect to every model of the chosen companions."""
    effect = keffects.resolve(effect_key)
    scales = effect.scaled(intensity)
    companions = roster.resolve(companion_keys)

    library = ModelLibrary(install)
    report = BuildReport(effect=effect.key, intensity=intensity, out_dir=str(out_dir))

    jobs = [(c, m) for c in companions for m in c.models]
    head_model_owners = _companions_with_head_models(library, companions)

    for i, (companion, model) in enumerate(jobs):
        if progress:
            progress(i, len(jobs), f"{companion.name}: {model}")
        if not library.has(model):
            report.missing.append(model)
            continue
        mdl, mdx = library.read(model)

        model_scales = dict(scales)
        if "head" in model_scales and companion.key in head_model_owners:
            from kmdlswap import layout as kl

            if not kapply.is_head_model(kl.parse(mdl, mdx)):
                # This companion's head lives in its own model. The body model's
                # "head_g" is only a small stub at the neck; scaling it would
                # bulge the collar while the real head stayed normal size.
                model_scales.pop("head")
                if not any(abs(v - 1.0) > 1e-6 for v in model_scales.values()):
                    continue

        new_mdl, new_mdx, result = kapply.apply_to_model(
            mdl, mdx, model_scales, pivot=pivot, model_name=model
        )
        if result.ok and result.changes:
            path = kapply.write_pair(out_dir, model, new_mdl, new_mdx)
            result.written = str(path)
        report.models.append(result)
    if progress:
        progress(len(jobs), len(jobs), "done")
    return report


def _companions_with_head_models(library: "ModelLibrary", companions) -> set[str]:
    """Which companions keep their head in a separate model file."""
    from kmdlswap import layout as kl

    owners = set()
    for c in companions:
        for m in c.models:
            if not library.has(m):
                continue
            if kapply.is_head_model(kl.parse(*library.read(m))):
                owners.add(c.key)
                break
    return owners


# Character models are named `p_`, `n_` or `c_` - but not all of them. The
# thirty player-creation heads are `pmhc01`, `pfha03` and so on, and the
# commoner heads are `comm_a_f`; none of them match, so none of them were ever
# offered as donors. That silently hid the most obvious heads in the game -
# twenty-one female and twenty-one male, all of them ordinary human faces.
PREFIXES = ("p_", "n_", "c_")


def head_models(install) -> set[str]:
    """Every model `heads.2da` names, lowercased.

    The game's own list of what counts as a head, which beats guessing at name
    patterns: it also turns up `ad_saul`, `czerka_com_h` and `darthband_h`,
    none of which follow any convention worth encoding.
    """
    try:
        from pykotor.extract.installation import Installation
        from pykotor.resource.formats.twoda import read_2da
        from pykotor.resource.type import ResourceType

        found = Installation(str(install)).resource("heads", ResourceType.TwoDA)
        if found is None:
            return set()
        table = read_2da(found.data)
        out = set()
        for i in range(table.get_height()):
            value = table.get_cell(i, "head").strip()
            if value:
                out.add(value.lower())
        return out
    except Exception:  # noqa: BLE001
        return set()


def character_models(install, library=None) -> list[str]:
    """Every model worth offering as a host or donor.

    The prefixed character models, plus every head the game itself names. Names
    the table lists but the install does not have are dropped - `heads.2da`
    points at `p_bastillah`, with two Ls, which is not a file.
    """
    lib = library if library is not None else ModelLibrary(install)
    named = head_models(install)
    return sorted(
        n for n in lib.index
        if lib.has(n) and (n.startswith(PREFIXES) or n in named)
    )


def classify(install, names=None, *, progress=None) -> dict[str, str]:
    """Sort an install's models by what a head swap can take from them.

    Head swapping is the job, and a donor list of 289 models is mostly bodies,
    torsos, robes and props. Reading each model to find out costs a couple of
    seconds once, which is cheaper than scrolling past three hundred names to
    find the ones that work.

    The question is not "is this a head model" but "can I take a head off it",
    and those differ. `apply.is_head_model` means "has no torso and no limbs",
    which is right for deciding how to scale a model and wrong here - a kath
    hound has neither and is not somewhere to get a face.

    * **head** - a model that *is* a head, with a `head` node and no body.
      What a human companion wears: `p_carthh`.
    * **creature** - a whole body carrying its head as a node. Borrowable all
      the same, and where the interesting aliens live: `n_quarren`, `p_hk47`.
    * **body** - no head node, so it has nothing to donate here.
    * **other** - parses, but has no mesh worth offering.
    """
    from kmdlswap import layout as kl

    from . import apply as kapply
    from . import parts as kparts

    lib = install if isinstance(install, ModelLibrary) else ModelLibrary(install)
    wanted = list(names if names is not None else lib.index)
    out: dict[str, str] = {}
    for i, name in enumerate(wanted):
        if progress is not None:
            progress(i, len(wanted), name)
        try:
            layout = kl.parse(*lib.read(name))
        except Exception:  # noqa: BLE001
            out[name] = "other"
            continue

        meshes = kparts.mesh_nodes(layout)
        if not meshes:
            out[name] = "other"
        elif not any(n.name.lower() == "head" for n in meshes):
            out[name] = "body" if kparts.survey(layout)["torso"] else "other"
        elif kapply.is_head_model(layout):
            out[name] = "head"
        else:
            out[name] = "creature"
    return out


DONOR_KINDS = ("head", "creature")
