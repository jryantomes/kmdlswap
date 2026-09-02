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
