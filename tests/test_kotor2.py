"""Reading KOTOR 2 models, and using them as donors for KOTOR 1.

The brief put KOTOR 2 out of scope, and this stays a *reading* capability:
K2 models are parsed so their geometry can be borrowed, and the host is still
written in its own format. Nothing writes a K2 file.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from kmdlswap import edit as ke
from kmdlswap import layout as kl
from kmdlswap import validate as kv
from kmdlswap.nodes import FUNCTION_POINTERS, MDL_VERTICES_AT, MDX_BLOCK_AT

K2_INSTALLS = [
    r"E:\SteamLibrary\steamapps\common\Knights of the Old Republic II",
    r"C:\Program Files (x86)\Steam\steamapps\common\Knights of the Old Republic II",
    r"C:\GOG Games\Star Wars - KotOR2",
]


def find_k2() -> Path | None:
    for c in [os.environ["KOTOR2_PATH"]] if "KOTOR2_PATH" in os.environ else K2_INSTALLS:
        p = Path(c)
        if (p / "chitin.key").is_file():
            return p
    return None


@pytest.fixture(scope="session")
def k2_path() -> Path:
    p = find_k2()
    if p is None:
        pytest.skip("no KOTOR 2 install found (set KOTOR2_PATH)")
    return p


@pytest.fixture(scope="session")
def k2(k2_path):
    from kmdlfun.library import ModelLibrary

    return ModelLibrary(str(k2_path))


def test_the_two_games_are_told_apart_by_their_function_pointers():
    """Measured across both installs: every one of K1's 2,832 models carries
    the first pair and every one of K2's 3,237 the second, with no exceptions
    and no other values anywhere."""
    assert FUNCTION_POINTERS[(4273776, 4216096)] == "K1"
    assert FUNCTION_POINTERS[(4285200, 4216320)] == "K2"
    assert len(FUNCTION_POINTERS) == 2


def test_an_unknown_game_is_refused_rather_than_guessed(pair):
    """A file that is neither must fail loudly. Guessing K1 would read K2's
    header 8 bytes early and produce offsets in the hundreds of millions."""
    mdl, mdx = pair("p_carthh")
    broken = bytearray(mdl)
    broken[12:16] = (12345).to_bytes(4, "little")
    with pytest.raises(kl.ParseError, match="function pointers"):
        kl.parse(bytes(broken), mdx)


def test_a_k2_model_parses_and_validates(k2):
    layout = kl.parse(*k2.read("n_quarren"))
    assert layout.game == "K2"
    report = kv.check(layout)
    assert report.ok, (
        f"gaps={len(report.gaps)} overlaps={len(report.overlaps)} "
        f"dangling={len(report.dangling)}"
    )


def test_k1_still_reads_as_k1(pair):
    layout = kl.parse(*pair("p_carthh"))
    assert layout.game == "K1"
    assert kv.check(layout).ok


def test_only_the_two_tail_offsets_move(k2, pair):
    """The whole difference that matters for reading.

    Compared field by field against `n_bith`, which both games ship: the header
    matches up to and including the vertex count at +304, and K2 then carries 8
    extra bytes before the MDX and vertex-array pointers.
    """
    assert MDX_BLOCK_AT["K2"] - MDX_BLOCK_AT["K1"] == 8
    assert MDL_VERTICES_AT["K2"] - MDL_VERTICES_AT["K1"] == 8

    one = kl.parse(*pair("n_bith")).node_by_name("head")
    two = kl.parse(*k2.read("n_bith")).node_by_name("head")
    # Fields before the shift must still land on sane values in both.
    for node in (one, two):
        assert node.vertex_count > 0
        assert node.mdx_stride in (24, 32, 40, 48, 56, 64, 72, 80)
        assert node.face_count > 0


def test_k2_geometry_extracts_like_k1_geometry(k2):
    """The point of reading K2 at all: its geometry has to come out in the same
    shape everything else in this project consumes."""
    layout = kl.parse(*k2.read("n_quarren"))
    node = layout.node_by_name("head")
    geo = ke.extract(layout, node)

    assert len(geo.positions) == node.vertex_count
    assert geo.faces
    assert max(v for f in geo.faces for v in f.vertices) < node.vertex_count
    assert "uv1" in geo.columns
    assert len(geo.columns["uv1"]) == node.vertex_count


def test_a_k2_head_goes_into_a_k1_host(k2, pair, tmp_path):
    """Cross-game transplant. Only geometry crosses; the host is written back
    as the K1 model it was."""
    from kmdlfun import transplant as ktp

    host_mdl, host_mdx = pair("p_carthh")
    donor = kl.parse(*k2.read("n_quarren"))
    assert donor.game == "K2"

    mdl, mdx, result = ktp.transplant_node(
        host_mdl, host_mdx, donor, "n_quarren", "Head", "head",
        fit=True, scale=1.45, with_texture=True,
    )
    assert result.ok, result.error

    after = kl.parse(mdl, mdx)
    assert after.game == "K1", "the host must stay a K1 file"
    assert kv.check(after).ok
    assert after.node_by_name("Head").vertex_count == donor.node_by_name("head").vertex_count


@pytest.mark.slow
def test_every_k2_model_parses(k2_path):
    """The corpus is the oracle here as it is for K1: 3,237 of 3,237."""
    from pykotor.extract.installation import Installation
    from pykotor.resource.type import ResourceType

    inst = Installation(str(k2_path))
    found: dict = {}
    for r in inst.chitin_resources():
        if r.restype() in (ResourceType.MDL, ResourceType.MDX):
            found.setdefault(r.resname().lower(), {})[r.restype()] = r

    checked = bad = 0
    for name, entry in found.items():
        if len(entry) != 2:
            continue
        checked += 1
        try:
            if not kv.check(kl.parse(entry[ResourceType.MDL].data(),
                                     entry[ResourceType.MDX].data())).ok:
                bad += 1
        except Exception:  # noqa: BLE001
            bad += 1
    assert checked > 3000
    assert bad == 0, f"{bad} of {checked} K2 models failed"


# --- the donor's own rig -----------------------------------------------------


def test_both_games_use_the_same_facial_rig(k2, pair):
    """Why a K2 head can keep its own weights at all.

    Bone *slots* are per-model indices and cannot be copied across. Bone *names*
    can - and all 16 of Carth's appear on a KOTOR 2 Quarren.
    """
    from kmdlfun import transplant as ktp

    host = kl.parse(*pair("p_carthh"))
    donor = kl.parse(*k2.read("n_quarren"))
    assert ktp.rigs_match(donor, donor.node_by_name("head"),
                          host, host.node_by_name("Head"))


def test_the_donors_weights_are_remapped_by_name_not_copied(k2, pair):
    """Slots differ between models; the mapping has to go through names."""
    from kmdlfun import transplant as ktp
    from kmdlswap import weights as kw

    host = kl.parse(*pair("p_carthh"))
    hn = host.node_by_name("Head")
    donor = kl.parse(*k2.read("n_quarren"))
    dn = donor.node_by_name("head")
    geo = ke.extract(donor, dn)

    out, absent = ktp.remap_influences(donor, dn, host, hn, geo.influences)
    assert not absent, absent
    assert len(out) == len(geo.influences)
    assert not kw.check(out)

    host_slots = {s for s in hn.bonemap if s >= 0}
    used = {i.bone_slot for infl in out for i in infl}
    assert used <= host_slots, "every weight must land on a slot the host has"
    assert len(used) == 16

    # Same weight *values*, different slot numbers - the donor's rigging is kept.
    # Not bit-exact: remapping renormalises, and the stored weights sum to 1.0
    # only within float32, so each shifts by about 1e-5.
    assert sorted(i.weight for i in out[0]) == pytest.approx(
        sorted(i.weight for i in geo.influences[0]), abs=1e-4
    )


def test_a_bone_the_host_lacks_is_dropped_and_reported(k2, pair):
    """Never invent one. Drop it, renormalise, and say which."""
    from kmdlfun import transplant as ktp
    from kmdlswap import weights as kw

    host = kl.parse(*pair("p_carthh"))
    hn = host.node_by_name("Head")
    donor = kl.parse(*k2.read("n_quarren"))
    dn = donor.node_by_name("head")
    geo = ke.extract(donor, dn)

    # Pretend the host has no jaw.
    crippled = type(hn)(**{f: getattr(hn, f) for f in hn.__slots__})
    jaw = next(i for i, n in enumerate(host.nodes) if n.name == "f_jaw_g")
    bonemap = list(hn.bonemap)
    bonemap[jaw] = -1
    crippled.bonemap = tuple(bonemap)

    out, absent = ktp.remap_influences(donor, dn, host, crippled, geo.influences)
    assert absent == ["f_jaw_g"]
    assert not kw.check([i for i in out if i]), "the rest must still be valid"


def test_place_moves_without_resizing(k2, pair):
    """The point of --place. Fitting shrinks a donor until its widest axis fits
    the host's box, which makes a Quarren that is not Quarren-sized."""
    import numpy as np

    from kmdlfun import transplant as ktp

    host = kl.parse(*pair("p_carthh"))
    hn = host.node_by_name("Head")
    donor = kl.parse(*k2.read("n_quarren"))
    dn = donor.node_by_name("head")

    def box(mesh):
        P = np.asarray(mesh.positions)
        return P.max(axis=0) - P.min(axis=0)

    native, _ = ktp.to_host_space(donor, dn, host, hn, place=True)
    fitted, _ = ktp.to_host_space(donor, dn, host, hn, fit=True)
    raw, _ = ktp.to_host_space(donor, dn, host, hn)

    assert np.allclose(box(native), box(raw)), "place must not resize"
    assert (box(fitted) < box(native)).all(), "fit shrinks this donor"

    # ...but it does move it onto the host part.
    host_mid = np.asarray(ke.extract(host, hn).positions).mean(axis=0)
    assert np.linalg.norm(np.asarray(native.positions).mean(axis=0) - host_mid) < \
        np.linalg.norm(np.asarray(raw.positions).mean(axis=0) - host_mid)
