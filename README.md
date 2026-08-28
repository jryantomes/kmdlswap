# kmdlswap

A scoped tool that replaces the geometry of a single mesh node inside a vanilla
KOTOR 1 model, leaving everything else byte-identical. **Not a character creator.**

See [`MDL_SWAP_TOOL_BRIEF.md`](MDL_SWAP_TOOL_BRIEF.md) for the full project brief.

## Status

| Milestone | State |
|-----------|-------|
| 0 — Byte-exact MDL/MDX round-trip | **Done — 2832/2832 (100%)** of vanilla K1 models. |
| 1 — Inspect | next |
| 2 — No-op swap | not started |
| 3 — Geometry replacement | not started |
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
