"""Jade Empire geometry, in KOTOR's conventions.

The two engines share a lineage and almost nothing about their file layout, so
the splice engine will never touch a Jade model. What Jade has is 158 heads and
112 bodies KOTOR does not, and geometry already has a route in: the one built
for sculpts and Blender exports. A Jade head becomes a head pack.

Everything here needs a real Jade install, because the format is only worth
testing against the files it was reverse-engineered from.
"""

from __future__ import annotations

import pytest

from kmdlfun import installs, jade


@pytest.fixture(scope="module")
def jade_path():
    found = installs.detect().get(installs.JADE)
    if not found:
        pytest.skip("no Jade Empire install on this machine")
    return found


@pytest.fixture(scope="module")
def k1_path():
    found = installs.detect().get(installs.K1)
    if not found:
        pytest.skip("no KOTOR install on this machine")
    return found


@pytest.fixture(scope="module")
def catalogue(jade_path):
    return jade.catalogue(jade_path)


@pytest.fixture(scope="module")
def a_head(catalogue):
    return next(e for e in catalogue if e.resref.lower() == "h_common01_")


# --- finding the models -----------------------------------------------------


def test_the_catalogue_finds_heads_and_bodies(catalogue):
    kinds = {}
    for entry in catalogue:
        kinds[entry.kind] = kinds.get(entry.kind, 0) + 1

    assert kinds.get(jade.HEAD, 0) > 100
    assert kinds.get(jade.BODY, 0) > 50


def test_a_models_two_halves_come_from_different_archives(a_head):
    """The MDL is in `<area>.rim` and the MDX in its `-a` companion. Reading
    one offset out of the other's archive gives vertices with no faces, and a
    mesh that looks empty rather than wrong."""
    assert a_head.mdx is not None
    assert a_head.mdl.archive != a_head.mdx.archive
    assert a_head.mdx.archive.stem.endswith("-a")


def test_every_entry_can_be_read(catalogue):
    """A catalogue entry that cannot be read is worse than one that is absent,
    because it only fails once somebody picks it."""
    for entry in catalogue[:12]:
        mdl, mdx = jade.read(entry)
        assert mdl[:4] or mdl, entry.resref
        assert len(mdl) == entry.mdl.size
        if entry.mdx:
            assert len(mdx) == entry.mdx.size


def test_the_bytes_match_what_the_game_keeps_loose(jade_path, a_head):
    """`override/` holds loose copies of some models. If the archive extraction
    is right, they are byte-identical."""
    from pathlib import Path

    loose_mdl = Path(jade_path) / "override" / "H_Common01_.mdl"
    loose_mdx = Path(jade_path) / "override" / "h_common01_.mdx"
    if not (loose_mdl.is_file() and loose_mdx.is_file()):
        pytest.skip("this install has no loose copy to compare against")

    mdl, mdx = jade.read(a_head)
    assert mdl == loose_mdl.read_bytes()
    assert mdx == loose_mdx.read_bytes()


def test_models_are_named_consistently_enough_to_sort(catalogue):
    """Unlike Jade's folder names, its resrefs are reliable."""
    for entry in catalogue:
        assert entry.kind == jade.kind_of(entry.resref)


def test_a_folder_that_is_not_a_jade_install_says_so(tmp_path):
    with pytest.raises(jade.JadeError, match="no data folder"):
        jade.catalogue(tmp_path)


# --- reading one ------------------------------------------------------------


def test_a_head_reads_as_geometry(a_head):
    mesh = jade.mesh(*jade.read(a_head))

    assert len(mesh.positions) > 100
    assert len(mesh.faces) > 100
    assert mesh.uvs, "without UVs it builds but renders untextured"
    assert len(mesh.uvs) == len(mesh.positions)


def test_every_face_indexes_a_vertex_that_exists(a_head):
    """A dropped vertex renumbers every face after it, which turns a handful of
    bad points into a scrambled mesh."""
    mesh = jade.mesh(*jade.read(a_head))
    top = len(mesh.positions)

    assert all(0 <= i < top for face in mesh.faces for i in face)


def test_it_arrives_upright(a_head):
    """Jade's height runs along X, KOTOR's along Z. Uncorrected, a head lies on
    its side - and the bounding box alone cannot tell you, which is why the
    rotation was settled by rendering."""
    mesh = jade.mesh(*jade.read(a_head))
    lo, hi = mesh.bounds
    span = hi - lo

    assert span[2] > span[0], "not taller than it is wide"
    assert span[2] > span[1], "not taller than it is deep"


def test_turning_the_model_does_not_mirror_it(a_head):
    """A reflection has determinant -1: it would invert every face and hand
    back a head that renders inside out."""
    import numpy as np

    assert np.linalg.det(jade.TO_KOTOR) == pytest.approx(1.0)


def test_the_scale_is_applied_and_can_be_changed(a_head):
    raw = jade.mesh(*jade.read(a_head), scale=1.0)
    scaled = jade.mesh(*jade.read(a_head), scale=0.5)

    raw_lo, raw_hi = raw.bounds
    small_lo, small_hi = scaled.bounds
    assert (small_hi - small_lo)[2] == pytest.approx((raw_hi - raw_lo)[2] * 0.5,
                                                     rel=1e-6)


def test_a_converted_head_is_about_the_size_of_a_KOTOR_one(a_head, install_path):
    """The point of the scale factor. Within a quarter either way is close
    enough for the fit step to finish the job without distorting anything."""
    from kmdlfun import render as krender
    from kmdlfun.library import ModelLibrary
    from kmdlswap import layout as kl
    import numpy as np

    mesh = jade.mesh(*jade.read(a_head))
    lo, hi = mesh.bounds
    jade_height = (hi - lo)[2]

    scene = krender.from_layout(kl.parse(*ModelLibrary(install_path).read("p_carthh")))
    p = np.asarray(scene.positions, dtype=float)
    kotor_height = (p.max(axis=0) - p.min(axis=0))[2]

    assert 0.75 < jade_height / kotor_height < 1.25, (
        f"jade {jade_height:.3f} against kotor {kotor_height:.3f}"
    )


def test_it_is_centred_on_its_own_origin(a_head):
    """A Jade head's node chain places it at the top of a body, about 1.8 units
    up. A head pack is expected around its own origin."""
    import numpy as np

    mesh = jade.mesh(*jade.read(a_head))
    lo, hi = mesh.bounds
    middle = (lo + hi) / 2

    assert np.linalg.norm(middle) < 0.05, middle


def test_rubbish_bytes_are_refused_rather_than_crashing(tmp_path):
    with pytest.raises(jade.JadeError):
        jade.mesh(b"not a jade model at all" * 8, None, tmp_dir=tmp_path)


# --- out as a head pack -----------------------------------------------------


def test_a_pack_is_written_that_the_head_builder_understands(a_head, tmp_path):
    from kmdlfun import headpack

    result = jade.to_pack(a_head, tmp_path / "pack")

    assert (result["pack"] / "head.obj").is_file()
    assert (result["pack"] / headpack.MANIFEST_NAME).is_file()
    assert result["triangles"] > 100


def test_the_manifest_says_it_is_already_in_kotors_conventions(a_head, tmp_path):
    import json

    from kmdlfun import headpack

    result = jade.to_pack(a_head, tmp_path / "pack")
    data = json.loads((result["pack"] / headpack.MANIFEST_NAME).read_text())

    assert data["up"] == "z", "it was converted on the way out"
    assert data["facing"] == "+y"
    assert "Jade" in data["notes"]


@pytest.mark.slow
def test_a_jade_head_builds_onto_carth(a_head, tmp_path, install_path):
    """The whole point, end to end. Everything after the conversion is the
    ordinary head-pack path - decimation, winding repair, the solidity check
    and the weight transfer all apply unchanged."""
    from kmdlfun import headbuild

    jade.to_pack(a_head, tmp_path / "pack")
    result = headbuild.run(str(tmp_path / "pack"), install=install_path,
                           host="p_carthh", node="Head", decimate=690,
                           repair=True, fit=True, reshape=False, hide=[],
                           crop=None, build=True)

    assert result.ok, "\n".join(result.lines)
    assert any("placement: centre within" in line for line in result.lines)


# --- pictures ---------------------------------------------------------------


def test_a_thumbnail_can_be_drawn_and_is_cached(a_head, tmp_path):
    first = jade.thumbnail(a_head, root=tmp_path)
    assert first is not None and first.is_file()

    again = jade.thumbnail(a_head, root=tmp_path)
    assert again == first


# --- textures ---------------------------------------------------------------
#
# A Jade mesh does not name its texture. It names a *material* by number; the
# material names the texture; and both live in the archives, split the same way
# models are - material beside the MDL, texture beside the MDX.


def test_the_material_names_its_texture(jade_path):
    """The rule this depends on: the diffuse texture is a null-terminated
    string at offset 0x64. Verified below against every material in the game."""
    assert jade.texture_name(jade_path, 13657) == "H_Common01"


def test_that_offset_holds_for_every_material_in_the_game(jade_path):
    """Scanning for the first printable run instead gets 13% of them wrong,
    because float bytes are frequently printable ASCII - so the rule has to be
    the offset, and it has to be checked against all of them."""
    from pathlib import Path

    materials = sorted(Path(jade_path).glob("override/*.mab"))
    if len(materials) < 100:
        pytest.skip("this install has no loose materials to check against")

    good = 0
    for path in materials:
        raw = path.read_bytes()
        if len(raw) <= jade.TEXTURE_NAME_AT:
            continue
        end = raw.find(b"\0", jade.TEXTURE_NAME_AT)
        name = raw[jade.TEXTURE_NAME_AT:end].decode("ascii", "replace")
        # A texture name is a resref: printable, no spaces, sane length.
        if name and name.isprintable() and " " not in name and len(name) <= 32:
            good += 1
    assert good / len(materials) > 0.99, f"{good}/{len(materials)}"


def test_an_unknown_material_is_not_an_error(jade_path):
    assert jade.texture_name(jade_path, 99999999) is None


def test_a_texture_decodes_to_an_image(jade_path):
    import io

    from PIL import Image

    data = jade.texture(jade_path, "H_Common01")
    assert data, "the texture did not decode"

    image = Image.open(io.BytesIO(data))
    assert image.size == (256, 256)
    assert image.mode in ("RGB", "RGBA")


def test_a_missing_texture_gives_nothing_rather_than_raising(jade_path):
    assert jade.texture(jade_path, "no_such_texture_anywhere") is None


def test_a_pack_carries_its_texture(a_head, tmp_path):
    result = jade.to_pack(a_head, tmp_path / "pack")

    assert result["texture"], result["notes"]
    tga = result["pack"] / f"{result['texture']}.tga"
    assert tga.is_file() and tga.stat().st_size > 1000
    assert any("decoded from .txb" in n for n in result["notes"])


def test_the_texture_name_fits_a_resref(a_head, tmp_path):
    """The filename becomes the resref and that field is 16 characters, so a
    long pack name must not produce one the engine will truncate."""
    result = jade.to_pack(a_head, tmp_path / "a_very_long_pack_name_indeed")

    assert len(result["texture"]) <= 16, result["texture"]


def test_only_one_texture_lands_in_the_pack(a_head, tmp_path):
    """`headpack` refuses a folder with several and no way to choose."""
    result = jade.to_pack(a_head, tmp_path / "pack")
    images = list(result["pack"].glob("*.tga")) + list(result["pack"].glob("*.tpc"))

    assert len(images) == 1


def test_the_texture_can_be_declined(a_head, tmp_path):
    result = jade.to_pack(a_head, tmp_path / "pack", with_texture=False)

    assert result["texture"] is None
    assert not list(result["pack"].glob("*.tga"))


def test_v_runs_the_other_way_from_ours(a_head):
    """Jade's V axis is upside down against this project's `.obj` pipeline.
    Left alone the texture still lands on the head and still looks like skin -
    the eyes end up near the eyes - so it reads as a slightly wrong model
    rather than as a flipped coordinate, which is why it went unnoticed until
    the two were rendered side by side."""
    import tempfile
    from pathlib import Path

    from kmdlfun.vendor.jade import parse_jade_mdl

    mdl_bytes, mdx_bytes = jade.read(a_head)
    folder = Path(tempfile.mkdtemp())
    (folder / "m.mdl").write_bytes(mdl_bytes)
    (folder / "m.mdx").write_bytes(mdx_bytes)
    raw = parse_jade_mdl(folder / "m.mdl", folder / "m.mdx")
    original = next(n.mesh.uv_layers[0] for n in raw.iter_nodes()
                    if n.mesh is not None and n.mesh.uv_layers)

    converted = jade.mesh(mdl_bytes, mdx_bytes)
    assert converted.uvs[0][1] == pytest.approx(1.0 - float(original[0][1]))
    assert converted.uvs[0][0] == pytest.approx(float(original[0][0]))


@pytest.mark.slow
def test_a_textured_jade_head_builds_and_the_texture_travels(a_head, tmp_path,
                                                             install_path):
    from kmdlfun import headbuild

    jade.to_pack(a_head, tmp_path / "pack")
    result = headbuild.run(str(tmp_path / "pack"), install=install_path,
                           host="p_carthh", node="Head", decimate=690,
                           repair=True, fit=True, reshape=False, hide=[],
                           crop=None, build=True)
    assert result.ok, "\n".join(result.lines)
    assert result.texture_path is not None

    written = tmp_path / "built"
    headbuild.write(result, written, "p_carthh")
    assert list(written.glob("*.tga")), sorted(p.name for p in written.iterdir())


# --- what is actually a head ------------------------------------------------


def test_masks_are_not_counted_as_heads(catalogue):
    """`H_` covers more than faces. `H_Mask*` are open shells of 78 to 185
    triangles that cannot pass a check asking whether a surface is closed or
    faces outward, because they are not meant to be either, and `H_Decap01` is
    a severed stump. Calling them heads turns ten sensible refusals into ten
    apparent failures."""
    masks = [e for e in catalogue if e.kind == jade.MASK]
    heads = [e for e in catalogue if e.kind == jade.HEAD]

    assert len(masks) >= 9, [e.resref for e in masks]
    assert all("mask" in e.resref.lower() or "decap" in e.resref.lower()
               for e in masks)
    assert not any("mask" in e.resref.lower() for e in heads)
    assert len(heads) > 140


def test_kind_of_reads_the_prefix_and_the_rest():
    assert jade.kind_of("H_Common01_") == jade.HEAD
    assert jade.kind_of("H_Mask03_") == jade.MASK
    assert jade.kind_of("h_decap01_") == jade.MASK
    assert jade.kind_of("N_Bandit_") == jade.BODY
    assert jade.kind_of("a010_01") == jade.OTHER


def test_a_mask_still_converts(catalogue, tmp_path):
    """Offering it is right even though it will not pass the head checks -
    somebody may want a mask, and refusing to convert it helps nobody."""
    mask = next(e for e in catalogue if e.kind == jade.MASK
                and "mask" in e.resref.lower())
    result = jade.to_pack(mask, tmp_path / "pack")

    assert result["triangles"] > 0
    assert (result["pack"] / "head.obj").is_file()


def test_heads_and_bodies_get_their_own_scale():
    """Measured separately and they disagree. Using one figure for both made
    heads visibly small in game."""
    assert jade.scale_for(jade.HEAD) == jade.HEAD_SCALE
    assert jade.scale_for(jade.BODY) == jade.BODY_SCALE
    assert jade.HEAD_SCALE != jade.BODY_SCALE
    # a mask is a face, so it scales like one
    assert jade.scale_for(jade.MASK) == jade.HEAD_SCALE


def test_the_body_scale_is_height_against_height():
    """It was 0.83, from Jade's X extent of 1.85 against a KOTOR body's height.

    1.85 is near-constant across the corpus and that constancy was read as
    evidence it was the height. It is the *arm span* - just as constant, and on
    a T-posed figure about half again the height. Measured height to height,
    KOTOR's median 1.576 against Jade's 1.618, the answer is 0.97: a Jade body
    is a few percent larger, not a sixth.
    """
    assert 0.93 <= jade.BODY_SCALE <= 1.02, (
        "a body scale near 0.83 is the arm span being compared to a height")


def test_a_pack_uses_the_scale_for_its_kind(a_head, tmp_path):
    """`to_pack` knows the kind; `mesh` only sees bytes, so the choice belongs
    where the entry is."""
    from kmdlswap.obj import read_obj

    def height(folder):
        m = read_obj(folder / "head.obj")
        return (max(p[2] for p in m.positions)
                - min(p[2] for p in m.positions))

    chosen = jade.to_pack(a_head, tmp_path / "chosen")
    as_body = jade.to_pack(a_head, tmp_path / "as_body", scale=jade.BODY_SCALE)

    # Which is larger is not the point and has changed once already; that the
    # kind decides, rather than a single default, is.
    assert height(chosen["pack"]) != height(as_body["pack"])
    assert abs(height(chosen["pack"])
               / (height(as_body["pack"]) / jade.BODY_SCALE)
               - jade.HEAD_SCALE) < 1e-6


# --- the texture resref ------------------------------------------------------


def test_the_texture_is_named_from_the_model_not_the_folder(tmp_path):
    """Two heads written into folders of the same name must not collide.

    The filename becomes the texture's resref, and it used to come from the
    output folder. The window's default folder is `jade_<resref>`, which spends
    fourteen characters before the digits that tell two heads apart: all eight
    `h_bandit0*` heads came out as `jade_h_bandit001`, and 42 of the 270 models
    in the catalogue shared a name with another. Installing two of them together
    means one wears the other's face.
    """
    from kmdlfun import installs, jade

    root = installs.detect().get(installs.JADE)
    if not root:
        import pytest

        pytest.skip("no Jade Empire install detected")

    from pathlib import Path

    wanted = ("h_bandit01_", "h_bandit02_")
    seen = set()
    for resref in wanted:
        entry = next(
            (e for e in jade.catalogue(Path(root)) if e.resref.lower() == resref), None
        )
        if entry is None:
            import pytest

            pytest.skip(f"{resref} not present")
        # Deliberately the same folder name for both.
        pack = tmp_path / str(len(seen)) / "j"
        jade.to_pack(entry, pack)
        textures = [p.name for p in pack.iterdir() if p.suffix == ".tga"]
        assert textures, f"{resref} produced no texture"
        seen.update(textures)

    assert len(seen) == len(wanted), f"two heads share a texture name: {seen}"


def test_every_head_in_the_catalogue_gets_its_own_texture_name():
    """Checked across the whole catalogue rather than a sample, because the
    collisions were in one family of names and a sample would miss them."""
    import collections
    from pathlib import Path

    from kmdlfun import installs, jade

    root = installs.detect().get(installs.JADE)
    if not root:
        import pytest

        pytest.skip("no Jade Empire install detected")

    names = collections.defaultdict(list)
    for entry in jade.catalogue(Path(root)):
        stem = entry.resref.strip("_").lower()[: jade.RESREF_STEM] + "01"
        names[stem].append(entry.resref)
        assert len(stem) <= 16, f"{stem} does not fit the resref field"

    clashing = {k: v for k, v in names.items() if len(v) > 1}
    assert not clashing, f"texture names collide: {clashing}"


class TestDrawnWithItsTexture:
    """A Jade head carries its eyes, brows and mouth in the atlas.

    Drawn flat they are all the same grey mask, which is no help at all when the
    picker's whole job is choosing a face.
    """

    @staticmethod
    def test_a_scene_carries_the_atlas(a_head):
        from kmdlfun import jade

        built = jade.scene(a_head)

        assert built.textured, "the head would draw as flat grey"
        assert built.uvs is not None and len(built.uvs) == len(built.positions)
        assert built.textures[0].ndim == 3

    @staticmethod
    def test_it_still_draws_without_one(a_head, monkeypatch):
        """An unreadable atlas costs the texture, not the picture."""
        from kmdlfun import jade

        monkeypatch.setattr(jade, "texture_for", lambda *_a, **_k: None)
        built = jade.scene(a_head)

        assert len(built.faces) and not built.textured


class TestBuiltIntoAHost:
    @staticmethod
    def test_it_builds_and_then_comes_from_the_cache(a_head, k1_path, jade_path):
        """Converting takes a few seconds - fine once, not fine every time a
        picker is clicked."""
        import time

        from kmdlfun import jade

        made = jade.as_head(a_head.resref, jade_path, k1_path, "p_carthh")
        assert made is not None
        mdl_at, mdx_at, _texture = made
        assert mdl_at.is_file() and mdx_at.is_file()

        start = time.perf_counter()
        again = jade.as_head(a_head.resref, jade_path, k1_path, "p_carthh")
        assert again[0] == mdl_at
        assert time.perf_counter() - start < 0.5, "the build was not cached"

    @staticmethod
    def test_an_unknown_head_is_refused_quietly(k1_path, jade_path):
        from kmdlfun import jade

        assert jade.as_head("no_such_head", jade_path, k1_path, "p_carthh") is None


class TestHostsAreNotAllOneSize:
    @staticmethod
    def test_a_smaller_host_still_takes_the_head(k1_path, jade_path):
        """Carth's head node is 0.161x0.225x0.281 and Bastila's is
        0.137x0.187x0.231, so a Jade head that drops straight into his is 1.4x
        too big for hers. It failed the size check outright and the creator
        could offer only male hosts."""
        from kmdlfun import jade

        made = jade.as_head("h_mercf01_", jade_path, k1_path, "P_BastilaH")

        assert made is not None, "a smaller host was refused the head"
        mdl_at, mdx_at, _texture = made
        assert mdl_at.is_file() and mdx_at.is_file()

    @staticmethod
    def test_a_host_with_room_is_not_shrunk(k1_path, jade_path):
        """Fitting is a fallback, not the default: a host the head already fits
        keeps it at full size."""
        import numpy as np

        from kmdlfun import jade, parts as kparts, space
        from kmdlfun import mouthparts as km
        from kmdlswap import layout as kl

        made = jade.as_head("h_mercf01_", jade_path, k1_path, "p_carthh")
        lay = kl.parse(made[0].read_bytes(), made[1].read_bytes())
        node = next(n for n in kparts.mesh_nodes(lay) if n.name.lower() == "head")
        P = km._model_space(lay, node, space.rest_pose(lay))
        height = float(P[:, 2].max() - P[:, 2].min())

        assert height > 0.27, f"the head was fitted when it did not need to be ({height:.3f})"


class TestHeadsThatWearTheirOwnCollar:
    """A converted head keeps whatever its mesh had below the jaw, and on some
    of them that is clothing - UV-mapped to a garment in the atlas rather than
    to skin. It shows as a coloured tube standing out of a KOTOR collar.
    """

    @staticmethod
    def test_the_head_seen_in_game_is_on_the_list():
        from kmdlfun import jade

        assert jade.wears_a_collar("h_mercf01_")

    @staticmethod
    def test_a_bare_neck_is_not():
        from kmdlfun import jade

        for name in ("h_bandit04_", "h_common01_", "h_stu01_", "h_miq01_"):
            assert not jade.wears_a_collar(name), name

    @staticmethod
    def test_the_two_that_read_as_collars_and_are_not():
        """A thumbnail is not enough to judge these on. `h_common01_` wears
        shoulder plates below the jaw and `h_trogr01_` has a mane; both read as
        a collar small and neither is one, and taking them at face value put the
        estimate at 35 heads instead of 18."""
        from kmdlfun import jade

        assert not jade.wears_a_collar("h_common01_")
        assert not jade.wears_a_collar("h_trogr01_")

    @staticmethod
    def test_it_is_a_minority_and_named(catalogue):
        """If most heads were like this the feature would not be worth having."""
        from kmdlfun import jade

        heads = {e.resref.lower() for e in catalogue
                 if jade.kind_of(e.resref) == jade.HEAD}
        assert jade.NECK_GARMENT <= heads, (
            jade.NECK_GARMENT - heads, "a name on the list is not a head in the game")
        assert len(jade.NECK_GARMENT) / len(heads) < 0.20

    @staticmethod
    def test_the_name_is_matched_however_it_is_written():
        from kmdlfun import jade

        assert jade.wears_a_collar("H_MercF01_")
        assert jade.wears_a_collar("  h_mercf01_  ")
        assert not jade.wears_a_collar("")


class TestBodiesStandUp:
    """A body does not share the heads' convention.

    A head's height runs along X and `TO_KOTOR` turns it upright; a body's runs
    along Z already and the figure is upside down along it. Put a body through
    the head's correction and it arrives lying on its side.
    """

    @staticmethod
    def girths(P, axis):
        import numpy as np

        v = P[:, axis]
        t = (v - v.min()) / (v.max() - v.min())
        others = [i for i in range(3) if i != axis]
        out = []
        for a, b in ((0, 1 / 3), (1 / 3, 2 / 3), (2 / 3, 1)):
            q = P[(t >= a) & (t <= b)][:, others]
            out.append(float(np.hypot(*(q.max(0) - q.min(0)))) if len(q) > 2 else 0.0)
        return out

    def test_a_body_comes_out_upright(self, catalogue):
        """Narrow at the feet, broad at the shoulders - the shape a KOTOR body
        has. Extents cannot check this: on a T-pose the arm span and the height
        are close enough that a bounding box reads the same either way."""
        import numpy as np

        entry = next((e for e in catalogue
                      if e.resref.lower() == "n_bandit_"), None)
        if entry is None:
            pytest.skip("n_bandit_ not present")
        P = np.asarray(jade.mesh(*jade.read(entry), kind=entry.kind,
                                 scale=jade.scale_for(entry.kind)).positions, float)

        low, _mid, high = self.girths(P, 2)
        assert high > low, "the figure is upside down"
        assert np.ptp(P[:, 2]) > np.ptp(P[:, 1]), "it is lying down"

    @staticmethod
    def test_the_turn_does_not_mirror_it():
        """A reflection maps the axis just as well and turns every face inside
        out - the same care `TO_KOTOR` takes."""
        import numpy as np

        assert round(float(np.linalg.det(jade.BODY_FACING)), 6) == 1.0

    @staticmethod
    def test_a_head_still_uses_the_head_correction(a_head):
        import numpy as np

        P = np.asarray(jade.mesh(*jade.read(a_head), kind=a_head.kind,
                                 scale=jade.scale_for(a_head.kind)).positions, float)
        assert np.ptp(P[:, 2]) > np.ptp(P[:, 1]), "the head is not upright"


class TestTheJadeSkeleton:
    """Jade bodies carry a full named skeleton, and it answers what the mesh
    will not.

    The arms' rest pose is the question that matters for porting a body: KOTOR's
    rest at 52-55 degrees below horizontal, and a mesh bound to those bones in a
    different pose puts its arms nowhere near them.
    """

    @staticmethod
    def bodies(catalogue):
        return [e for e in catalogue if jade.kind_of(e.resref) == jade.BODY]

    def test_a_body_carries_named_bones(self, catalogue):
        entry = next((e for e in self.bodies(catalogue)
                      if e.resref.lower() == "n_bandit_"), None)
        if entry is None:
            pytest.skip("n_bandit_ not present")
        bones = jade.skeleton(entry)

        assert len(bones) > 30
        for name in ("BLArmUppeL01", "HandL", "LegUppeL", "SpinBone0"):
            assert name in bones, name

    def test_every_mapped_bone_is_really_there(self, catalogue):
        """The map is only worth having if the names in it exist."""
        for entry in self.bodies(catalogue)[:6]:
            try:
                bones = jade.skeleton(entry)
            except jade.JadeError:
                continue
            missing = [k for k in jade.BONE_NAMES if k not in bones]
            assert not missing, (entry.resref, missing)

    def test_the_arms_rest_where_kotor_s_do_not(self, catalogue):
        """5.7 degrees against KOTOR's 52-55 - a T-pose against an A-pose.

        Measured off the geometry this came out between -20 and +11 and could
        not be found at all on a robed figure or a child, because a robe's hem
        is wider than any arm. Off the bones it is the same number every time.
        """
        seen = []
        for entry in self.bodies(catalogue)[:8]:
            try:
                angle = jade.arm_rest(entry)
            except jade.JadeError:
                continue
            if angle is not None:
                seen.append((entry.resref, angle))
        assert len(seen) >= 4, seen
        for resref, angle in seen:
            assert 0 < angle < 20, (resref, angle)
        spread = max(a for _r, a in seen) - min(a for _r, a in seen)
        assert spread < 2.0, f"the rest pose should be a constant, got {seen}"


class TestTheQuaternionOrder:
    """Jade stores a node's orientation `w` first, and reading it any other way
    turns the whole model.

    On a body that turn came within a hair of a half-revolution, so a corrective
    flip hid it - and neither of the two numeric checks that were meant to catch
    an upside-down figure could see past it. The bones can.
    """

    @staticmethod
    def bodies(catalogue):
        return [e for e in catalogue if jade.kind_of(e.resref) == jade.BODY]

    def test_the_bones_land_inside_the_skin(self, catalogue):
        """The check that settles the order. A skeleton is inside its body."""
        import numpy as np

        checked = 0
        for entry in self.bodies(catalogue)[:5]:
            try:
                bones = jade.skeleton(entry)
                mesh = jade.mesh(*jade.read(entry), orient=False, centre=False,
                                 scale=1.0, kind=jade.BODY)
            except jade.JadeError:
                continue
            skin = np.asarray(mesh.positions, dtype=float)
            pts = np.array([bones[k] for k in jade.BONE_NAMES if k in bones])
            gap = np.linalg.norm(skin[None, :, :] - pts[:, None, :],
                                 axis=2).min(axis=1)
            # Read the other way round the worst bone sits 0.43 out - a hand's
            # width away from any part of the body it belongs to.
            assert gap.max() < 0.2, (entry.resref, float(gap.max()))
            checked += 1
        assert checked >= 3

    def test_a_body_stands_up_without_being_turned_over(self, catalogue):
        import numpy as np

        for entry in self.bodies(catalogue)[:5]:
            try:
                bones = jade.skeleton(entry)
            except jade.JadeError:
                continue
            if "FootBallL" not in bones or "HeadBone" not in bones:
                continue
            assert bones["FootBallL"][2] < bones["HeadBone"][2], entry.resref
            assert abs(bones["FootBallL"][2]) < 0.2, "feet near the ground"


class TestSwingingTheArmsDown:
    """Jade stands its people in a T-pose; KOTOR's rest is an A-pose.

    Forty-seven degrees separate them, and a body dropped onto KOTOR's skeleton
    with its arms still out sideways has half of each arm somewhere the engine
    will never put it.
    """

    @staticmethod
    def bodies(catalogue):
        return [e for e in catalogue if jade.kind_of(e.resref) == jade.BODY]

    def test_the_arms_land_on_the_angle_asked_for(self, catalogue):
        import numpy as np

        checked = 0
        for entry in self.bodies(catalogue)[:5]:
            try:
                model = jade._parse(*jade.read(entry))
            except jade.JadeError:
                continue
            where, _parent = jade._tree(model)
            swing = jade.repose(model, jade.KOTOR_ARM_REST)
            assert swing, entry.resref

            def after(name):
                if name not in swing:
                    return where[name]
                pivot, turn = swing[name]
                return pivot + turn @ (where[name] - pivot)

            for side in ("L", "R"):
                v = after(f"Hand{side}") - after(f"BLArmUppe{side}01")
                v = v / np.linalg.norm(v)
                got = float(np.degrees(np.arctan2(-v[2], abs(v[0]))))
                assert abs(got - jade.KOTOR_ARM_REST) < 0.5, (entry.resref, side, got)
            checked += 1
        assert checked >= 3

    def test_the_move_falls_away_towards_the_middle(self, catalogue):
        """A body is posed, not rebuilt. Travel should fall off from the hands
        to the spine, and it does - averaged by distance from the centreline it
        goes 0.48, 0.26, 0.11, 0.008, 0.001. The torso is carried along a
        millimetre by a shoulder cap that shares the bicep's weight, which is
        what blend skinning is for; it is not disturbed.
        """
        import numpy as np

        bands = ((0.60, 9.9), (0.45, 0.60), (0.30, 0.45), (0.15, 0.30), (0.0, 0.15))
        checked = 0
        for entry in self.bodies(catalogue)[:4]:
            try:
                plain = np.asarray(jade.mesh(*jade.read(entry), kind=jade.BODY,
                                             centre=False, scale=1.0).positions, float)
                posed = np.asarray(jade.mesh(*jade.read(entry), kind=jade.BODY,
                                             centre=False, scale=1.0,
                                             pose=jade.KOTOR_ARM_REST).positions, float)
            except jade.JadeError:
                continue
            travel = np.linalg.norm(plain - posed, axis=1)
            out = np.abs(plain[:, 0])
            means = []
            for low, high in bands:
                band = (out >= low) & (out < high)
                if band.sum() > 10:
                    means.append(float(travel[band].mean()))
            assert len(means) >= 4, entry.resref
            assert means == sorted(means, reverse=True), (entry.resref, means)
            assert means[0] > 0.3, (entry.resref, means)
            assert means[-1] < 0.01, (entry.resref, means)

            # And the arms really did come in - narrower, and no shorter.
            assert np.ptp(posed[:, 0]) < np.ptp(plain[:, 0]) * 0.8
            assert abs(np.ptp(posed[:, 2]) - np.ptp(plain[:, 2])) < 1e-6
            checked += 1
        assert checked >= 3

    def test_the_shoulder_does_not_tear(self, catalogue):
        """Every vertex follows the bones it is weighted to, so one weighted
        half to the bicep and half to the chest travels half the way. Rotating
        the arm island outright would leave a hole at the shoulder instead."""
        import numpy as np

        entry = next((e for e in self.bodies(catalogue)
                      if e.resref.lower() == "n_bandit_"), None)
        if entry is None:
            pytest.skip("n_bandit_ not present")
        plain = np.asarray(jade.mesh(*jade.read(entry), kind=jade.BODY,
                                     centre=False, scale=1.0).positions, float)
        posed = np.asarray(jade.mesh(*jade.read(entry), kind=jade.BODY,
                                     centre=False, scale=1.0,
                                     pose=jade.KOTOR_ARM_REST).positions, float)
        travel = np.linalg.norm(plain - posed, axis=1)
        # Out at the hand the arm swings furthest; at the shoulder itself it
        # barely moves. If the join were rigid there would be no middle.
        shoulder = (np.abs(plain[:, 0]) > 0.30) & (np.abs(plain[:, 0]) < 0.45)
        assert shoulder.any()
        assert 0.0 < travel[shoulder].max() < travel.max() * 0.5

    def test_a_head_is_left_alone(self, a_head):
        """Heads have no arms, and asking for a pose should not disturb one."""
        import numpy as np

        plain = np.asarray(jade.mesh(*jade.read(a_head), kind=a_head.kind,
                                     centre=False, scale=1.0).positions, float)
        posed = np.asarray(jade.mesh(*jade.read(a_head), kind=a_head.kind,
                                     centre=False, scale=1.0,
                                     pose=jade.KOTOR_ARM_REST).positions, float)
        assert np.abs(plain - posed).max() < 1e-9

    @staticmethod
    def test_kotor_s_own_arms_are_where_the_constant_says(k1_path):
        """The target is measured, not chosen. If a future KOTOR install reads
        differently this is the test that says so."""
        import numpy as np

        from kmdlfun import space
        from kmdlfun.library import ModelLibrary
        from kmdlswap import layout as kl

        seen = []
        for name in ("PMBBM", "PFBBM"):
            lay = kl.parse(*ModelLibrary(k1_path).read(name))
            rest = space.rest_pose(lay)
            for side in ("l", "r"):
                a = np.asarray(rest[lay.node_by_name(f"{side}bicep_g").index]
                               .position, float)
                b = np.asarray(rest[lay.node_by_name(f"{side}hand_g").index]
                               .position, float)
                v = (b - a) / np.linalg.norm(b - a)
                seen.append(float(np.degrees(np.arctan2(-v[2], abs(v[0])))))
        assert min(seen) > 50.0 and max(seen) < 58.0, seen
        assert min(seen) <= jade.KOTOR_ARM_REST <= max(seen)


class TestWhichWayRoundABodyGoes:
    """The check that two renders could not make.

    A half-turned human looks very like a human, so a body facing backwards -
    and handed the wrong way round with it - survived being looked at twice. The
    two skeletons settle it between them without anybody having to squint.
    """

    @staticmethod
    def kotor_bone(k1_path, model, bone):
        import numpy as np

        from kmdlfun import space
        from kmdlfun.library import ModelLibrary
        from kmdlswap import layout as kl

        lay = kl.parse(*ModelLibrary(k1_path).read(model))
        rest = space.rest_pose(lay)
        return np.asarray(rest[lay.node_by_name(bone).index].position, float)

    def test_both_games_hand_a_body_the_same_way(self, catalogue, k1_path):
        """KOTOR's left bicep sits at negative x. So must Jade's left arm, or
        the port comes out mirrored - left hand on the right wrist."""
        import numpy as np

        left = self.kotor_bone(k1_path, "PMBBM", "lbicep_g")
        right = self.kotor_bone(k1_path, "PMBBM", "rbicep_g")
        assert left[0] < 0 < right[0], "KOTOR is not built the way this assumes"

        checked = 0
        for entry in [e for e in catalogue
                      if jade.kind_of(e.resref) == jade.BODY][:5]:
            try:
                bones = jade.skeleton(entry)
            except jade.JadeError:
                continue
            here = jade.BODY_FACING @ bones["BLArmUppeL01"]
            there = jade.BODY_FACING @ bones["BLArmUppeR01"]
            assert here[0] < 0 < there[0], (entry.resref, here[0], there[0])
            checked += 1
        assert checked >= 3

    def test_both_games_point_the_toes_the_same_way(self, catalogue, k1_path):
        """The other axis, and the one that says front from back: in KOTOR the
        toes sit forward of the ball of the foot along +y."""
        import numpy as np

        step = (self.kotor_bone(k1_path, "PMBBM", "lfootT_g")
                - self.kotor_bone(k1_path, "PMBBM", "lfoot_g"))
        assert step[1] > 0, "KOTOR is not built the way this assumes"

        checked = 0
        for entry in [e for e in catalogue
                      if jade.kind_of(e.resref) == jade.BODY][:5]:
            try:
                bones = jade.skeleton(entry)
            except jade.JadeError:
                continue
            if "FootToesL" not in bones or "FootBallL" not in bones:
                continue
            forward = jade.BODY_FACING @ (bones["FootToesL"] - bones["FootBallL"])
            assert forward[1] > 0, (entry.resref, forward)
            checked += 1
        assert checked >= 3


class TestCuttingABodyIntoKotorMeshes:
    """Jade ships a body as one mesh weighted to 45 bones. KOTOR will not skin
    one mesh to more than seventeen - no model in the game does - so the body
    has to be cut up before it can be a KOTOR body at all.
    """

    @staticmethod
    def bodies(catalogue):
        return [e for e in catalogue if jade.kind_of(e.resref) == jade.BODY]

    @staticmethod
    def parts_of(entry, **kw):
        return jade.partition(jade._parse(*jade.read(entry)), **kw)

    def test_no_part_asks_for_more_bones_than_kotor_allows(self, catalogue):
        """The whole point. One bone over and the engine drops the mesh."""
        checked = 0
        for entry in self.bodies(catalogue)[:12]:
            try:
                parts = self.parts_of(entry)
            except jade.JadeError:
                continue
            assert parts, entry.resref
            for part in parts:
                assert len(part.bones) <= jade.BONE_CAP, (
                    entry.resref, part.name, len(part.bones))
            checked += 1
        assert checked >= 8

    def test_kotor_itself_never_goes_over_that_cap(self, k1_path):
        """`BONE_CAP` is measured, not chosen. If it is wrong, every part this
        module writes is built on a wrong number."""
        from kmdlfun.library import ModelLibrary
        from kmdlswap import layout as kl

        lib = ModelLibrary(k1_path)
        worst = 0
        for name in ("PMBBM", "PFBBM", "P_CarthBB", "p_juhanibb", "n_darthrevan"):
            if not lib.has(name):
                continue
            lay = kl.parse(*lib.read(name))
            for node in lay.nodes:
                if node.in_animation is None and node.is_skin:
                    worst = max(worst, sum(1 for s in node.bonemap if s >= 0))
        assert worst, "no skinned meshes found"
        assert worst <= jade.BONE_CAP
        # 17 is not a ceiling nobody reaches - the game sits right on it.
        assert worst == jade.BONE_CAP

    def test_not_one_triangle_is_dropped_or_drawn_twice(self, catalogue):
        checked = 0
        for entry in self.bodies(catalogue)[:8]:
            try:
                model = jade._parse(*jade.read(entry))
            except jade.JadeError:
                continue
            before = 0

            def count(node):
                nonlocal before
                found = node.mesh
                if found is not None and found.render and found.vertices:
                    before += len(found.triangles or ())
                for child in node.children or []:
                    count(child)

            count(model.root)
            after = sum(len(p.faces) for p in jade.partition(model))
            assert before == after, (entry.resref, before, after)
            checked += 1
        assert checked >= 6

    def test_each_part_carries_weights_it_can_use(self, catalogue):
        """Weights are renormalised after the merge and the prune, and every
        slot indexes that part's own bone list - not the model's."""
        checked = 0
        for entry in self.bodies(catalogue)[:8]:
            try:
                parts = self.parts_of(entry)
            except jade.JadeError:
                continue
            for part in parts:
                assert len(part.weights) == len(part.positions), part.name
                for slots in part.weights:
                    assert slots, part.name
                    assert abs(sum(w for _s, w in slots) - 1.0) < 1e-6
                    for slot, _w in slots:
                        assert 0 <= slot < len(part.bones)
            checked += 1
        assert checked >= 6

    def test_no_two_nodes_share_a_name(self, catalogue):
        """A body can arrive as several meshes, each with a torso's worth of
        triangles. MDL nodes are addressed by name and a duplicate is a model
        the game misreads."""
        checked = 0
        for entry in self.bodies(catalogue)[:12]:
            try:
                parts = self.parts_of(entry)
            except jade.JadeError:
                continue
            names = [p.name for p in parts]
            assert len(names) == len(set(names)), (entry.resref, names)
            checked += 1
        assert checked >= 8

    def test_the_limbs_come_out_where_limbs_go(self, catalogue):
        """Named LArm, and on the left. The split is by weight, not by
        position, so this is a real check and not a restatement."""
        import numpy as np

        checked = 0
        for entry in self.bodies(catalogue)[:8]:
            try:
                parts = self.parts_of(entry)
            except jade.JadeError:
                continue
            where = {}
            for part in parts:
                if part.name in ("Torso", "LArm", "RArm", "Legs"):
                    where[part.name] = np.asarray(part.positions, dtype=float)
            if not {"LArm", "RArm", "Torso", "Legs"} <= set(where):
                continue
            assert where["LArm"][:, 0].mean() < 0 < where["RArm"][:, 0].mean()
            assert where["Legs"][:, 2].mean() < where["Torso"][:, 2].mean()
            # The arms are out at the sides, further out than the trunk.
            assert (abs(where["LArm"][:, 0]).max()
                    > abs(where["Torso"][:, 0]).max())
            checked += 1
        assert checked >= 5

    def test_it_only_names_bones_kotor_actually_has(self, catalogue, k1_path):
        """A weight on a bone the target skeleton does not carry is a weight
        that goes nowhere."""
        from kmdlfun.library import ModelLibrary
        from kmdlswap import layout as kl

        lib = ModelLibrary(k1_path)
        known = set()
        for name in ("PMBBM", "PFBBM", "P_CarthBB"):
            lay = kl.parse(*lib.read(name))
            known |= {n.name.lower() for n in lay.nodes if n.in_animation is None}

        checked = 0
        for entry in self.bodies(catalogue)[:8]:
            try:
                parts = self.parts_of(entry)
            except jade.JadeError:
                continue
            for part in parts:
                unknown = [b for b in part.bones if b.lower() not in known]
                assert not unknown, (entry.resref, part.name, unknown)
            checked += 1
        assert checked >= 6

    def test_a_seam_vertex_goes_into_both_parts(self, catalogue):
        """Splitting a mesh means the vertices along the cut belong to two
        parts, and each part needs its own copy. Both copies keep the same
        weights, so the seam still moves as one when the model animates."""
        entry = next((e for e in self.bodies(catalogue)
                      if e.resref.lower() == "n_bandit_"), None)
        if entry is None:
            pytest.skip("n_bandit_ not present")
        model = jade._parse(*jade.read(entry))
        before = 0

        def count(node):
            nonlocal before
            found = node.mesh
            if found is not None and found.render and found.vertices:
                before += len(found.vertices)
            for child in node.children or []:
                count(child)

        count(model.root)
        after = sum(len(p.positions) for p in jade.partition(model))
        assert after > before, (before, after)
        # A cut through a body, not a shredding of it.
        assert after < before * 1.6, (before, after)


class TestTheUvsComeOutTheSameWayTwice:
    """`mesh` and `partition` read the same model and must agree about it.

    Jade's V axis runs the opposite way to the one this project's pipeline
    expects, and `partition` used to read the layer straight out of the reader
    and skip the turn. The body then wore a plausible outfit off the wrong rows
    of its own atlas - which reads as a slightly wrong model rather than as a
    flipped coordinate, and is exactly the kind of thing that survives being
    looked at.
    """

    @staticmethod
    def test_turning_a_uv_over_is_its_own_undoing():
        u, v = jade.turn_uv((0.25, 0.75))
        assert (u, v) == (0.25, 0.25)
        assert jade.turn_uv(jade.turn_uv((0.25, 0.75))) == (0.25, 0.75)

    @staticmethod
    def test_a_partitioned_body_uses_the_same_uvs_as_the_mesh(catalogue):
        """Not vertex for vertex - the parts renumber and duplicate seams - but
        the same set, and the same span of V."""
        import numpy as np

        bodies = [e for e in catalogue if jade.kind_of(e.resref) == jade.BODY]
        checked = 0
        for entry in bodies[:5]:
            try:
                whole = jade.mesh(*jade.read(entry), kind=jade.BODY,
                                  scale=jade.BODY_SCALE)
                parts = jade.partition(jade._parse(*jade.read(entry)))
            except jade.JadeError:
                continue
            if not whole.uvs:
                continue
            mine = np.asarray([uv for p in parts for uv in p.uvs], dtype=float)
            theirs = np.asarray(whole.uvs, dtype=float)
            assert len(mine), entry.resref
            assert abs(mine[:, 1].min() - theirs[:, 1].min()) < 1e-6, entry.resref
            assert abs(mine[:, 1].max() - theirs[:, 1].max()) < 1e-6, entry.resref
            assert abs(mine[:, 0].min() - theirs[:, 0].min()) < 1e-6, entry.resref
            # Every UV a part carries is one the whole mesh carries.
            want = {(round(u, 6), round(v, 6)) for u, v in theirs}
            got = {(round(u, 6), round(v, 6)) for u, v in mine}
            assert got <= want, entry.resref
            checked += 1
        assert checked >= 3
