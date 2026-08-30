# Custom textures work

**Date:** 2026-08-30
**Verified in-game on:** `p_hk47`, head node replaced with Tripo geometry
**Status:** confirmed

## The result

A texture that does **not** ship with the game can be dropped into `Override/`
and referenced by a model, and the engine loads and maps it correctly.

That was the largest open limitation on the character-creator plan. Until now
every swap could only point at a texture already in the game, which meant a
donated part always wore somebody else's colours.

## How

1. **Convert.** The source was a 4096×4096 JPEG (Tripo's UV atlas). Vanilla head
   textures are 256×256 and HK-47's body is 512×512, so it was resized to
   **512×512** and written as an **uncompressed TGA**. No TPC encoder is needed —
   the engine reads loose TGA out of `Override/`.
2. **Name it.** KOTOR resrefs are at most 16 characters; the model's texture
   field is 32 bytes. `tripohead` is safe on both counts.
3. **Point at it.** The texture reference is a fixed 32-byte field in the trimesh
   subheader at `+88`, so this is a patch in place: nothing moves and no offset
   needs fixing up. `kmdlswap replace --texture tripohead`.
4. **Ship both.** The `.tga` goes in `Override/` beside the `.mdl`/`.mdx`.

No V-flip was needed. Blender's OBJ export and KOTOR agree on the TGA
bottom-left origin, so the mapping came through the OBJ round trip unchanged.

## Why this case was the easy one

HK-47's `head` is **unskinned**, so the constraint that a skinned head's vertex
count must not change (`reports/HEAD_ANIMATION_FINDINGS.md`) does not apply. The
donor's own topology *and* its own UV layout could be kept, with no resampling
and no smearing.

For a **skinned** head the UVs must be resampled onto the host's topology
(`kmdlfun transplant --with-texture`), which is a lossier path — the mapping is
interpolated where each host vertex lands on the donor surface.

## Fittings the new head does not account for

HK-47's `Mesh01` is his eye bar: a thin strip, 0.190 × 0.041 × 0.043, hanging off
`talkdummy` under `head`. After the swap it sat in mid-air, the same class of
problem as Carth's leftover hair.

Two remedies exist, and which is right is a judgement call:

- **Move it** (`tools/place_fitting.py`). The node itself cannot move — node
  positions live in headers this project never rewrites — but translating the
  geometry *inside* the node is indistinguishable for a small part. Placing it
  at 45% of head height put it roughly where the new face's eyes are.
- **Hide it** (`--hide`). One byte, the render flag at trimesh `+313`.

For HK-47 **hiding won**. The eye bar is modelled to sit in a recessed slot on a
flat faceplate; on a rounded organic face it reads as floating no matter where it
is placed, because the problem is its shape rather than its position. Moving a
fitting works when the new surface resembles the old one, and does not when the
geometry disagrees.

## Sizing a foreign head

Fitting on the tightest axis guarantees the part fits inside the target box, but
leaves it visibly small — the first attempt was 0.212 × 0.238 against HK's
0.300 × 0.333. `--scale` multiplies that fit.

The second lesson was subtler: at 1.4× the head was the right width but hung into
his shoulders. A humanoid head is proportionally **taller** than HK's boxy droid
one, so centring it pushes the extra height downwards. Anchoring the **chin**
where the vanilla head's chin sat, and letting the extra height go upward, fixed
it. Final: **1.15× scale, centre-z 0.098** (vanilla was 0.078), giving
0.244 × 0.273 × 0.306.
