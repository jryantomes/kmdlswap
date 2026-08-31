"""Ranking donors by how well they will actually sit on a given host.

The donor list is long - K2 alone offers a few hundred models a head can be
taken from - and alphabetical order says nothing about which ones are worth
building. Some land almost perfectly; some come out smashed. Finding out by
building each one costs minutes apiece, so the list is sorted by a number that
predicts the result instead.

**What is measured.** `transplant.transfer_strain` already answers the right
question: weight transfer gives every new vertex the influences of the nearest
point on the *host's* surface, so wherever donor and host shapes disagree, a
vertex inherits from whatever happened to be closest and then swings with a
bone that has nothing to do with it. In game that is the "animates, but is
smashed about" failure. The fraction of donor vertices sitting far from the
host's surface is therefore a direct measure of how much of the donor is going
to be driven by the wrong thing.

**Measured after fitting, on purpose.** Raw strain would mostly rank donors by
size: a head twice as large disagrees with the host surface everywhere, even if
it is the same shape. Since the tool would apply `--fit` anyway, the ranking
applies it too, and what survives is disagreement of *shape*, which is the part
no scaling will rescue.

**The grades are vanilla's own numbers, not invented thresholds.** Fitting all
61 vanilla heads onto Carth gives a median of 0%, a 75th percentile of 1.2%, a
90th of 4.8%, and a worst case of 11.5% (`n_yoda`). So a donor inside 1.2% is
no stranger to the host than half the heads the game ships; one at 11% is no
worse than a head that ships and works. Only past that is a donor doing
something vanilla never asks the engine to do. Grading against shipped content
keeps the bar empirical - the alternative is a score that looks authoritative
and means nothing.

The other facts a donor carries - whether its own weights can come across,
whether it needs decimating, what extra parts would have to be folded in - are
reported alongside rather than folded into the number. They are different kinds
of thing, and mixing them into one score would hide exactly the detail that
decides whether a donor is worth trying.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from kmdlswap import edit as ke
from kmdlswap import layout as kl

from . import transplant as ktrans

# From fitting every vanilla head onto Carth; see transplant.FAR_FRACTION.
VANILLA_P75 = 0.012
VANILLA_P90 = 0.048
VANILLA_WORST = 0.115

GRADES = (
    (VANILLA_P75, "clean"),
    (VANILLA_P90, "good"),
    (VANILLA_WORST, "rough"),
)

# Past what a KOTOR head normally carries, decimation has real work to do.
BUDGET = 1200


@dataclass
class Fit:
    """One donor measured against one host."""

    donor: str
    donor_node: str
    host: str
    host_node: str
    blocked: str | None = None
    far: float = 0.0
    mean: float = 0.0
    own_weights: bool = False
    vertices: int = 0
    size_ratio: float = 1.0
    extra_parts: list[str] = field(default_factory=list)

    @property
    def grade(self) -> str:
        if self.blocked:
            return "blocked"
        for limit, name in GRADES:
            if self.far <= limit:
                return name
        return "hard"

    @property
    def rank_key(self) -> tuple:
        return (self.blocked is not None, self.far, self.mean)

    def notes(self) -> list[str]:
        """What the number does not say."""
        if self.blocked:
            return [self.blocked]
        out = []
        if self.own_weights:
            out.append("keeps its own weights - facial animation comes across intact")
        if self.size_ratio > 1.5:
            out.append(
                f"{self.size_ratio:.1f}x the host on its worst axis, so it needs "
                f"--fit or it will clip"
            )
        if self.vertices > BUDGET:
            out.append(f"{self.vertices} vertices, over budget - needs --decimate")
        if self.extra_parts:
            out.append(
                f"{len(self.extra_parts)} extra part(s) to fold in: "
                f"{', '.join(self.extra_parts[:4])}"
            )
        if self.far > VANILLA_WORST:
            out.append(
                "further from the host's shape than any head the game ships - "
                "expect parts driven by the wrong bones"
            )
        return out

    @property
    def line(self) -> str:
        if self.blocked:
            return f"{self.donor:<22} {'blocked':<8} {self.blocked}"
        marks = "".join(
            (
                "w" if self.own_weights else "-",
                "d" if self.vertices > BUDGET else "-",
                "+" if self.extra_parts else "-",
            )
        )
        return (
            f"{self.donor:<22} {self.grade:<8} {self.far:>6.1%} far  "
            f"{self.mean:>6.1%} mean  {marks}  {self.vertices:>5} verts"
        )


def head_node(layout):
    """The node a head transplant would take from this model."""
    from . import parts as kparts

    for node in kparts.mesh_nodes(layout):
        if node.name.lower() == "head":
            return node
    return None


def measure(
    host_layout,
    host_node,
    donor_layout,
    donor_node,
    *,
    donor_name: str = "",
    host_name: str = "",
) -> Fit:
    """How well one donor node would sit in one host node."""
    fit = Fit(
        donor=donor_name or donor_node.name,
        donor_node=donor_node.name,
        host=host_name,
        host_node=host_node.name,
        vertices=donor_node.vertex_count,
    )

    blocked = ktrans.check_pair(host_layout, host_node, donor_layout, donor_node)
    if blocked:
        fit.blocked = blocked
        return fit

    try:
        offset = ktrans.model_alignment(donor_layout, donor_node, host_layout, host_node)
        mesh, alignment = ktrans.to_host_space(
            donor_layout,
            donor_node,
            host_layout,
            host_node,
            fit=True,
            place=True,
            model_offset=offset,
        )
    except Exception as exc:  # noqa: BLE001
        fit.blocked = f"cannot be placed: {type(exc).__name__}: {exc}"
        return fit

    host_geo = ke.extract(host_layout, host_node)
    fit.mean, fit.far = ktrans.transfer_strain(host_geo, mesh.positions)
    fit.size_ratio = alignment.worst_ratio
    try:
        fit.own_weights = ktrans.rigs_match(
            donor_layout, donor_node, host_layout, host_node
        )
        fit.extra_parts = ktrans.auto_merge_candidates(
            donor_layout, donor_node, host_layout, host_node
        )
    except Exception:  # noqa: BLE001
        pass          # both are extra detail, not reasons to lose the measurement
    return fit


def rank(
    host_mdl: bytes,
    host_mdx: bytes,
    library,
    donors,
    *,
    host_name: str = "",
    progress=None,
) -> list[Fit]:
    """Measure every donor against one host, best first.

    `library` is anything with `.has(name)` and `.read(name)` - a `ModelLibrary`
    for either game, so a K1 host can be ranked against K2's models.
    """
    host_layout = kl.parse(host_mdl, host_mdx)
    host_node = head_node(host_layout)
    if host_node is None:
        raise ValueError(f"{host_name or 'host'} has no 'head' node to replace")

    donors = list(donors)
    out: list[Fit] = []
    for i, name in enumerate(donors):
        if progress is not None:
            progress(i, len(donors), name)
        if not library.has(name):
            continue
        try:
            donor_layout = kl.parse(*library.read(name))
        except Exception as exc:  # noqa: BLE001
            out.append(
                Fit(
                    donor=name,
                    donor_node="?",
                    host=host_name,
                    host_node=host_node.name,
                    blocked=f"will not parse: {type(exc).__name__}",
                )
            )
            continue
        node = head_node(donor_layout)
        if node is None:
            continue          # not a donor a head can come from; classify() agrees
        out.append(
            measure(
                host_layout, host_node, donor_layout, node,
                donor_name=name, host_name=host_name,
            )
        )

    out.sort(key=lambda f: f.rank_key)
    return out


def summarise(fits) -> str:
    """A short count by grade, for the top of a report."""
    from collections import Counter

    counts = Counter(f.grade for f in fits)
    order = ["clean", "good", "rough", "hard", "blocked"]
    parts = [f"{counts[g]} {g}" for g in order if counts[g]]
    return ", ".join(parts) if parts else "nothing measured"
