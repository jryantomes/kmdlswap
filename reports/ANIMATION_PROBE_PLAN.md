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
