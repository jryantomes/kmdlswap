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
| E | `tongue` grown by 3 vertices; Head byte-identical | **breaks** |

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

Probe E sharpened the rule. `tongue` is skinned like `Head`, but the facial bones
do not deform it and it is not the last MDX block - growing it broke facial
animation anyway. `hair` is *unskinned*, and growing it did not. All three probes
changed the same thing in kind, and the amounts do not separate them:

| Probe | Mesh | Skinned | Stride | MDX bytes added | Result |
|---|---|---|---|---|---|
| C | `Head` | yes | 64 | 192 | breaks |
| E | `tongue` | yes | 64 | 192 | breaks |
| D | `hair` | **no** | 32 | 96 | works |

**The discriminator is skinning** - not which mesh, not where it sits in the MDX,
not how much the file grows. Any skinned mesh in a head model is affected.

Body meshes may differ: HK-47's `TorsoHoses` went from 124 vertices to 24 and
still moved with his torso. But that is a single case, and it only confirmed
gross motion rather than fine deformation, so it is treated as a caution rather
than a clearance.

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

## What the modding community knows (searched 2026-08-30)

Short version: **nobody has published this.** The constraint we measured is not
documented anywhere findable, and the canonical reverse-engineering thread lists
our exact questions as open.

### The canonical thread is explicit about the gap

[Kotor/TSL Model Format (MDL/MDX) Technical
Details](https://deadlystream.com/topic/4501-kotortsl-model-format-mdlmdx-technical-details/)
is the community's format reference. It acknowledges as unresolved:

- the flag structures distinguishing node types,
- skin mesh header composition (bonemap, bone indices),
- **whether per-frame vertex arrays or morph targets exist**,
- bone count limitations.

Those are precisely the places we would have to look. The thread is described by
its own participants as ongoing reverse-engineering rather than documentation.

### What the community does say, and why none of it fits

| Claim | Source | Does it explain our failure? |
|---|---|---|
| Head models have no animations of their own; they inherit from a **supermodel** | [Missing animations in head models](https://deadlystream.com/topic/5551-tsl-missing-animations-in-head-models/) | No. We never touch the supermodel field, and the same file animates correctly until the vertex count changes. |
| Broken animation comes from **bad bone weights** in the MDX | same | No. Probe C kept weights byte-identical to vanilla and animation still broke. |
| KOTOR "bones" are **objects acting as bones**, not a real skeleton | [Creating new facial animations](https://deadlystream.com/topic/7429-creating-new-facial-animations/) | Consistent with what we see, but not a mechanism. |
| Changing vertex counts "complicates animation **retargeting**" | [Missing animations in head models](https://deadlystream.com/topic/5551-tsl-missing-animations-in-head-models/) | Closest thing to our finding anywhere, but it is a passing remark about workflow, with no mechanism and no distinction between skinned and unskinned meshes. |
| Max **16 bones per mesh** | [Creating new facial animations](https://deadlystream.com/topic/7429-creating-new-facial-animations/) | Half right - see below. |

### Two things worth having, from reading kotorblender

[kotorblender](https://github.com/seedhartha/kotorblender) is an independent
implementation that round-trips these files, so it is a real second opinion.

**Our skin header reading is correct.** Field for field, its reader agrees with
ours: an unknown array def, the two MDX stride offsets for weights and bone
indices, the bonemap offset and count, qbone/tbone/garbage array defs, then a
fixed 16-entry `bone_indices` table. This eliminates a live hypothesis - we are
not misreading a field.

**Nothing in the skin header is derived from the vertex count.** The bonemap is
sized by node count, qbones and tbones by bone count, and the two MDX offsets are
positions *within* the vertex stride, so they do not move when the count changes.
An independent implementation having no vertex-count-dependent field either is
decent evidence that the dependency is not in the file at all.

### A community claim our corpus contradicts

The "16 bones per mesh" limit is the size of the fixed `bone_indices[16]` table
in the skin header, not a cap on what a mesh may use. Across all 164 character
models and 495 skinned meshes:

| bone slots used | 1-9 | 10-13 | 14 | 15 | 16 | **17** |
|---|---|---|---|---|---|---|
| meshes | 115 | 99 | 124 | 80 | 67 | **10** |

Ten vanilla meshes use 17, including `n_yoda:Head`, `n_trandoshan:Head` and
`p_juhanibb:torso`. So the bonemap, not the 16-slot table, is what the engine
reads - which is what this project already concluded independently, and why
`NodeInfo.bones` carries the note to prefer the bonemap.

### One hypothesis this killed

The search suggested morph-target / per-frame vertex animation as a mechanism -
which would explain the constraint perfectly, since stored vertex arrays would
have the old count. It is wrong for KOTOR characters: the `ANIM` node flag
(0x80) exists in the format but **no node in `p_carthh`, `p_hk47` or
`p_bastilah` carries it**. Every mesh is `mesh`, `mesh|skin` or `mesh|dangly`.

### Where this leaves us

There is no wheel to avoid reinventing. The constraint is real, ours is
apparently the first measurement of it, and an independent reader of the same
format exposes nothing that would explain it - so the dependency is most likely
in the engine's runtime handling of skinned geometry, not in a field we are
failing to update. `--reshape` remains the right answer.
