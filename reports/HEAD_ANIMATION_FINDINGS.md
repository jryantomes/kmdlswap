# Changing a head mesh's vertex count breaks facial animation

**Date:** 2026-08-29
**Model:** `p_carthh` (Carth's head), tested in dialogue in-game
**Status:** reproduced and bounded by bisection; **mechanism unknown**

## The finding

Replacing the geometry of a skinned **head** mesh breaks the character's facial
animation — mouth and eyebrows stop moving in conversation — **if and only if the
vertex count changes.**

| Probe | What changed | Facial animation |
|---|---|---|
| A | Head vertex positions scaled 1.25×; count, faces, weights untouched | **works** |
| C | 3 duplicate vertices appended that no face references; positions, faces, weights otherwise untouched | **breaks** |
| D | `hair` grown by 3 vertices; Head untouched | **works** |

Vanilla was confirmed as a control: Carth's mouth and eyes move in the same
conversation.

## What this rules out

Probe D is the important one. `Head` is the **last** MDX block in `p_carthh`, so
growing it shifts *no* other block; `hair` is block 9 of 26, so growing it shifts
**16** blocks. The probe that shifted sixteen blocks worked and the probe that
shifted none broke. So the splice and the offset fix-up are sound, and the cause
is the head's own vertex count.

Also eliminated, each by measurement rather than assumption:

- **Bone slots** — identical 16, including `f_jaw_g`, `f_um_g` and the brows.
- **Weight distribution** — facial bones hold 30.2% of weight mass in vanilla,
  29.7% after; spatially faithful too (`f_jaw_g` 47.0% → 49.7% of jaw-region
  weight).
- **MDX values** — no NaN or infinity, weights sum to 1, unit normals, row 0
  byte-identical to vanilla.
- **Skin subheader** — completely unchanged by the edit; its `+0/+4/+8` fields
  are zero in all 238 skinned meshes checked, and `unknown0_count` always equals
  `bonemap_count`, so nothing there is per-vertex.
- **`mdx_data_buffer_offset`** (model header +172) — zero in all 700 models
  checked.
- **Geometry-header `unknown0`** (28 bytes) — zero.
- **Model header** — identical between the working and broken probes except
  `mdx_size`, which both update the same way.

Body meshes do **not** behave this way: HK-47's `TorsoHoses` went from 124
vertices to 24 and still moved with his torso.

## Two real bugs found on the way

Both were found by systematically diffing vanilla against output, after
hypothesis-driven checks had failed. Neither turned out to be the cause, but both
were genuine:

1. **Face normals were shading normals.** The per-face normal was computed as the
   average of the three vertex normals. Vertex normals are smoothed for shading
   and do not lie in the triangle's plane. The correct value is the normalised
   edge cross product with `d = -(n · p0)`, which reproduces vanilla to 1.2e-7 on
   all 744 faces of `p_carthh:Head`; the averaged version was wrong on **every**
   face.
2. **Per-face material was flattened.** Every face was given the first face's
   material value, which is wrong on 118 of 744 faces — vanilla varies it per
   face, and it reads as a smoothing group. Transplants now carry the donor's own
   values.

With both fixed, a self-transplant differs from vanilla by 828 bytes of pure
float noise (worst deviation 1.6e-07), with material, adjacency and vertex
indices exact.

## The workaround: reshape instead of replace

Since moving a head's vertices is safe and changing their number is not, a head
swap keeps the host's topology and *moves* its vertices onto the donor's surface
(`kmdlfun transplant --reshape`). Vertex count, faces, UVs and weights are all
preserved byte-for-byte; only positions change.

The trade-off is real and worth stating: the result has the **host's** resolution
and the **host's** UVs. A donor with finer detail cannot express it, and where the
two shapes differ greatly the host's topology stretches to reach.

**Verified in-game (2026-08-29).** `p_carthh` reshaped onto `n_rodian`'s head:
the face is visibly changed - the Rodian snout pulls his profile forward - and
his mouth animates normally in dialogue. Vertex count, faces, UVs and per-vertex
weights are byte-identical to vanilla; only positions moved, and both files are
exactly the original size.

One detail that mattered: weights must pass through **verbatim**, not be
re-derived. Re-deriving them by nearest point after the surface has moved
silently dropped a bone (16 slots became 15), because a bone's region no longer
got sampled. Topology is unchanged in a reshape, so vertex *i* simply keeps its
own weights.

## Textures ride along safely

A texture reference is a fixed 32-byte field in the trimesh header at `+88`, so
changing it is a patch in place - no splice, no offsets to fix. All meshes in a
head model share one texture, so it is one decision per model.

The mapping was the real question. A reshaped head has the *host's* topology, so
its UVs belong to the host's texture; using the donor's texture needs the
donor's mapping. `snap_to_surface` already computes barycentric coordinates
where each host vertex lands on the donor surface, so those interpolate the
donor's UV at that point.

**Verified in-game (2026-08-29):** `p_carthh` reshaped onto `n_dustilh` with
`--with-texture`. The face has Dustil's shape and Dustil's texture, the skin
reads continuous into the neck with no UV scrambling, and facial animation is
intact. Vertex count, faces and per-vertex weights stay byte-identical to
vanilla and both file sizes are unchanged - the configuration the engine
requires.

So a head swap can change shape *and* colouring while keeping animation, as long
as the vertex count is left alone.

## Still unknown

Why the count matters. Nothing in the file that this project can identify depends
on a skinned head mesh's vertex count. The engine evidently does. Until that is
understood, `--reshape` is a workaround, not a fix, and head swaps should use it.
