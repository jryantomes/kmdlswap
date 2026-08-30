# Character-model catalogue — is a parts-bin creator viable?

> **Stale images.** Every preview referenced here was rendered with the
> camera on the wrong side: KOTOR characters face +Y, not -Y, so these
> all show the backs of heads. The measurements below are unaffected -
> only the pictures are. See [FACING_FINDINGS.md](FACING_FINDINGS.md).

**Date:** 2026-08-29
**Tools:** [`tools/build_catalogue.py`](../tools/build_catalogue.py),
[`src/kmdlfun/catalogue.py`](../src/kmdlfun/catalogue.py)
**Scope:** all 164 `p_*` / `n_* `/ `c_*` models in a vanilla K1 install

The question behind this is narrow: can geometry move between vanilla models
*without touching the hierarchy* — the one constraint that keeps this tool safe?

## Supermodel families

164 character models, all of which parse and validate, group into 22 families by
supermodel. A supermodel supplies the skeleton and animations, so models sharing
one already agree on most node names.

| Supermodel | Models | Biggest members |
|---|---:|---|
| NULL (self-contained) | 55 | `n_darthmalak` 3,522t, `c_rancor` 3,036t, `c_bantha` 3,032t |
| `S_Female02` | 45 | `n_darthrevan` 3,192t, `n_calonord` 2,309t |
| `S_Female03` | 23 | `n_darthrevanf` 3,060t, `n_tuskenf` 2,088t |
| `S_Male02` | 8 | `n_jedimalek` 2,866t, `n_yoda` 1,842t |
| 18 others | 2–3 each | |

Note `S_Female02` is used by plenty of male characters — the name is a skeleton
identifier, not a statement about the character.

## The parts bin is real

Within `S_Female02`, counting only **visible, swappable** meshes and matching
node names case-insensitively:

| Part | Interchangeable models |
|---|---:|
| head | **25** |
| torso | **24** |
| left arm / right arm | **22** each |
| eyelids, eyes, teeth, tongue | 8–17 |

`S_Female03` gives 15 torsos and 11 of each arm. That is a genuine bin: a host
model plus ~25 heads and ~24 torsos is already thousands of vanilla-only
combinations, before any custom geometry.

## Naming is inconsistent, and it matters less than it looks

The same logical part appears under different names and casing even inside one
family — `torso` (15 models) and `Torso` (9), `LArm` (15), `larm` (4), `Larm`
(2), `ArmL` (3).

That fragments an exact-name grouping badly. It is **not** a hard limit, because
a swap never renames anything: the host keeps its own node name and only the
*geometry* moves. Matching is a heuristic for pairing donor to recipient, so
case-insensitive matching is legitimate and raises the `S_Female02` head pool
from 18 models to 25, and torsos from 15 to 24.

Classifying by body part rather than by name goes further still — 28 torso-ish
and 27 limb-ish donors in `S_Female02` — but that is looser and would need the
user to confirm the pairing.

## What this does not establish

The catalogue proves node names and skeletons line up. It does **not** prove the
geometry is compatible:

- **Proportions.** `S_Female02` includes humans, a Wookiee, a Rodian, Darth
  Malak. Their torsos share a node name and a skeleton, not a silhouette. Weight
  transfer would work — the recipient's own weights are inherited, so bone slots
  are always correct — but whether a Wookiee torso sits sensibly on a human
  skeleton is untested.
- **Textures.** A donated mesh keeps the host's texture and its own UVs, which
  is exactly why the Tripo head came out mis-coloured. A convincing result needs
  the donor's texture too, which is outside this tool.
- **Attachment.** Nothing here checks that a donor part meets its neighbours at
  the seams. Two models can share a node name and still have a neck that does
  not line up with the head above it.

The honest summary: **assembly is viable, appearance is unproven.** The next
useful step is previews — rendering each model and each part — so the bin can be
judged by eye instead of by triangle count.
