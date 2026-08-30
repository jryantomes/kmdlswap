# Probe plan: why does changing a skinned head's vertex count break facial animation?

**Written:** 2026-08-30
**Status:** plan, nothing executed yet
**Background:** [HEAD_ANIMATION_FINDINGS.md](HEAD_ANIMATION_FINDINGS.md)

## Reframing the problem first

The rule as currently written — *a skinned head mesh's vertex count cannot
change* — is almost certainly not the real rule, and the plan below is built on
saying so.

**Vanilla itself ships head models at many different vertex counts and animates
all of them:**

| Carth | Bastila | Carth (BB) | Mission | Zaalbar | Canderous | Jolee |
|---|---|---|---|---|---|---|
| 565 | 554 | 368 | 446 | 473 | 545 | 615 |

So the engine has no expected number. There is nothing magic about 565. And the
modding community ports heads from *The Old Republic* — entirely foreign meshes,
arbitrary counts — and those animate.

That makes the honest statement of the problem:

> When **we** change a skinned head's vertex count, something else that must
> change with it does not. Everything else the engine needs is still derived
> from vanilla's count.

This is a much better problem, because it is a search for a stale field rather
than a search for an engine mystery. The probes are ordered accordingly: the
cheapest ones that could localise a stale field come first, and the expensive
in-game bisection comes last.

## Fix the measurement before taking more of it

Every in-game probe so far returned one bit — "animation broke" — and one round
was lost to ambiguity about whether the vanilla control had been tested. Before
running anything else, fix the observation protocol:

**Every in-game probe records the same five observations, in the same scene:**

1. **Lipsync** — does the mouth move during spoken dialogue?
2. **Blink** — do the eyelids blink on idle? (a facial animation that needs no
   conversation, so it separates "lipsync" from "all facial animation")
3. **Brows / expression** — do the brows move on an emotive line?
4. **Head turn** — does the head still turn and tilt as a unit?
5. **Control** — does a *different, unmodified* character in the same scene do
   all four?

Observation 4 is the one never yet recorded, and it is diagnostic on its own.
If the head still turns but nothing on the face moves, the mesh is still being
skinned and only the facial bones are inert. If the head has gone rigid or
detached, skinning itself has been switched off. Those are different bugs.

---

## Tier 0 — costs nothing, run before touching the game

### P0a. Find a known-good counter-example

Obtain any community custom human head that is **not** a vertex-count-preserving
edit of a vanilla head — a TOR port is the clearest case — and measure its head
node's vertex count against every vanilla head.

- **If its count matches no vanilla head and it animates in game:** the "count
  cannot change" rule is disproved outright, and we now hold a *known-good file
  built by other tools*. Every later probe becomes a diff against it. This is
  the single highest-value outcome available and it costs a download.
- **If every custom head turns out to preserve a vanilla count:** that is
  evidence the community hit this too and worked around it silently, which is
  worth knowing and worth writing up.

### P0b. Exhaustive semantic diff of the broken probe against vanilla

We diffed selected fields. Diff *everything* the parser can name — every header
field, every array, every span classified as unknown — between vanilla
`p_carthh` and the known-broken probe C build, and list every difference with no
filtering. Prior diffs were hypothesis-driven and so could only find what was
already suspected.

### P0c. Confirm the rebuild path is not the confound

Checked while writing this plan, and it changes the picture: **probe A also went
through `replace_geometry`.** `kmdlfun.apply.scale_geometry` calls it, so the
scaled-head probe exercised the entire rebuild — normals, per-face material,
adjacency, MDX repack — at an unchanged vertex count, and animated correctly.

Two things follow for free:

- **The rebuild path is cleared.** A and C ran identical code and differ only in
  the vertex count. That isolates the count far more tightly than the report
  claimed, and removes "our rewrite is subtly wrong" as an explanation.
- **96.3% adjacency fidelity is proven harmless for animation.**
  `docs/CUSTOM_HEAD_SPEC.md` lists this as an open caveat; probe A closes it.

Remaining desk check: confirm the adjacency arrays in the A and C builds are
identical to each other. They should be — neither touches faces — and if they
are not, adjacency comes back as a suspect.

### P0d. Scan for a stale second copy of the vertex count

**The most likely single explanation, and it costs nothing to test.** If the
engine reads 568 from one field and something still says 565, that stale field
is the bug — and it is findable without the game.

Search the vanilla MDL for every `u16` and `u32` equal to a value derived from
the head's count: 565 itself, and 565 × stride, × 12, × 4, × 3, and the byte
length of the vertex, normal and UV arrays. Record every hit and its offset.
Then do the same on the broken probe C build and diff the two sets.

- Any location holding a count-derived value in vanilla that **still holds the
  vanilla-derived value** in the broken build is a stale field and a direct
  candidate for the cause.
- If every such location updated correctly, no stale copy exists in the MDL and
  the cause is outside it — which sends us to P1b.

This is the probe that best fits the reframing above: the engine happily accepts
many different counts, so the failure is much more likely to be an internal
inconsistency than a rejected number.

---

## Tier 1 — one build each, maximum discrimination per game trip

### P1a. Take vertices *away* instead of adding them

Every probe so far **added** vertices. Build Carth's head with three fewer
(collapse three edges, weights passed through verbatim for survivors).

| result | meaning |
|---|---|
| breaks | the engine compares the count against something fixed — an equality check |
| works | only growth hurts, which means a buffer sized at load and overrun |

Either answer halves the hypothesis space, and the "works" branch would point
straight at an allocation derived from the file itself.

### P1b. Separate the declared count from the buffer size

Grow the head's **MDX block** by three vertices' worth of bytes — fixing every
downstream MDX offset and `mdx_size` exactly as a real edit would — but leave
the node's `vertex_count` and the MDL-side vertex and face arrays **untouched**.
The engine then reads 565 vertices out of a block that holds 568.

| result | meaning |
|---|---|
| works | the engine reads the declared count; block size and file size are irrelevant; the cause lives in what changes *because* the count changed |
| breaks | the engine is sensitive to MDX block or total size, not to the declared count — which would be a completely different search |

This is safe: the buffer is over-provisioned, never under. It is also the
cleanest single separation available anywhere in this problem.

### P1c. *Retired before it was run* — same-count rebuild

This probe was drafted on the assumption that probe A patched positions in place
and so had never tested the rebuild path. That was wrong: `scale_geometry` calls
`replace_geometry`, so probe A already rebuilt everything at an unchanged count
and animated correctly. See P0c. No game trip needed.

Worth recording as a method note: the probe was proposed because "no probe has
separated *count changed* from *rebuilt*", which sounded right and was checkable
in one grep. Check first.

---

## Tier 2 — scope

### P2a. Same edit on a body model

Apply probe C's exact recipe — three unreferenced vertices — to a skinned mesh
in a human **body** model, and watch body animation.

- **Body animation fine:** the constraint is specific to head models, and bodies
  are open for the character creator.
- **Body animation breaks:** it is a general property of skinned meshes, which
  is worse news but sharply narrows the mechanism and closes off a direction we
  would otherwise waste effort on.

Either way this answers a question the character creator needs regardless of
whether the head problem is ever solved.

---

## Tier 3 — the differential, if Tier 0 and 1 have not settled it

### P3a. Build the same change two ways and diff

Add three vertices to Carth's head twice: once with MDLedit or MDLOps
(decompile → edit → recompile, which rebuilds every field from scratch), once
with our splice. Confirm in game which animates.

If theirs works and ours does not, the answer is a byte diff between two files
that differ by exactly the thing we are looking for. This converts an
open-ended search into a bounded one, which is why it is worth the setup cost —
but Tier 0 and 1 may make it unnecessary, so it is last.

### P3b. Risky, hold in reserve

Raise the declared `vertex_count` without adding the data. The engine would read
past the end of the block. It may crash, and a crash tells us little. Only worth
running if P1b came back "breaks" and we need the mirror image.

---

## Decision tree

```
P0d finds a field still holding a vanilla-derived value? ─ yes ─> that is the bug; fix and retest
                                                         └ no
P1b works (declared count is what matters)? ─ no ──> chase MDX block/total size, not the count
                                            └ yes
P1a removal also breaks? ─ yes ─> equality check against something external; go to P0a / P3a
                         └ no ──> load-time allocation overrun; look for a size field
```

P0d and P0a cost no game time and either could end this on their own. Run both
before building anything.

## What would close this out

Any one of: a stale count-derived field found by scanning (P0d), a community
head with a non-vanilla count that animates (P0a), or a diff against an
MDLedit-built file (P3a). The first two cost no game time, and none of the three
requires understanding the engine — only finding what disagrees.

---

# Results — 2026-08-30

Tier 0 executed with `tools/probe_diff.py` against a rebuilt probe C
(`p_carthh`, `Head`, 565 → 568 inert vertices).

## P0d — no stale copy of the vertex count. **Negative.**

The scan initially flagged four "surviving" values, including the promising
`36160 = 565 x stride 64`. All four were **u16 coincidences landing inside
`face_array`** — ordinary index data that happens to equal those numbers. The
only location holding a genuine count is `trimesh_header of Head +304`, and it
updated 565 → 568 correctly.

Method note: the first scan conflated u16 and u32 hits, and a follow-up
comparison read *unaligned* words, producing a screen of impressive-looking
deltas that were all the same +36 pointer shift seen through misaligned windows
(36<<24, 36<<16, 36<<8). Both were artefacts of the tool, not findings.

## P0b — the file is internally perfect. **Negative, and strongly so.**

Comparing span by span, with every pointer and count the parser knows masked out:

```
offsets: vanilla 552, probe 552
counts : vanilla 619, probe 619
count fields differing: 3
    mdl_data_size   @0x00004: 80026 -> 80062
    mdx_size        @0x00008: 53120 -> 53312
    model_mdx_size  @0x000bc: 53120 -> 53312

spans differing outside 'Head' AFTER masking known pointers/counts: 0
```

**Zero.** Every byte outside the edited node is either identical or a pointer
that shifted by exactly the right amount, and the three size fields all updated
correctly. Since the coverage validator already proves every byte lies in
exactly one span, this is not a spot check — it is exhaustive.

So the probe C file is exactly what a 568-vertex `p_carthh` should look like,
and the engine still mishandles it. **The "stale field" reframing is dead.**

## A real format discovery: every MDX block carries a sentinel row

Every mesh block is exactly one vertex longer than `vertex_count x stride`.
Across all 164 character models and **7,290 mesh blocks, without a single
exception**, the extra row is there. Its first three floats are a parked
position, and the value splits perfectly by mesh type:

| mesh type | sentinel position | blocks |
|---|---|---|
| unskinned | `10,000,000` | 6,795 |
| skinned | `1,000,000` | 495 |

No exceptions either way. For `p_carthh:Head` the full row is position
`1e6, 1e6, 1e6`, normal zero, UV zero, weights `(1, 0, 0, 0)`, bone indices
`(0, 0, 0, 0)`.

Our splice preserves it byte-identically, so it is **not** the bug. But the
engine evidently chooses this value per mesh type, which means something reads
it — and it splits on *exactly the axis that discriminates our failure*.
That earns it a probe of its own.

## Where this leaves the plan

P0d and P0b are both spent, and both came back clean. The file is right. That
leaves three possibilities, and the ordering has changed:

1. **The observation is wrong.** A provably-clean file that misbehaves should
   raise suspicion of the measurement before the engine. The in-game checks so
   far returned one ambiguous bit and never recorded whether the head still
   turns. Given how the camera-facing error survived a check that felt like
   verification, this now deserves to go first.
2. **The engine allocates or caches something from the count** that no field in
   the file expresses. P1b is the sharpest remaining build.
3. **Something outside the MDL/MDX** — a `.lip`, a 2DA, a cached resource.

### New probe: P1d — write the wrong sentinel

Change a skinned head's sentinel from `1e6` to `1e7` (the unskinned value) and
change nothing else: same vertex count, same everything, one float triple
rewritten.

| result | meaning |
|---|---|
| facial animation breaks | the engine reads the sentinel, and we have a mechanism to pull on — the first one this investigation has had |
| nothing happens | the sentinel is inert bookkeeping and the skinned/unskinned split is a compiler artefact |

Cheap, safe, and it tests the only structure yet found that divides skinned from
unskinned meshes the same way the bug does.

### Revised order

1. **Re-observe** probe C in game with the five-point protocol (especially: does
   the head still turn?).
2. **P1d** — the sentinel.
3. **P1b** — declared count versus buffer size.
4. **P1a** — removal instead of addition.

## Probe C re-run — 2026-08-30, confirmed

Rebuilt probe C installed to Override and tested on Carth in conversation:
**animation broke again.**

This matters more than a repeat usually would, because the file it broke on is
the one P0b proved is internally perfect. Two possibilities die here:

- **Not a stale field.** Every byte outside the edited node is identical to
  vanilla or a pointer that shifted by exactly the right amount, and all three
  size fields updated. There is nothing left in the file to be stale.
- **Not a phantom.** The failure is real and reproducible, so the original
  finding stands rather than dissolving on closer measurement.

That leaves the engine doing something with the count that no field in the file
expresses, and makes the sentinel probe (P1d) the most interesting thing left:
it is the only structure found so far that divides skinned from unskinned
meshes on the same axis as the failure.

**Still outstanding from the protocol:** whether the head continues to *turn*
as a unit. "Animations broke" does not separate "facial bones inert while
skinning works" from "skinning switched off entirely", and those point in
opposite directions.

## The head is RIGID — skinning is being switched off

Probe C re-observed with the protocol: **Carth's head does not turn.** It is
rigid, not merely frozen-faced.

This is the most informative single observation the investigation has produced,
because it changes what is failing. The engine is not losing the facial bone
animation while continuing to skin the mesh. It is **refusing the mesh as a skin
mesh at all** and falling back to rigid bind pose. Something validates the skin
data at load and rejects it.

### It follows that the failure is model-wide, not per-mesh

Probe E grew `tongue` — a skinned mesh the facial bones do not deform — and
facial animation broke. If a rejected mesh only lost *its own* skinning, the
`Head` mesh would have been untouched and Carth's face would still have moved.
It did not. So editing any skinned mesh's count takes down skinning for the
whole model, which points at a **model-level skin setup that fails wholesale**
rather than a per-mesh check.

That reframes the target again: look for something the engine builds once, for
the model, out of all the skinned meshes together.

### What this rules in and out

- **Not the facial bones, not the supermodel, not lipsync.** Head models carry
  no animation of their own (`p_carthh`'s supermodel is `S_Female02`, which has
  62 meshes and no skinned ones at all), and none of that machinery is involved
  in deciding whether to skin a mesh.
- **Consistent with every earlier probe.** Unskinned `hair` was safe because it
  never enters the skin setup at all.

### Revised probe order

Both remaining Tier 1 probes now test the same question — what the model-level
skin setup is sensitive to — from two sides:

1. **P1d, the sentinel** (built, `out_probe/test2_sentinel/`). Twelve bytes, no
   size change, no count change. The spare MDX row is the only structure known
   to be chosen *per mesh type*, so it is plausibly part of skin setup.
2. **P1b, buffer versus count** (built, `out_probe/test3_buffer/`). The MDX
   block grows by three rows while `vertex_count` stays at 565 and the MDL does
   not change length at all. Tells us whether the setup keys off the declared
   count or off the buffer geometry.

## P1d, the sentinel — **negative**

Skinned `Head` sentinel rewritten from `1,000,000` to the unskinned
`10,000,000`, nothing else touched. In game: head turns, all animation normal.

**The sentinel is inert.** The engine does not read it. The perfect
skinned/unskinned split across 7,290 blocks is a compiler artefact - MDLOps or
whatever built these models chose the value by mesh type, and nothing consumes
it. A tidy correlation that meant nothing, which is worth recording precisely
because it looked so promising.

It did earn something unplanned: **a positive control.** A file written by our
splice, installed to Override, loads and animates correctly. So probe C's
failure is not "this tool emits broken models" - the pipeline is sound and the
failure is specific to what probe C changes.

## P1b, buffer versus count — **the buffer is innocent**

MDX block grown by three rows, both MDX size fields updated, `vertex_count` left
at 565, MDL length unchanged. In game: **head turns, everything works.**

So the engine does not care how large the vertex buffer is, or what `mdx_size`
says. It reads the declared count and is satisfied. Combined with probe C, the
trigger is on the MDL side.

### Standing after four in-game probes

| probe | `vertex_count` | MDL arrays | MDX block | skinning |
|---|---|---|---|---|
| vanilla | 565 | 565 | 565+1 | works |
| C | **568** | **568** | **568+1** | **rigid** |
| P1d sentinel | 565 | 565 | 565+1 (value changed) | works |
| P1b buffer | 565 | 565 | **568+1** | works |

Probe C still moves two things at once - the count field and the MDL vertex
array, whose growth shifts ~295 pointers. P1e separates them: it does everything
probe C does and then writes the old count back, so the engine is told 565 while
every array behind it holds 568.

- **works** → the count field alone is the trigger, and growing a skinned mesh's
  arrays is otherwise harmless.
- **breaks** → the count is innocent and growing a *skinned* mesh's MDL arrays
  is the problem. Probe D already showed that growing an *unskinned* mesh's
  arrays and shifting pointers is fine, so this would localise it to skinned
  geometry specifically.
