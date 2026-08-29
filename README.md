# kmdlswap

A scoped tool that replaces the geometry of a single mesh node inside a vanilla
KOTOR 1 model, leaving everything else byte-identical. **Not a character creator.**

See [`MDL_SWAP_TOOL_BRIEF.md`](MDL_SWAP_TOOL_BRIEF.md) for the full project brief.

## Status

| Milestone | State |
|-----------|-------|
| 0 — Byte-exact MDL/MDX round-trip | **Done — 2832/2832 (100%)** of vanilla K1 models. |
| 1 — Inspect | **Done** — `kmdlswap inspect` |
| 2 — No-op swap | **Done — 76,703/76,703 mesh nodes, and verified in-game.** |
| 3 — Geometry replacement | next |
| 4 — CLI | skeleton only (`src/kmdlswap/cli.py`) |

### Milestone 0 result

Our parser accounts for **every byte** of all 2,832 MDL/MDX pairs in the vanilla
install: full span coverage, no overlaps, every stored pointer resolving to a
span boundary of the expected kind, and byte-identical re-emission — in 12
seconds. (PyKotor: 0/2832 in 607s.)

```bash
.venv/Scripts/python tools/corpus_check.py --install "E:\SteamLibrary\steamapps\common\swkotor"
.venv/Scripts/python -m pytest -q          # fast checks
.venv/Scripts/python -m pytest -q -m slow  # full-corpus sweep
```

### Milestone 1 — inspect

```bash
.venv/Scripts/kmdlswap inspect p_hk47 --install "E:\SteamLibrary\steamapps\common\swkotor"
```

Reports the node tree with exact casing and parent paths, per-node vertex/face
counts, which meshes are skinned and which bones they reference, observed
influences per vertex, supermodel, and bounding box. Exits non-zero with a
warning if the model does not fully validate — a model we cannot account for is
one we must not edit.

### Milestone 2 — no-op swap

Every mesh node's geometry is extracted to decoded components, the arrays are
**rebuilt from those components**, spliced back, and the model byte-diffed. All
**76,703 mesh nodes** across the corpus come back byte-identical, and every
result re-validates. Resize (shrink/grow) tests cover the splice's offset-fixup
logic, which a no-op never exercises.

```bash
.venv/Scripts/python tools/noop_swap_sweep.py --install "<K1 root>"
```

**Verified in-game.** A no-op output is byte-identical to vanilla, so loading it
would only test the Override mechanism. The informative test is a *resize probe*:
a mesh padded with inert duplicate vertices no face references, so nothing
visible changes but both files grow and every pointer past the splice must be
rewritten.

```bash
.venv/Scripts/python tools/write_resize_probe.py --install "<K1 root>" --model p_hk47 --node head --out out_probe/
```

For `p_hk47:head` that moves ~494 stored pointers (MDL +768 B, MDX +2,048 B).
Loaded into `Override/`, HK-47 rendered and animated correctly — idle, walk and
head turn all confirmed. Findings:
[`reports/MILESTONE_2_FINDINGS.md`](reports/MILESTONE_2_FINDINGS.md).

### Skinning census

A corpus-wide measurement of vanilla's skinning behaviour lives in
[`reports/SKINNING_FINDINGS.md`](reports/SKINNING_FINDINGS.md). Headlines: no
vanilla vertex exceeds **4** influences; weights are **always** normalised; the
skin subheader's 16-slot bone table is **not** the per-mesh limit (21 meshes use
17 bones) and its unused entries are garbage — the bonemap is the authority.

## Setup

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e .
```

Requires Python 3.11+, a vanilla K1 install (used as both test corpus and oracle).
This machine's install: `E:\SteamLibrary\steamapps\common\swkotor`.

## Milestone 0 harness

```bash
# Round-trip every MDL/MDX pair in the install and byte-diff:
.venv/Scripts/python tools/roundtrip_eval.py --install "E:\SteamLibrary\steamapps\common\swkotor"

# Characterise where a single model's round-trip diverges:
.venv/Scripts/python tools/diff_anatomy.py --install "<install>" --name p_hk47
```

## Key finding — PyKotor round-trip

PyKotor 2.3.12's `MDLBinaryReader`/`MDLBinaryWriter` perform a **lossy semantic
reconstruction**, not a faithful round-trip. Against the full vanilla K1 corpus:

- **0 / 2,832** models re-emit byte-identically (44 also fail to read at all).
- p_hk47: MDL shrinks 948 bytes, **85,695** distinct diff runs across the file
  (recomputed offsets, dropped/zeroed float regions, reordered node data).

Full write-up: [`reports/MILESTONE_0_FINDINGS.md`](reports/MILESTONE_0_FINDINGS.md).

This is too much loss to fix with offset patches. Milestone 0 needs a
**byte-surgical** reader/writer of our own: parse only enough structure to locate
the target mesh node's arrays, splice, and fix up the offsets/counts/sizes that
actually changed — everything else passes through as raw original bytes. An
unmodified round-trip is then identity by construction.

PyKotor remains useful as a format reference and cross-check oracle.

Design & implementation plan: [`docs/BYTE_SURGICAL_DESIGN.md`](docs/BYTE_SURGICAL_DESIGN.md).
