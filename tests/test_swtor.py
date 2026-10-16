"""Reading Star Wars: The Old Republic models.

The install is the corpus and the oracle, the same bargain the rest of these
tests make - and more so here than anywhere else, because nothing in
`swtor.py` came from documentation. Every field offset was measured, so the
tests that matter are the ones that measure it again: that a decoded mesh has
the bounding box its own file asserts, and that no triangle in any of the 993
heads names a vertex that does not exist.
"""

from __future__ import annotations

import struct

import pytest

from kmdlfun import swtor


# --- naming, which needs no install ----------------------------------------


@pytest.mark.parametrize("name,kind", [
    ("head_human_bmn_caucasian_a01", swtor.HEAD),
    ("head_twilek_bfa_non_a03", swtor.HEAD),
    ("hair_human_bfn_a12", swtor.HAIR),
    ("hair_abyssin_bma_non_a01", swtor.HAIR),
    ("face_bhhelmet02_v01", swtor.OTHER),      # a helmet, not a face
    ("bms_body_a01", swtor.OTHER),
    ("headband_a01", swtor.OTHER),             # starts with head, is not one
])
def test_a_mesh_is_named_for_what_it_is(name, kind):
    assert swtor.kind_of(name) == kind


@pytest.mark.parametrize("name,code", [
    ("head_human_bmn_caucasian_a01", "bmn"),
    ("head_zabrakimp_bfa_non_a02", "bfa"),
    ("head_bfn_lana_a01", "bfn"),
    ("head_human_bmf_african_a03", "bmf"),      # the male set has no `bmb`
    ("head_human_caucasian_revan", None),       # modelled for a person
    ("head_human_doc_a01", None),
    ("head_bmnx_odd_a01", None),                # a code has to be its own part
])
def test_a_head_names_the_body_it_was_modelled_for(name, code):
    assert swtor.body_type_of(name) == code
    assert swtor.is_player_head(name) is (code is not None)


# --- the vertex layout ------------------------------------------------------


@pytest.mark.parametrize("flags,expected", [
    (0x02f, 12),      # position, then the normal
    (0x12f, 20),      # skinned: bone indices and weights sit in between
    (0x13f, 20),
    (0x16f, 20),
    (0x17f, 20),
])
def test_the_normal_follows_the_position_unless_the_mesh_is_skinned(flags, expected):
    """Its own rule, independent of where the UVs are.

    Scored the same way: the winning channel decodes unit length for 100% of
    vertices in all five layouts, the runners-up for 0 to 19% of them.
    """
    assert swtor.normal_offset(flags) == expected


@pytest.mark.parametrize("vertex_size,flags,expected", [
    (24, 0x02f, 20),      # position, normal, tangent, one UV set
    (32, 0x12f, 28),      # the above plus skinning - every head
    (36, 0x13f, 32),      # one more four-byte channel, still one UV set
    (36, 0x16f, 28),      # a second UV set, which displaces the first
    (40, 0x17f, 32),      # both
])
def test_the_uv_offset_is_the_same_rule_for_every_layout(vertex_size, flags, expected):
    """Four bytes from the end, or eight when a second UV set follows.

    Found by decoding every aligned position in every mesh of all five
    layouts and scoring how much lands in [0, 1]: the winners scored 0.97 to
    0.99 and the runners-up 0.20 to 0.62.
    """
    assert swtor.uv_offset(vertex_size, flags) == expected


# --- refusals, which are the point of a measured reader ---------------------


def test_something_that_is_not_a_model_is_refused_rather_than_read():
    assert not swtor.is_model(b"DDS \x7c\x00\x00\x00")
    with pytest.raises(swtor.SwtorError, match="GAWB"):
        swtor.parse(b"DDS \x7c\x00\x00\x00" + b"\0" * 200)


def test_a_model_version_that_has_not_been_read_is_refused():
    """Guessing past an unknown version reads somebody else's bytes as
    geometry. Every file in the install is version 5; a 6 would be new."""
    raw = b"GAWB" + struct.pack("<II", 6, 3) + b"\0" * 200
    with pytest.raises(swtor.SwtorError, match="version 6"):
        swtor.parse(raw)


def test_an_archive_that_is_not_myp_is_refused(tmp_path):
    bad = tmp_path / "not_an_archive.tor"
    bad.write_bytes(b"PK\x03\x04" + b"\0" * 64)
    with pytest.raises(swtor.SwtorError, match="MYP"):
        swtor.entries(bad)


def test_an_archive_version_that_has_not_been_read_is_refused(tmp_path):
    bad = tmp_path / "future.tor"
    bad.write_bytes(b"MYP\0" + struct.pack("<I", 9) + b"\0" * 64)
    with pytest.raises(swtor.SwtorError, match="version 9"):
        swtor.entries(bad)


def test_a_folder_without_the_archives_is_not_an_install(tmp_path):
    with pytest.raises(swtor.SwtorError, match="swtor_main_global_1.tor"):
        swtor.assets_dir(tmp_path)


# --- the install ------------------------------------------------------------


def test_the_assets_folder_is_found_from_the_game_folder(swtor_path):
    found = swtor.assets_dir(str(swtor_path))
    assert (found / swtor.MARKER_ARCHIVE).is_file()


def test_the_head_archive_is_where_the_heads_are(swtor_path):
    found = swtor.archives(str(swtor_path))
    assert [p.name for p in found] == list(swtor.HEAD_ARCHIVES)


def test_an_archive_hands_back_every_entry_it_declares(swtor_path):
    """The table is a linked list and a mis-read `next` silently truncates it,
    so the count is worth asserting rather than assuming."""
    archive = swtor.archives(str(swtor_path))[0]
    found = swtor.entries(archive)
    assert len(found) == 11800
    assert all(e.offset > 0 and e.size > 0 for e in found)


def test_every_indexed_model_is_a_head(swtor_heads):
    assert len(swtor_heads) == 993
    assert all(e.kind == swtor.HEAD for e in swtor_heads)
    assert all(e.name.startswith(swtor.HEAD_PREFIX) for e in swtor_heads)
    # Eleven are modelled for a named character rather than for a body.
    assert sum(swtor.is_player_head(e.name) for e in swtor_heads) == 982


def test_a_listing_narrows_to_one_body(swtor_path, swtor_heads):
    """The filter a character creator wants: 993 heads is not a choice."""
    found = swtor.catalogue(str(swtor_path), index=swtor_heads, body_type="bfn")
    assert 50 < len(found) < 200
    assert all(swtor.body_type_of(e.name) == "bfn" for e in found)
    assert [e.name for e in found] == sorted(e.name for e in found)


def test_a_known_head_reads_the_same_every_time(swtor_head):
    assert swtor_head.vertices == 1938
    assert swtor_head.triangles == 2828
    assert swtor_head.bones == 33
    assert swtor_head.oversize == pytest.approx(1.19, abs=0.02)


def test_a_listing_can_drop_what_will_not_fit_a_head_node(swtor_path, swtor_heads):
    """A third of the catalogue is lekku, montrals or a two-metre Trandoshan,
    and no scale makes those a face."""
    fits = swtor.catalogue(str(swtor_path), index=swtor_heads, max_oversize=1.25)
    assert len(fits) == 562
    assert all(e.oversize <= 1.25 for e in fits)

    biggest = max(swtor_heads, key=lambda e: e.oversize)
    assert biggest.oversize > 8
    assert "trandoshan" in biggest.name
    assert biggest not in fits

    humans = [e for e in swtor_heads if e.name.startswith("head_human_")]
    assert all(e.oversize <= 1.25 for e in humans)


def test_a_head_carries_the_face_rig_it_is_skinned_to(swtor_head):
    """Not used yet - a pack takes geometry only - but this is the evidence
    that a retarget is a name map rather than a research project."""
    found = swtor.mesh(swtor_head.source.read())
    assert "fc_jaw" in found.bones
    assert "Head" in found.bones
    assert sum(b.startswith("fc_lip_") for b in found.bones) >= 4
    assert sum(b.startswith("fc_lid_") for b in found.bones) == 4


def test_the_decoded_mesh_has_the_bounding_box_the_file_states(swtor_head):
    """The cross-check the whole reader rests on.

    The vertex count, the vertex stride and the buffer offset are three
    separate fields, and getting any of them wrong still produces plausible
    floats. The file states its own bounding box in a header this module never
    reads, so agreement is independent evidence rather than a tautology.
    """
    raw = swtor_head.source.read()
    stated_min = struct.unpack_from("<3f", raw, 0x20)
    stated_max = struct.unpack_from("<3f", raw, 0x30)
    found = swtor.mesh(raw, scale=1.0)

    # Undo the conversion the reader applies: (x, y, z) -> (x, -z, y) / SCALE.
    back = [(p[0] / swtor.SCALE, p[2] / swtor.SCALE, -p[1] / swtor.SCALE)
            for p in found.positions]
    for axis in range(3):
        values = [p[axis] for p in back]
        assert min(values) == pytest.approx(stated_min[axis], abs=1e-6)
        assert max(values) == pytest.approx(stated_max[axis], abs=1e-6)


def test_the_conversion_is_a_rotation_and_not_a_mirror(swtor_head):
    """A mirror reverses every triangle, and the mesh renders inside out.

    The first head through this reader scored 5% of its surface facing
    outward because `(x, z, y)` looks like the same rotation and is not. This
    is that mistake, made deliberately, so the check that catches it is
    tested rather than trusted.
    """
    from kmdlfun import headspec
    from kmdlswap.obj import ObjMesh

    found = swtor.mesh(swtor_head.source.read(), scale=swtor.HEAD_SCALE)
    good = ObjMesh(name=found.name, positions=found.positions,
                   uvs=found.uvs, faces=found.faces)
    assert headspec.check_mesh(good).accepted is False   # density, and only that
    assert [f.check for f in headspec.check_mesh(good).failures] == ["density"]

    mirrored = ObjMesh(name=found.name, faces=found.faces, uvs=found.uvs,
                       positions=[(p[0], -p[1], p[2]) for p in found.positions])
    checks = [f.check for f in headspec.check_mesh(mirrored).failures]
    assert "solid" in checks


def test_a_head_reduces_to_a_budget_a_head_model_can_carry(swtor_head):
    """The claim the module exists to support.

    A head arrives at three times a vanilla head's triangle count, so the only
    question that matters is whether it survives the reduction. At 1,300 - the
    recommended budget, above vanilla's range and far under the whole-model
    ceiling - every check passes and the face is still the same face.

    700 also passes every check here, and the render says its nose has
    collapsed into a wedge. That is why this asserts the budget the docstring
    recommends rather than the smallest one the checks tolerate.
    """
    from kmdlfun import decimate, headspec, repair
    from kmdlswap.obj import ObjMesh

    found = swtor.mesh(swtor_head.source.read(), scale=swtor.HEAD_SCALE,
                       piece=swtor.SKIN_PIECE)
    mesh = ObjMesh(name=found.name, positions=found.positions,
                   uvs=found.uvs, faces=found.faces)
    mesh = repair.crop_below(mesh, 0.2)[0]
    reduced = decimate.simplify(mesh, 1300)
    assert reduced.after == pytest.approx(1300, abs=5)

    verdict = headspec.check_mesh(reduced.mesh)
    assert verdict.accepted, verdict.lines()
    # Above vanilla's range is expected and warned about, never refused.
    assert [f.check for f in verdict.warnings] == ["density"]


def test_a_head_arrives_the_size_a_head_is(swtor_head):
    """Ten metres to the unit, and a head is about a quarter of one."""
    found = swtor.mesh(swtor_head.source.read(), scale=swtor.HEAD_SCALE)
    height = (max(p[2] for p in found.positions)
              - min(p[2] for p in found.positions))
    width = (max(p[0] for p in found.positions)
             - min(p[0] for p in found.positions))
    # A vanilla head mesh measures 0.236 tall and 0.161 wide. This one carries
    # a neck, which is what the extra height is - see the module docstring.
    assert 0.24 <= height <= 0.30
    assert 0.14 <= width <= 0.20


def test_the_pieces_of_a_head_are_the_face_and_its_eyes(swtor_head):
    raw = swtor_head.source.read()
    found = swtor.pieces(raw)
    assert len(found) == 2
    first, second = found
    assert first[0] == 0
    assert second[0] == first[1]                    # they tile the index block
    assert first[1] + second[1] == swtor_head.triangles
    assert second[1] < first[1]                     # eyes are always the smaller


def test_keeping_one_piece_drops_the_vertices_it_stops_using(swtor_head):
    """An unreferenced vertex is not harmless: `headspec` counts components,
    and a stray point is one."""
    raw = swtor_head.source.read()
    whole = swtor.mesh(raw)
    skin = swtor.mesh(raw, piece=swtor.SKIN_PIECE)
    eyes = swtor.mesh(raw, piece=1)

    assert len(skin.faces) + len(eyes.faces) == len(whole.faces)
    assert len(skin.positions) < len(whole.positions)
    assert len(skin.uvs) == len(skin.positions)
    assert max(max(f) for f in skin.faces) == len(skin.positions) - 1
    # The eyes are a pair of small spheres, nowhere near the size of the face.
    def height(m):
        return max(p[2] for p in m.positions) - min(p[2] for p in m.positions)

    assert height(eyes) < 0.05
    assert height(skin) > 0.25


def test_a_head_brings_the_normals_its_author_gave_it(swtor_head):
    """Not the ones a face average would produce.

    They differ on 30.5% of vertices by more than 25 degrees, and that share
    is the author's hard edges - nostrils, lip line, eyelids. Recomputing
    throws exactly those away. The evidence they are right and not noise is
    that the winding check goes to 0.0% disagreement against them.
    """
    import math

    found = swtor.mesh(swtor_head.source.read())
    assert len(found.normals) == len(found.positions)
    for n in found.normals[:200]:
        assert math.isclose(math.dist((0, 0, 0), n), 1.0, abs_tol=0.02)

    # They point the same way the faces do, or the mesh would light inside out.
    agree = 0
    for a, b, c in found.faces[:400]:
        p0, p1, p2 = (found.positions[i] for i in (a, b, c))
        u = [p1[i] - p0[i] for i in range(3)]
        v = [p2[i] - p0[i] for i in range(3)]
        face = (u[1]*v[2] - u[2]*v[1], u[2]*v[0] - u[0]*v[2], u[0]*v[1] - u[1]*v[0])
        length = math.dist((0, 0, 0), face) or 1.0
        agree += sum(face[i] / length * found.normals[a][i] for i in range(3)) > 0
    assert agree / 400 > 0.95


def test_normals_follow_the_piece_they_belong_to(swtor_head):
    raw = swtor_head.source.read()
    skin = swtor.mesh(raw, piece=swtor.SKIN_PIECE)
    assert len(skin.normals) == len(skin.positions)
    assert len(skin.normals) < len(swtor.mesh(raw).normals)


def test_the_unit_conversion_is_applied_once_and_always(swtor_head):
    """`SCALE` is a unit conversion, so it is not something a caller opts
    into - and applying it twice puts a head at ten metres tall."""
    raw = swtor_head.source.read()
    plain = swtor.mesh(raw)
    scaled = swtor.mesh(raw, scale=0.5)
    height = max(p[2] for p in plain.positions) - min(p[2] for p in plain.positions)
    half = max(p[2] for p in scaled.positions) - min(p[2] for p in scaled.positions)
    assert 0.25 < height < 0.40
    assert half == pytest.approx(height / 2)


def test_a_pack_leaves_the_eyes_behind_unless_asked(swtor_head, tmp_path):
    """A KOTOR head model draws its own eyes, and these shatter on
    decimation."""
    without = swtor.to_pack(swtor_head, tmp_path / "a")
    with_them = swtor.to_pack(swtor_head, tmp_path / "b", with_eyes=True)
    assert without["triangles"] < with_them["triangles"]
    assert with_them["triangles"] == swtor_head.triangles
    assert "eyes dropped" in " ".join(without["notes"])
    assert "eyes dropped" not in " ".join(with_them["notes"])


# --- the cache --------------------------------------------------------------


def test_the_index_is_cached_against_the_archive_it_came_from(swtor_path):
    """The scan costs four seconds because every entry has to be decompressed
    to be identified. Doing that once per game patch is the whole point."""
    fresh = swtor.index_of(str(swtor_path), use_cache=False)
    cached = swtor.index_of(str(swtor_path))
    assert {e.name for e in fresh} == {e.name for e in cached}
    assert {e.source.offset for e in fresh} == {e.source.offset for e in cached}


def test_a_cache_written_for_other_kinds_is_not_reused(swtor_path):
    """A cache holding only heads must not answer a question about hair."""
    archive = swtor.archives(str(swtor_path))[0]
    assert swtor._load_cache(archive, (swtor.HEAD,)) is not None
    assert swtor._load_cache(archive, (swtor.HEAD, swtor.HAIR)) is None


def test_a_corrupt_cache_is_ignored_rather_than_raised_on(swtor_path, monkeypatch,
                                                          tmp_path):
    archive = swtor.archives(str(swtor_path))[0]
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(swtor, "_cache_file", lambda _a: bad)
    assert swtor._load_cache(archive, (swtor.HEAD,)) is None


# --- out, as a head pack ----------------------------------------------------


def test_a_pack_is_written_in_kotor_s_conventions(swtor_head, tmp_path):
    import json

    from kmdlfun import headpack

    out = swtor.to_pack(swtor_head, tmp_path / "pack")
    assert (tmp_path / "pack" / "head.obj").is_file()
    # The eyes are left behind, so this is the face piece rather than the whole.
    assert out["triangles"] == swtor.pieces(swtor_head.source.read())[0][1]
    assert out["uvs"] == out["vertices"]
    assert out["texture"] is None

    manifest = json.loads(
        (tmp_path / "pack" / headpack.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["up"] == swtor.UP
    assert manifest["facing"] == swtor.FACING
    assert manifest["target"] == "head"


def test_a_pack_says_what_it_could_not_bring(swtor_head, tmp_path):
    """A head that silently arrives without its texture or its face rig is
    worse than one that says so."""
    out = swtor.to_pack(swtor_head, tmp_path / "pack")
    notes = " ".join(out["notes"])
    assert "texture" in notes
    assert "rig" in notes


def test_a_pack_reads_back_as_the_mesh_that_went_in(swtor_head, tmp_path):
    from kmdlswap import obj as kobj

    out = swtor.to_pack(swtor_head, tmp_path / "pack")
    back = kobj.read_obj(tmp_path / "pack" / "head.obj")
    assert len(back.faces) == out["triangles"]
    assert len(back.positions) == out["vertices"]
    # The authored normals have to survive the round trip, or the build falls
    # back to recomputing them and the hard edges are lost again.
    assert back.has_normals


# --- the whole corpus -------------------------------------------------------


@pytest.mark.slow
def test_every_head_in_the_install_decodes(swtor_heads):
    """993 heads, and the reader has to be right about all of them.

    A wrong stride or a wrong index offset shows up here as a triangle naming
    a vertex that does not exist, which `mesh` refuses rather than returning
    quietly broken geometry.
    """
    for entry in swtor_heads:
        found = swtor.mesh(entry.source.read(), scale=swtor.HEAD_SCALE)
        assert len(found.positions) == entry.vertices
        assert len(found.faces) == entry.triangles
        assert len(found.uvs) == entry.vertices
        assert max(max(f) for f in found.faces) < entry.vertices


@pytest.mark.slow
def test_every_head_is_the_size_its_own_file_says(swtor_heads):
    """The bounding box check, over the whole corpus rather than one head.

    This is the test that says the reader is right, and it is deliberately not
    a check that the numbers look like a head: 300 of the 993 are wider or
    taller than any head, and every one of them agrees with the box its file
    states. A shape heuristic would have called those failures and the real
    failure - a stride wrong by four bytes - would have hidden among them.
    """
    for entry in swtor_heads:
        raw = entry.source.read()
        stated_min = struct.unpack_from("<3f", raw, 0x20)
        stated_max = struct.unpack_from("<3f", raw, 0x30)
        # Only single-mesh files can be compared against the model's own box.
        model = swtor.parse(raw)
        if len(model.meshes) != 1:
            continue
        found = swtor.mesh(raw, scale=1.0, model=model)
        back = [(p[0] / swtor.SCALE, p[2] / swtor.SCALE, -p[1] / swtor.SCALE)
                for p in found.positions]
        for axis in range(3):
            values = [p[axis] for p in back]
            assert min(values) == pytest.approx(stated_min[axis], abs=1e-6), entry.name
            assert max(values) == pytest.approx(stated_max[axis], abs=1e-6), entry.name


@pytest.mark.slow
def test_the_indexed_size_is_the_size_the_mesh_decodes_to(swtor_heads):
    """`Entry.box` is measured during the scan so a listing need not decode
    993 models to sort them. It has to be the same number."""
    for entry in swtor_heads:
        found = swtor.mesh(entry.source.read(), scale=1.0)
        for axis, indexed in zip(range(3), entry.box):
            values = [p[axis] for p in found.positions]
            assert max(values) - min(values) == pytest.approx(indexed, abs=1e-5), entry.name
