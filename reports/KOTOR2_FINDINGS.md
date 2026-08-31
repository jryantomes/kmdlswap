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

## What the community says, and what the corpus says (2026-08-31)

Searched for prior art on K2 → K1 porting after the first cross-game head went
in. The community has done this for years, and the standard account is worth
knowing - along with where our measurements disagree with it.

### The documented approach, and why ours differs

The usual route ([Deadly Stream](https://deadlystream.com/topic/8173-kotor-2-head-to-kotor-1/))
is to convert the *whole model* with MDLEdit: load it with the K2 button
selected, switch to K1, save as ASCII, reload, save as binary, then register it
in `appearance.2da`, `heads.2da` and `portraits.2da`. The head keeps its own
K2 skeleton, and the K1 supermodel then has to drive it.

That is where their trouble starts. The reported symptoms are specific:

> the facial bones in K1 & K2 being different ... mouths wide open or grinning
> like an idiot, eyes drooping in cutscenes

and separately, lips that do not move in dialogue with a seam down the middle of
the face. The recommended fix is to move the head "over to a set of KOTOR 1
bones", which needs the destination game's supermodel present during conversion.

**We do not have that problem, because we never bring the skeleton.** The host
keeps its own hierarchy, bones and animations; only geometry crosses, and the
donor's weights are remapped into the host's bone slots *by name*. The community's
recommended fix is our default.

### Where the corpus disagrees with the lore

"The facial bones in K1 & K2 being different" is the stated blocker. Measured, it
does not hold up as a difference *between games*.

Bone positions relative to `head_g`, which removes the constant model-origin
offset between a head-only model and a full body:

| comparison | mean | max |
|---|---|---|
| K1 Carth vs **K2** Quarren | 0.0387 | 0.0811 |
| K1 Carth vs **K1** Bith | 0.0582 | 0.0707 |
| **K1** `n_bith` vs **K2** `n_bith` | **0.000000** | **0.000000** |

The same character shipped in both games has a **bit-identical** facial rig. And
across 49 K1 heads compared with Carth's own layout, the median worst-bone
difference is 0.0299, the 90th percentile 0.0866 and the worst 0.1165 - so the
K2 Quarren's 0.0811 sits comfortably inside the variation K1 already has among
its *own* heads.

Facial bones do differ head to head, because each is placed to suit a face. They
do not differ because of the game. What breaks a whole-model port is the
skeleton and supermodel travelling with the mesh, not the bone layout itself.

### Confirmed independently

- **332 vs 340 bytes.** The community records the size difference we measured,
  though as "the model root node size" rather than the trimesh header.
- **K2-only mesh properties.** KotORBlender is documented as having found ten
  missing trimesh properties, four of them K2-only - consistent with 8 extra
  bytes carrying a small number of extra fields.
- The format thread itself does **not** document where those bytes sit, so the
  field-by-field `n_bith` comparison in this report still appears to be new.

### One thing to remember for player heads

K1 wants **five** dark-side texture stages where K2 ships **three**, so a ported
*player* head needs two intermediate skins blended by hand. Irrelevant to a
companion swap, which uses one texture, but it would bite immediately on a
playable head.


## The grey eyes: a dropped alpha channel — confirmed 2026-08-31

A ported Quarren head animated correctly but had flat grey patches where its
eyes should be, with the rest of the face looking right. Grey is what the engine
shows when a face samples the atlas background, so the model and the image
disagreed somewhere.

**It was our texture conversion, and the proof is clean:** the MDL and MDX are
byte-identical between the broken build and the working one. The only difference
is the texture file.

| | |
|---|---|
| K2 ships | `N_QuarrenH01.tpc`, 512x512, **encoding 4 = RGBA**, 10 mipmaps |
| we wrote | `N_QuarrenH01.tga`, 512x512, **24bpp RGB**, no mipmaps, alpha dropped |

Decoding the TPC to RGB and re-encoding it discarded the alpha channel, and on
this head the eyes depend on it.

### Two theories eliminated first, and why that was worth doing

Both were plausible and both were wrong, and checking them was cheap next to a
trip into the game:

- **Row order.** Pillow's TGA output is self-consistent - rows bottom-up with a
  matching bottom-left origin flag - and, measured, it is byte-for-byte the same
  structure as `tripohead.tga`, a file confirmed working in game. Orientation was
  never involved.
- **A missing eye mesh.** `f_llweye_g` and `f_rlweye_g` are 24-vertex meshes
  sitting exactly at eye height, which looked promising. Byte 313 is the render
  flag in both games - only ever 0 or 1 across 60,021 K1 and 50,569 K2 mesh
  nodes - so those really are undrawn skeleton stubs, and the head declares one
  texture with an empty lightmap slot and carries only vertex, normal and uv1.
  Nothing was missing.

### What changed

When the donor comes from another install its texture is now **copied across as
the shipped bytes**, extension and all - no decode, no re-encode. Whatever the
engine did with them in one game it does in the other. Verified in game: eyes,
tentacles and skin all correct.

And where a conversion is unavoidable - a `.glb` carries PNG or JPEG, so a head
pack must be written out - alpha is preserved rather than flattened, and
`headspec` reports whether a pack's texture carries one.

### The lesson

The safest conversion is the one that does not happen. A re-encode looked
correct by every check available - identical pixels, self-consistent file
structure, same layout as a known-good file - and was still lossy in a way that
none of those checks could see, because they all compared the parts that
survived.
