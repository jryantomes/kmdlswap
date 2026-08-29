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

> The brief's Milestone 3 experiment (build variants capped at 1/2/4/8 and test
> in-game) is still worth running for the 8 case specifically: it would show
> whether the engine reads a wider stride at all. The 1/2/4 arms are now
> predictable from vanilla evidence.

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
