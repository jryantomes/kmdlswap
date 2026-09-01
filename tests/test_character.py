"""How much a new character needs depends on what it is for.

Learned from two mods on the test machine rather than reasoned about.
`rfk_broker` is a talking NPC and edits no table at all: a stock appearance, no
portrait, the default scripts, a conversation. `hkrfkjr` is a recruitable
companion and carries a custom appearance row, a custom portrait row, henchman
scripts and NoPermDeath.

Treating those the same means either a companion that does not work or an NPC
carrying four files it does not need.
"""

from __future__ import annotations

import pytest

from kmdlfun import character as kchar


def blueprint(path):
    from pykotor.resource.formats.gff import read_gff

    return read_gff(path.read_bytes()).root


def utc(ch):
    return next(p for p in ch.files if p.suffix == ".utc")


def test_a_plain_npc_edits_no_tables(install_path, tmp_path):
    """The cheapest character there is: it wears something already in the game."""
    ch = kchar.create(install_path, tmp_path, resref="my_npc", kind=kchar.NPC,
                      name="Someone")

    assert [p.name for p in ch.files] == ["my_npc.utc"]
    assert not any(p.suffix == ".2da" for p in ch.files)
    assert not ch.todo, "an NPC needs nothing else from anyone"

    root = blueprint(utc(ch))
    assert str(root.value("TemplateResRef")) == "my_npc"
    assert str(root.value("Conversation")) == "", "a plain NPC does not talk"
    assert str(root.value("ScriptDialogue")) == "k_def_dialogue01"


def test_a_talker_is_wired_for_conversation(install_path, tmp_path):
    ch = kchar.create(install_path, tmp_path, resref="my_talker",
                      kind=kchar.TALKER, name="Chatty", model="p_testhead")

    root = blueprint(utc(ch))
    assert str(root.value("Conversation")) == "my_talker"
    assert str(root.value("ScriptDialogue")) == "k_def_dialogue01", (
        "a talker is not a companion; it keeps the default scripts"
    )
    assert root.value("NoPermDeath") == 0
    assert any("dlg" in t for t in ch.todo), "the conversation itself is writing"
    assert not any(p.name == "portraits.2da" for p in ch.files)


def test_a_companion_gets_what_a_companion_needs(install_path, tmp_path):
    """Portrait, henchman scripts and NoPermDeath - the three things the HK
    recruit mod has that the broker does not."""
    ch = kchar.create(install_path, tmp_path, resref="my_mate",
                      kind=kchar.COMPANION, name="My Mate", model="p_testhead")

    names = {p.name for p in ch.files}
    assert "portraits.2da" in names
    assert "appearance.2da" in names and "heads.2da" in names

    root = blueprint(utc(ch))
    assert str(root.value("ScriptDialogue")) == "k_hen_dialogue01"
    assert root.value("NoPermDeath") == 1
    assert root.value("PortraitId") == ch.portrait_row
    assert str(root.value("Conversation")) == "my_mate"
    assert len(ch.todo) >= 2, "the recruit plumbing is still the modder's"


def test_the_three_kinds_differ_in_what_they_write(install_path, tmp_path):
    """A companion writes strictly more; an NPC and a talker write the same
    files and differ in what is *in* them, which is worth stating so the next
    reader does not "fix" it."""
    made = {}
    for kind in kchar.KINDS:
        made[kind] = kchar.create(install_path, tmp_path / kind,
                                  resref=f"x_{kind}", kind=kind,
                                  model="p_testhead")

    npc, talker, companion = (made[k] for k in kchar.KINDS)
    # By extension: the blueprint is named after its own resref, so the
    # filenames differ for a reason that is not the point.
    names = {k: {p.suffix if p.suffix != ".2da" else p.name for p in v.files}
             for k, v in made.items()}

    assert names["npc"] == names["talker"], "same files, different contents"
    assert names["companion"] > names["talker"], "a companion adds the portrait"
    assert "portraits.2da" in names["companion"] - names["talker"]

    # And without a model an NPC writes nothing but its blueprint.
    bare = kchar.create(install_path, tmp_path / "bare", resref="bare",
                        kind=kchar.NPC)
    assert len(bare.files) == 1 < len(npc.files)


def test_a_name_needs_no_tlk_patching(install_path, tmp_path):
    """`hkrfkjr` is called `GH0-RFK` with a literal string rather than a StrRef,
    which is the difference between a rename and patching dialog.tlk."""
    ch = kchar.create(install_path, tmp_path, resref="my_npc", kind=kchar.NPC,
                      name="Zorbo the Magnificent")
    root = blueprint(utc(ch))
    assert "Zorbo the Magnificent" in str(root.value("FirstName"))


def test_an_unknown_kind_is_refused(install_path, tmp_path):
    with pytest.raises(kchar.CharacterError):
        kchar.create(install_path, tmp_path, resref="x", kind="sidekick")


def test_a_model_gives_the_character_its_own_appearance(install_path, tmp_path):
    with_model = kchar.create(install_path, tmp_path / "a", resref="a",
                              kind=kchar.NPC, model="p_testhead")
    without = kchar.create(install_path, tmp_path / "b", resref="b",
                           kind=kchar.NPC)

    assert with_model.appearance_row is not None
    assert without.appearance_row is None
    assert blueprint(utc(with_model)).value("Appearance_Type") == \
        with_model.appearance_row


def test_a_talking_npc_does_not_get_the_wandering_animal_spawn(install_path, tmp_path):
    """`k_def_ambmob` is what `c_bantha` and `c_dewback` run.

    Counted across all 205 vanilla creature blueprints: 52 use it and *none* of
    those hold a conversation. An NPC given it stands in a dialogue running a
    wander loop, which is what broken animation on a talking NPC looks like -
    and it is the one field that differed on the mod this was first copied from.
    """
    for kind in (kchar.NPC, kchar.TALKER):
        ch = kchar.create(install_path, tmp_path / kind, resref=f"n_{kind}",
                          kind=kind)
        spawn = str(blueprint(utc(ch)).value("ScriptSpawn"))
        assert spawn == "k_def_spawn01", f"{kind} got {spawn}"

    ch = kchar.create(install_path, tmp_path / "mate", resref="n_mate",
                      kind=kchar.COMPANION)
    assert str(blueprint(utc(ch)).value("ScriptSpawn")) == "k_hen_spawn01"


def test_the_spawn_scripts_are_ones_vanilla_actually_uses(install_path):
    """Not invented: every value here appears on a shipped blueprint."""
    assert kchar.DEFAULT_SCRIPTS["ScriptSpawn"] == "k_def_spawn01"
    assert kchar.HENCHMAN_SCRIPTS["ScriptSpawn"] == "k_hen_spawn01"
    assert "ambmob" not in str(kchar.DEFAULT_SCRIPTS)
