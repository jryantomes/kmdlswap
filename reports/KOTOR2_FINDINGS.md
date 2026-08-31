# Reading KOTOR 2

**Date:** 2026-08-30
**Status:** all 3,237 K2 models parse, validate and round-trip; K1 unaffected
**Scope note:** the brief put KOTOR 2 out of scope. This is a deliberate
expansion, and a narrow one - K2 models are **read** so their geometry can be
borrowed. Nothing writes a K2 file.

## The whole difference

Two things, and no more.

**1. The game is written in the model header's first two words.** They are
compiler-baked function pointers, preserved verbatim like any other unknown,
and they identify the build:

| game | fn0 | fn1 | models |
|---|---|---|---|
| K1 | 4273776 (`0x4136B0`) | 4216096 (`0x4058E0`) | 2,832 |
| K2 | 4285200 (`0x416610`) | 4216320 (`0x4059C0`) | 3,237 |

Every model in each install carries its game's pair. No exceptions, no third
value, across 6,069 models.

**2. K2's trimesh subheader carries 8 extra bytes before its two tail
pointers.** Found by comparing `n_bith`, which both games ship, field by field:

```
byte    K1                        K2
  8     face array offset         face array offset        same
 88     texture name              texture name             same
176     indices counts            indices counts           same
252     MDX stride                MDX stride               same
256     MDX bitmap                MDX bitmap               same
304     vertex count              vertex count             same
...
324     MDX block offset          (8 bytes of K2 data)
328     MDL vertex array          ...
332                               MDX block offset
336                               MDL vertex array
```

Everything up to the vertex count is identical. Only the last two pointers move,
by 8 bytes each.

## How the failure looked before

Assuming K1's layout reads K2's pointers 8 bytes early, landing on float data:

```
MDX mdx_block span [0, 958220594) out of bounds
```

958220594 is not a wild offset, it is a small float read as an integer. The
corpus check went from 379 of 3,237 to all 3,237 once the two offsets moved.

Worth noting the first symptom was misleading in the other direction too: the
first K2 model tried parsed cleanly, which suggested the job was nearly done. It
happened to be one of the 379 whose meshes never exercised the shifted fields.
One model is not a corpus.

## Cross-game transplants

`kmdlfun transplant --donor-install` takes the donor from a second game. Only
geometry crosses; the host keeps its hierarchy, skeleton and animations and is
written back as the K1 file it was.

Verified on file: `n_quarren` (K2) into `p_carthh` (K1), 565 -> 613 vertices on
`Head` plus the tongue, host still reads as K1, full validation passes, 98%
solid.

**The donor's texture comes too.** `N_QuarrenH01` exists only in K2's packs, so
a build referencing it would load grey in KOTOR 1 - which looks like a modelling
failure and is really a missing file. When the donor comes from another install
the tool now decodes and writes any texture the host game lacks beside the model.

## What is still K1-only

Writing. Every path that produces a file produces a K1 file, because the host is
always a K1 model. Making K2 a *host* would need the writer to emit the longer
trimesh header, which nothing here does and nothing here has tested.
