# Foreign mesh trial — Tripo/Mixamo FBX into HK-47

**Date:** 2026-08-29
**Source:** `D:\Downloads\FBX FILE.fbx` — a Tripo-generated character auto-rigged
with Mixamo. One mesh, 29,071 vertices, 56,647 triangles, 52 `mixamorig:` bones.
**Tooling:** `tools/blender_fbx.py`, `tools/blender_fit_part.py` (Blender 3.6
headless), then `kmdlswap replace`.

## Result — the brief's definition of done, met

> A user can take `p_hk47.mdl`, replace the head mesh node with custom geometry
> of similar density, and get a model that loads in KOTOR 1 and animates
> correctly using HK-47's inherited animations.

The Tripo character's head — carved out, decimated, fitted and rotated — renders
correctly on HK-47 in-game, forward-facing, with his body untouched.

| | |
|---|---|
| Source head region | 1,857 vertices above weight 0.5, 3,312 triangles |
| After decimation | 1,366 vertices, 1,198 triangles |
| Vanilla head | 481 vertices, 393 triangles |
| Whole model | 2,467 → 3,272 triangles (brief's practical budget: 2,000–4,000) |
| MDL / MDX | 1,009,979 → 1,051,189 B / 110,464 → 138,784 B |

## The real finding: every failure was silent

Nothing on this path failed loudly. **Every one of the following produced a
model that passed all of kmdlswap's validators — full byte coverage, offset
closure, identity — and was still wrong.** The validators check that a file is
structurally sound, not that geometry is where a human meant it to be.

### 1. Blender's OBJ exporter writes world space

The mesh is parented to the armature, so the parent chain was baked into the
exported coordinates. The head landed at local centre `(0.428, 0.245, −0.673)`
instead of near the node origin — floating off to the side and below the neck.
Fix: detach the object and force an identity world matrix before export.

### 2. The exporter evaluates modifiers

An Armature modifier survived the carve, so the export applied the *current
pose* to the mesh — rotating and displacing it. This one was visible as a
non-uniform bounding-box change (0.180×0.161×0.266 became 0.296×0.198×0.272);
a pure translation bug would not change extents. Fix: strip all modifiers first.

### 3. A node's geometry is not centred on its own origin

HK-47's head geometry sits at `(0, +0.038, +0.078)` relative to its node origin.
Dropping a fitted part at `(0,0,0)` left it about a third of a head-height low.
Fix: an explicit target centre, read from the node being replaced.

### 4. Axis conventions differ

The head rendered coherently but faced HK-47's right shoulder. Derived rather
than guessed, from two agreeing signals:

- A head is near-symmetric ear-to-ear and asymmetric nose-to-back, so the axis
  with the largest asymmetry is the facing axis. Vanilla HK-47's head:
  **Y, −0.286** → faces −Y. The Tripo head: **X, −0.092** → faces −X.
- With HK-47 facing −Y and Z up, his right side is −X — exactly where the face
  was pointing.

A +90° rotation about Z aligns them. Applied as a Blender object rotation and
then baked, **not** by rewriting vertex coordinates, so the normals rotate too;
rotating coordinates alone leaves shading lit from the old direction.

### 5. Carving by "any weight at all" produces debris

Selecting the `mixamorig:Head` group by any nonzero weight dragged in a ragged
fringe. Combined with a 13.6× decimation, the first attempt rendered as a
faceted shell with a visible hollow interior and a fragment floating beside it.

| | First attempt | After fixes |
|---|---|---|
| Connected components | 6 | **1** |
| Open (hole) edges | 146 of 658 | **4 of 1,798** |
| Backwards-wound faces | 33 of 392 | **9 of 1,198** |
| Decimation ratio | 13.6× | **2.8×** |

Fix: require weight > 0.5, delete loose geometry, fill holes, recalculate
normals outward, keep only the largest island, and decimate less aggressively.

## A Blender quirk worth recording

Setting `vertex.select` in object mode does **not** reach the edit-mode
selection in headless Blender. The first version of the weight-threshold carve
therefore deleted the head and kept the body — it reported keeping 28,059 of
29,071 vertices, which is what exposed it. Pruning the vertex group down to its
strongly-weighted members and then using `bpy.ops.object.vertex_group_select()`
works.

## Scope note

This FBX could not be used wholesale, and that is not a limitation to fix: it is
one mesh of 56,647 triangles — **23× the entire HK-47 model** — carrying a
foreign Mixamo rig. The brief is explicit that importing a foreign rig is what
breaks, and that this tool swaps one node rather than building a character. The
trial deliberately used it as a *source of geometry* for a single node.

## What is still unverified

- The head node on HK-47 is **unskinned**. A foreign mesh has not been put into
  a *skinned* node, so weight transfer from foreign topology is proven only by
  the synthetic `boxhoses` probe, not by real authored geometry.
- Face adjacency is rebuilt at 96.3% fidelity. Nothing here would have exposed a
  difference.
- Texture coordinates are Tripo's, applied to HK-47's texture, so the head is
  mis-coloured. That is a texturing problem, outside this tool's scope.
