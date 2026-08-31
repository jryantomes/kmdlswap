"""Sorting donors into male, female and droid.

A list of 164 models in alphabetical order does not answer the question anyone
actually has, which is "show me the female heads". Four sources answer it, and
they are consulted in this order because that is the order of how much they can
be trusted.

**1. Whether it is a droid is structural, and exact.** A droid's head node is
rigid and its model carries no facial bones - the `f_*_g` gimbals that drive a
mouth and brows. Across all 77 KOTOR 1 models with a head node, "rigid head and
no facial bones" selects exactly the ten droids, with no misses and no false
positives. Nothing is guessed from a name.

**2. The companions are curated, because the game's own data is wrong about
them.** `portraits.2da` marks `po_pjolee` as sex 1, and Jolee Bindo is male;
`po_pcarth` has no appearance number at all, so Carth resolves to nothing.
Both rows have `forpc=0`. There are nine companions and everyone knows who they
are, so they are written down rather than inferred.

**3. `portraits.2da`, but only where `forpc=1`.** Those thirty rows are the
player-creation heads and every one of them is right: `pfh*` is sex 1, `pmh*`
is sex 0. The `forpc=0` rows are the ones nobody maintained, so they are
ignored entirely rather than trusted and occasionally wrong.

**4. Names, last and conservatively.** `comm_a_f` and `n_childfh` say what they
are. Substring matching is a trap here - "Malak" contains "mal" - so only
whole-token patterns count, and anything still unresolved stays `unknown`
rather than being guessed.

"Either" is a real answer, not a shrug. Revan is the player character and can
be male or female, so one head model is worn by both bodies; filtering to
female includes it, because it genuinely is a female Revan's face. `unknown` is
kept for the different case of having no evidence at all.

What is deliberately *not* used: the supermodel. It looks like it should say -
until you notice `S_Female02` is the supermodel of `p_carthh`, `n_dustilh` and
`pmhc01`, all of them male. It names an animation set, not a person.
"""

from __future__ import annotations

import re

MALE = "male"
FEMALE = "female"
DROID = "droid"
# Not "we could not tell" but "it is deliberately both". Revan is the player
# character and can be either, so one head model is worn by `N_DarthRevanM` and
# `N_DarthRevanF` alike. Filtering to male or to female both include these,
# because such a head genuinely is a valid choice for either.
EITHER = "either"
UNKNOWN = "unknown"

LOOKS = (MALE, FEMALE, EITHER, DROID, UNKNOWN)


def matches(look: str, wanted: str) -> bool:
    """Does a model of this look belong in a list filtered to `wanted`?"""
    if wanted in (MALE, FEMALE) and look == EITHER:
        return True
    return look == wanted


def is_droid(layout) -> bool:
    """A rigid head and no facial bones.

    Measured across every KOTOR 1 model with a head node: this is true of all
    ten droids and of nothing else. An organic head either is skinned or brings
    the `f_*_g` gimbals that drive its face, and usually both.
    """
    from . import compat

    head = compat.head_node(layout)
    if head is None or head.is_skin:
        return False
    return not any(
        n.name.lower().startswith("f_") and n.name.lower().endswith("_g")
        for n in layout.nodes
    )


def _from_roster() -> dict[str, str]:
    """The companions, written down. See the module docstring for why."""
    from . import roster

    out = {}
    for c in roster.COMPANIONS:
        if not c.look:
            continue
        for model in c.models:
            out[model.lower()] = c.look
    return out


def _from_portraits(install) -> dict[str, str]:
    """Player-creation heads, from the game's own tables.

    Only `forpc=1` rows are read. The rest of that column was never maintained
    and gets party members wrong.
    """
    try:
        from pykotor.extract.installation import Installation
        from pykotor.resource.formats.twoda import read_2da
        from pykotor.resource.type import ResourceType

        inst = Installation(str(install))

        def table(name):
            found = inst.resource(name, ResourceType.TwoDA)
            return read_2da(found.data) if found else None

        app, heads, port = table("appearance"), table("heads"), table("portraits")
        if not (app and heads and port):
            return {}

        head_of = {}
        for i in range(heads.get_height()):
            value = heads.get_cell(i, "head").strip()
            if value:
                head_of[i] = value.lower()

        head_for_appearance = {}
        for i in range(app.get_height()):
            nh = app.get_cell(i, "normalhead").strip()
            if nh.isdigit() and int(nh) in head_of:
                head_for_appearance[i] = head_of[int(nh)]

        out = {}
        for i in range(port.get_height()):
            if port.get_cell(i, "forpc").strip() != "1":
                continue
            number = port.get_cell(i, "appearancenumber").strip()
            sex = port.get_cell(i, "sex").strip()
            if number.isdigit() and sex.isdigit():
                head = head_for_appearance.get(int(number))
                if head:
                    out[head] = FEMALE if int(sex) == 1 else MALE
        return out
    except Exception:  # noqa: BLE001
        return {}


def _from_body(install) -> dict[str, str]:
    """The body a head is worn with, which is named for what it is.

    `appearance.2da` pairs each head with a body model, and the generic bodies
    carry the sex in their name: Dustil wears `N_SithComM`, Davik, Gadon and
    Vrook all wear `N_CommM`. This reaches the named NPCs, which nothing else
    does - no table records their sex directly.

    A head worn by both bodies is reported as `EITHER`, not as a guess and not
    as unknown: `n_darthrevanh` is worn with `N_DarthRevanM` and
    `N_DarthRevanF` because Revan is the player character and can be either,
    so that head really is a valid choice for both.

    That reading is only trusted when nothing better has an opinion. Two other
    heads are worn by both - `comm_w_m` and `pmhc02` - and both are male heads
    the game reused on a female NPC body. Their own name and `portraits.2da`
    say male, and those are consulted first.
    """
    try:
        from pykotor.extract.installation import Installation
        from pykotor.resource.formats.twoda import read_2da
        from pykotor.resource.type import ResourceType

        inst = Installation(str(install))

        def table(name):
            found = inst.resource(name, ResourceType.TwoDA)
            return read_2da(found.data) if found else None

        app, heads = table("appearance"), table("heads")
        if not (app and heads):
            return {}

        head_of = {}
        for i in range(heads.get_height()):
            value = heads.get_cell(i, "head").strip()
            if value:
                head_of[i] = value.lower()

        seen: dict[str, set] = {}
        for i in range(app.get_height()):
            nh = app.get_cell(i, "normalhead").strip()
            if not (nh.isdigit() and int(nh) in head_of):
                continue
            body = app.get_cell(i, "race").strip()
            # A trailing M or F, and only that: `P_CarthBB` ends in B and says
            # nothing.
            match = re.search(r"(?:^|[a-z])([MF])$", body)
            if match:
                seen.setdefault(head_of[int(nh)], set()).add(
                    MALE if match.group(1) == "M" else FEMALE
                )
        return {head: (next(iter(s)) if len(s) == 1 else EITHER)
                for head, s in seen.items()}
    except Exception:  # noqa: BLE001
        return {}


# Whole tokens only. Substrings are a trap: "Malak" contains "mal", and
# "female" contains "male".
_FEMALE_NAME = re.compile(
    r"(?:^|_)f(?:$|\d|_)|_f\d*$|fh\d*$|female|(?:^|_)fem"
    # `n_wookief`, `n_tuskenf`, `n_darkjedif`: a bare trailing f after a word.
    r"|[a-z]{4,}f$"
)
_MALE_NAME = re.compile(
    r"(?:^|_)m(?:$|\d|_)|_m\d*$|mh\d*$|(?<!fe)male"
    r"|[a-z]{4,}m$"
)


def _from_name(name: str) -> str | None:
    n = name.lower()
    # Player-creation heads say it plainly: p f h c 01 / p m h c 01.
    pc = re.match(r"^p([fm])h[a-z]", n)
    if pc:
        return FEMALE if pc.group(1) == "f" else MALE
    if _FEMALE_NAME.search(n):
        return FEMALE
    if _MALE_NAME.search(n):
        return MALE
    return None


def looks(install, names=None, *, library=None, progress=None) -> dict[str, str]:
    """Sort models into male, female, droid or unknown.

    `install` is a game folder; `library` may be supplied to avoid rebuilding a
    `ModelLibrary` that the caller already has.
    """
    from kmdlswap import layout as kl

    from .library import ModelLibrary

    lib = library or ModelLibrary(install)
    wanted = list(names if names is not None else lib.index)

    curated = _from_roster()
    portraits = _from_portraits(install)
    bodies = _from_body(install)

    out: dict[str, str] = {}
    for i, name in enumerate(wanted):
        if progress is not None:
            progress(i, len(wanted), name)
        key = name.lower()

        # Structural first: it is the only one of these that cannot be wrong.
        try:
            if is_droid(kl.parse(*lib.read(name))):
                out[name] = DROID
                continue
        except Exception:  # noqa: BLE001
            pass

        # A head worn by both bodies is only "either" when nothing better has
        # an opinion. `comm_w_m` and `pmhc02` are worn by a female body too,
        # but they are male heads the game reused - and their own name, or
        # `portraits.2da`, says so plainly.
        body = bodies.get(key)
        out[name] = (curated.get(key)
                     or portraits.get(key)
                     or (body if body != EITHER else None)
                     or _from_name(key)
                     or body
                     or UNKNOWN)
    return out


def summarise(looked: dict[str, str]) -> str:
    from collections import Counter

    counts = Counter(looked.values())
    return ", ".join(f"{counts[k]} {k}" for k in LOOKS if counts[k])
