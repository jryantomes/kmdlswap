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
    # Written down rather than read from the game, because the game is wrong
    # about two of them: portraits.2da marks Jolee as sex 1, and Carth's row
    # has no appearance number at all. See `who.py`.
    look: str = ""


COMPANIONS: tuple[Companion, ...] = (
    Companion("bastila", "Bastila Shan",
              ("p_bastilaba", "p_bastilabb", "p_bastilabb02", "p_bastilah"), look="female"),
    Companion("carth", "Carth Onasi",
              ("p_carthba", "p_carthbb", "p_carthbbh", "p_carthh"), look="male"),
    Companion("mission", "Mission Vao",
              ("p_missionba", "p_missionbb", "p_missionh"), look="female"),
    Companion("zaalbar", "Zaalbar",
              ("p_zaalbar",), "single self-contained model", look="male"),
    Companion("canderous", "Canderous Ordo",
              ("p_candba", "p_candbb", "p_candh"), look="male"),
    Companion("jolee", "Jolee Bindo",
              ("p_joleeba", "p_joleebb", "p_joleeh"), look="male"),
    Companion("juhani", "Juhani",
              ("p_juhani", "p_juhaniba", "p_juhanibb", "p_juhanih"), look="female"),
    Companion("hk47", "HK-47",
              ("p_hk47",), "head is a node inside the body model", look="droid"),
    Companion("t3m3", "T3-M4",
              ("p_t3m3",), "head is a node inside the body model", look="droid"),
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


def default_look(models, is_head) -> tuple[str | None, str | None]:
    """The body and head a companion is normally seen in.

    A companion ships several models - Carth has an underwear body, a clothed
    one, a spare head and his own - and listing order is not preference. A
    preview showing him in his underwear with the wrong face answers a question
    nobody asked.

    Bodies ending `bb` are the clothed default; `ba` is the underlayer. Among
    heads the plain `p_<name>h` is the character's own, and the longer names are
    variants, so the shortest wins.
    """
    heads = sorted((m for m in models if is_head(m)), key=lambda m: (len(m), m))
    bodies = [m for m in models if not is_head(m)]
    clothed = [m for m in bodies if m.lower().endswith("bb")]
    return (clothed[0] if clothed else (bodies[0] if bodies else None),
            heads[0] if heads else None)
