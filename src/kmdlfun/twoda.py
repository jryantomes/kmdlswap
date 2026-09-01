"""Telling the game a new character exists.

A renamed model in Override is a file nothing references. `appearance.2da` is
what turns it into someone the game can spawn, and for a head so is
`heads.2da`.

The pattern here is copied from a mod on this machine that works - the HK
recruit mod - because a working example beats a guess about a format nobody
documents. Two things it does that this follows:

**Append, never edit.** Comparing that mod's tables against the shipped ones
gives 510 rows where the game ships 509, and *zero* changed cells in the rows
that already existed. Every existing appearance keeps its meaning, so nothing
that referenced row 42 yesterday points somewhere else today.

**Copy a row that already works.** An appearance row has fifty-odd columns -
walk speed, drive animations, blood colour, hit radius, per-slot body models -
and a new character wants almost all of them the same as somebody. The mod's
new row is HK-47's with the label, model and texture changed. Filling fifty
columns from first principles is how a character ends up sliding along the
ground.

**Read what is installed, not what shipped.** The tables are loaded through
Override first, so a new row lands on top of whatever mods are already there
rather than reverting them. The consequence is that what this writes is
specific to this install and not something to hand to a stranger - a real
distributable would patch rather than replace, which is a different job.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

HEADS = "heads"
APPEARANCE = "appearance"


class TwoDAError(RuntimeError):
    pass


@dataclass
class Registration:
    """What was written, and what the game will call it."""

    files: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    head_row: int | None = None
    appearance_row: int | None = None
    label: str = ""


def _load(install, name: str):
    """The table as the game would read it: Override first, then the packs."""
    from pykotor.extract.installation import Installation
    from pykotor.resource.formats.twoda import read_2da
    from pykotor.resource.type import ResourceType

    found = Installation(str(install)).resource(name, ResourceType.TwoDA)
    if found is None:
        raise TwoDAError(f"{name}.2da not found in that install")
    return read_2da(found.data)


def _save(table, path: Path) -> None:
    from pykotor.resource.formats.twoda import bytes_2da

    path.write_bytes(bytes_2da(table))


def find_appearance(table, model: str) -> int | None:
    """The row whose body model is `model`, to copy defaults from."""
    wanted = model.lower()
    for i in range(table.get_height()):
        if table.get_cell(i, "race").strip().lower() == wanted:
            return i
    return None


def find_head_row(table, head: str) -> int | None:
    wanted = head.lower()
    for i in range(table.get_height()):
        if table.get_cell(i, "head").strip().lower() == wanted:
            return i
    return None


def register_head(install, out_dir, head_resref: str, *, label: str,
                  like: str = "p_carthh", dressed: bool = True,
                  outfit: Outfit | str | None = None) -> Registration:
    """Add a head model to `heads.2da`, and an appearance that wears it.

    `like` is an existing *head* whose appearance supplies the fifty columns
    this one does not care about - body models, walk speed, blood colour.

    `dressed` repeats one body across every clothing slot, which is what stops
    a new character spawning in the underwear its template wears when nothing
    is equipped. `outfit` says what to repeat - one from `outfits()`, or the
    template's own body if left out. Turn `dressed` off for a party member who
    really should change clothes with their armour.
    """
    out_dir = Path(out_dir)
    reg = Registration(label=label)

    heads = _load(install, HEADS)
    if find_head_row(heads, head_resref) is not None:
        raise TwoDAError(f"{head_resref} is already in heads.2da")
    row = heads.add_row(str(heads.get_height()), {"head": head_resref})
    reg.head_row = row
    reg.notes.append(f"heads.2da: {head_resref} added as row {row}")

    appearance = _load(install, APPEARANCE)
    template = _appearance_using_head(appearance, heads, like)
    if template is None:
        raise TwoDAError(
            f"no appearance wears {like!r}, so there is nothing to copy defaults from"
        )
    new_row = _append_like(appearance, template, {
        "label": label,
        "normalhead": str(row),
    })
    # A backup head is what the game falls back to; pointing it at the new one
    # keeps a damaged state from reverting to whoever was copied.
    if "backuphead" in appearance.get_headers():
        appearance.set_cell(new_row, "backuphead", str(row))
    reg.appearance_row = new_row
    reg.notes.append(
        f"appearance.2da: row {new_row} {label!r}, copied from row {template} "
        f"and pointed at head {row}"
    )
    if dressed:
        note = dress(appearance, new_row, outfit)
        if note:
            reg.notes.append(f"appearance.2da: {note}")

    out_dir.mkdir(parents=True, exist_ok=True)
    for name, table in ((HEADS, heads), (APPEARANCE, appearance)):
        path = out_dir / f"{name}.2da"
        _save(table, path)
        reg.files.append(path)
    return reg


def register_look(install, out_dir, *, label: str, body: str | None = None,
                  outfit=None, head: str | None = None,
                  like: str = "p_carthh") -> Registration:
    """An appearance for a character assembled out of parts already in the game.

    The cheapest kind of new character there is: no geometry is written, no
    model is spliced, and `heads.2da` is only touched if the head is one this
    tool built. A humanoid is `race` + a clothed body per equipment slot +
    a row of `heads.2da`, and all three already exist for a hundred and thirty
    combinations the game itself never ships.

    `body` becomes `race`. `outfit` fills every clothing slot, so what the
    character wears does not depend on what it is carrying. `head` may be a
    vanilla head - in which case its existing row is reused rather than
    duplicated - or a resref this tool has just written, which gets one.
    """
    out_dir = Path(out_dir)
    reg = Registration(label=label)

    heads = _load(install, HEADS)
    head_row = None
    head_is_new = False
    if head:
        head_row = find_head_row(heads, head)
        if head_row is None:
            head_row = heads.add_row(str(heads.get_height()), {"head": head})
            head_is_new = True
            reg.notes.append(f"heads.2da: {head} added as row {head_row}")
        else:
            # Adding a second row for a head the game already knows would work,
            # and would also grow the table by one every time somebody reused
            # a vanilla face.
            reg.notes.append(f"heads.2da: {head} is already row {head_row}, reused")
        reg.head_row = head_row

    appearance = _load(install, APPEARANCE)
    template = _appearance_using_head(appearance, heads, like)
    if template is None:
        template = find_appearance(appearance, like)
    if template is None:
        raise TwoDAError(
            f"nothing in appearance.2da uses {like!r}, so there is nothing to "
            f"copy the fifty columns nobody wants to fill from"
        )

    changes = {"label": label}
    if head_row is not None:
        changes["normalhead"] = str(head_row)
    if body:
        changes["race"] = body
    new_row = _append_like(appearance, template, changes)
    if head_row is not None and "backuphead" in appearance.get_headers():
        appearance.set_cell(new_row, "backuphead", str(head_row))
    reg.appearance_row = new_row

    said = f"appearance.2da: row {new_row} {label!r}, copied from row {template}"
    if body:
        said += f", body {body}"
    if head_row is not None:
        said += f", head row {head_row}"
    reg.notes.append(said)

    note = dress(appearance, new_row, outfit)
    if note:
        reg.notes.append(f"appearance.2da: {note}")

    out_dir.mkdir(parents=True, exist_ok=True)
    # Only write the table that changed. Shipping an unmodified `heads.2da`
    # would still overwrite whatever a person's other mods had put there.
    written = [(APPEARANCE, appearance)]
    if head_is_new:
        written.append((HEADS, heads))
    for name, table in written:
        path = out_dir / f"{name}.2da"
        _save(table, path)
        reg.files.append(path)
    return reg


def register_creature(install, out_dir, model_resref: str, *, label: str,
                      texture: str | None = None,
                      like: str = "p_hk47") -> Registration:
    """Add a self-contained model - one that carries its own head - as an
    appearance of its own. This is the shape the HK recruit mod uses."""
    out_dir = Path(out_dir)
    reg = Registration(label=label)

    appearance = _load(install, APPEARANCE)
    template = find_appearance(appearance, like)
    if template is None:
        raise TwoDAError(f"no appearance uses {like!r} as its model")

    changes = {"label": label, "race": model_resref}
    if texture:
        changes["modela"] = texture
    new_row = _append_like(appearance, template, changes)
    reg.appearance_row = new_row
    reg.notes.append(
        f"appearance.2da: row {new_row} {label!r}, model {model_resref}"
        + (f", texture {texture}" if texture else "")
        + f", copied from row {template}"
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{APPEARANCE}.2da"
    _save(appearance, path)
    reg.files.append(path)
    return reg


SLOTS = "abcdefghi"


@dataclass(frozen=True)
class Outfit:
    """A body model and the texture that goes with it - one thing to wear."""

    model: str
    texture: str
    rows: int = 0
    example: str = ""

    @property
    def label(self) -> str:
        return f"{self.model}  ({self.example})" if self.example else self.model

    def __str__(self) -> str:
        worn = f" - {self.example}" if self.example else ""
        return f"{self.model}{worn}"


def outfits(install, *, library=None) -> list[Outfit]:
    """Every outfit the game already dresses somebody in, commonest first.

    The clothing slots of `appearance.2da` are a wardrobe: 117 distinct
    body-and-texture pairs across the 313 humanoid rows, from Czerka officer to
    Jedi councillor to the generic armour classes. Rather than guess what a new
    character should wear, offer the modder the rack.

    Pass `library` to drop anything whose model is not on disk.
    """
    appearance = _load(install, APPEARANCE)
    headers = appearance.get_headers()
    seen: dict[tuple[str, str], list] = {}

    for row in range(appearance.get_height()):
        if appearance.get_cell(row, "modeltype").strip().upper() != "B":
            continue
        label = appearance.get_cell(row, "label").strip()
        for slot in SLOTS:
            if f"model{slot}" not in headers:
                continue
            model = appearance.get_cell(row, f"model{slot}").strip()
            texture = appearance.get_cell(row, f"tex{slot}").strip()
            if not model or model == "****":
                continue
            entry = seen.setdefault((model.lower(), texture.lower()),
                                    [model, texture, 0, ""])
            entry[2] += 1
            if not entry[3] and label:
                entry[3] = label.replace("_", " ")

    found = [Outfit(m, tx, n, eg) for m, tx, n, eg in seen.values()]
    if library is not None:
        found = [o for o in found if library.has(o.model)]
    return sorted(found, key=lambda o: (-o.rows, o.model.lower()))


def dress(table, row: int, outfit: Outfit | str | None = None) -> str | None:
    """Put the same body in every clothing slot, the way NPCs do.

    A `modeltype B` appearance carries a body model per equipment slot, and the
    game uses `modela` when nothing is equipped. For a party member those are
    real variants - Carth's `modela` is his underwear and `modelb` his jacket -
    so a new character copied from his row and given no clothes spawns in the
    underwear. That is not a missing item; it is the row working as designed
    for somebody else.

    Every plain NPC sidesteps it by repeating one model across all nine slots:
    the Czerka officer is `N_CzerkaOff` nine times, so what he is wearing never
    depends on what he is carrying. This does the same, using the body the row
    already names as its `race`.
    """
    # Duck-typed rather than isinstance: a caller assembling a character hands
    # over a catalogue entry, and requiring it to be this exact class is how
    # two modules end up with two Outfits that are not each other.
    if hasattr(outfit, "model"):
        body = outfit.model
        texture = getattr(outfit, "texture", "") or outfit.model
    else:
        body = (outfit or table.get_cell(row, "race")).strip()
        if not body:
            return None
        # The texture that goes with that body, taken from whichever slot
        # already pairs them, rather than assuming the two share a name -
        # `N_CommM` wears `N_CommMD`.
        texture = body
        for slot in SLOTS:
            column = f"model{slot}"
            if column in table.get_headers() and                     table.get_cell(row, column).strip().lower() == body.lower():
                found = table.get_cell(row, f"tex{slot}").strip()
                if found:
                    texture = found
                break

    for slot in SLOTS:
        for column, value in ((f"model{slot}", body), (f"tex{slot}", texture)):
            if column in table.get_headers():
                table.set_cell(row, column, value)
    return f"wearing {body} ({texture}) in every clothing slot, so what it "            f"wears does not depend on what it is carrying"


def _append_like(table, template: int, changes: dict[str, str]) -> int:
    """A new row carrying every column of `template`, then the changes.

    Explicit rather than a library copy because the point is that *all* fifty
    columns come across: walk speed, drive animations, blood colour, hit
    radius. A new character filled in from first principles is how one ends up
    sliding along the ground.
    """
    cells = {c: table.get_cell(template, c) for c in table.get_headers()}
    cells.update(changes)
    return table.add_row(str(table.get_height()), cells)


def _appearance_using_head(appearance, heads, head_resref: str):
    """An appearance row that wears the named head model."""
    row = find_head_row(heads, head_resref)
    if row is None:
        return None
    wanted = str(row)
    for i in range(appearance.get_height()):
        if appearance.get_cell(i, "normalhead").strip() == wanted:
            return i
    return None
