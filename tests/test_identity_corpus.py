"""Milestone 0 acceptance: every vanilla K1 model must parse into a span map
that covers every byte, resolves every pointer, and re-emits byte-identically.

A high pass rate on a large corpus is the only real proof the reader is correct.
"""

from __future__ import annotations

import pytest

from kmdlswap import layout as kl
from kmdlswap import validate as kv

CHARACTER_MODELS = ["p_hk47", "p_bastilah", "p_carthh", "p_t3m3", "p_zaalbar"]


@pytest.mark.parametrize("name", CHARACTER_MODELS)
def test_character_model_round_trips(pair, name):
    mdl, mdx = pair(name)
    rep = kv.check(kl.parse(mdl, mdx))
    assert not rep.gaps, f"{name}: {len(rep.gaps)} gaps, {rep.gap_bytes} bytes unaccounted"
    assert not rep.overlaps, f"{name}: {rep.overlaps[0]}"
    assert not rep.dangling, f"{name}: {rep.dangling[0]}"
    assert rep.identity_mdl and rep.identity_mdx


def test_hk47_structure(pair):
    """The Definition of Done model. Spot-check the facts a user needs in order
    to pick a target node."""
    lay = kl.parse(*pair("p_hk47"))
    assert lay.model_name == "P_HK47"
    geometry = [n for n in lay.nodes if n.in_animation is None]
    assert len(geometry) == lay.node_count

    head = lay.node_by_name("head")
    assert head.is_mesh
    assert head.vertex_count > 0
    assert head.face_count > 0
    # Exact casing and full parent path survive the round trip.
    assert head.path(lay.nodes).startswith("P_HK47")


def test_serialize_is_a_copy_not_a_reconstruction(pair):
    """Identity must come from copying original bytes, not regenerating them -
    that is the whole premise of the byte-surgical design."""
    mdl, mdx = pair("p_hk47")
    lay = kl.parse(mdl, mdx)
    out_mdl, out_mdx = kv.serialize(lay)
    assert out_mdl == mdl
    assert out_mdx == mdx


@pytest.mark.slow
def test_whole_corpus(resources):
    """Full-install sweep. Marked slow; run with `-m slow`."""
    failures = []
    for name in sorted(resources):
        entry = resources[name]
        try:
            rep = kv.check(kl.parse(entry["mdl"].data(), entry["mdx"].data()))
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
            continue
        if not rep.ok:
            failures.append(
                f"{name}: gaps={len(rep.gaps)}({rep.gap_bytes}B) "
                f"overlaps={len(rep.overlaps)} dangling={len(rep.dangling)} "
                f"identity={rep.identity_mdl and rep.identity_mdx}"
            )
    assert not failures, f"{len(failures)}/{len(resources)} models failed:\n" + "\n".join(
        failures[:25]
    )
