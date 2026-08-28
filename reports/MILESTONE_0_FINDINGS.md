# Milestone 0 findings — PyKotor round-trip evaluation

**Date:** 2026-08-28
**Install (corpus + oracle):** `E:\SteamLibrary\steamapps\common\swkotor` (vanilla K1, Steam)
**PyKotor:** 2.3.12
**Harness:** [`tools/roundtrip_eval.py`](../tools/roundtrip_eval.py), [`tools/diff_anatomy.py`](../tools/diff_anatomy.py)

## Method

Enumerate every `MDL` resource in `chitin.key`'s BIFs (2,832 pairs), read each
`MDL`+`MDX` through `MDLBinaryReader(game=Game.K1)`, re-emit with
`MDLBinaryWriter`, and byte-diff both streams against the originals.

## Result

| Metric | Value |
|--------|-------|
| Pairs tested | 2,832 |
| **Byte-exact round-trips** | **0** |
| Mismatches | 2,788 |
| Hard read errors | 44 (`unpack requires a buffer of 4 bytes` — mostly `fx_*`, `m12a*` module models) |

**Pass rate: 0.0%.** Not a single vanilla model survives a PyKotor read→write
unchanged.

### Nature of the divergence (p_hk47, representative)

- MDL: 1,009,979 → 1,009,031 bytes (−948), first diff at offset **4** (the
  model-data-size header field), **85,695 distinct diff runs** spread across the
  whole file.
- Diffs include: recomputed array offsets, node data reordered, and large float
  regions **zeroed out** (data the reader parses but the writer does not
  round-trip — bounding data / controller keys / fields it treats as unknown).
- MDX: same size here, but diverges from offset 98,786. Across the corpus MDX
  size changes too — e.g. `c_bmspecdiff` MDX 160,596 → 129,504 (−31 KB),
  `c_bantha` MDX 217,392 → 234,144 (+16 KB).

This is a **lossy semantic reconstruction**, not a faithful serializer. The
magnitude (tens of thousands of diff runs, dropped geometry bytes, size changes
in both streams) rules out fixing it with offset/size patches.

## Implication for the project

The brief's optimistic path ("if PyKotor round-trips, Milestone 0 is nearly
free") **does not apply.** Milestone 0 requires our own **byte-surgical**
MDL/MDX handling:

1. Keep the original file as an immutable `bytes` buffer.
2. Parse only the structure needed to navigate: file header, name array, node
   tree, per-mesh headers, and the offsets/counts of the geometry + skin arrays.
   (PyKotor's `io_mdl.py` reader is an accurate map of these layouts — use it as
   documentation, not as the engine.)
3. "Write" = produce the original bytes verbatim, except for spliced regions,
   with fix-ups applied only to the offsets/counts/sizes that genuinely moved
   (model data size at +4, MDX size/offset in header, name offsets, affected
   node array pointers, downstream node offsets).
4. An unmodified round-trip is then **identity by construction** — the Milestone 0
   acceptance test passes trivially, and the diff discipline the brief wants is
   applied only to the regions we deliberately touched.

PyKotor stays in the toolbox as a cross-check oracle (parse both, compare
semantic fields) and as a format reference.

## Outcome — Milestone 0 closed

The byte-surgical parser (`src/kmdlswap/{_io,nodes,layout,validate}.py`) reaches
**2832 / 2832 (100%)** on the same corpus in **12 seconds**: full span coverage,
zero overlaps, every stored pointer resolving to a span boundary of the expected
kind, byte-identical re-emission of both streams. Harness: `tools/corpus_check.py`;
locked in by `tests/test_identity_corpus.py`.

### Format corrections found by driving coverage to 100%

Each of these was a real defect in the best available reference, surfaced because
an unaccounted byte is a hard failure rather than a rounding error:

1. **Light subheader field order.** `flare_radius` (f32) is the **first** field,
   followed by five `(offset, count, count2)` triples. PyKotor reads the radius
   *after* the triples, mis-framing the entire subheader — which is why lens-flare
   arrays (`flare_sizes` / `flare_positions` / `flare_colors` / flare texture name
   offsets + strings) never round-trip through it.
2. **MDX offset 0 is a real address**, not a null sentinel — the first mesh block
   starts there. Only `0xFFFFFFFF` means "no block".
3. **A zero-vertex mesh owns no MDX block.** Its stride reads as the `0xFFFFFFFF`
   sentinel and its stale `mdx_data_offset` of 0 must not be mistaken for a claim
   on the first block, or two nodes appear to own the same bytes.
4. **`offset_to_animations` is stale when `animation_count == 0`** — it holds a
   leftover value pointing into node data. It is not a live pointer.
5. **Saber blades keep geometry in the MDL, not the MDX**: three `vertex_count`-sized
   arrays (positions `vec3`, texcoords `vec2`, normals `vec3`) reached from the
   saber subheader.
6. **Geometry-header padding is uninitialised garbage** (`p_hk47`: `eb 1f 3d`),
   varying per model. PyKotor normalises it to MDLOps' `31 96 bd`. We pass it
   through, as the brief requires.

## Artifacts

- `reports/roundtrip_all.json` — full per-model results (gitignored; regenerate
  with the harness).
- `reports/roundtrip_p.json` — `p_*` subset.
