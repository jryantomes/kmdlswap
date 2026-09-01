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

## Scale: measured, and it goes the other way

Reported by the addon's author, 2026-09-02: *Jade models are around 10-11%
smaller than their KOTOR equivalents and need scaling up by roughly that much.*

**Measured here on 2026-09-02, that is backwards.** Jade heads are *larger*
than KOTOR heads, by close to the same 11%.

| | Jade median | KOTOR median | KOTOR / Jade |
|---|---|---|---|
| longest dimension, geometry as stored | 0.3086 | 0.2734 | **0.886** (−11.4%) |
| longest dimension, × the header's `model.scale` | 0.3174 | 0.2734 | **0.861** (−13.9%) |
| middle | 0.2306 | 0.2353 | 1.020 |
| shortest | 0.1953 | 0.1638 | 0.839 |

So a Jade head arriving in KOTOR wants scaling **down** by 11-14%, not up.

The magnitude agreeing this closely while the sign disagrees is worth raising
with the author rather than quietly overriding: it reads like the same
measurement described from the other end, or an inverted convention somewhere.
**Ask before trusting either number.**

### How it was measured

16 heads against 105. Both sides are the axis-aligned box of every *drawn*
vertex, in world space, with node transforms accumulated from the model root -
KOTOR through this project's own scene builder, the one the previews use.

Three things had to be got right, and each was wrong first:

- **World space, not local.** Combining each mesh node's raw vertices without
  its rest transform is meaningless once a model has more than one mesh. It
  reported Carth's head as 3.24 tall and 0.16 wide. Jade heads are a single
  mesh and so came out right *by accident*, which is exactly the accident that
  makes a wrong number look plausible.
- **Sorted extents, not axis order.** Jade heads are longest along X where
  KOTOR's are longest along Z, so matching axis 0 to axis 0 compares a width
  against a height. Sorting each model's three extents largest-first is
  rotation-invariant.
- **Heads, confirmed by eye.** `reports/jade_vs_kotor_head.png` draws
  `H_Common01_` beside `p_carthh` through the same renderer. Both are heads -
  the Jade one has ears and a cranium and is simply lying on its side. Had it
  been a bust with shoulders it would have measured larger for a reason with
  nothing to do with engine scale, and no amount of median-taking would have
  shown that.

Node scales are all 1.0, so ignoring them is safe. `model.scale` in the header
is not: it is 1.045 on most heads and 0.75 on `H_Girl01GH_`, which reads like a
real runtime scale. Whether the engine applies it is the one open question in
these numbers, and it moves the answer from −11% to −14% without changing its
direction.

### What is not established

- **16 heads.** That is every head this install has as a loose file. They are
  not in the RIMs (area geometry), not in `artcreatures.bif` (1163 of its 1164
  models are `v_*` effects despite the name), and not in `data/bips/*.mod`
  (animations, numeric resrefs). `override/` is where this install keeps its
  character models, and its files are dated the same day as the install.
- **No bodies.** Jade's `C_*` models here are creatures - `c_tentacle_` is 14
  units long - with no humanoid equivalent to put beside a KOTOR body. If
  "models are smaller" was about whole characters rather than heads, that is
  untested.
- **Nothing in game.** No converted head has been put in front of the engine,
  which is the only test that has ever settled a scale question in this project.

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
