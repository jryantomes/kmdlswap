# Milestone 2 — no-op swap

**Date:** 2026-08-28
**Harness:** [`tools/noop_swap_sweep.py`](../tools/noop_swap_sweep.py)
**Tests:** `tests/test_swap.py`

## Method

For every mesh node in every vanilla K1 model: extract the node's geometry into
decoded components, rebuild the MDX block, face array, MDL-side vertex array and
index array **from those components**, splice them back, and byte-diff the whole
model. Then re-parse the result and re-run the Milestone 0 validators.

This is deliberately not a byte copy. The arrays are genuinely regenerated, so
identity proves the extract/rebuild path is faithful — not merely that nothing
was touched. With no content change every delta is zero, which isolates the
rewrite mechanism from any question about replacement geometry.

## Result

**76,703 / 76,703 mesh nodes re-emit byte-identically**, across all 2,832 models.
Every result also re-parses with full coverage, offset closure and identity.

Lightsaber blade nodes (`saber` flag) are explicitly **refused**, not silently
mishandled: their geometry lives in MDL-side arrays rather than the MDX stream,
which is outside this tool's scope.

## What the no-op does *not* test

All deltas are zero, so the splice's offset-shifting logic never fires. That is
covered separately by resize tests in `tests/test_swap.py`, which shrink and grow
a mesh and then assert the result:

- parses, covers every byte, resolves every pointer, and re-serialises identically;
- has correct updated `vertex_count` / `faces_count` / indices counts;
- leaves the hierarchy untouched — same nodes, names, casing, parents,
  supermodel and animation list;
- leaves **every other mesh's geometry byte-for-byte unchanged**;
- has wrapper and model-header sizes tracking the new buffers.

## Findings

### 1. Influence slots are not always compacted

Two meshes — `c_spar2:repsoilderhead` and `n_gammorean:Gamorian` — contain
vertices whose single influence sits in **MDX slot 1 with slot 0 empty**:
`weights = (0.0, 1.0, 0.0, 0.0)`, `bones = (-1.0, 0.0, -1.0, -1.0)`.

Every other skinned vertex in the game fills slots from 0. Compacting these on
rebuild is almost certainly semantically identical — but "almost certainly" is
what the brief's preserve-don't-invent rule exists to prevent, and it is the
difference between 76,701 and 76,703. `Influence` now records `stride_slot`, and
rebuild honours it. New geometry leaves it at `-1` and fills slots in order.

### 2. The MDX trailing sentinel is not zeros

Every mesh block carries 1–2 vertex rows past `vertex_count`, holding position
`(1e7, 1e7, 1e7)` or `(1e6, 1e6, 1e6)`, the rest zeroed — and on skinned meshes
`weight[0] = 1.0` with bone slot 0. Purpose undocumented. It does not depend on
the geometry, so it is carried through verbatim.

### 3. The counters array is not derived from geometry

`counters[0]` values (84, 81, 186, 187, 88, …) correlate with neither vertex nor
face counts. Preserved verbatim.

### 4. Face adjacency is well-formed and will need rebuilding

Over 16,031 vanilla faces, all three neighbour indices per face are either a
valid face index or `0xFFFF` ("no neighbour") — never out of range. A real
geometry change must therefore recompute adjacency rather than carry it across.
Tracked as a Milestone 3 obligation in
[`docs/BYTE_SURGICAL_DESIGN.md`](../docs/BYTE_SURGICAL_DESIGN.md).

### 5. Every MDX stride is fully accounted for

All 76,703 mesh nodes: `stride == sum(declared columns) + 32 if skinned`, with
zero unexplained padding, across 9 distinct layouts. `stride_layout()` asserts
this and refuses to rebuild a stride it cannot fully explain.

## Status

The file-side half of Milestone 2 passes. Per the brief, **a successful file
build is not proof** — the remaining half is loading a no-op output in KOTOR 1
and confirming it renders and animates. That has not been done and is not
something this tooling can establish.
