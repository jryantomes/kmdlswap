"""Resolving a texture name to pixels, in the order the engine would.

A preview that reads a different file from the one the game will read is worse
than no preview, so the search order is the thing worth testing: loose files
beat packed ones, and anything the caller hands in beats both.
"""

from __future__ import annotations

import numpy as np
import pytest

from kmdlfun import textures


def write_tga(path, colour=(10, 200, 30), size=(8, 8)):
    Image = pytest.importorskip("PIL.Image", reason="Pillow needed to author a TGA")
    img = Image.new("RGB", size, colour)
    img.save(path)
    return path


def test_a_vanilla_texture_decodes(install_path):
    cache = textures.TextureCache(install_path)
    tex = cache.get("P_CarthH01")
    assert tex is not None, f"P_CarthH01 did not resolve: {cache.problems}"
    assert tex.dtype == np.uint8
    assert tex.ndim == 3 and tex.shape[2] == 3
    assert tex.shape[0] >= 32 and tex.shape[1] >= 32
    # A skin texture is not a flat fill; a decode that silently produced one
    # colour would still have the right shape.
    assert len(np.unique(tex.reshape(-1, 3), axis=0)) > 100


def test_an_unknown_name_is_none_not_an_exception(install_path):
    cache = textures.TextureCache(install_path)
    assert cache.get("no_such_texture_anywhere_01") is None


def test_a_loose_file_beats_the_texture_packs(install_path, tmp_path):
    """This is what makes a custom head work: Override wins, and a pack folder
    handed in directly wins over that, so a head can be previewed before it is
    installed anywhere."""
    write_tga(tmp_path / "P_CarthH01.tga", colour=(1, 2, 3))
    cache = textures.TextureCache(install_path, extra=[tmp_path])
    tex = cache.get("P_CarthH01")
    assert tex is not None
    assert tex.shape[:2] == (8, 8)
    assert np.array_equal(tex[0, 0], [1, 2, 3])


def test_lookup_is_case_insensitive(tmp_path):
    write_tga(tmp_path / "MyHead.tga")
    cache = textures.TextureCache(extra=[tmp_path])
    assert cache.get("myhead") is not None
    assert cache.get("MYHEAD") is not None


def test_each_name_is_decoded_once(tmp_path):
    write_tga(tmp_path / "skin.tga")
    cache = textures.TextureCache(extra=[tmp_path])
    assert cache.get("skin") is cache.get("skin")


def test_a_broken_file_is_reported_not_raised(tmp_path):
    (tmp_path / "broken.tga").write_bytes(b"not an image at all")
    cache = textures.TextureCache(extra=[tmp_path])
    assert cache.get("broken") is None
    assert any("broken" in p for p in cache.problems), "the failure must be reported"


def test_no_install_and_no_folders_resolves_nothing():
    cache = textures.TextureCache()
    assert cache.get("P_CarthH01") is None
    assert not cache.problems
