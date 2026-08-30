# Skinning findings — vanilla K1 census

**Date:** 2026-08-28
**Corpus:** all 2,832 MDL/MDX pairs in a vanilla K1 Steam install
**Harness:** [`tools/influence_census.py`](../tools/influence_census.py)

Measured over **386,120 skinned vertices** in **968 skinned meshes** across
**333 models**. This addresses two of the brief's "known unknowns" on the data
side. It does not replace in-game testing of the engine's limits — but it
establishes what the shipped game actually does, which is the strongest
available prior and bounds what a weight-transfer step must emit.

## 1. Max influences per vertex — observed ceiling is 4

| Influences | Vertices | Share |
|-----------:|---------:|------:|
| 1 | 196,343 | 50.85% |
| 2 | 151,729 | 39.30% |
| 3 | 35,167 | 9.11% |
| 4 | 2,881 | 0.75% |
| **5+** | **0** | **0%** |

**No vanilla vertex carries more than 4 influences**, matching the MDX stride,
which reserves exactly four `(weight, bone)` pairs (weights and bone indices are
each 4 floats). The structure cannot express a fifth without changing the stride.

Per-mesh maxima: 9 meshes cap at 1, 164 at 2, 501 at 3, 294 at 4. So 4 is
routinely exercised, not a rarity — it is safe to emit up to 4, and a transfer
capped at 4 gives up nothing vanilla uses.

Examples by ceiling — 1: `c_embmcube:ChamferBox01`, 2: `ad_saul:tongue`,
3: `3dgui:torso`, 4: `3dgui:BackCape`.

> The brief's Milestone 3 experiment is worked through in the next section. The
> 8 case turns out not to be reachable at all: the stride holds exactly four
> (weight, bone) pairs.

## 1b. The influence-cap experiment

The brief asks for variants capped at 1, 2, 4 and 8 influences, tested in-game,
and calls the finding publishable regardless of whether the tool ships. Measured
over all 386,120 skinned vertices (`tools/influence_cap_experiment.py`):

| Cap | Vertices affected | Weight discarded (mean) | median | p95 | max |
|----:|------------------:|------------------------:|-------:|----:|----:|
| 1 | 189,777 (**49.2%**) | 34.8% | 36.3% | 60.0% | 75.0% |
| 2 | 38,048 (9.9%) | 19.5% | 22.0% | 33.3% | 50.0% |
| 3 | 2,881 (**0.75%**) | 12.9% | 13.3% | 25.0% | 25.0% |
| 4 | 0 | - | - | - | - |

"Weight discarded" is the share of a vertex's total weight held by the
influences a cap removes, before renormalisation. It bounds the **data** loss
exactly. It does not predict the **visual** error, which also depends on how far
apart the dropped bone and its replacements travel during an animation - only
in-game testing settles that.

**The 8 arm is not reachable.** The MDX vertex stride holds exactly four
(weight, bone) pairs. A fifth influence cannot be expressed without widening the
stride, which changes the vertex format rather than the geometry, and is outside
what this tool does. Reporting that is more useful than inventing a result.

### What this predicts

The striking number is that capping at 1 discards **34.8% of weight on average**,
with a median of 36%. Vanilla skinning is not "one dominant bone plus a token
neighbour" - roughly half of all skinned vertices are genuine blends, often near
65/35. So:

- **Cap 3 should be visually indistinguishable** from vanilla: it touches 0.75%
  of vertices, and those keep ~87% of their weight.
- **Cap 2 should be subtle but present**, concentrated at joints.
- **Cap 1 should visibly crease or snap at joints**, because half of all
  vertices lose a third of their weighting.

That is a prediction made before the in-game test, not a description of it.
Worst case throughout is `c_bantha:btBody_front`, where a 4-way even split loses
75% of its weight at cap 1.

Test variants are built by `kmdlswap replace --max-influences N`; the meshes used
were `p_hk47:TorsoHoses` (2 influences max) and `p_bastilabb:torso`, the only
companion mesh found using all four slots.

## 2. Weights are always normalised

Across all 386,120 vertices, weight sums fall in **[0.999999, 1.000001]** —
float32 rounding only. **Zero** vertices deviate. Whether the *engine*
renormalises is still unknown, but vanilla data never relies on it, so the
brief's "normalize to 1.0 defensively" is exactly what the shipped content does.

## 3. The 16-slot bone table is NOT the per-mesh bone limit

The skin subheader contains a fixed 16-entry `u16` bone table. It reads like a
cap, and PyKotor exposes it as `bones`. It is not:

- **21 vanilla meshes reference 17 distinct bones** — e.g. `n_darthrevan:torso`,
  `p_juhanibb:torso`, `n_yoda:Head`, `rep_soldier_f:head`, `pfhc03:Head`.
- In every such case the **bonemap agrees** (declares 17), so 17 is real, not a
  parse artifact.
- Entries in the 16-slot table past the used count are **uninitialised garbage**
  (`p_hk47:R_hose` yields values like 63976, 16167). Reading it as authoritative
  produces nonsense bones.

**The bonemap is the authority.** Use the fixed table for nothing.

Distinct bones per mesh peaks broadly at 14–16 (245 / 147 / 176 meshes) with a
tail to 17.

## 4. Bonemap semantics — resolved

`bonemap` holds **one float per geometry node, in node order**. The value is that
node's slot in the `qbones`/`tbones` arrays, or `-1` when the node is not a bone.

- It is indexed **by node, not by vertex**, so it **does not resize** when a
  mesh's geometry changes. This retires design risk #2 in
  [`docs/BYTE_SURGICAL_DESIGN.md`](../docs/BYTE_SURGICAL_DESIGN.md): a geometry
  swap leaves the bonemap, qbones and tbones untouched.
- Per-vertex MDX bone indices are **slots**, resolved to nodes by inverting the
  bonemap.
- Verified: `bonemap_count == len(geometry nodes)` on every skinned mesh checked,
  and inverting it on `p_bastilabb:ArmL` yields exactly the expected arm chain
  (`lbicep_g`, `lforearm_g`, `lhand_g`, finger bones).

## 5. Positions are stored twice, and always agree

Every mesh keeps its vertex positions in **both** the MDX stream and an MDL-side
`vec3` array (`vertices_offset` in the trimesh subheader). On `p_hk47:head` the
two are byte-for-byte identical. A geometry swap **must write both**; asserted by
`tests/test_inspect.py::test_mdx_positions_match_the_mdl_side_vertex_array`.
