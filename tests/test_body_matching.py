"""Pairing body parts across the two naming conventions nobody wrote down.

Counted over the 67 KOTOR 1 body models: sixteen name their arms
`larm`/`rarm` and nine name them `arml`/`armr`. Nothing records this, so Carth
and Bastila - both perfectly ordinary humans in perfectly ordinary clothes -
paired only their torsos and swapped no arms at all.

The dangerous version of this fix pairs a left arm with a right one. That does
not fail, it produces a body whose elbows bend the wrong way, and it reads as a
rigging fault rather than a naming one. So the side is part of the key, and the
property is checked across every body pair in the game rather than on an
example.
"""

from __future__ import annotations

import itertools

import pytest

from kmdlfun import transplant as ktp
from kmdlfun.library import DONOR_KINDS, ModelLibrary, character_models, classify
from kmdlswap import layout as kl


@pytest.fixture(scope="module")
def k1(install_path):
    return ModelLibrary(str(install_path))


@pytest.fixture(scope="module")
def bodies(k1, install_path):
    """Every body model in the install, parsed once."""
    kinds = classify(k1, character_models(str(install_path), k1))
    out = {}
    for name, kind in kinds.items():
        if kind != "body":
            continue
        try:
            out[name] = kl.parse(*k1.read(name))
        except Exception:  # noqa: BLE001
            continue
    return out


class Fake:
    def __init__(self, name):
        self.name = name


# --- the convention ---------------------------------------------------------


def test_the_two_conventions_meet(k1):
    """Carth uses `LArm`/`RArm`, Bastila uses `ArmL`/`ArmR`."""
    if not (k1.has("p_carthbb") and k1.has("p_bastilabb")):
        pytest.skip("need both bodies")

    host = kl.parse(*k1.read("p_carthbb"))
    donor = kl.parse(*k1.read("p_bastilabb"))

    exact = ktp.match_nodes(host, donor, aliases=False)
    aliased = ktp.match_nodes(host, donor)

    assert len(exact) == 1, f"only the torso used to pair: {exact}"
    assert len(aliased) == 3, aliased
    assert ("LArm", "ArmL") in aliased
    assert ("RArm", "ArmR") in aliased


def test_a_left_part_never_pairs_with_a_right_one(bodies):
    """The property that makes aliasing safe, over every body pair in the game.

    An arm on the wrong side does not fail a validator and does not look like a
    naming mistake in game - it looks like the rig is broken.
    """
    crossed = []
    for a, b in itertools.combinations(sorted(bodies), 2):
        for host_node, donor_node in ktp.match_nodes(bodies[a], bodies[b]):
            left, right = ktp.canonical(host_node), ktp.canonical(donor_node)
            if left and right and left != right:
                crossed.append((a, b, host_node, donor_node))

    assert not crossed, f"{len(crossed)} crossed pairings, e.g. {crossed[:3]}"


def test_aliasing_is_worth_having(bodies):
    """It should move a real share of the corpus, not one lucky pair."""
    improved = 0
    total = 0
    for a, b in itertools.combinations(sorted(bodies), 2):
        total += 1
        exact = len(ktp.match_nodes(bodies[a], bodies[b], aliases=False))
        if len(ktp.match_nodes(bodies[a], bodies[b])) > exact:
            improved += 1

    assert improved > total * 0.2, (
        f"only {improved} of {total} body pairs gained anything"
    )


# --- being careful ----------------------------------------------------------


def test_exact_names_win(k1):
    """A donor naming its parts the host's way is never reinterpreted."""
    if not k1.has("p_carthbb"):
        pytest.skip("need p_carthbb")
    host = kl.parse(*k1.read("p_carthbb"))

    pairs = ktp.match_nodes(host, host)
    assert all(h == d for h, d in pairs), pairs
    assert len(pairs) == len(ktp.match_nodes(host, host, aliases=False))


def test_an_ambiguous_model_is_left_alone():
    """Two nodes reducing to the same part is not something a name can settle,
    so neither is used rather than picking one."""
    index = ktp._canonical_index([Fake("torso"), Fake("torso2"), Fake("LArm")])

    assert "torso" not in index, "two torsos should disqualify the part"
    assert index.get("arm.l") == "LArm", "the unambiguous part still resolves"


def test_the_alias_table_keeps_sides_apart():
    lefts = {k for k, v in ktp.ALIASES.items() if v.endswith(".l")}
    rights = {k for k, v in ktp.ALIASES.items() if v.endswith(".r")}

    assert lefts and rights
    assert not (lefts & rights)
    for name in lefts:
        assert ktp.canonical(name) != ktp.canonical(next(iter(rights)))


def test_turning_it_off_restores_the_old_behaviour(k1):
    if not (k1.has("p_carthbb") and k1.has("p_bastilabb")):
        pytest.skip("need both bodies")
    host = kl.parse(*k1.read("p_carthbb"))
    donor = kl.parse(*k1.read("p_bastilabb"))

    assert ktp.match_nodes(host, donor, aliases=False) == [("Torso", "torso")]


def test_heads_are_unaffected(k1):
    """Head models already agreed on their names, so nothing here should move."""
    for host, donor in (("p_carthh", "n_dustilh"), ("p_carthh", "p_bastilah")):
        if not (k1.has(host) and k1.has(donor)):
            continue
        h, d = kl.parse(*k1.read(host)), kl.parse(*k1.read(donor))
        assert ktp.match_nodes(h, d) == ktp.match_nodes(h, d, aliases=False)


def test_pairs_come_back_in_the_hosts_own_order(k1):
    """The anchor is chosen from these and the report is read in this order."""
    if not (k1.has("p_carthbb") and k1.has("p_bastilabb")):
        pytest.skip("need both bodies")
    host = kl.parse(*k1.read("p_carthbb"))
    donor = kl.parse(*k1.read("p_bastilabb"))

    from kmdlfun import parts as kparts

    order = [n.name for n in kparts.mesh_nodes(host)]
    got = [h for h, _ in ktp.match_nodes(host, donor)]
    assert got == sorted(got, key=order.index)
