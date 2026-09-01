"""Telling the game a new character exists.

A renamed model in Override is a file nothing references. These rows are what
make it reachable, and the pattern is taken from a working mod on the test
machine rather than guessed: append, never edit, and copy a row that already
works.
"""

from __future__ import annotations

import pytest

from kmdlfun import twoda as k2da


@pytest.fixture
def out(tmp_path):
    return tmp_path


def read(path):
    from pykotor.resource.formats.twoda import read_2da

    return read_2da(path.read_bytes())


# --- adding a head ----------------------------------------------------------


def test_a_new_head_gets_a_row_and_an_appearance_that_wears_it(install_path, out):
    reg = k2da.register_head(install_path, out, "p_testhead",
                             label="Test_Head", like="p_carthh")

    heads = read(out / "heads.2da")
    appearance = read(out / "appearance.2da")

    assert heads.get_cell(reg.head_row, "head") == "p_testhead"
    assert appearance.get_cell(reg.appearance_row, "label") == "Test_Head"
    assert appearance.get_cell(reg.appearance_row, "normalhead") == str(reg.head_row)
    assert {p.name for p in reg.files} == {"heads.2da", "appearance.2da"}


def test_nothing_that_already_existed_is_touched(install_path, out):
    """Rows are addressed by index. Changing one silently re-points every
    creature, script and save that referenced it."""
    before_heads = k2da._load(install_path, "heads")
    before_app = k2da._load(install_path, "appearance")

    k2da.register_head(install_path, out, "p_testhead", label="Test_Head")

    after_heads = read(out / "heads.2da")
    after_app = read(out / "appearance.2da")

    assert after_heads.get_height() == before_heads.get_height() + 1
    assert after_app.get_height() == before_app.get_height() + 1

    for before, after in ((before_heads, after_heads), (before_app, after_app)):
        changed = [
            (i, c)
            for i in range(before.get_height())
            for c in before.get_headers()
            if before.get_cell(i, c) != after.get_cell(i, c)
        ]
        assert not changed, changed[:5]


def test_the_new_row_inherits_the_fifty_columns_nobody_wants_to_fill(install_path, out):
    """An appearance row carries walk speed, drive animations, blood colour,
    hit radius and a body model per clothing slot. Filled in from first
    principles, a character slides along the ground."""
    reg = k2da.register_head(install_path, out, "p_testhead",
                             label="Test_Head", like="p_carthh")
    appearance = read(out / "appearance.2da")
    row = reg.appearance_row

    assert appearance.get_cell(row, "modeltype") == "B", "a head sits on a body"
    assert appearance.get_cell(row, "race"), "it needs a body model"
    for column in ("walkdist", "rundist", "modela"):
        assert appearance.get_cell(row, column) not in ("", "****"), column


def test_registering_the_same_head_twice_is_refused(install_path, out):
    k2da.register_head(install_path, out, "p_testhead", label="Test_Head")
    # The second call reads the *install*, which does not have it yet, so this
    # is about the guard rather than the file just written.
    with pytest.raises(k2da.TwoDAError):
        k2da.register_head(install_path, out, "p_carthh", label="Clash")


def test_copying_from_something_that_is_not_there_is_refused(install_path, out):
    with pytest.raises(k2da.TwoDAError):
        k2da.register_head(install_path, out, "p_testhead",
                           label="Test_Head", like="p_no_such_head")


# --- adding a self-contained model ------------------------------------------


def test_a_creature_gets_its_model_as_its_race(install_path, out):
    """The shape the HK recruit mod uses: `modeltype` F, and the model resref
    in `race` rather than a head index."""
    reg = k2da.register_creature(install_path, out, "p_mydroid",
                                 label="My_Droid", texture="mydroid_tex",
                                 like="p_hk47")
    appearance = read(out / "appearance.2da")
    row = reg.appearance_row

    assert appearance.get_cell(row, "race") == "p_mydroid"
    assert appearance.get_cell(row, "label") == "My_Droid"
    assert appearance.get_cell(row, "modela") == "mydroid_tex"
    assert appearance.get_cell(row, "modeltype") == "F"
    assert [p.name for p in reg.files] == ["appearance.2da"]


def test_it_builds_on_what_is_installed_not_on_what_shipped(install_path, out):
    """Loaded through Override first, so a new row lands on top of other mods
    rather than reverting them - and the count proves which copy was read."""
    live = k2da._load(install_path, "appearance")
    k2da.register_creature(install_path, out, "p_mydroid", label="My_Droid")
    after = read(out / "appearance.2da")

    assert after.get_height() == live.get_height() + 1


def test_a_2da_can_be_installed(install_path, out):
    """It is how the game learns the model exists, so it has to travel."""
    from kmdlfun import install as kinstall

    assert ".2da" in kinstall.INSTALLABLE
    k2da.register_head(install_path, out, "p_testhead", label="Test_Head")
    names = {p.name for p in kinstall.collect(out)}
    assert {"heads.2da", "appearance.2da"} <= names


# --- what it wears ----------------------------------------------------------
#
# Seen in game on 2026-09-01: a character copied from Carth's row spawned in
# his underwear. Not a bug in the row - `modela` is the body worn when nothing
# is equipped, and for a party member who changes clothes that is `P_CarthBA`.
# The blueprint carried no clothing, so the game used it.


def slots(table, row, column="model"):
    return [table.get_cell(row, f"{column}{s}") for s in k2da.SLOTS]


def test_a_new_character_does_not_inherit_a_party_members_underwear(
        install_path, out):
    """The failure, stated directly: Carth's unequipped slot must not survive
    into a character who owns no clothes."""
    reg = k2da.register_head(install_path, out, "p_testhead",
                             label="Test", like="p_carthh")
    appearance = read(out / "appearance.2da")
    worn = slots(appearance, reg.appearance_row)

    assert "P_CarthBA" not in worn, "spawns in the underwear"
    assert len(set(worn)) == 1, f"still changes with equipment: {sorted(set(worn))}"


def test_every_slot_gets_the_same_body_the_way_npcs_do(install_path, out):
    """The Czerka officer is `N_CzerkaOff` nine times over, so what he is
    wearing never depends on what he is carrying. Copy that."""
    reg = k2da.register_head(install_path, out, "p_testhead",
                             label="Test", like="p_carthh")
    appearance = read(out / "appearance.2da")
    row = reg.appearance_row

    assert set(slots(appearance, row)) == {appearance.get_cell(row, "race")}
    assert len(set(slots(appearance, row, "tex"))) == 1


def test_an_outfit_can_be_chosen(install_path, out):
    rack = k2da.outfits(install_path)
    pick = next(o for o in rack if o.model.lower() == "n_czerkaoff")

    reg = k2da.register_head(install_path, out, "p_testhead", label="Test",
                             like="p_carthh", outfit=pick)
    appearance = read(out / "appearance.2da")

    assert set(slots(appearance, reg.appearance_row)) == {pick.model}
    assert set(slots(appearance, reg.appearance_row, "tex")) == {pick.texture}


def test_an_outfit_can_be_named_rather_than_picked(install_path, out):
    """The GUI passes back the resref it showed, not the object."""
    reg = k2da.register_head(install_path, out, "p_testhead", label="Test",
                             like="p_carthh", outfit="N_CzerkaOff")
    appearance = read(out / "appearance.2da")

    assert set(slots(appearance, reg.appearance_row)) == {"N_CzerkaOff"}


def test_the_texture_is_taken_from_the_slot_that_pairs_it(install_path, out):
    """`N_CommM` wears `N_CommMD`. Assuming the two share a name puts a
    character in a texture that does not exist."""
    rack = k2da.outfits(install_path)
    commoner = next(o for o in rack if o.model.lower() == "n_commf")

    assert commoner.texture.lower() != commoner.model.lower()

    reg = k2da.register_head(install_path, out, "p_testhead", label="Test",
                             like="p_carthh", outfit=commoner)
    appearance = read(out / "appearance.2da")
    assert set(slots(appearance, reg.appearance_row, "tex")) == {commoner.texture}


def test_a_party_member_can_keep_changing_clothes(install_path, out):
    """Off is a real answer: somebody building an actual party member wants
    the per-slot variants that made this a problem in the first place."""
    reg = k2da.register_head(install_path, out, "p_testhead", label="Test",
                             like="p_carthh", dressed=False)
    appearance = read(out / "appearance.2da")

    assert len(set(slots(appearance, reg.appearance_row))) > 1


def test_the_wardrobe_is_what_the_game_already_wears(install_path, out):
    from kmdlfun.library import ModelLibrary

    rack = k2da.outfits(install_path, library=ModelLibrary(install_path))
    models = {o.model.lower() for o in rack}

    assert len(rack) > 50, "the wardrobe should be worth browsing"
    assert {"n_czerkaoff", "n_jedicounm", "n_commf"} <= models
    assert all(o.texture for o in rack), "an outfit with no texture is unwearable"
    assert rack == sorted(rack, key=lambda o: (-o.rows, o.model.lower()))
