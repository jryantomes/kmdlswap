# The head-animation constraint was our own stale pointer

**Date:** 2026-08-30
**Status:** cause identified, fixed in the parser, awaiting in-game confirmation
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

If confirmed in game, the following all dissolve:

- **The vertex-count rule.** Skinned head meshes can change vertex count.
- **`--reshape` as a requirement.** It stays useful for keeping a host's UVs and
  weights, but it is no longer the only safe path.
- **The custom-head ceiling.** A human head could take genuinely new geometry at
  its own resolution, not just vanilla topology pushed onto a donor surface.
- **`docs/CUSTOM_HEAD_SPEC.md`'s skinned-head warning**, and the support matrix
  rows built on it.

None of that should be rewritten until it is confirmed in game. A successful
build is not proof.

## Method note worth keeping

Two false rules held for a day each: "characters face -Y" and "vertex counts
cannot change". Both were induced from real measurements, both survived checks
that felt like verification, and both fell to a test that *could have come out
the other way*. The marker probe could only ever show the camera pointed at
whatever it pointed at; the diff could only ever show changes, never omissions.
When a check confirms a belief, ask what result would have falsified it.
