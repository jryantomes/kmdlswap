"""The three things a character is made of, and what the game pairs with what.

Not to be confused with `catalogue.py`, which indexes model *files*, or
`parts.py`, which classifies the mesh nodes inside one. This is about what a
character wears and whose face it has.

A KOTOR humanoid is assembled, not authored. `appearance.2da` names a base body
in `race`, a clothed body per equipment slot, and a row of `heads.2da` in
`normalhead`; the model files are shared between hundreds of characters. So a
new character does not need new geometry at all - it needs a body, an outfit
and a head, and three rows saying which.

Every relationship here is read out of the shipped tables rather than guessed.
A row that says `race = N_TwilekF` and `normalhead = 74` is the game telling us
that head belongs on that body, and a slot model sitting in the same row is it
telling us that body wears that outfit. So each part knows what it has actually
been seen with, and the tool can put a Twi'lek head on a Czerka uniform while
still being able to say that nothing in the game ever did.

The player bodies are the one family with a *designed* split, and it is worth
knowing because it is the clearest illustration of the three axes:
`P{M|F}B{A..I}{S|M|L}` is sex, then armour class, then build. Nine outfits
across three physiques, twice over.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# One Outfit, declared where it is written rather than where it is browsed.
# Two modules each defining their own is how `dress` ends up refusing the
# catalogue entry the picker just handed it.
from .twoda import Outfit

SLOTS = "abcdefghi"
BODY_TYPE = "B"          # a body that takes a separate head
SELF_CONTAINED = "F"     # carries its own head and can never wear another

# P M B C M  ->  player, male, body, armour class C, medium build
BUILDS = {"S": "small", "M": "medium", "L": "large"}


@dataclass(frozen=True)
class Head:
    """A head model and the `heads.2da` row that names it."""

    model: str
    row: int
    look: str = "unknown"

    @property
    def label(self) -> str:
        return self.model


@dataclass
class Body:
    """A base body, and everything the game has been seen to put on it."""

    model: str
    label: str = ""
    rows: int = 0
    look: str = "unknown"
    outfits: list[Outfit] = field(default_factory=list)
    heads: list[int] = field(default_factory=list)

    @property
    def build(self) -> str:
        """small / medium / large, for the player bodies that encode it."""
        name = self.model.upper()
        if len(name) == 5 and name.startswith(("PMB", "PFB")):
            return BUILDS.get(name[4], "")
        return ""

    @property
    def display(self) -> str:
        bits = [self.model]
        if self.label and self.label.lower() != self.model.lower():
            bits.append(f"({self.label})")
        if self.build:
            bits.append(f"- {self.build}")
        return "  ".join(bits)


@dataclass
class Catalogue:
    """Everything on offer, and which combinations the game already ships."""

    bodies: list[Body] = field(default_factory=list)
    outfits: list[Outfit] = field(default_factory=list)
    heads: list[Head] = field(default_factory=list)
    # Model name -> male / female / droid / unknown, for every part of every
    # kind. An outfit is a body model and so has a sex the same way a body
    # does; without this, filtering the wardrobe to "female" empties it.
    looks: dict = field(default_factory=dict)

    def look_of(self, model) -> str:
        name = getattr(model, "model", model)
        return self.looks.get(str(name).lower(), "unknown")

    def body(self, model: str) -> Body | None:
        want = (model or "").strip().lower()
        return next((b for b in self.bodies if b.model.lower() == want), None)

    def head(self, model: str) -> Head | None:
        want = (model or "").strip().lower()
        return next((h for h in self.heads if h.model.lower() == want), None)

    def outfit(self, model: str) -> Outfit | None:
        want = (model or "").strip().lower()
        return next((o for o in self.outfits if o.model.lower() == want), None)

    def heads_for(self, body: Body | str | None) -> list[Head]:
        """Heads first, vanilla-compatible ones in front.

        Not a filter. The whole reason to reach for this tool is a combination
        the game does not ship, so forbidding those would forbid the point;
        what it can do is say which ones are already known to work.
        """
        found = body if isinstance(body, Body) else self.body(body or "")
        if found is None:
            return list(self.heads)
        seen = set(found.heads)
        return sorted(self.heads, key=lambda h: (h.row not in seen, h.model.lower()))

    def outfits_for(self, body: Body | str | None) -> list[Outfit]:
        """Outfits, the ones this body is already dressed in first."""
        found = body if isinstance(body, Body) else self.body(body or "")
        if found is None:
            return list(self.outfits)
        seen = {o.model.lower() for o in found.outfits}
        return sorted(self.outfits,
                      key=lambda o: (o.model.lower() not in seen, -o.rows,
                                     o.model.lower()))

    def pairs_with(self, body: Body | str | None, *, head=None, outfit=None) -> bool:
        """Has the game itself ever put these together?"""
        found = body if isinstance(body, Body) else self.body(body or "")
        if found is None:
            return False
        if head is not None:
            row = head.row if isinstance(head, Head) else self.head(str(head))
            row = row.row if isinstance(row, Head) else row
            return row in found.heads
        if outfit is not None:
            name = outfit.model if isinstance(outfit, Outfit) else str(outfit)
            return name.lower() in {o.model.lower() for o in found.outfits}
        return False


def build(install, *, library=None) -> Catalogue:
    """Read the tables and work out what goes with what.

    Pass `library` to drop anything whose model is not on disk - a part that
    cannot be drawn cannot be previewed, and a part that cannot be loaded
    cannot be worn.
    """
    from . import twoda as k2da

    appearance = k2da._load(install, k2da.APPEARANCE)
    heads_table = k2da._load(install, k2da.HEADS)
    headers = appearance.get_headers()

    cat = Catalogue()
    cat.heads = _read_heads(heads_table, library)
    known_rows = {h.row for h in cat.heads}

    bodies: dict[str, Body] = {}
    outfits: dict[tuple[str, str], list] = {}

    for row in range(appearance.get_height()):
        if appearance.get_cell(row, "modeltype").strip().upper() != BODY_TYPE:
            continue
        label = appearance.get_cell(row, "label").strip().replace("_", " ")
        race = appearance.get_cell(row, "race").strip()
        head_row = appearance.get_cell(row, "normalhead").strip()

        worn = []
        for slot in SLOTS:
            if f"model{slot}" not in headers:
                continue
            model = appearance.get_cell(row, f"model{slot}").strip()
            texture = appearance.get_cell(row, f"tex{slot}").strip()
            if not model or model == "****":
                continue
            entry = outfits.setdefault((model.lower(), texture.lower()),
                                       [model, texture, 0, ""])
            entry[2] += 1
            if not entry[3] and label:
                entry[3] = label
            worn.append((model, texture))

        if not race:
            continue
        body = bodies.setdefault(race.lower(), Body(model=race, label=label))
        body.rows += 1
        if head_row.isdigit() and int(head_row) in known_rows:
            if int(head_row) not in body.heads:
                body.heads.append(int(head_row))
        for model, texture in worn:
            if not any(o.model.lower() == model.lower() for o in body.outfits):
                body.outfits.append(Outfit(model, texture))

    cat.outfits = sorted(
        (Outfit(m, tx, n, eg) for m, tx, n, eg in outfits.values()),
        key=lambda o: (-o.rows, o.model.lower()),
    )
    cat.bodies = sorted(bodies.values(), key=lambda b: b.model.lower())

    if library is not None:
        cat.outfits = [o for o in cat.outfits if library.has(o.model)]
        cat.bodies = [b for b in cat.bodies if library.has(b.model)]
        for body in cat.bodies:
            body.outfits = [o for o in body.outfits if library.has(o.model)]

    _classify(cat, install, library)
    return cat


def _read_heads(table, library) -> list[Head]:
    found = []
    for row in range(table.get_height()):
        model = table.get_cell(row, "head").strip()
        if not model or (library is not None and not library.has(model)):
            continue
        found.append(Head(model=model, row=row))
    return found


def _classify(cat: Catalogue, install, library) -> None:
    """Male / female / droid, through the same reader the donor lists use.

    One pass over every part rather than a lookup each, because the classifier
    reads `portraits.2da` and `appearance.2da` to make up its mind and doing
    that per name would read them a hundred and fifty times.

    The player bodies are the exception: they carry the sex in their own name,
    `PMB...` against `PFB...`, and that beats anything inferred. `who` refuses
    to guess elsewhere, and unknown is a real answer that filters nothing out.
    """
    from . import who as kwho

    names = sorted({p.model for p in
                    (*cat.bodies, *cat.outfits, *cat.heads)})
    try:
        looked = kwho.looks(install, names, library=library)
    except Exception:  # noqa: BLE001
        return              # a catalogue without sexes still works

    cat.looks = {name.lower(): look for name, look in looked.items()}
    # The player bodies carry their own sex - `PMB...` against `PFB...` - and
    # their own name beats anything inferred from who wears them.
    for name in list(cat.looks):
        upper = name.upper()
        if len(upper) == 5 and upper.startswith(("PMB", "PFB")):
            cat.looks[name] = kwho.MALE if upper[1] == "M" else kwho.FEMALE

    for body in cat.bodies:
        body.look = cat.look_of(body.model)
    cat.heads = [Head(h.model, h.row, cat.look_of(h.model)) for h in cat.heads]
