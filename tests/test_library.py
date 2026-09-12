"""The index of an install's models, and what it is safe to share.

Reading `chitin.key` is half a second and the answer never changes while the
app is open, so it is cached per folder. That cache is shared by every worker
thread in the window, which makes *what* is in it a correctness question and
not a tidiness one.
"""

from __future__ import annotations

import concurrent.futures as cf

import pytest

from kmdlfun import library as klib


@pytest.fixture
def lib(install_path):
    return klib.ModelLibrary(str(install_path))


def test_the_index_is_read_once_per_folder(install_path, monkeypatch):
    klib.forget_indexes()
    reads = []
    real = klib._index

    def counted(install):
        if install not in klib._INDEXES:
            reads.append(install)
        return real(install)

    monkeypatch.setattr(klib, "_index", counted)
    klib.ModelLibrary(str(install_path))
    klib.ModelLibrary(str(install_path))
    klib.ModelLibrary(str(install_path))
    assert len(reads) == 1, "the second and third should have come from memory"


def test_forgetting_the_index_makes_it_read_again(install_path):
    klib.ModelLibrary(str(install_path))
    assert klib._INDEXES
    klib.forget_indexes()
    assert not klib._INDEXES
    assert klib.ModelLibrary(str(install_path)).has("p_hk47")


def test_the_index_holds_plain_data_and_nothing_lazy(lib):
    """This is the whole reason the cache is shaped the way it is.

    It held PyKotor's own `FileResource`s once, on the reasoning that reading
    from one does not change it. Reading from one does not - but it reads
    through a `CaseAwarePath`, and a `pathlib.Path` builds pieces of itself
    on first use and keeps them. Two threads sharing one of those are two
    threads writing the same half-built cache, and what came of that was the
    interpreter going down with an access violation inside pathlib rather
    than any exception a test could catch.

    A path, an offset and a length have nothing lazy in them.
    """
    for name, entry in list(lib.index.items())[:50]:
        for kind, where in entry.items():
            assert kind in (klib.MDL, klib.MDX), name
            assert isinstance(where, tuple) and len(where) == 3, name
            path, offset, size = where
            assert type(path) is str, f"{name}: {type(path)} is not a plain str"
            assert type(offset) is int and type(size) is int


def test_the_same_model_read_from_many_threads_comes_back_the_same(lib):
    """The reads share an index and nothing else. Eight threads on one model
    have to agree with a single read of it, byte for byte."""
    wanted = [n for n in ("p_hk47", "p_carthh", "p_bastilah", "p_t3m3")
              if lib.has(n)]
    assert wanted
    once = {n: lib.read(n) for n in wanted}

    def again(_seed):
        return {n: lib.read(n) for n in wanted}

    with cf.ThreadPoolExecutor(8) as pool:
        for got in pool.map(again, range(24)):
            assert got == once


def test_a_model_that_is_not_there_is_not_claimed(lib):
    assert not lib.has("no_such_model_at_all")
    with pytest.raises(KeyError):
        lib.read("no_such_model_at_all")


def test_a_model_with_only_half_a_pair_is_not_offered(lib, monkeypatch):
    """`has` is what every caller filters on, and a model with an MDL and no
    MDX cannot be read - offering it would turn a filter into a crash."""
    index = dict(lib.index)
    index["half_a_model"] = {klib.MDL: ("nowhere", 0, 0)}
    monkeypatch.setattr(lib, "index", index)
    assert not lib.has("half_a_model")
