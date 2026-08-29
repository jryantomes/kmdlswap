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

## Status — PASSED, including in-game

The file-side half passes: 76,703/76,703 mesh nodes byte-identical.

**In-game verification: passed (2026-08-28).** Because the no-op output is
byte-identical to vanilla, loading it would only have tested the Override
mechanism, not this tool. The informative test is instead a *resize probe*
([`tools/write_resize_probe.py`](../tools/write_resize_probe.py)): the `head`
node of `p_hk47` padded with 64 inert duplicate vertices that no face
references.

| | |
|---|---|
| head vertices | 481 -> 545 |
| faces | 393 (unchanged; the copies stay unreferenced) |
| MDL | 1,009,979 -> 1,010,747 (+768) |
| MDX | 110,464 -> 112,512 (+2,048) |
| stored pointers past the splice | ~494 rewritten |

Nothing visible should change, but the file layout shifts substantially and
every offset after the edit had to be recalculated. Loaded into `Override/`,
HK-47 **rendered correctly and animated correctly — idle, walk, and head turn
all confirmed**.

That is direct evidence, from the engine rather than from our own validators,
that the splice and offset-fixup logic is sound: the game read a model whose
arrays had all moved and resolved every pointer correctly.

It also incidentally answers a question raised when designing the probe: the
engine walks the face list rather than iterating the raw vertex array, since 64
unreferenced vertices produced no visible artifact.

### What this does not establish

- Only one splice shape was tested (a grow, on one unskinned mesh). Shrinks, and
  edits to *skinned* meshes, are covered by the validators but not yet in-game.
- The probe changed no vertex positions, so nothing here speaks to whether
  replacement *content* renders correctly. That is Milestone 3.
