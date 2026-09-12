"""Reading Neverwinter Nights models.

The install is the corpus and the oracle, the same bargain the rest of these
tests make. Everything `nwn.py` claims about where a field sits was worked out
by reading all 32,832 models rather than from documentation, so the test that
matters most is the one that reads all of them again.
"""

from __future__ import annotations

import pytest

from kmdlfun import nwn


# --- naming, which needs no install ----------------------------------------


@pytest.mark.parametrize("resref,kind", [
    ("pmh0_head012", nwn.HEAD),
    ("pfe2_head007", nwn.HEAD),
    ("pmo0_head001", nwn.HEAD),
    ("plc_a01", nwn.PLACEABLE),
    ("plc_barrel", nwn.PLACEABLE),
    ("pmh0_bicepl255", nwn.OTHER),   # a body part, not a head
    ("c_dragred", nwn.OTHER),
    ("dag01_a01_01", nwn.OTHER),     # a tile
    ("pmh0_head", nwn.OTHER),        # no number
    ("ph0_head001", nwn.OTHER),      # no gender letter
    ("pxh0_head001", nwn.OTHER),     # not a race the game has
])
def test_a_model_is_named_for_what_it_is(resref, kind):
    assert nwn.kind_of(resref) == kind


def test_a_text_model_is_recognised_rather_than_parsed():
    """A third of the install is ASCII MDL. Saying so is a better answer than
    a struct error from reading a comment as a header."""
    assert nwn.is_ascii_model(b"# Exported from something\n")
    assert not nwn.is_ascii_model(b"\0\0\0\0rest of a binary model")
    with pytest.raises(nwn.NwnError, match="text MDL"):
        nwn.split(b"# Exported from something\n" + b"\0" * 40)


def test_a_wrapper_that_does_not_add_up_is_refused():
    """The three sizes at the front have to account for the whole file. A
    mismatch means this is not the format, and guessing past it would read
    somebody else's bytes as geometry."""
    import struct

    raw = struct.pack("<3I", 0, 999, 999) + b"\0" * 40
    with pytest.raises(nwn.NwnError, match="wrapper says"):
        nwn.split(raw)


# --- the format, against the real install ----------------------------------


def test_the_key_file_is_found_wherever_the_build_keeps_it(nwn_path):
    found = nwn.key_path(str(nwn_path))
    assert found.is_file()
    assert found.name in nwn.KEY_NAMES


def test_a_folder_that_is_not_the_game_says_so(tmp_path):
    with pytest.raises(nwn.NwnError, match="nwn_base.key"):
        nwn.key_path(tmp_path)


def test_the_install_index_finds_the_models(nwn_index):
    models = [k for k in nwn_index if k[1] == nwn.MDL_TYPE]
    assert len(models) > 30000, "the base game ships 32,832 models"
    assert ("pmh0_head012", nwn.MDL_TYPE) in nwn_index


def test_the_catalogue_offers_heads_and_placeables(nwn_path, nwn_index):
    cat = nwn.catalogue(str(nwn_path), index=nwn_index)
    kinds = {e.kind for e in cat}
    assert kinds == {nwn.HEAD, nwn.PLACEABLE}
    heads = [e for e in cat if e.kind == nwn.HEAD]
    assert len(heads) > 400, "434 heads in the base game"
    # Heads first, so the list opens on what the tab is for.
    assert cat[0].kind == nwn.HEAD


def test_a_head_reads_as_geometry(nwn_index):
    found = nwn.mesh(nwn_index[("pmh0_head012", nwn.MDL_TYPE)].read(),
                     kind=nwn.HEAD)
    assert len(found.positions) == 120
    assert len(found.faces) == 163
    # Every vertex has to carry the same attributes or the indices stop
    # meaning the same thing in each array.
    assert len(found.uvs) == len(found.positions)
    assert len(found.normals) == len(found.positions)
    assert max(max(f) for f in found.faces) < len(found.positions)
    assert found.textures == ["pmh0_head012"]


def test_a_head_comes_out_the_size_of_a_kotor_head(nwn_index):
    """Both games measure in the same units, which is the whole reason NWN
    needs no scaling. A head is about a quarter of a unit tall."""
    found = nwn.mesh(nwn_index[("pmh0_head012", nwn.MDL_TYPE)].read(),
                     kind=nwn.HEAD)
    lo, hi = found.bounds
    assert 0.2 < hi[2] - lo[2] < 0.35


def test_a_head_stands_up_the_way_kotor_heads_do(nwn_index):
    """Z is up and X is left-to-right, which is what makes NWN geometry usable
    without a rotation.

    Only two of the three axes can be argued from numbers. A head is taller
    than it is wide and it is symmetric across the centre line, and both of
    those are checked here. Which way it *looks* cannot be: a nose and the
    back of a skull both stick out, and on `pmh0_head012` the hair reaches
    further back than the nose reaches forward, so the extreme point is
    behind the head rather than on its face. That one was settled by cutting
    the mesh in half and rendering each half - the +Y half is the one with
    the eyes, the same as a KOTOR head - and `nwn.FACING` records the answer.
    """
    found = nwn.mesh(nwn_index[("pmh0_head012", nwn.MDL_TYPE)].read(),
                     kind=nwn.HEAD)
    lo, hi = found.bounds
    assert hi[2] - lo[2] > hi[0] - lo[0], "a head is taller than it is wide"
    across = max(abs(lo[0]), abs(hi[0]))
    assert abs(abs(lo[0]) - abs(hi[0])) < across * 0.1, (
        "a face is symmetric about X, which is how we know X is the "
        "left-to-right axis"
    )


def test_a_placeable_welds_its_several_meshes_into_one(nwn_index):
    """A crate is four nodes. A head pack holds one mesh, so they are
    concatenated with their face indices shifted - and the test that it was
    done right is that no face points outside the array."""
    found = nwn.mesh(nwn_index[("plc_c09", nwn.MDL_TYPE)].read(),
                     kind=nwn.PLACEABLE)
    assert len(found.positions) == 287
    assert len(found.faces) == 159
    assert max(max(f) for f in found.faces) < len(found.positions)
    assert len(found.textures) > 1, "each node names its own texture"


def test_a_walkmesh_is_not_offered_as_geometry(nwn_index):
    """The collision box is a mesh by the flag and scenery by intent. Welding
    one into a head pack would put a cube on somebody's face."""
    model = nwn.parse(nwn_index[("plc_c09", nwn.MDL_TYPE)].read())
    for node in model.nodes:
        if node.flags & nwn.HAS_AABB:
            assert not node.is_mesh


@pytest.mark.slow
def test_every_binary_model_in_the_install_parses(nwn_index):
    """The claim `nwn.py` makes is that the node header is 112 bytes and the
    name fields are 64. This is what that claim is worth: 25,598 models, no
    exceptions and no special cases."""
    parsed = text = 0
    broken = []
    for (name, restype), source in nwn_index.items():
        if restype != nwn.MDL_TYPE:
            continue
        raw = source.read()
        if nwn.is_ascii_model(raw):
            text += 1
            continue
        try:
            nwn.mesh(raw, kind=nwn.kind_of(name))
        except Exception as exc:  # noqa: BLE001
            broken.append(f"{name}: {type(exc).__name__}: {exc}")
        else:
            parsed += 1
    assert not broken[:10], broken[:10]
    assert parsed > 25000
    assert text > 7000, "and a third of them are text, which is not a failure"


# --- textures ---------------------------------------------------------------


def test_a_head_texture_is_built_out_of_its_palette(nwn_path, nwn_index):
    """A head has no picture of itself in the game - only a layer and a
    brightness per pixel, and a shared palette. This is where the face comes
    from."""
    got = nwn.read_texture(str(nwn_path), "pmh0_head012", index=nwn_index)
    assert got is not None
    _name, data = got
    pixels, width, height = nwn.read_tga(data)
    assert (width, height) == (256, 256)
    assert len(pixels) == width * height * 3
    # Not a flat fill, and not the grey a missing palette would give.
    assert len({pixels[i:i + 3] for i in range(0, len(pixels), 3 * 997)}) > 20


def test_the_skin_tone_can_be_chosen(nwn_path, nwn_index):
    """176 of them, which is the point of the format. Two different choices
    have to give two different faces."""
    _n, fair = nwn.read_texture(str(nwn_path), "pmh0_head012",
                                index=nwn_index, colours={"skin": 0})
    _n, other = nwn.read_texture(str(nwn_path), "pmh0_head012",
                                 index=nwn_index, colours={"skin": 120})
    assert fair != other


def test_the_greyscale_beside_a_head_is_not_mistaken_for_it(nwn_path, nwn_index):
    """`pmh0_head012` ships a 64x64 greyscale TGA under the same name as its
    PLT. Taking whichever was found first put a smudge on every face."""
    assert ("pmh0_head012", nwn.TGA_TYPE) in nwn_index
    _n, data = nwn.read_texture(str(nwn_path), "pmh0_head012", index=nwn_index)
    _pixels, width, height = nwn.read_tga(data)
    assert (width, height) == (256, 256), "the PLT, not the 64x64 greyscale"


def test_a_tga_that_is_not_truecolour_is_refused_rather_than_guessed(nwn_index):
    raw = nwn_index[("pmh0_head012", nwn.TGA_TYPE)].read()
    assert raw[2] != nwn.TGA_TRUECOLOUR
    assert nwn.read_tga(raw) == (b"", 0, 0)


def test_a_tga_survives_being_written_and_read_back():
    rgb = bytes(range(0, 96)) * 2
    tga = nwn.write_tga(rgb, 8, 8)
    back, width, height = nwn.read_tga(tga)
    assert (width, height) == (8, 8)
    assert back == rgb


# --- the head pack ----------------------------------------------------------


def test_a_head_is_written_as_a_pack_the_tool_can_build(nwn_path, nwn_index,
                                                        tmp_path):
    from kmdlfun import headpack

    entry = next(e for e in nwn.catalogue(str(nwn_path), index=nwn_index)
                 if e.resref == "pmh0_head012")
    made = nwn.to_pack(entry, tmp_path / "nwn_head", install=str(nwn_path),
                       index=nwn_index)

    pack = headpack.load(made["pack"])
    assert pack.ok, pack.problems
    assert made["vertices"] == 120
    assert made["triangles"] == 163
    assert made["texture"], "the face should have come with it"
    assert (made["pack"] / f"{made['texture']}.tga").is_file()
    assert len(made["texture"]) <= 16, "a resref field is sixteen characters"
    # Already in KOTOR's own conventions, so nothing downstream should rotate
    # or rescale it.
    assert pack.manifest["up"] == "z"
    assert pack.manifest["facing"] == nwn.FACING


def test_two_heads_do_not_share_a_texture_name(nwn_path, nwn_index):
    """The name comes from the model, not the folder. Named from the folder,
    every head written into `nwn_pmh0_head0**` truncated to the same sixteen
    characters and the second one installed wore the first one's face."""
    cat = [e for e in nwn.catalogue(str(nwn_path), index=nwn_index)
           if e.kind == nwn.HEAD]
    names = {(e.resref.strip("_").lower())[:nwn.RESREF_STEM] + "01"
             for e in cat}
    assert len(names) == len(cat), "every head needs its own texture name"


# --- the command line -------------------------------------------------------


def run_cli(argv, capsys):
    from kmdlfun.cli import main

    code = main(argv)
    return code, capsys.readouterr()


def test_the_command_lists_what_is_there(nwn_path, capsys):
    code, out = run_cli(["nwn", "--install", str(nwn_path)], capsys)
    assert code == 0
    assert "model(s) in" in out.out
    assert "pmh0_head012" in out.out
    assert "Pass one of these and --out to convert it." in out.out


def test_the_command_lists_placeables_when_asked(nwn_path, capsys):
    code, out = run_cli(
        ["nwn", "--install", str(nwn_path), "--kind", "placeable"], capsys)
    assert code == 0
    assert "plc_" in out.out
    assert "pmh0_head012" not in out.out


def test_a_name_that_is_not_there_is_refused(nwn_path, capsys):
    code, out = run_cli(
        ["nwn", "no_such_model", "--install", str(nwn_path)], capsys)
    assert code == 1
    assert "no model named" in out.err


def test_converting_without_an_out_folder_says_so(nwn_path, capsys):
    """Rather than writing somewhere the caller did not choose."""
    code, out = run_cli(
        ["nwn", "pmh0_head012", "--install", str(nwn_path)], capsys)
    assert code == 1
    assert "--out is required" in out.err


def test_a_folder_that_is_not_the_game_is_refused(tmp_path, capsys):
    code, out = run_cli(["nwn", "--install", str(tmp_path)], capsys)
    assert code == 1
    assert "nwn_base.key" in out.err


def test_the_command_writes_a_pack(nwn_path, tmp_path, capsys):
    from kmdlfun import headpack

    out_dir = tmp_path / "pack"
    code, out = run_cli(
        ["nwn", "pmh0_head012", "--install", str(nwn_path),
         "--out", str(out_dir), "--skin", "40", "--hair", "12"], capsys)
    assert code == 0, out.err
    assert headpack.load(out_dir).ok
    assert "wrote a head pack to" in out.out
    # The next step is spelled out, because knowing you have a pack is not
    # the same as knowing what to do with it.
    assert "kmdlfun head" in out.out


def test_the_chosen_colours_reach_the_texture(nwn_path, tmp_path, capsys):
    packs = []
    for skin in (0, 150):
        out_dir = tmp_path / f"skin{skin}"
        code, _out = run_cli(
            ["nwn", "pmh0_head012", "--install", str(nwn_path),
             "--out", str(out_dir), "--skin", str(skin)], capsys)
        assert code == 0
        packs.append(next(out_dir.glob("*.tga")).read_bytes())
    assert packs[0] != packs[1], "--skin has to reach the picture"
