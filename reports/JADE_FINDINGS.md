# Jade Empire

Jade Empire runs on the same engine lineage as KOTOR, which made it look like
the cheapest of the other-engine options: the Upcoming tab carried it as *"its
file wrapper is KOTOR's with eight bytes inserted, and the reader already gets
through the wrapper and the model header before it stops. Whether the node
structures are another fixed shift or a real difference is the open question."*

**It is a real difference.** Answered 2026-09-02 from JadeBlender 6.6.0, a
KotorBlender fork that reads, writes and converts Jade models, supplied by its
author. What follows is read out of that addon's own constants and parser and
checked against ours, not inferred.

## The structures are all different sizes

| structure | KOTOR (`kmdlswap/nodes.py`) | Jade PC v7 |
|---|---|---|
| data base / wrapper | 12 | **20** |
| model header | 196 | 220 (`0xDC`) |
| node header | 80 | **60** (`0x3C`) |
| trimesh header | 332 (K1) / 340 (K2) | 228 (`0xE4`) |
| skin header | 100 | 160 (`0xA0`) |
| face record | 32 | 28 (`0x1C`) |
| controller | 16, inline in the node | `0x24` header + `0x10` per descriptor |

The eight-byte wrapper shift is real, and it is *only* the wrapper. Nothing
inside follows it.

## But the node header shares a prefix

This is the part worth knowing, because it explains why our reader got as far
as it did before failing. The first 52 bytes are the same layout in both:

| offset | KOTOR | Jade |
|---|---|---|
| +0 | `u16` type flags, `u16` supernode | `u32` flags (bits up to `0x80000`) |
| +4 | `u16` node number | `u16` tree node number |
| +6 | `u16` name index | `u16` file node number / name index |
| +8 | `u32` geometry header pointer | `u32` model pointer |
| +12 | `u32` parent pointer | `u32` parent pointer |
| +16 | `f32[3]` position | `f32[3]` position |
| +28 | `f32[4]` orientation | `f32[4]` orientation |
| +44 | `u32` children offset | `u32` children offset |
| +48 | `u32` children count | `u32` children count |
| **+52** | `u32` children count2 | **`f32` scale** |
| +56 | `u32` controllers offset | **`f32` max animation distance** |
| +60.. | two more 12-byte arrays, to 80 | *ends* |

So both descend from the same transform block and part company at +52, where
KOTOR's array-capacity convention (offset, count, count2) gives way to two
scalars. Jade then moves controllers out of the node entirely, into their own
header and descriptor list, where KOTOR keeps them inline as a third array.

Jade also adds node classes KOTOR has no bit for: `gob`, `collision`, `sphere`,
`capsule`, `weapon_trail`, `dangly_bone`, and a `controllers` bit at `0x40000`.
KOTOR's `saber` bit (`0x800`) is Jade's `weapon_trail`.

## Where the models live

Worth stating plainly, because two wrong answers came first and both looked
right:

| place | what is actually in it |
|---|---|
| `data/<area>/*.rim` | **the character models** - 100 archives across 52 area folders |
| `data/*.rim` (928) | area geometry, `a010_*` and friends |
| `data/artcreatures.bif` | visual effects: 1163 of its 1164 models are `v_*` |
| `data/bips/*.mod` | animations, keyed by numeric resref |
| `data/mmenu-a.rim` | menu assets, `AEG*` |
| `override/` | whatever has been extracted there - 32 models on this install |

Scanning `data/*.rim` and not `data/**/*.rim` finds 1735 models and one head.
Scanning recursively finds 7113 models, **499 head entries resolving to 158
distinct heads**, and 456 bodies. The per-area RIMs are where everything is,
which matches the community wiki: NPC models sit in the area folders that use
them, so the same head appears in several archives.

## Scale: measured, and it goes the other way

Reported by the addon's author, 2026-09-02: *Jade models are around 10-11%
smaller than their KOTOR equivalents and need scaling up by roughly that much.*

**Measured on 158 Jade heads against 105 of KOTOR's, that is backwards.** Jade
heads are *larger*, and want scaling **down**.

| dimension | Jade median | KOTOR median | KOTOR / Jade |
|---|---|---|---|
| longest | 0.3210 | 0.2734 | **0.852** (−14.8%) |
| middle | 0.2408 | 0.2353 | 0.977 (−2.3%) |
| shortest | 0.1953 | 0.1638 | 0.839 (−16.1%) |
| longest × header `model.scale` | 0.3298 | 0.2734 | 0.829 (−17.1%) |

### There is no single factor

The middle dimension is within 2% while the other two differ by 15%. A uniform
scale would move all three together, so **one number cannot make a Jade head
into a KOTOR-proportioned one** - they are shaped differently, longer and wider
front-to-back but similar across. Anyone applying a single multiplier is
choosing which axis to be right about.

That is the part most worth taking back to the author. The direction disagrees
with what we were told, and the premise - that a single percentage exists -
looks shaky too. **Confirm before trusting any of it**, including this.

### How it was measured

The axis-aligned box of every *drawn* vertex, in world space, with node
transforms accumulated from the model root; KOTOR through this project's own
scene builder, the one the previews use. Four things had to be right, and each
was wrong first:

- **The sample.** The first pass measured 16 heads from `override/`, because a
  `glob` where an `rglob` was needed hid the 100 area archives. Ten times the
  data moved the answer from −11% to −15% - same direction, different number,
  which is exactly the sort of correction a small sample cannot warn you about.
- **World space, not local.** Combining mesh nodes' raw vertices without their
  rest transforms reported Carth's head as 3.24 tall and 0.16 wide. Jade heads
  are usually a single mesh and so came out right *by accident*, which is how
  that error survives.
- **Sorted extents, not axis order.** Jade heads are longest along X where
  KOTOR's are longest along Z, so axis 0 against axis 0 compares a width to a
  height. Sorting each model's extents largest-first is rotation-invariant.
- **Heads, confirmed by eye.** `reports/jade_vs_kotor_head.png` draws
  `H_Common01_` beside `p_carthh` through the same renderer. Both are heads;
  the Jade one is simply on its side. A bust with shoulders would have measured
  larger for a reason having nothing to do with engine scale.

Node scales are all 1.0. `model.scale` in the header is not: 1.045 on 109 of
the 158, 1.0 on 38, and 0.75, 0.77 or 1.7 on the rest, which reads like a real
runtime scale. Whether the engine applies it moves the answer from −15% to
−17% without changing its direction.

### What is still not established

- **No bodies compared.** 456 `N_*` bodies exist and were not measured against
  KOTOR's; if "models are smaller" meant whole characters rather than heads,
  that remains untested.
- **Nothing in game.** No converted head has been put in front of the engine,
  which is the only thing that has ever settled a scale question in this
  project.

## Heads arrive rotated

A second difference, not mentioned in the original note and visible in the
render: with node transforms applied, a Jade head's crown-to-chin axis lies
along **X**, where KOTOR's lies along **Z**. The raw mesh before transforms is
Z-long like KOTOR's, so it is the head model's own root transform that carries
the rotation.

Anything converting a Jade head onto a KOTOR body has to correct for that, and
a head that arrives 90 degrees out is a more obvious failure than one that
arrives 11% wrong - which is some comfort.

## What this means for the tool

**Do not build native Jade reading.** It is a second full reader and writer for
an engine that this addon already handles, and handles in both directions:
`io/model_conversion.py` does deterministic Jade ↔ KotOR conversion through a
shared scene graph, returning a structured report of `warnings`, `losses` and
`blockers` rather than converting silently.

The route is the same shape as the one recorded for Neverwinter Nights and
SWTOR, and for the same reason:

1. Open the Jade `.mdl` in Blender with JadeBlender.
2. Export as a KOTOR `.mdl`, or as `.glb` into the **Custom head** tab.
3. Check the scale against a vanilla model before trusting it.

## Licence

JadeBlender is GPL-3.0-or-later. This project [is now GPL-3.0-or-later
too](../LICENSE), which was the point: format facts — offsets, sizes, flag
values — were never restricted and could always be used, but an implementation
can only be borrowed if the licences agree. Now they do.
