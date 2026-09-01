"""The three things a character is made of.

A KOTOR humanoid is assembled rather than authored: `appearance.2da` names a
base body, a clothed body per equipment slot, and a row of `heads.2da`. All
three already exist for anything the game ships, so a new character need not
involve geometry at all.

What is tested here is that the relationships are *read* rather than guessed. A
row saying `race = N_TwilekF` with `normalhead = 74` is the game telling us that
head goes on that body; nothing here should invent a pairing it was not told
about, and nothing should forbid one either.
"""

from __future__ import annotations

import pytest

from kmdlfun import wardrobe as kw


@pytest.fixture(scope="module")
def catalogue(install_path):
    from kmdlfun.library import ModelLibrary

    return kw.build(install_path, library=ModelLibrary(install_path))


# --- what is on offer -------------------------------------------------------


def test_there_is_enough_to_build_a_character_from(catalogue):
    assert len(catalogue.bodies) > 20
    assert len(catalogue.outfits) > 80
    assert len(catalogue.heads) > 90


def test_every_part_named_is_a_model_that_exists(catalogue, install_path):
    """A part that cannot be loaded cannot be worn, and a part that cannot be
    drawn cannot be previewed."""
    from kmdlfun.library import ModelLibrary

    lib = ModelLibrary(install_path)
    for group in (catalogue.bodies, catalogue.outfits, catalogue.heads):
        missing = [p.model for p in group if not lib.has(p.model)]
        assert not missing, missing


def test_a_body_is_one_that_takes_a_separate_head(catalogue):
    """`modeltype F` carries its own head and can never wear another, so
    offering one as a body is offering something that cannot work."""
    assert catalogue.body("P_CarthBB") is not None
    assert catalogue.body("N_CommM") is not None
    # A self-contained creature is not a body you can put a head on.
    assert catalogue.body("c_bantha") is None


def test_outfits_are_not_just_the_body_list_renamed(catalogue):
    """If they were, 'wardrobe' would not be a separate choice at all."""
    bodies = {b.model.lower() for b in catalogue.bodies}
    outfits = {o.model.lower() for o in catalogue.outfits}

    assert len(outfits - bodies) > 50, "most outfits are never a base body"


def test_an_outfit_knows_the_texture_that_goes_with_it(catalogue):
    """`N_CommF` wears `N_CommFD`. Assuming the two share a name is how a
    character ends up white or untextured."""
    commoner = catalogue.outfit("N_CommF")

    assert commoner is not None
    assert commoner.texture
    assert commoner.texture.lower() != commoner.model.lower()


def test_the_player_bodies_split_into_sex_class_and_build(catalogue):
    """`P{M|F}B{A..I}{S|M|L}` - the one family where the game itself separates
    the three axes, and the clearest illustration of what this tab does."""
    medium = catalogue.body("PMBCM")
    small = catalogue.body("PMBCS")

    if medium is not None:
        assert medium.build == "medium"
    if small is not None:
        assert small.build == "small"


# --- what goes with what ----------------------------------------------------


def test_a_body_knows_the_heads_the_game_puts_on_it(catalogue):
    carth = catalogue.body("P_CarthBB")

    assert carth.heads, "no head was ever recorded for Carth's body"
    assert catalogue.pairs_with(carth, head=catalogue.head("p_carthh"))


def test_a_body_knows_the_outfits_the_game_dresses_it_in(catalogue):
    carth = catalogue.body("P_CarthBB")

    assert catalogue.pairs_with(carth, outfit=catalogue.outfit("PMBCM"))


def test_a_combination_the_game_never_ships_is_reported_not_refused(catalogue):
    """The whole reason to reach for this tool is a combination that does not
    exist yet. Filtering those out would filter out the point."""
    twilek = catalogue.body("N_TwilekF")
    carths_face = catalogue.head("p_carthh")

    assert not catalogue.pairs_with(twilek, head=carths_face), "premise changed"
    assert carths_face in catalogue.heads_for(twilek), "it was hidden"


def test_compatible_parts_are_offered_first(catalogue):
    """Not a filter, an ordering: what the game already does, in front."""
    carth = catalogue.body("P_CarthBB")
    offered = catalogue.heads_for(carth)

    known = [h for h in offered if catalogue.pairs_with(carth, head=h)]
    assert known, "nothing known-good to put first"
    assert offered[:len(known)] == known, "a known pairing was not in front"


def test_the_same_is_true_of_outfits(catalogue):
    carth = catalogue.body("P_CarthBB")
    offered = catalogue.outfits_for(carth)
    known = [o for o in offered if catalogue.pairs_with(carth, outfit=o)]

    assert known
    assert offered[:len(known)] == known


def test_with_no_body_chosen_everything_is_offered(catalogue):
    assert len(catalogue.heads_for(None)) == len(catalogue.heads)
    assert len(catalogue.outfits_for(None)) == len(catalogue.outfits)


def test_nothing_is_lost_by_reordering(catalogue):
    """A sort that drops entries is worse than no sort."""
    carth = catalogue.body("P_CarthBB")

    assert len(catalogue.heads_for(carth)) == len(catalogue.heads)
    assert len(catalogue.outfits_for(carth)) == len(catalogue.outfits)


# --- who each part is -------------------------------------------------------


def test_every_kind_of_part_can_be_sexed(catalogue):
    """An outfit is a body model, so it has a sex the same way a body does.
    Without this, filtering the wardrobe to 'female' empties it."""
    from kmdlfun import who as kwho

    for group in (catalogue.bodies, catalogue.outfits, catalogue.heads):
        known = [p for p in group
                 if catalogue.look_of(p) != kwho.UNKNOWN]
        assert len(known) > len(group) // 2, "most parts should be placeable"


def test_a_player_body_is_sexed_by_its_own_name(catalogue):
    """`PMB` against `PFB` is the game saying so outright, and beats anything
    inferred from who happens to wear it."""
    from kmdlfun import who as kwho

    for name in ("PMBCM", "PMBDM"):
        if catalogue.body(name):
            assert catalogue.look_of(name) == kwho.MALE, name
    for name in ("PFBCM", "PFBDM"):
        if catalogue.body(name):
            assert catalogue.look_of(name) == kwho.FEMALE, name


def test_an_unknown_part_is_unknown_rather_than_guessed(catalogue):
    assert catalogue.look_of("nothing_by_this_name") == "unknown"


# --- looking things up ------------------------------------------------------


def test_parts_are_found_however_they_are_cased(catalogue):
    """The tables are not consistent - `p_CarthH` sits next to `P_CarthBB`."""
    assert catalogue.body("p_carthbb") is not None
    assert catalogue.body("P_CARTHBB") is not None
    assert catalogue.head("P_CARTHH") is not None
    assert catalogue.outfit("n_czerkaoff") is not None


def test_asking_for_something_absent_gives_nothing_rather_than_raising(catalogue):
    assert catalogue.body("no_such_body") is None
    assert catalogue.head("no_such_head") is None
    assert catalogue.outfit("no_such_outfit") is None
    assert catalogue.pairs_with(None, head=catalogue.head("p_carthh")) is False
