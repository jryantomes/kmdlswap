# Support matrix — what kmdlswap can actually edit

**Date:** 2026-08-29
**Harness:** [`tools/support_matrix.py`](../tools/support_matrix.py)
**Corpus:** all 2,832 MDL/MDX pairs in a vanilla K1 install

The design doc promised this and never produced it, so the tool's refusals lived
scattered across the code and a user met them one model at a time. Every reason
below is a real code path, exercised against the whole corpus.

## Models

**2,832 of 2,832 are usable** — every vanilla model parses, accounts for every
byte, resolves every stored pointer, and re-serialises identically. No model in
the game is refused outright.

## Mesh nodes

76,782 geometry mesh nodes (animation node-trees excluded):

| Outcome | Nodes | Share |
|---|---:|---:|
| **swappable** | 34,764 | 45.3% |
| `needs_uv2` — carries a second UV set | 37,025 | 48.2% |
| `needs_tangent` — carries a tangent frame | 4,914 | 6.4% |
| `saber` — lightsaber blade | 64 | 0.1% |
| `empty` — no vertices | 15 | <0.1% |

45% looks alarming in isolation. It is not, because of how it distributes.

## By model type — the number that matters

| Category | Models | Mesh nodes | Swappable | Main blocker |
|---|---:|---:|---:|---|
| **player / companion** | 24 | 1,155 | **100%** | — |
| item | 125 | 224 | **100%** | — |
| effect | 29 | 32 | **100%** | — |
| NPC | 86 | 4,007 | 98% | tangent |
| creature | 54 | 2,128 | 94% | tangent |
| placeable | 249 | 1,128 | 94% | tangent |
| weapon | 136 | 301 | 79% | saber blades |
| module / room | 1,646 | 59,161 | **30%** | lightmap UVs |

**Every mesh node of every player and companion model is swappable.** The tool is
complete on the thing the brief scoped it to. The 45% headline is dominated by
module/room geometry, which carries lightmap UVs and was never in scope — rooms
are 59,161 of the 76,782 nodes, so they swamp the total.

## Why each refusal exists

- **`needs_uv2` / `needs_tangent` / `needs_colour`** — the MDX stride carries a
  column an OBJ cannot express. `swap.build_replacement` refuses rather than
  zero-fill it, because inventing values for data the engine reads is exactly
  what the brief rules out. Lifting this needs a richer interchange format, not
  a change to the splice engine.
- **`saber`** — a lightsaber blade keeps its geometry in MDL-side arrays rather
  than the MDX stream. A different code path, deliberately out of scope.
- **`empty`** — a mesh node with no vertices owns no MDX block at all.
- **`model_invalid`** — the parser cannot account for every byte or resolve every
  pointer. Zero vanilla models hit this, but a modded or corrupt file could, and
  it is refused rather than edited blind.

## Visible versus present

Of the 34,764 swappable nodes, **16,786 are actually drawn**. The rest are the
skeleton's invisible `_g` boxes — byte 313 of the trimesh subheader is a render
flag, and 18,058 vanilla mesh nodes have it clear. Editing an invisible node
succeeds and changes nothing anyone can see, which is why `kmdlfun` filters on
the render flag before reporting what an effect will do.

## Reading this as a user

- Editing a **companion or player model**: everything works.
- Editing an **NPC, creature or placeable**: almost everything works; a handful
  of meshes with tangent frames are refused with a message naming the column.
- Editing a **room**: expect most meshes to be refused. That is the tool
  declining to fabricate lightmap coordinates, not a bug.
- A refusal is always a hard error at write time, never a silently wrong model.
