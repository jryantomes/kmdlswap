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
    pivot: str = "bounds",
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
