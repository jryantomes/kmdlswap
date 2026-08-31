"""Sorting donors into male, female and droid.

The interesting part is which sources can be trusted. The game ships tables
that look authoritative and are not: `portraits.2da` marks Jolee as sex 1 and
he is male, and Carth's row has no appearance number at all. So the tests below
are mostly about *not* believing things - the classifier says `unknown` rather
than guessing, and every source it does use is checked against characters
whose identity nobody disputes.
"""

from __future__ import annotations

import pytest

from kmdlfun import who
from kmdlfun.library import (DONOR_KINDS, ModelLibrary, character_models,
                             classify)


@pytest.fixture(scope="module")
def k1(install_path):
    return ModelLibrary(str(install_path))


@pytest.fixture(scope="module")
def donors(k1, install_path):
    names = character_models(str(install_path), k1)
    return [n for n, k in classify(k1, names).items() if k in DONOR_KINDS]


@pytest.fixture(scope="module")
def looked(install_path, k1, donors):
    return who.looks(str(install_path), donors, library=k1)


@pytest.fixture(scope="module")
def look_of(install_path, k1):
    """One model by name, whether or not it is offered as a donor.

    Juhani's and Revan's heads are not in the donor list - they have no plain
    `head` mesh node - but they are the two clearest tests of the sources, so
    they are asked about directly.
    """
    def get(name: str):
        if not k1.has(name):
            pytest.skip(f"{name} is not in this install")
        return who.looks(str(install_path), [name], library=k1)[name]

    return get


# --- droids are structural --------------------------------------------------


def test_droids_are_told_apart_by_how_they_are_built(k1, donors, install_path):
    """A rigid head and no facial bones, which is exactly the ten droids.

    Names are not consulted. `c_drdprobe` and `c_drdmktwo` are droids by name
    and have no head node at all, so they are not donors and never come up;
    `p_hk47` and `p_t3m3` are droids and say nothing about it in their names.
    """
    from kmdlswap import layout as kl

    expected = {"c_drdassassin", "c_drdastro", "c_drdmkfour", "c_drdmkone",
                "c_drdprot", "c_drdsentry", "c_drdspyder", "c_drdwar",
                "p_hk47", "p_t3m3"}
    found = {n for n in donors if who.is_droid(kl.parse(*k1.read(n)))}

    assert found == expected, f"missed {expected - found}, invented {found - expected}"


def test_an_organic_head_is_never_a_droid(k1):
    from kmdlswap import layout as kl

    for name in ("p_carthh", "p_bastilah", "n_dustilh", "n_rodian", "n_yoda"):
        if k1.has(name):
            assert not who.is_droid(kl.parse(*k1.read(name))), name


def test_hk47_and_t3_are_droids_without_their_names_being_read(looked):
    assert looked["p_hk47"] == "droid"
    assert looked["p_t3m3"] == "droid"


# --- the parts the game gets wrong ------------------------------------------


def test_the_companions_come_out_right_where_the_game_does_not(looked, look_of):
    """`portraits.2da` says Jolee is sex 1, and Carth's row has no appearance
    number. Both are `forpc=0` rows, which is why that column is only read for
    `forpc=1`, and why the nine companions are written down instead."""
    assert looked["p_joleeh"] == "male", "the game's own table says otherwise"
    assert looked["p_carthh"] == "male", "the game's own table says nothing"
    assert looked["p_candh"] == "male"
    assert looked["p_bastilah"] == "female"
    assert looked["p_missionh"] == "female"
    assert look_of("p_juhanih") == "female"


def test_the_player_creation_heads_come_from_the_games_tables(install_path, k1):
    """The `forpc=1` rows are the ones that were maintained, and they are right."""
    heads = ["pmhc01", "pfhc01", "pmha03", "pfhb02"]
    present = [h for h in heads if k1.has(h)]
    if not present:
        pytest.skip("player heads are not separate models in this install")

    looked = who.looks(str(install_path), present, library=k1)
    for name in present:
        assert looked[name] == ("female" if name[1] == "f" else "male"), name


def test_named_npcs_are_read_from_the_body_they_wear(looked):
    """Nothing records their sex directly, but the body does: Dustil wears
    `N_SithComM`, Davik and Gadon and Vrook all wear `N_CommM`."""
    for name in ("n_dustilh", "n_davikh", "n_gadonh", "n_vrookh"):
        assert looked.get(name) == "male", name


# --- refusing to guess ------------------------------------------------------


def test_a_head_worn_by_both_is_reported_as_both(look_of):
    """Revan is the player character and can be either, so one head model is
    worn by `N_DarthRevanM` and `N_DarthRevanF` alike.

    That is not missing evidence, so calling it unknown would be wrong in a way
    that costs something: filtering to female would hide a head that genuinely
    is a female Revan.
    """
    assert look_of("n_darthrevanh") == who.EITHER
    assert who.matches(who.EITHER, "male")
    assert who.matches(who.EITHER, "female")
    assert not who.matches(who.EITHER, "droid")


def test_a_male_head_reused_on_a_female_body_is_still_male(look_of):
    """Two other heads are worn by both bodies and neither is ambiguous.

    `comm_w_m` is a male commoner head the game also hangs on `L_RepOffF`, and
    `pmhc02` is a player male head reused for `N_JediCounF`. Their own name and
    `portraits.2da` say male, and both are consulted before the body is.
    """
    for name in ("comm_w_m", "pmhc02"):
        assert look_of(name) == "male", name


def test_a_head_with_no_evidence_stays_unknown(looked):
    """Dodonna's body is `N_Dodonna` - no marker - and no table says more."""
    assert looked.get("n_dodonnah") == "unknown"


def test_substrings_do_not_decide_anything(looked):
    """"Malak" contains "mal" and "female" contains "male", which is why the
    name patterns match whole tokens only."""
    for name in ("n_darthmalak", "n_darthmalak02", "n_darthmalak03"):
        assert looked.get(name) == "unknown", (
            f"{name} was classified from a substring of 'Malak'"
        )


def test_aliens_are_not_forced_into_a_box(looked):
    """The axis does not apply to most of them and the data does not say, so
    they stay unknown rather than being assigned."""
    for name in ("n_bith", "n_duros", "n_rodian", "n_trandoshan", "n_yoda"):
        if name in looked:
            assert looked[name] == "unknown", name


def test_everything_lands_in_one_of_the_four(looked):
    assert set(looked.values()) <= set(who.LOOKS)


def test_the_split_is_useful_rather_than_mostly_unknown(looked):
    """A classifier that answered "unknown" almost every time would be honest
    and useless. Over half of the donors should be placed."""
    placed = [v for v in looked.values() if v != "unknown"]
    assert len(placed) > len(looked) * 0.5, who.summarise(looked)
    assert who.summarise(looked).count(",") >= 2


# --- KOTOR 2 -----------------------------------------------------------------


def test_the_second_games_heads_are_read_from_its_own_tables(k2_path):
    """`heads.2da` and the rest are read from whichever install is asked
    about, so a K2 donor list is built from K2's data rather than K1's."""
    from kmdlfun.library import PREFIXES, ModelLibrary, character_models

    lib = ModelLibrary(str(k2_path))
    offered = character_models(str(k2_path), lib)
    by_prefix = [n for n in offered if n.startswith(PREFIXES)]

    assert len(offered) > len(by_prefix) + 40, "K2 gained nothing from heads.2da"
    assert "comm_a_f" in offered
    # TSL ships elderly commoner heads that K1 has no equivalent of.
    assert any(n.startswith("old_") for n in offered), "K2-only heads are missing"
    # Its table names K1 characters whose models are not in this install.
    assert all(lib.has(n) for n in offered)


def test_the_tsl_cast_is_curated_like_the_first_games(k2_path):
    """Their bodies end in `BB`, so the body test says nothing, and their heads
    end in `h` like everyone else's. Without writing them down the entire
    second-game cast came out unknown."""
    lib = ModelLibrary(str(k2_path))
    expected = {
        "p_attonh": "male", "p_baodurh": "male", "p_discipleh": "male",
        "p_hanharr": "male", "p_mandalorebb": "male",
        "p_mirah": "female", "p_handmaidenh": "female", "p_visash": "female",
        "p_kreiah": "female", "p_atrisbb": "female",
        "p_g0t0": "droid", "p_hk47": "droid", "p_t3m4": "droid",
    }
    present = {n: v for n, v in expected.items() if lib.has(n)}
    if not present:
        pytest.skip("no TSL cast models in this install")

    looked = who.looks(str(k2_path), list(present), library=lib)
    wrong = {n: (v, looked[n]) for n, v in present.items() if looked[n] != v}
    assert not wrong, wrong


def test_kreias_several_models_all_resolve(k2_path):
    """She has six, and prefix curation is what covers them all."""
    lib = ModelLibrary(str(k2_path))
    kreia = [n for n in lib.index if n.startswith("p_kreia") and lib.has(n)]
    if not kreia:
        pytest.skip("no Kreia models in this install")

    looked = who.looks(str(k2_path), kreia, library=lib)
    assert set(looked.values()) == {"female"}, looked


def test_the_droid_test_still_works_on_the_second_game(k2_path):
    """It reads the model, not a table, so it needs nothing game-specific."""
    from kmdlswap import layout as kl

    lib = ModelLibrary(str(k2_path))
    for name in ("p_hk47", "p_t3m4", "c_drdwar"):
        if lib.has(name):
            assert who.is_droid(kl.parse(*lib.read(name))), name
    for name in ("p_attonh", "p_mirah"):
        if lib.has(name):
            assert not who.is_droid(kl.parse(*lib.read(name))), name
