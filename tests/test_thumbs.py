"""Cached faces for the donor list.

A name does not tell you what a face looks like, and the list is a few hundred
names. Nothing here touches Tk - the cache is a directory of PNGs, and the app
turns those into widgets - so it can be tested without a window.
"""

from __future__ import annotations

import time

import pytest

from kmdlfun import thumbs
from kmdlfun.library import ModelLibrary


@pytest.fixture(scope="module")
def k1(install_path):
    return ModelLibrary(str(install_path))


def test_a_face_is_drawn_and_kept(k1, tmp_path):
    mdl, mdx = k1.read("p_carthh")
    first = thumbs.render(mdl, mdx, root=tmp_path)

    assert first is not None and first.is_file()
    assert first.stat().st_size > 0
    assert first.suffix == ".png"

    again = thumbs.render(mdl, mdx, root=tmp_path)
    assert again == first, "a second call must reuse the file, not redraw it"


def test_the_cache_is_keyed_by_what_it_draws(k1, tmp_path):
    """A model swapped into Override keeps its name and changes its bytes.

    Keyed by name, the list would keep showing the face that is gone - which is
    exactly the situation this tool creates every time it builds something.
    """
    mdl, mdx = k1.read("p_carthh")
    other, _ = k1.read("p_bastilah")

    assert thumbs.key_for(mdl, mdx) != thumbs.key_for(other, mdx)
    assert thumbs.key_for(mdl, mdx) != thumbs.key_for(mdl, mdx, size=32)
    assert thumbs.key_for(mdl, mdx) == thumbs.key_for(bytes(mdl), bytes(mdx))


def test_a_model_with_nothing_visible_yields_no_face(k1, tmp_path):
    """`n_darthrevanh` has no visible meshes at all - it is the one model in
    the game the catalogue cannot draw. A gap in the list beats an exception
    that stops the list opening."""
    if not k1.has("n_darthrevanh"):
        pytest.skip("n_darthrevanh not in this install")

    assert thumbs.render(*k1.read("n_darthrevanh"), root=tmp_path) is None


def test_rubbish_bytes_are_a_gap_not_a_crash(tmp_path):
    assert thumbs.render(b"not a model", b"nor this", root=tmp_path) is None


def test_cached_reports_without_drawing(k1, tmp_path):
    mdl, mdx = k1.read("p_carthh")
    assert thumbs.cached(mdl, mdx, root=tmp_path) is None
    thumbs.render(mdl, mdx, root=tmp_path)
    assert thumbs.cached(mdl, mdx, root=tmp_path) is not None


def test_ensure_yields_as_it_goes(k1, tmp_path):
    """A generator so faces can reach the screen while the rest are drawn."""
    names = ["p_carthh", "p_bastilah", "no_such_model", "p_hk47"]
    got = dict(thumbs.ensure(k1, names, root=tmp_path))

    assert set(got) == {"p_carthh", "p_bastilah", "p_hk47"}
    assert all(p.is_file() for p in got.values())


def test_ensure_can_be_abandoned(k1, tmp_path):
    """The list changes whenever the filter does, so a run that is no longer
    about the visible list has to be droppable."""
    seen = []

    def stop():
        return len(seen) >= 1

    for name, _ in thumbs.ensure(k1, ["p_carthh", "p_bastilah", "p_hk47"],
                                 root=tmp_path, should_stop=stop):
        seen.append(name)

    assert len(seen) == 1, seen


def test_the_cache_actually_saves_the_work(k1, tmp_path):
    names = ["p_carthh", "p_bastilah", "p_hk47"]

    cold = time.perf_counter()
    dict(thumbs.ensure(k1, names, root=tmp_path))
    cold = time.perf_counter() - cold

    warm = time.perf_counter()
    dict(thumbs.ensure(k1, names, root=tmp_path))
    warm = time.perf_counter() - warm

    assert warm < cold / 2, f"cold {cold:.3f}s, warm {warm:.3f}s - caching does nothing"
