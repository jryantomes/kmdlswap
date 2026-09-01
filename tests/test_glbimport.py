"""Geometry from outside the game, turned into something buildable.

This is the route that put a Tripo-generated head on Carth - confirmed in game:
it turns with the neck and opens its mouth. The reading of the `.glb` itself is
covered in `test_gltf.py`; what is here is the pack that gets written, because
that is the part a build then depends on.
"""

from __future__ import annotations

import json

import pytest

from kmdlfun import glbimport


TRI = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
FACES = [(0, 1, 2)]
UVS = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]


@pytest.fixture
def glb(tmp_path):
    """A minimal .glb, built by the same helpers the reader is tested with."""
    from test_gltf import build_glb, simple

    def write(*, uvs=True, name="head.glb"):
        doc, blob = simple(TRI, FACES, uvs=UVS if uvs else None)
        path = tmp_path / name
        path.write_bytes(build_glb(doc, blob))
        return path
    return write


def test_a_pack_has_everything_a_build_needs(glb, tmp_path):
    result = glbimport.run(glb(), tmp_path / "pack")

    assert (result.pack / "head.obj").is_file()
    assert any(p.name.endswith(".json") for p in result.files), result.files
    assert result.vertices > 0
    assert result.triangles > 0


def test_the_manifest_says_which_way_is_up(glb, tmp_path):
    """glTF is Y-up with -Z forward. Getting this wrong puts a head on its
    side or facing backwards, and it looks like a broken import rather than a
    coordinate convention."""
    from kmdlfun import headpack

    result = glbimport.run(glb(), tmp_path / "pack")
    data = json.loads((result.pack / headpack.MANIFEST_NAME).read_text())

    assert data["up"] == "y"
    assert data["facing"] == "+y"
    assert "head.glb" in data["notes"]


def test_a_missing_file_says_so_rather_than_raising_something_opaque(tmp_path):
    with pytest.raises(glbimport.ImportError_, match="no such file"):
        glbimport.run(tmp_path / "nothing.glb", tmp_path / "pack")


def test_something_that_is_not_a_glb_is_refused(tmp_path):
    bad = tmp_path / "bad.glb"
    bad.write_bytes(b"this is not a glb, not even slightly" * 4)

    with pytest.raises(glbimport.ImportError_):
        glbimport.run(bad, tmp_path / "pack")


def test_a_pack_with_no_uvs_is_reported_not_hidden(glb, tmp_path):
    """It still builds; it just renders untextured. Saying nothing here is how
    someone spends an evening wondering why their head is grey."""
    result = glbimport.run(glb(uvs=False), tmp_path / "pack")
    text = " ".join(glbimport.summarise(result, "head.glb"))

    assert result.has_uvs is False
    assert "NO" in text and "untextured" in text


def test_the_texture_resref_fits_the_field(glb, tmp_path):
    """A texture name is a resref and the field is 16 characters. A longer one
    is truncated by the writer and the model then points at nothing."""
    long_name = tmp_path / "a_very_long_pack_name_indeed"
    result = glbimport.run(glb(), long_name)

    if result.texture:
        assert len(result.texture) <= 16, result.texture


def test_alpha_survives_the_conversion():
    """Dropping alpha is what cost a ported Quarren its eyes: the MDL and MDX
    were byte-identical either way and the texture was the whole difference."""
    Image = pytest.importorskip("PIL.Image")

    opaque = Image.new("RGBA", (4, 4), (10, 20, 30, 255))
    partial = Image.new("RGBA", (4, 4), (10, 20, 30, 128))

    assert not glbimport.has_alpha(opaque), "an opaque channel carries nothing"
    assert glbimport.has_alpha(partial)
    assert not glbimport.has_alpha(Image.new("RGB", (4, 4), (1, 2, 3)))


def test_the_summary_reads_the_same_in_both_places(glb, tmp_path):
    """One account, so the window and the terminal cannot drift."""
    result = glbimport.run(glb(), tmp_path / "pack")
    lines = glbimport.summarise(result, "head.glb")

    assert lines[0] == "head.glb"
    assert any("vertices" in line for line in lines)
    assert any("triangles" in line for line in lines)
    assert any(str(result.pack) in line for line in lines)
