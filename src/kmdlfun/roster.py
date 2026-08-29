"""Which models make up each K1 companion.

Human companions keep their head in a *separate* model (`p_carthh`), attached to
the body model at runtime. HK-47 and T3-M4 are self-contained, with the head as
a node inside the one model. Anything touching heads therefore has to work on a
per-model basis, not per-character.

Model names are the resrefs to read out of the install; they are listed
explicitly rather than pattern-matched so a typo shows up as "not found in your
install" instead of silently doing nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Companion:
    key: str
    name: str
    models: tuple[str, ...]
    note: str = ""


COMPANIONS: tuple[Companion, ...] = (
    Companion("bastila", "Bastila Shan",
              ("p_bastilaba", "p_bastilabb", "p_bastilabb02", "p_bastilah")),
    Companion("carth", "Carth Onasi",
              ("p_carthba", "p_carthbb", "p_carthbbh", "p_carthh")),
    Companion("mission", "Mission Vao",
              ("p_missionba", "p_missionbb", "p_missionh")),
    Companion("zaalbar", "Zaalbar",
              ("p_zaalbar",), "single self-contained model"),
    Companion("canderous", "Canderous Ordo",
              ("p_candba", "p_candbb", "p_candh")),
    Companion("jolee", "Jolee Bindo",
              ("p_joleeba", "p_joleebb", "p_joleeh")),
    Companion("juhani", "Juhani",
              ("p_juhani", "p_juhaniba", "p_juhanibb", "p_juhanih")),
    Companion("hk47", "HK-47",
              ("p_hk47",), "head is a node inside the body model"),
    Companion("t3m3", "T3-M4",
              ("p_t3m3",), "head is a node inside the body model"),
)

BY_KEY = {c.key: c for c in COMPANIONS}


def resolve(keys: list[str] | None) -> list[Companion]:
    """Turn CLI-style keys into companions. ``None`` or ``["all"]`` means all."""
    if not keys or "all" in keys:
        return list(COMPANIONS)
    unknown = [k for k in keys if k not in BY_KEY]
    if unknown:
        raise KeyError(
            f"unknown companion(s): {', '.join(unknown)}. "
            f"Known: {', '.join(sorted(BY_KEY))}"
        )
    return [BY_KEY[k] for k in keys]
