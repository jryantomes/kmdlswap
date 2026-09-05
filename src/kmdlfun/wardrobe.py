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
    """A head model and the `heads.2da` row that names it.

    `game` is empty for a head the target install already has, and holds the
    other game's install path for one borrowed from it. A borrowed head needs
    its model shipping alongside the table rows, because a row can only name a
    model the game can find - see `heads_from`.
    """

    model: str
    row: int
    look: str = "unknown"
    game: str = ""
    # "" for a head this install already has, "k2" for one borrowed from KOTOR
    # II, "jade" for one that has to be converted before it is a head at all.
    source: str = ""

    @property
    def label(self) -> str:
        if not self.game:
            return self.model
        return f"{self.model}  ({'Jade Empire' if self.source == 'jade' else 'KOTOR II'})"


@dataclass
class Body:
    """A base body, and everything the game has been seen to put on it."""

    model: str
    label: str = ""
    rows: int = 0
    look: str = "unknown"
    outfits: list[Outfit] = field(default_factory=list)
    heads: list[int] = field(default_factory=list)
    # Whether the game's own character creator offers this body. See
    # `_player_rows`.
    player: bool = False

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
    player_rows = _player_rows(install)

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

        if not race and row in player_rows:
            # The character-creation rows leave `race` blank - the player's
            # base body is not a race, it is the underwear the outfit slots
            # dress over. Slot A is that body: `PFBAS`, `PMBAM` and the rest.
            race = appearance.get_cell(row, "modela").strip()
        if not race or race == "****":
            continue
        body = bodies.setdefault(race.lower(), Body(model=race, label=label))
        body.rows += 1
        if row in player_rows:
            body.player = True
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


def _player_rows(install) -> set[int]:
    """The `appearance.2da` rows the game's own character creator offers.

    Not guessed from names. `portraits.2da` is the character-creation screen:
    every row with `forpc = 1` is a portrait a new player can pick, and its
    `appearance_s`, `appearancenumber` and `appearance_l` columns name that
    portrait's small, medium and large appearance rows. In KOTOR that is 90
    rows resolving to six bodies - `PFBA` and `PMBA` in each of three builds.

    They are worth singling out because they are the best-supported bodies in
    the game: each is paired with fifteen heads in the shipped tables and wears
    the complete nine-class wardrobe in its own build, which no other body
    does. Everything else is one character's costume.
    """
    from . import twoda as k2da

    try:
        table = k2da._load(install, "portraits")
    except Exception:  # noqa: BLE001
        return set()          # a catalogue without this still works
    headers = set(table.get_headers())
    columns = [c for c in ("appearance_s", "appearancenumber", "appearance_l")
               if c in headers]
    if "forpc" not in headers or not columns:
        return set()
    rows = set()
    for row in range(table.get_height()):
        if table.get_cell(row, "forpc").strip() != "1":
            continue
        for column in columns:
            value = table.get_cell(row, column).strip()
            if value.isdigit():
                rows.add(int(value))
    return rows


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
        if body.player:
            # `P_FEM_A_LRG_01` is the row's name for itself and says nothing a
            # person picking a body wants to know. The build has to stay in the
            # label: pickers key on it, and "player female" alone is the same
            # string for all three female builds, which silently collapsed six
            # bodies into two.
            body.label = " ".join(
                x for x in ("player", body.look if body.look != "unknown" else "",
                            body.build) if x)
    cat.heads = [Head(h.model, h.row, cat.look_of(h.model), h.game)
                 for h in cat.heads]


def jade_heads(jade_install, *, limit: int | None = None) -> list[Head]:
    """Heads Jade Empire has, which no KOTOR install does.

    Different from `heads_from` in the one way that matters: a KOTOR II head is
    already a KOTOR model and only has to be copied, while a Jade head is not a
    model this engine can load at all. Every structure in the format is a
    different size, so it has to be converted to geometry and built into a host
    head before the game has anything to name. The row is filled in at build
    time like any other borrowed head.
    """
    from . import jade as kjade

    try:
        entries = kjade.catalogue(jade_install, kinds=(kjade.HEAD,))
    except Exception:  # noqa: BLE001 - no Jade install is not an error
        return []
    if limit is not None:
        entries = entries[:limit]
    return [Head(model=e.resref, row=-1, look="unknown",
                 game=str(jade_install), source="jade") for e in entries]


def heads_from(other_install, *, avoiding=(), library=None) -> list[Head]:
    """Heads the *other* game has that this one does not.

    A KOTOR II head can be worn in KOTOR, but only if the model travels with
    the table rows: an appearance row names a model by resref, and a resref the
    game cannot find leaves an invisible head.

    Names that exist in both are skipped, and that is not a nicety. Measured
    across the two installs: 108 heads in KOTOR, 151 in KOTOR II, and **78 names
    in common**. Shipping one of those into Override would not add a head - it
    would replace KOTOR's own, for every character already using it. The 73 that
    are unique to KOTOR II are the ones that can be offered safely.
    """
    from . import library as klib
    from . import who as kwho

    taken = {str(n).lower() for n in avoiding}
    names = [m for m in sorted(klib.head_models(other_install))
             if m.lower() not in taken]

    # Sexed against the game they come from, not this one. Without it every
    # borrowed head is "unknown", and `who.matches` reads unknown as no answer
    # rather than any answer - so setting the picker to male or female emptied
    # the list of all of them, which looks like the tool refusing a KOTOR II
    # head rather than filtering it away.
    looks = {}
    try:
        looks = kwho.looks(other_install, names,
                           library=klib.ModelLibrary(other_install))
    except Exception:  # noqa: BLE001
        pass            # unknown is still a usable answer, just a worse one

    # Row -1: it has no row in *this* game's table yet. `register_look` adds one
    # when the character is created.
    return [Head(model=m, row=-1, look=looks.get(m, "unknown"),
                 game=str(other_install), source="k2") for m in names]
