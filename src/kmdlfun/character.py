"""Turning a model into somebody the game can place.

A model and an appearance row are not a character. A character is a **creature
blueprint** - a `.utc` - and how much else it needs depends entirely on what it
is for. That distinction was learned from two mods installed on the test
machine rather than reasoned about:

`rfk_broker.utc`, a plain talking NPC, is 3,231 bytes and needs almost nothing:
a stock `Appearance_Type` of 198, `PortraitId` 0, the default `k_def_*`
scripts, and a conversation. No table was edited for it at all.

`hkrfkjr.utc`, a recruitable companion, carries a custom appearance row, a
custom portrait row, the henchman `k_hen_*` scripts, `NoPermDeath`, and a pile
of recruit scripts and journal entries around it.

So there are three answers, not one:

* **npc** - a body in the world. An appearance row if it wears a custom model,
  a blueprint, and nothing else.
* **talker** - the same, wired for conversation. The `.dlg` itself is writing,
  not tooling, so the blueprint points at one and says so.
* **companion** - the above plus a portrait row, henchman scripts and
  `NoPermDeath`. The recruit script, the party slot and the journal are still
  the modder's; what is generated is the part that is mechanical.

One thing worth knowing, because it saves patching `dialog.tlk`: a name can be
a literal string rather than a StrRef. `hkrfkjr` is called `GH0-RFK` that way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

NPC = "npc"
TALKER = "talker"
COMPANION = "companion"
KINDS = (NPC, TALKER, COMPANION)

# The spawn script decides how a creature behaves once it exists, and picking
# the wrong one is not a subtle mistake: `k_def_ambmob` is the ambient-mobile
# script, used by 52 vanilla blueprints of which **none** hold a conversation.
# Its examples are `c_bantha`, `c_brith`, `c_dewback` - it is what wandering
# animals run. An NPC given it stands in a conversation running a wander loop,
# which reads as broken animation.
#
# Every vanilla NPC that talks uses `k_def_spawn01`, or `k_hen_spawn01` if it
# is a party member. Counted across all 205 shipped creature blueprints.
DEFAULT_SCRIPTS = {
    "ScriptDialogue": "k_def_dialogue01",
    "ScriptSpawn": "k_def_spawn01",
    "ScriptHeartbeat": "k_def_heartbt01",
    "ScriptAttacked": "k_def_attacked01",
}
# Companions run the henchman set instead; `rfk_broker` uses the default one
# and `hkrfkjr` this one, which is how the difference was found.
HENCHMAN_SCRIPTS = {
    "ScriptDialogue": "k_hen_dialogue01",
    "ScriptSpawn": "k_hen_spawn01",
    "ScriptHeartbeat": "k_hen_heartbt01",
}

STOCK_TEMPLATE = "n_duros001"


class CharacterError(RuntimeError):
    pass


@dataclass
class Character:
    kind: str
    resref: str
    files: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    todo: list[str] = field(default_factory=list)
    appearance_row: int | None = None
    portrait_row: int | None = None


def create(install, out_dir, *, resref: str, kind: str = NPC,
           name: str | None = None, model: str | None = None,
           label: str | None = None, like: str = "p_carthh",
           template: str = STOCK_TEMPLATE, outfit=None) -> Character:
    """Write the files a new character of `kind` needs.

    `model` is a head resref this character should wear - the thing a build
    just produced. Without one it reuses whatever the template blueprint wore,
    which is the cheapest kind of NPC and edits no tables at all.

    `outfit` is what the body wears - one of `twoda.outfits()`, or a body
    model resref. Left out, it wears the template's own body, and the reason
    to set it is that a party member's row dresses differently from an NPC's:
    Carth's unequipped slot is his underwear, so a character copied from him
    and given no clothes spawns in it.
    """
    if kind not in KINDS:
        raise CharacterError(f"{kind!r} is not one of {', '.join(KINDS)}")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ch = Character(kind=kind, resref=resref)
    label = label or resref

    appearance_id = None
    if model:
        from . import twoda as k2da

        reg = k2da.register_head(install, out_dir, model, label=label,
                                 like=like, outfit=outfit)
        appearance_id = reg.appearance_row
        ch.appearance_row = reg.appearance_row
        ch.files.extend(reg.files)
        ch.notes.extend(reg.notes)
    else:
        ch.notes.append(
            "no custom model, so it wears the template's appearance and no "
            "table is edited"
        )

    if kind == COMPANION:
        portrait = _register_portrait(install, out_dir, resref, appearance_id)
        if portrait is not None:
            ch.portrait_row, path, note = portrait
            if path not in ch.files:
                ch.files.append(path)
            ch.notes.append(note)

    path, note = _blueprint(
        install, out_dir, resref=resref, kind=kind, name=name or label,
        appearance_id=appearance_id, portrait_id=ch.portrait_row,
        template=template,
    )
    ch.files.append(path)
    ch.notes.append(note)

    if kind in (TALKER, COMPANION):
        ch.todo.append(
            f"write {resref}.dlg - the blueprint points at it, but a "
            f"conversation is writing rather than tooling"
        )
    if kind == COMPANION:
        ch.todo.append(
            "a companion still needs a recruit script, a party slot and "
            "journal entries; those are yours"
        )
    return ch


def _register_portrait(install, out_dir, resref, appearance_id):
    """Companions show a portrait in the party screen; NPCs do not have one."""
    from pykotor.resource.formats.twoda import bytes_2da

    from . import twoda as k2da

    table = k2da._load(install, "portraits")
    template = 0
    cells = {c: table.get_cell(template, c) for c in table.get_headers()}
    # A resref is 16 characters, and a name cut mid-word looks like a bug.
    cells["baseresref"] = f"po_{resref.lower()}"[:16]
    if appearance_id is not None and "appearancenumber" in cells:
        cells["appearancenumber"] = str(appearance_id)
    if "forpc" in cells:
        cells["forpc"] = "0"
    row = table.add_row(str(table.get_height()), cells)

    path = out_dir / "portraits.2da"
    path.write_bytes(bytes_2da(table))
    return row, path, (f"portraits.2da: row {row} {cells['baseresref']!r} "
                       f"(supply that image, or the party screen shows nothing)")


def _blueprint(install, out_dir, *, resref, kind, name, appearance_id,
               portrait_id, template):
    """A `.utc`, copied from a stock one so the fifty fields nobody edits are right."""
    from pykotor.common.language import LocalizedString
    from pykotor.extract.installation import Installation
    from pykotor.resource.formats.gff import bytes_gff, read_gff
    from pykotor.resource.type import ResourceType

    found = Installation(str(install)).resource(template, ResourceType.UTC)
    if found is None:
        raise CharacterError(f"no blueprint {template!r} to copy from")
    data = found.data if isinstance(found.data, (bytes, bytearray)) else found.data()

    gff = read_gff(data)
    root = gff.root
    resref_type = type(root.value("TemplateResRef"))

    root.set_resref("TemplateResRef", resref_type(resref))
    root.set_string("Tag", resref.upper()[:32])
    root.set_locstring("FirstName", LocalizedString.from_english(name))
    if appearance_id is not None:
        root.set_uint16("Appearance_Type", appearance_id)

    scripts = dict(DEFAULT_SCRIPTS)
    if kind == COMPANION:
        scripts.update(HENCHMAN_SCRIPTS)
        root.set_uint8("NoPermDeath", 1)
        if root.exists("BodyBag"):
            root.set_uint8("BodyBag", 1)
    for field_name, value in scripts.items():
        if root.exists(field_name):
            root.set_resref(field_name, resref_type(value))

    if kind in (TALKER, COMPANION):
        root.set_resref("Conversation", resref_type(resref))
    elif root.exists("Conversation"):
        root.set_resref("Conversation", resref_type(""))

    if portrait_id is not None and root.exists("PortraitId"):
        root.set_uint16("PortraitId", portrait_id)

    path = out_dir / f"{resref}.utc"
    path.write_bytes(bytes_gff(gff))
    return path, (f"{path.name}: a {kind} named {name!r}"
                  + (f", appearance {appearance_id}" if appearance_id is not None
                     else ", wearing the template's appearance"))
