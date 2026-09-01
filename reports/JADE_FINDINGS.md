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

## Models are smaller

Reported by the addon's author, 2026-09-02: **Jade models are around 10–11%
smaller than their KOTOR equivalents and need scaling up by roughly that much.**

Recorded as supplied and **not yet verified here** — nobody on this machine has
a Jade install to measure against, so treat 1.10–1.11 as a starting factor to
check rather than a derived constant. The way to settle it is the way donor fit
was settled: put a converted Jade head next to a vanilla one, compare bounding
heights, and read the ratio off the measurement rather than the estimate.

That is worth doing before it matters, because scale errors in this project
have not announced themselves. A donor head fitted to the wrong box stood 0.242
tall against the correct 0.400 and floated a fifth of its own height above the
collar, and that was visible only in game.

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
