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


# --- borrowing parts a host has no name for ----------------------------------


def to_model(host, node_name, mesh):
    """A host node's local coordinates back in host model space.

    `to_host_space` returns each part in the local space of whichever host node
    is carrying it, so two parts cannot be compared directly - a head in Head's
    frame and a tentacle in hair's frame are numbers about different origins.
    """
    import numpy as np

    from kmdlfun import space

    rest = space.rest_pose(host)[host.node_by_name(node_name).index]
    R = np.asarray(rest.rotation)
    T = np.asarray(rest.position)
    return np.asarray(mesh.positions) @ R.T + T


def centre_of(points):
    import numpy as np

    P = np.asarray(points)
    return (P.min(axis=0) + P.max(axis=0)) / 2.0


def test_a_shared_alignment_keeps_parts_in_their_relative_places(k2, pair):
    """A Quarren's mouth tentacles are four separate nodes, and Carth has no
    node called `tent01`. He does have spare facial nodes, and vertex counts are
    free, so they can carry the tentacles - but only if every part moves by the
    *same* amount. Centred individually on four unrelated host nodes they would
    land in four wrong places.
    """
    import numpy as np

    from kmdlfun import transplant as ktp

    host = kl.parse(*pair("p_carthh"))
    donor = kl.parse(*k2.read("n_quarren"))
    offset = ktp.model_alignment(donor, donor.node_by_name("head"),
                                 host, host.node_by_name("Head"))

    head, _ = ktp.to_host_space(donor, donor.node_by_name("head"),
                                host, host.node_by_name("Head"), model_offset=offset)
    tent, _ = ktp.to_host_space(donor, donor.node_by_name("tent01"),
                                host, host.node_by_name("hair"), model_offset=offset)

    head_c = centre_of(to_model(host, "Head", head))
    tent_c = centre_of(to_model(host, "hair", tent))

    # The anchor lands exactly on the part it replaces.
    assert np.allclose(head_c, centre_of(to_model(
        host, "Head", type("M", (), {"positions": ke.extract(
            host, host.node_by_name("Head")).positions})())), atol=1e-6)

    # The tentacle keeps the spacing it had on the donor, in model space.
    donor_gap = float(np.linalg.norm(
        centre_of(to_model(donor, "tent01", type("M", (), {"positions": ke.extract(
            donor, donor.node_by_name("tent01")).positions})()))
        - centre_of(to_model(donor, "head", type("M", (), {"positions": ke.extract(
            donor, donor.node_by_name("head")).positions})()))))
    got = float(np.linalg.norm(tent_c - head_c))
    assert got == pytest.approx(donor_gap, abs=1e-6), (
        f"spacing changed: donor {donor_gap:.4f}, built {got:.4f}"
    )
    assert 0.02 < got < 0.5, f"a tentacle should sit near the face, got {got:.3f}"


def test_recentring_each_part_separately_would_scatter_them(k2, pair):
    """The failure the shared alignment exists to prevent."""
    import numpy as np

    from kmdlfun import transplant as ktp

    host = kl.parse(*pair("p_carthh"))
    donor = kl.parse(*k2.read("n_quarren"))

    scattered = []
    for host_name, donor_name in (("Head", "head"), ("hair", "tent01")):
        mesh, _ = ktp.to_host_space(donor, donor.node_by_name(donor_name),
                                    host, host.node_by_name(host_name), place=True)
        scattered.append(centre_of(to_model(host, host_name, mesh)))

    offset = ktp.model_alignment(donor, donor.node_by_name("head"),
                                 host, host.node_by_name("Head"))
    aligned = []
    for host_name, donor_name in (("Head", "head"), ("hair", "tent01")):
        mesh, _ = ktp.to_host_space(donor, donor.node_by_name(donor_name),
                                    host, host.node_by_name(host_name),
                                    model_offset=offset)
        aligned.append(centre_of(to_model(host, host_name, mesh)))

    gap_scattered = float(np.linalg.norm(scattered[1] - scattered[0]))
    gap_aligned = float(np.linalg.norm(aligned[1] - aligned[0]))
    assert abs(gap_scattered - gap_aligned) > 1e-3, (
        "recentring each part on its own host node must change the spacing, "
        "or this test proves nothing"
    )


# --- folding rigid parts into a skinned mesh ---------------------------------


def test_merged_parts_are_bound_to_the_bone_they_hung_from(k2, pair):
    """A Quarren's mouth tentacles are rigid meshes parented to its lip bones,
    so they swing when it talks. Carried in one of Carth's spare nodes they
    would follow his whole head instead, because every facial mesh of his hangs
    off `head_g` - which is a parenting problem no amount of placing fixes.

    Folding them into the head and weighting each 100% to its old parent bone
    reproduces exactly the motion the parenting gave them.
    """
    from kmdlfun import transplant as ktp
    from kmdlswap import weights as kw

    host = kl.parse(*pair("p_carthh"))
    hn = host.node_by_name("Head")
    donor = kl.parse(*k2.read("n_quarren"))
    dn = donor.node_by_name("head")

    tents = ["tent01", "tent02", "tent03", "tent04"]
    positions, faces, uvs, influences, notes = ktp.merge_into(
        donor, dn, tents, host, hn
    )

    base = ke.extract(donor, dn)
    assert len(positions) > len(base.positions), "nothing was merged"
    assert len(influences) == len(positions)
    assert len(uvs) == len(positions)
    assert not kw.check(influences)
    assert max(v for f in faces for v in f) < len(positions)

    slot_to_name = {s: host.nodes[i].name for i, s in enumerate(hn.bonemap) if s >= 0}
    expected = {"tent01": "f_lmc_g", "tent02": "f_Llm_g",
                "tent03": "f_rmc_g", "tent04": "f_Rlm_g"}
    at = len(base.positions)
    for name in tents:
        count = donor.node_by_name(name).vertex_count
        block = influences[at:at + count]
        assert all(len(i) == 1 and i[0].weight == 1.0 for i in block), (
            f"{name} must be rigidly bound, not blended"
        )
        got = {slot_to_name[i[0].bone_slot] for i in block}
        assert got == {expected[name]}, f"{name} bound to {got}"
        at += count


def test_a_part_whose_bone_the_host_lacks_is_skipped_and_reported(k2, pair):
    """Never bind it to something arbitrary just to keep it."""
    from kmdlfun import transplant as ktp

    host = kl.parse(*pair("p_carthh"))
    donor = kl.parse(*k2.read("n_quarren"))
    # `cape` hangs off a torso bone that a head model has no equivalent of.
    _, _, _, _, notes = ktp.merge_into(
        donor, donor.node_by_name("head"), ["cape"], host, host.node_by_name("Head")
    )
    assert any("skipped" in n for n in notes), notes


def test_drift_reports_where_the_part_ends_up(k2, pair):
    """It used to be measured before placing, so a correctly aligned merge
    still reported a drift of 1.5 - which misled me while building this."""
    from kmdlfun import transplant as ktp

    host = kl.parse(*pair("p_carthh"))
    donor = kl.parse(*k2.read("n_quarren"))
    _, aligned = ktp.to_host_space(donor, donor.node_by_name("head"),
                                   host, host.node_by_name("Head"), place=True)
    _, raw = ktp.to_host_space(donor, donor.node_by_name("head"),
                               host, host.node_by_name("Head"))
    assert aligned.drift < 1e-6, f"placed part should report no drift, got {aligned.drift}"
    assert raw.drift > 1.0, "an unplaced donor really is far away"


def test_merge_remaps_the_base_mesh_weights_too(k2, pair):
    """The bug this exists to prevent, and the symptom it produced.

    `merge_into` folded extra parts in with host bone slots but passed the base
    mesh's weights through untouched. Bone slots are per-model indices ordered
    completely differently - Carth's slot 1 is `f_lns_g` while the Quarren's is
    `head_g` - so the Quarren's entire skull drove Carth's nose bone. In game
    the back of the head moved with the mouth.

    The invariant: weight mass per bone *name* must survive the transplant. The
    same mesh is going in, so the same bones should be doing the same work.
    """
    import collections

    from kmdlfun import transplant as ktp

    host = kl.parse(*pair("p_carthh"))
    hn = host.node_by_name("Head")
    donor = kl.parse(*k2.read("n_quarren"))
    dn = donor.node_by_name("head")

    def mass_by_name(layout, node, influences):
        slot_to_name = {s: layout.nodes[i].name.lower()
                        for i, s in enumerate(node.bonemap) if s >= 0}
        out = collections.Counter()
        for infl in influences:
            for one in infl:
                out[slot_to_name.get(one.bone_slot, f"slot{one.bone_slot}")] += one.weight
        total = sum(out.values()) or 1.0
        return {k: v / total for k, v in out.items()}

    before = mass_by_name(donor, dn, ke.extract(donor, dn).influences)
    _, _, _, merged, _ = ktp.merge_into(donor, dn, [], host, hn)
    after = mass_by_name(host, hn, merged)

    assert set(before) == set(after), (
        f"bones changed: only in donor {set(before) - set(after)}, "
        f"only in built {set(after) - set(before)}"
    )
    for name in before:
        assert after[name] == pytest.approx(before[name], abs=0.01), (
            f"{name} carried {before[name]:.1%} on the donor and {after[name]:.1%} "
            f"after - the slots were not remapped"
        )
    # And the skull must still be the dominant bone, not a nose.
    assert max(after, key=after.get) == "head_g"


def test_a_texture_with_alpha_keeps_it_through_import(tmp_path):
    """Dropping alpha is what cost a ported Quarren its eyes.

    Its texture is RGBA; converting to RGB threw the channel away and the eyes
    rendered flat grey while the rest of the face looked right. The model files
    were byte-identical either way - the texture was the whole difference.
    """
    from PIL import Image

    from kmdlfun.cli import _has_alpha

    opaque = Image.new("RGBA", (4, 4), (10, 20, 30, 255))
    assert not _has_alpha(opaque), "an all-opaque alpha channel carries nothing"

    partial = Image.new("RGBA", (4, 4), (10, 20, 30, 255))
    partial.putpixel((1, 1), (10, 20, 30, 0))
    assert _has_alpha(partial)

    # and it survives a round trip through the format we write
    path = tmp_path / "t.tga"
    partial.save(path)
    with Image.open(path) as back:
        assert back.convert("RGBA").getchannel("A").getextrema()[0] == 0


def test_a_donor_texture_is_copied_not_re_encoded(k2_path):
    """The safest conversion is the one that does not happen.

    A K2 texture the host game lacks is copied across as the shipped bytes,
    extension and all, rather than decoded and re-encoded. That is what fixed
    the Quarren's eyes: the re-encode dropped an alpha channel.
    """
    import numpy as np

    from kmdlfun import textures

    raw = textures.raw_texture(k2_path, "N_QuarrenH01")
    assert raw is not None
    data, ext = raw
    assert ext == "tpc"
    assert len(data) > 1000
    # The copy must decode to exactly what the game's own lookup gives.
    assert np.array_equal(textures._decode_tpc(data),
                          textures.TextureCache(k2_path).get("N_QuarrenH01"))
