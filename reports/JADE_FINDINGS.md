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

**Measured on 158 Jade heads and 112 Jade bodies against 105 KOTOR heads and 95
KOTOR bodies, that is backwards.** Jade models are *larger* and want scaling
**down**, by about a sixth.

| | height | depth | across |
|---|---|---|---|
| **bodies**, KOTOR / Jade | **0.830** | **0.827** | 0.715 |
| **heads**, KOTOR / Jade | **0.858** | 0.994 | 0.831 |

Bodies are the measurement to trust: height and depth agree to within 0.4% on
207 models, which is what a real uniform scale looks like. In absolute terms a
Jade body stands **1.846** where a KOTOR body stands **1.533**.

**Working figure: multiply Jade geometry by ≈0.83 to bring it into KOTOR**, or
≈1.20 going the other way. Not 1.10.

### The axes had to be matched by meaning first

An earlier pass here sorted each model's three extents largest-first, concluded
that "no single factor fits", and was wrong to. Sorting was a stopgap for not
knowing the axis convention, and for bodies it is actively misleading: a figure
with its arms out has an arm span longer than its height, so "the longest
extent" silently means different things for different models.

Once the convention is known the picture is clean. **Jade's height runs along
X; KOTOR's along Z.** Jade body X extents sit at 1.85 with almost no spread
while their Z extents range from 1.5 to 5.2 - the wide ones being capes,
weapons and outstretched arms. Comparing height to height and depth to depth
gives the agreement above; the `across` column is the pose-dependent one and
should be ignored in both rows.

Heads are the noisier of the two. Their height and across agree at 0.83-0.86,
but depth comes out at 0.994 - Jade heads are taller and broader than KOTOR's
while being the same front-to-back. That is a real difference in proportion on
top of the difference in size, and it is why a converted Jade head may still
look slightly wrong after a uniform scale.

### How it was measured

The axis-aligned box of every *drawn* vertex, in world space, with node
transforms accumulated from the model root; KOTOR through this project's own
scene builder, the one the previews use. Four things had to be right, and each
was wrong first:

- **The sample.** The first pass measured 16 heads from `override/`, because a
  `glob` where an `rglob` was needed hid the 100 area archives. Ten times the
  data moved the answer by four points - the sort of correction a small sample
  cannot warn you about.
- **World space, not local.** Combining mesh nodes' raw vertices without their
  rest transforms reported Carth's head as 3.24 tall and 0.16 wide. Jade heads
  are usually a single mesh and so came out right *by accident*, which is how
  that error survives.
- **Axes matched by meaning.** As above.
- **Heads, confirmed by eye.** `reports/jade_vs_kotor_head.png` draws
  `H_Common01_` beside `p_carthh` through the same renderer. Both are heads;
  the Jade one is simply on its side. A bust with shoulders would have measured
  larger for reasons having nothing to do with engine scale.

Node scales are all 1.0. `model.scale` in the header is not: 1.045 on most
models, 1.0 on many, and 0.75-1.7 on a handful, which reads like a real runtime
scale. Applying it moves the body factor from 0.830 to about 0.79 without
changing the direction.

### What is still not established

**Nothing has been in front of the engine.** That is the only thing that has
ever settled a scale question in this project, and it is worth saying that the
direction here disagrees with the person who has actually built a converter.
Take 0.83 as the measurement, not as the answer, and ask him what he measured.

## The per-model `scale` should be ignored

Jade's model header carries a `scale`: 1.045 on most heads, 1.0 on many, and
0.75 or 1.7 on a handful. It looked like the explanation for the heads that
come out the wrong size, and it is not - applying it makes **every** one of
them worse:

| head | span against Carth's head node | `model.scale` | with it applied |
|---|---|---|---|
| `h_girl01_` | 94% | 0.750 | 70% |
| `h_judge01_` | 125% | 1.045 | 131% |
| `h_minstr01_` | 141% | 1.045 | 147% |
| `h_trogr01_` | 344% | 1.700 | 584% |
| `h_common01_` | 93% | 1.045 | 97% |

Ignoring it leaves ordinary heads at 93-94% of the node, which is right. So
whatever that field is for, it is not a size the importer should apply, and the
question is closed.

The heads that *are* the wrong size are the wrong **shape**, not the wrong
scale: `h_judge01_` and `h_minstr01_` wear hats, `h_girl01_` is wider than she
is tall because of her pigtails, and `h_trogr01_` is a troglodyte. Fitting
scales by the tightest axis, so a head that is wide for its height gets shrunk
to fit the width and ends up too short.

## In game, 2026-09-02

A Jade head on Vex, a KOTOR NPC whose appearance row, body and clothes were
left alone so the head was the only variable.

**It works.** The head sits on the neck, is the right sort of size, animates
with the head, and reads as a person.

**Two findings.**

*Slightly too small, and the scale was not to blame.* The fit step resizes to
the tightest axis of the host node; a Jade head is fractionally wider than
Carth's, so the width ratio of 0.980 bound and cost 9% of the height. Placing
and resizing are separate now and resizing is off by default. The scale is also
per kind — 0.86 for heads against 0.83 for bodies — because that is what was
measured, and using the body figure for heads was visibly short.

*The mouth does not open,* and this one is a real format difference rather than
a bug. A KOTOR head has **no mouth opening**: its lips are continuous surface
that the jaw bone stretches apart, with separate teeth and tongue nodes behind
it. A Jade head has an actual hole with two rims of 14 vertices each, at 35%
and 38% of its height. The jaw binding is fine — 182 weighted vertices against
vanilla's 63 — but weight transfer works by proximity and the rims sit a
fraction of a unit apart, so both are bound alike and travel together. A KOTOR
donor shares the host's lip topology, which is why a Bith head's mouth moved on
this same character. Separating them needs something proximity cannot give.

## Heads arrive rotated

A second difference, not mentioned in the original note and visible in the
render: with node transforms applied, a Jade head's crown-to-chin axis lies
along **X**, where KOTOR's lies along **Z**. The raw mesh before transforms is
Z-long like KOTOR's, so it is the head model's own root transform that carries
the rotation.

Anything converting a Jade head onto a KOTOR body has to correct for that, and
a head that arrives 90 degrees out is a more obvious failure than one that
arrives 11% wrong - which is some comfort.

## The whole corpus, not three examples

Three heads were checked by hand and all three worked, which says almost
nothing about a hundred and fifty. `tools/jade_sweep.py` converts every one and
builds it onto Carth, and [reports/JADE_SWEEP.md](JADE_SWEEP.md) is what came
back: **136 of 148 build, and all 148 carry a texture.**

The sweep paid for itself twice over.

**Ten of the 158 are not heads.** `H_Mask01`-`09` are masks - open shells of 78
to 185 triangles - and `H_Decap01` is a severed stump of 40. They cannot pass a
check asking whether a surface is closed or faces outward, because they are not
meant to be either, and counting them as failed heads was ten sensible refusals
dressed up as breakage. They are their own kind now, still offered.

**The `one piece` check was wrong about hats.** It asked whether an island sat
inside the largest one's bounding box, which misreads a topknot or an ear that
reaches past the face. Measured across these heads, every such island *touches*
- the widest gap is a tenth of the head - while the loose fragments the check
exists for sit whole model-widths away. Asking about the gap instead fixed
seven heads and left the original fragment test failing correctly.

### What still does not build, and why it is not a bug

**Six fail on size**, and all six are the wrong *shape* rather than the wrong
scale: `h_judge01_` and `h_minstr01_` wear hats, `h_girl01_` is wider than she
is tall because of her pigtails, `h_trogr01_` and `h_trogr05_` are
troglodytes at 344% and 240% of a human head. Fitting scales by the tightest
axis, so a head that is wide for its height is shrunk to fit its width and
ends up too short. A fit that matched *height* and let width overflow would
take most of these, and is a change to weigh rather than make quietly.

**Six fail on solidity** - under 76% of the surface facing outward, against
vanilla's worst of 77%. Winding repair runs first and gets them to about 4%
disagreement, so this is not a winding fault: the geometry genuinely folds back
on itself, which on `h_piratf01_` and `h_old05_` is layered hair. These are the
ones where a person should look at the preview and decide.

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
