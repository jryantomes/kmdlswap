# Milestone 3 — geometry replacement

**Date:** 2026-08-28
**Modules:** `obj.py`, `weights.py`, `topology.py`, `swap.py`
**Tests:** `tests/test_geometry_replacement.py` (22 tests)

## What works

`kmdlswap replace <model> --node <name> --mesh new.obj --out <dir>` reads an OBJ,
inherits skin weights from the mesh being replaced, rebuilds face adjacency, and
splices the result in. The output is re-parsed and re-validated before anything
is written; a model that fails validation is refused rather than saved.

### Fidelity: the OBJ round trip is lossless

`extract → OBJ → replace` reproduces the **entire MDX byte-for-byte**, on
unskinned *and* skinned meshes — the transferred weights come back bit-identical
to the originals. OBJ is written with 9 significant digits, which round-trips a
float32 exactly; the format stores float32, so that is the precision that
matters.

The MDL does change, but only inside the target node's `face_array`: face
normals and plane coefficients are recomputed, and adjacency is rebuilt.
Verified byte-by-byte — every differing byte in a `p_hk47:head` swap lies in that
one span, and vertex indices and material values are untouched.

## Findings

### 1. Face adjacency: convention recovered, tolerance not

Adjacency was undocumented. Testing candidate rules against 16,031 vanilla faces
settled it:

| Rule | Agreement |
|---|---|
| by vertex index, undirected | 22–46% |
| **welded by position, undirected** | 92.5% |
| **welded by position, directed half-edge** | **96.3%** |

Edges are `(v0,v1), (v1,v2), (v2,v0)` — the two rotations score ~0%, so the
ordering is certain. Two refinements matter:

- **Weld by position first.** Meshes split vertices at UV seams; vanilla's
  adjacency crosses those seams regardless.
- **Match directed half-edges.** The neighbour across `(a,b)` is the face holding
  `(b,a)`. This is what handles double-sided surfaces: `p_bastilabb:Frntflap` has
  23 edges shared by *four* faces, and undirected matching gives up on all of
  them (0/40 faces correct) where directed matching succeeds.

The residual ~3.7% is most likely a weld *tolerance* in the original compiler —
we weld on exact float equality. Adjacency values are always in range, which is
the invariant that matters; `topology.check_adjacency` asserts it.

### 2. Weight transfer is exact on its own input

Closest-point-on-triangle with barycentric interpolation, as the brief specifies.
Transferring a mesh's weights onto its own vertex positions returns the original
weights with max deviation **5e-7** and a 100% match on which bones are used,
across every mesh tried. That is the strongest available self-check short of
in-game evidence.

Two rules from the vanilla census are enforced: at most 4 influences per vertex,
and weights normalised to 1.0. Influences below 0.1% of a vertex's total are
dropped and the rest renormalised — barycentric blending across a seam otherwise
leaves a bone with a vanishing share, which vanilla never stores and which wastes
one of only four stride slots.

### 3. Character models never carry unauthorable MDX columns

An OBJ cannot express a second UV set, vertex colours, or tangent frames. Rather
than zero-fill them, `build_replacement` **refuses** the node.

This turns out to cost nothing in scope: every mesh in the character models
checked (`p_hk47`, `p_bastilabb`, `c_bantha`, `c_drdastro`, `3dgui`) uses stride
24, 32 or 64 — that is, `vertex`, `normal`, `uv1`, plus skin data. Only rooms and
placeables carry the rest (`crossgob:Corner09` has `uv2`;
`c_bmspecdiff:RLeg` has `tangent`; `m02aa_01a:Mesh460` has both).

### 4. MDX blocks are 8-byte aligned

All 76,703 vanilla MDX block starts are ≡0 mod 8 — universal, no exceptions.
Block sizes are ≡0 mod 8 except in 53 models where the *final* block ends the
file unaligned. Changing a vertex count therefore has to preserve the block's
size modulo 8, or every later block slides out of alignment. `build_mdx_block`
pads with zeros to maintain it, which is what vanilla itself does (the extra
bytes after a sentinel row are zeros).

This matters for strides ≡4 mod 8 (60, 68, 76, 100), where an odd change in
vertex count would otherwise break alignment.

### 5. MDL arrays have no alignment requirement

Array start offsets are uniformly distributed mod 16, and the corpus has zero
coverage gaps — MDL arrays are packed contiguously with no padding whatsoever.
Growing or shrinking one needs no alignment handling. This retires design risk 3
for the MDL side.

## Status — PASSED, including in-game

48 tests pass; the corpus still parses and validates at 2832/2832.

Per the brief, a successful file build is not proof. Three artifacts are built
for in-game testing, each isolating a different thing:

| Artifact | Node | Change | Tests |
|---|---|---|---|
| `out_m3/bighead` | `head` (unskinned) | scaled 1.35×, same topology | new vertex positions render |
| `out_m3/fathoses` | `TorsoHoses` (skinned) | bulged along normals, same topology | skinned geometry still deforms correctly |
| `out_m3/boxhoses` | `TorsoHoses` (skinned) | replaced by a 24-vertex box, 124→24 verts | weight transfer onto **new topology**, and a **shrink** splice |

`boxhoses` is the strongest test: nothing is inherited by index, so if the box
moves with HK-47's torso the barycentric transfer is genuinely working. It is
also the first *shrinking* splice to be tested in-game (MDL −4,392 B,
MDX −6,400 B); Milestone 2 only exercised a grow.

### In-game results

All three **PASSED** in-game on 2026-08-29.

| Artifact | Result |
|---|---|
| `bighead` | Visibly enlarged head, textured, animating normally. Replacement vertex positions are genuinely read and rendered. |
| `fathoses` | Hoses visibly larger, textured, and moving with the body. Skinned geometry survives a rewrite and still deforms. |
| `boxhoses` | The box moves and flexes with HK-47's torso. Weight transfer onto entirely new topology works, and a shrinking splice loads correctly. |

`boxhoses` is the result that matters. Its 24 vertices share nothing with the
original 124 by index - every one got its bone weights from the closest point on
the original hose surface, interpolated across the containing triangle. The box
tracking his torso is direct engine evidence that the barycentric transfer is
correct, not merely self-consistent.

It also clears the last untested splice direction: Milestone 2 only ever grew a
model in-game, while this shrank it (MDL 4,392 B smaller, MDX 6,400 B smaller).

**Note on `fathoses` appearance.** The hoses rendered as over-inflated wedges
rather than fatter tubes. That was the probe generator, not the pipeline: the
bulge displacement was scaled by the mesh's *largest* extent (0.133 units) while
the hoses are only 0.059 units thick, so every vertex moved more than twice the
mesh's own thickness. Coincident vertices were confirmed to share identical
normals, so nothing tore - the geometry was exactly what was asked for. The
probe now scales displacement by the thinnest axis.

### Not yet established

- **No genuinely foreign mesh has been through the pipeline.** All three probes
  derive their geometry from the mesh being replaced. The pipeline accepts any
  OBJ, but a mesh authored in Blender - with its own scale, axis convention and
  UV layout - has not been tested, and coordinate-space mistakes are the most
  likely first failure for a real user.
- The influence-cap experiment (1/2/4/8) from the brief is only half-answered:
  the census shows vanilla never exceeds 4 and the stride cannot hold a fifth,
  so caps 1/2/4 are supported and testable via `--max-influences`, but whether
  the engine would read a **wider stride** for 8 is untested and would require
  changing the stride itself, which this tool does not do.
- Adjacency is 96.3% faithful, not exact. Whether the difference is visible
  in-game is unknown.
