# The head-animation constraint was our own stale pointer

**Date:** 2026-08-30
**Status:** cause identified, fixed, and **confirmed in game 2026-08-30**
**Supersedes the central claim of:** [HEAD_ANIMATION_FINDINGS.md](HEAD_ANIMATION_FINDINGS.md)

## The finding

There is **no vertex-count constraint**. The rule this project has worked around
since 2026-08-29 —

> a skinned head mesh's vertex count cannot change, or facial animation breaks

— is wrong in every part. The count was innocent, skinning was a coincidence,
and the engine was behaving correctly the whole time.

**The MDL model header carries a node pointer at `+168` that this parser never
read, and therefore never relocated.** Grow any array that sits before its
target and the pointer is left pointing 36 bytes short, into the middle of the
previous node. The engine then loads the model rigid.

## What the field is

An offset, relative to byte 12 like every other MDL offset, sitting immediately
after the 32-byte supermodel name. The parser jumped from `base+104` to
`base+176` and skipped it.

It resolves to the **exact start of a node header in all 164 vanilla character
models** — no exceptions, none landing mid-span, none out of range:

| target | models |
|---|---|
| `neck_g` | 37 (every human head model) |
| the model's own root node | the rest |

A head model points at the neck, a body model at its root. The name
`super_root_node` is inferred from that behaviour, not from documentation.

## How it hid for so long

The pointer only matters when an edit grows something *before* its target.
Whether that happened tracked, by pure coincidence, the thing we thought was the
variable:

| probe | grew | that array ends | vs target 47642 | predicted | observed |
|---|---|---|---|---|---|
| C | `Head` | 41594 | before | break | **rigid** |
| E | `tongue` | 8974 | before | break | **broke** |
| D | `hair` | 60586 | **after** | work | **works** |
| Milestone 2 | HK-47 `head` | 888953 | **after** | work | **worked** |

Four for four, including the two that produced the skinned-versus-unskinned
theory. `hair` is unskinned *and* happens to sit after the pointer's target;
`Head` and `tongue` are skinned *and* happen to sit before it. Two coincidences
lined up and produced a false rule that survived five in-game probes.

## Why the earlier analysis could not have found it

The exhaustive diff (P0b) compared every span with all known pointers masked and
reported **zero** differences outside the edited node. That was true and
useless: a diff detects a pointer that changed *wrongly*. It is structurally
blind to one that should have changed and did not, because staying identical is
exactly what it looks like.

Finding it needed the opposite question — *which words that look like offsets
into the shifted region did **not** move?* — which is what finally surfaced it,
one suspect among 203 candidates, the rest being float data and a `65536`
artefact.

## The sequence that got there

Each in-game probe cost a trip into the game, so the ordering mattered:

1. **Probe C re-run** — broke again, on a file proved internally consistent.
   Ruled out "stale field we already parse" and "measurement artefact".
2. **Head is rigid, not frozen-faced** — the single most valuable observation.
   Changed the diagnosis from "facial animation fails" to "the engine refuses
   to skin the model", and implied the failure is model-wide rather than
   per-mesh.
3. **Sentinel probe** — negative. The spare MDX row is inert. Also served as an
   unplanned positive control: our splice can produce files that load and
   animate correctly.
4. **Buffer probe** — worked. MDX size and layout are irrelevant; the trigger is
   on the MDL side.
5. **Count probe** — broke with the count reverted. **The count field is
   innocent**; growing the MDL arrays is what matters. That inverted the finding
   and pointed straight at relocation.

Observation 2 is the one that mattered most, and it exists only because the
protocol asked "does the head still turn?" — a question five previous probes had
never recorded.

## The fix

`layout.py` now reads `base+168` and registers it as an offset targeting a
`node_header`, so the rewriter relocates it like any other pointer.

Registering it also makes the validator *stronger*: offset closure now proves
this pointer resolves to a node header, so a future edit that fails to move it
is a build-time failure rather than a silent in-game one. Corpus: **2832/2832**.

Verified on file — rebuilding probe C, the pointer moves `47630 -> 47666` and
resolves to `neck_g`, where before it stayed at `47630` and resolved to nothing.

## What this changes

**Confirmed in game on 2026-08-30.** The rebuilt probe C - the same edit that
had come back rigid every previous time - loads with the head turning and all
animation working. The following all dissolve:

- **The vertex-count rule.** Skinned head meshes can change vertex count.
- **`--reshape` as a requirement.** It stays useful for keeping a host's UVs and
  weights, but it is no longer the only safe path.
- **The custom-head ceiling.** A human head could take genuinely new geometry at
  its own resolution, not just vanilla topology pushed onto a donor surface.
- **`docs/CUSTOM_HEAD_SPEC.md`'s skinned-head warning**, and the support matrix
  rows built on it.

All of these have now been updated. `would_break_facial_animation` returns
False and is kept only so callers and tests have something to point at; the
headspec check reports a pass; the transplant refusal is gone and `--reshape` is
no longer forced.

The regression test is
`tests/test_transplant.py::test_the_super_root_pointer_survives_a_growing_edit`.
It grows `Head` (whose array sits *before* the pointer's target, so the pointer
must move) and `hair` (which sits after, so it must not), and requires both to
resolve to a node header. It can fail in either direction rather than merely
confirming.

## Method note worth keeping

Two false rules held for a day each: "characters face -Y" and "vertex counts
cannot change". Both were induced from real measurements, both survived checks
that felt like verification, and both fell to a test that *could have come out
the other way*. The marker probe could only ever show the camera pointed at
whatever it pointed at; the diff could only ever show changes, never omissions.
When a check confirms a belief, ask what result would have falsified it.

## A foreign mesh into a skinned node — confirmed 2026-08-30

The largest untested path in the project, and the one the vertex-count rule had
blocked outright. A Tripo-generated head, decimated to 900 triangles, fitted and
weight-transferred onto Carth's skinned `Head` node:

```
vertices    565 -> 1574        (foreign topology, not a reshape)
triangles   744 -> 900
skinning    transferred; max 4 influences/vertex, 12 bones
```

**In game: head turns, mouth moves in dialogue, brows do not.**

All three were predicted before the test, including the negative one. Weight
transfer kept 12 of the host's 16 bones and dropped `f_lbrw_g`, `f_mdbrw_g`,
`f_rbrw_g` and `f_rns_g` — the brow bones, because the donor head is smooth
where Carth's brow ridge is and no transferred vertex landed in their regions.
Predicting a specific absence and observing it is much stronger evidence that
the model is right than another success would have been.

So the pointer fix holds for genuine geometry replacement, not only for padding
probes, and barycentric weight transfer onto foreign topology works.

### Known gap: bones with no transferred weight go silent

Weight transfer samples the host surface at the donor's vertices. A bone whose
region is small, or which sits where the donor's shape differs, gets no sample
and simply stops driving anything. It fails quietly and looks like "that part of
the face doesn't animate".

The fix is bounded: after transfer, any host bone with no influence should claim
the vertex nearest its region, at a small weight, with renormalisation. That
guarantees every bone the host had still moves something. Not yet built.

### Not a pipeline problem: the donor mesh

The result looks like a lumpy blob with a topknot. That is the input.
`tripo_full.obj` is a poor carve — bulging cheeks, protruding eyeball spheres,
no real face — and rendering it undecimated beside the decimated version shows
decimation reproducing it faithfully. The pipeline is sound; the mesh is not.
Worth remembering when judging future results by eye.
