# kmdlswap

A scoped tool that replaces the geometry of a single mesh node inside a vanilla
KOTOR 1 model, leaving everything else byte-identical. **Not a character creator.**

See [`MDL_SWAP_TOOL_BRIEF.md`](MDL_SWAP_TOOL_BRIEF.md) for the full project brief.

## Status

| Milestone | State |
|-----------|-------|
| 0 — Byte-exact MDL/MDX round-trip | **Done — 2832/2832 (100%)** of vanilla K1 models. |
| 1 — Inspect | **Done** — `kmdlswap inspect` |
| 2 — No-op swap | **Done — 76,703/76,703 mesh nodes, and verified in-game.** |
| 3 — Geometry replacement | **Done — verified in-game, including a foreign FBX mesh.** |
| 4 — CLI | **Done** — `inspect`, `extract`, `replace` |

### Milestone 0 result

Our parser accounts for **every byte** of all 2,832 MDL/MDX pairs in the vanilla
install: full span coverage, no overlaps, every stored pointer resolving to a
span boundary of the expected kind, and byte-identical re-emission — in 12
seconds. (PyKotor: 0/2832 in 607s.)

```bash
.venv/Scripts/python tools/corpus_check.py --install "E:\SteamLibrary\steamapps\common\swkotor"
.venv/Scripts/python -m pytest -q          # fast checks
.venv/Scripts/python -m pytest -q -m slow  # full-corpus sweep
```

### Milestone 1 — inspect

```bash
.venv/Scripts/kmdlswap inspect p_hk47 --install "E:\SteamLibrary\steamapps\common\swkotor"
```

Reports the node tree with exact casing and parent paths, per-node vertex/face
counts, which meshes are skinned and which bones they reference, observed
influences per vertex, supermodel, and bounding box. Exits non-zero with a
warning if the model does not fully validate — a model we cannot account for is
one we must not edit.

### Milestone 2 — no-op swap

Every mesh node's geometry is extracted to decoded components, the arrays are
**rebuilt from those components**, spliced back, and the model byte-diffed. All
**76,703 mesh nodes** across the corpus come back byte-identical, and every
result re-validates. Resize (shrink/grow) tests cover the splice's offset-fixup
logic, which a no-op never exercises.

```bash
.venv/Scripts/python tools/noop_swap_sweep.py --install "<K1 root>"
```

**Verified in-game.** A no-op output is byte-identical to vanilla, so loading it
would only test the Override mechanism. The informative test is a *resize probe*:
a mesh padded with inert duplicate vertices no face references, so nothing
visible changes but both files grow and every pointer past the splice must be
rewritten.

```bash
.venv/Scripts/python tools/write_resize_probe.py --install "<K1 root>" --model p_hk47 --node head --out out_probe/
```

For `p_hk47:head` that moves ~494 stored pointers (MDL +768 B, MDX +2,048 B).
Loaded into `Override/`, HK-47 rendered and animated correctly — idle, walk and
head turn all confirmed. Findings:
[`reports/MILESTONE_2_FINDINGS.md`](reports/MILESTONE_2_FINDINGS.md).

### Milestone 3 — geometry replacement

```bash
.venv/Scripts/kmdlswap extract p_hk47 --install "<K1 root>" --node head --out head.obj
.venv/Scripts/kmdlswap replace p_hk47 --install "<K1 root>" --node head --mesh head.obj --out out/
```

`replace` inherits skin weights from the mesh being replaced (closest point on
the source surface, barycentric interpolation), rebuilds face adjacency, and
re-validates the result before writing. `extract -> OBJ -> replace` reproduces
the **entire MDX byte-for-byte**, transferred skin weights included; the only
MDL change is inside the target node's face array.

Meshes carrying MDX columns an OBJ cannot express - a second UV set, vertex
colours, tangent frames - are **refused** rather than zero-filled. No character
model carries them; only rooms and placeables do.

**Verified in-game.** Three probes on `p_hk47`, all passing: a head scaled 135%
(new positions render), a skinned node deformed (skinned geometry still flexes),
and a skinned node replaced by a 24-vertex box, down from 124 (weight transfer
onto entirely new topology, plus a shrinking splice). The box moves with HK-47's
torso, which is the evidence that matters: none of its vertices inherited weights
by index.

**Definition of done, met.** A Tripo-generated character auto-rigged with Mixamo
was carved down to its head, decimated to 1,198 triangles, fitted and rotated
into HK-47's `head` node — and renders correctly in-game, forward-facing, with
his body untouched.

Findings: [`reports/MILESTONE_3_FINDINGS.md`](reports/MILESTONE_3_FINDINGS.md)
and [`reports/FOREIGN_MESH_FINDINGS.md`](reports/FOREIGN_MESH_FINDINGS.md) — the
latter is the important one for anyone bringing in outside geometry, because
**every mistake on that path is silent**: world-space export, a surviving
armature modifier, a node origin that is not the geometry centre, and a differing
axis convention each produced a model that passed every validator and was still
wrong.

## kmdlfun — companion effects app

A separate, playful tool built on the kmdlswap engine. Every edit goes through
the same validated splice path, so the same coverage, offset-closure and
identity checks guard these as guard a real geometry swap.

```bash
kmdlfun effects                 # list effects
kmdlfun companions              # list companions and their models
kmdlfun preview --install "<K1 root>" --companion hk47 --effect bighead
kmdlfun build   --install "<K1 root>" --effect bighead --companion all --out out_fun/
kmdlfun build   --install "<K1 root>" --effect bighead --companion all --out out/                 --pivot bounds  # the old per-node pivot, kept for comparison
kmdlfun gui                     # Tkinter desktop app (no extra dependencies)
kmdlfun render p_hk47 --install "<K1 root>" --highlight head --out shot.png
kmdlfun render p_hk47 --install "<K1 root>" --compare out/p_hk47.mdl --out before_after.png
```

Effects: **bighead**, **smallhead**, **bobblehead**, **chibi**, **bigmitts** —
each a uniform scale of a part, with an adjustable intensity.

Four things the models forced:

- **Human companions keep their head in a separate model** (`p_carthh`), which
  holds hair, teeth, eyes, brows and tongue as *separate nodes*. Scaling only
  the node called `head` would leave the hair and eyes at original size, so a
  head model scales entirely, minus the neck that joins the body. Their body
  models carry a small `head_g` stub that is deliberately left alone.
- **A part must grow about one point, not one point per node.** Scaling each
  node about its own centre pins every centre where it was, so a ten-node head
  comes apart as it grows: the face skin swallows the eyeballs and the skullcap
  sinks into the skull. Parts now scale about the joint they hang from, read
  from the skeleton (`head_g`), and every distance inside the head scales with
  it. In-game this was "the eyes seem non-existent" and "her headband has gone
  see-through"; measured, it was 11.8% of the eyeball showing through the socket
  in vanilla and **0%** after the effect.
- **Most meshes in a model are not drawn.** Byte 313 of the trimesh subheader is
  a render flag, and 18,058 of the 76,767 vanilla mesh nodes have it clear — a
  human body draws exactly three meshes (`torso`, `LArm`, `RArm`) and carries
  forty-odd invisible `_g` boxes that are the skeleton. Effects target visible
  meshes only, so `bigmitts` on a human now says *nothing matches* instead of
  reporting 42 changed nodes and looking identical.
- **Node names are not unique** — T3-M4 has two nodes called `FootL` — so
  everything addresses nodes by index, never by name.

Node *positions* live in headers kmdlswap never touches, so only geometry inside
a node can scale. That ceiling is real: `chibi` cannot shorten a character,
because height is where the bones are, and its shrunken limbs still swing about
joints they are no longer near. Heads and extremities work well; whole-body
proportions need the rig to scale with the mesh.

### Previewer

The app has a **Preview** tab, and `kmdlfun render` does the same thing from the
command line. It draws the posed model straight out of MDL/MDX bytes, so
previewing a build is a check on the output rather than a re-display of the
input mesh.

It is a software rasteriser in numpy, not Blender. `tools/render_catalogue.py`
still shells out to Blender and should: for 164 models the several seconds of
start-up cost amortise away. For one model they do not, and a preview you have
to wait for is a preview you stop using. A full HK-47 body is 2,467 triangles
and draws in about 76 ms, which is fast enough to drag with the mouse.

The **comparison** is the part that earns it. A single untextured render tells
you little — vanilla heads look strange without their texture too. Vanilla drawn
beside your build, framed by one shared ruler, shows at a glance whether a head
landed at the right size and in the right place. Its first real use showed the
decimated Tripo head sitting noticeably smaller than HK-47's own, which had
previously taken a trip into the game to notice.

Two conventions are pinned by tests because they fail silently by eye. The
camera sits on -Y looking towards +Y, since KOTOR characters face -Y — invert it
and every head preview shows the back of the skull and still looks plausible.
And a before-and-after must share one framing, or a head that changed size looks
unchanged. There is no backface culling and lighting is two-sided, because the
head spec tolerates 5% of faces winding against their normals and culling by
winding would punch holes in meshes we accept.

It draws geometry only: no texture, no animation. So it says nothing about the
one failure this project knows is real — that a skinned head's vertex count must
not change. A preview is not proof either.

Findings and measurements:
[`reports/KMDLFUN_PIVOT_FINDINGS.md`](reports/KMDLFUN_PIVOT_FINDINGS.md).

### Skinning census

A corpus-wide measurement of vanilla's skinning behaviour lives in
[`reports/SKINNING_FINDINGS.md`](reports/SKINNING_FINDINGS.md). Headlines: no
vanilla vertex exceeds **4** influences; weights are **always** normalised; the
skin subheader's 16-slot bone table is **not** the per-mesh limit (21 meshes use
17 bones) and its unused entries are garbage — the bonemap is the authority.

## Setup

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e .
```

Requires Python 3.11+, a vanilla K1 install (used as both test corpus and oracle).
This machine's install: `E:\SteamLibrary\steamapps\common\swkotor`.

## Milestone 0 harness

```bash
# Round-trip every MDL/MDX pair in the install and byte-diff:
.venv/Scripts/python tools/roundtrip_eval.py --install "E:\SteamLibrary\steamapps\common\swkotor"

# Characterise where a single model's round-trip diverges:
.venv/Scripts/python tools/diff_anatomy.py --install "<install>" --name p_hk47
```

## Key finding — PyKotor round-trip

PyKotor 2.3.12's `MDLBinaryReader`/`MDLBinaryWriter` perform a **lossy semantic
reconstruction**, not a faithful round-trip. Against the full vanilla K1 corpus:

- **0 / 2,832** models re-emit byte-identically (44 also fail to read at all).
- p_hk47: MDL shrinks 948 bytes, **85,695** distinct diff runs across the file
  (recomputed offsets, dropped/zeroed float regions, reordered node data).

Full write-up: [`reports/MILESTONE_0_FINDINGS.md`](reports/MILESTONE_0_FINDINGS.md).

This is too much loss to fix with offset patches. Milestone 0 needs a
**byte-surgical** reader/writer of our own: parse only enough structure to locate
the target mesh node's arrays, splice, and fix up the offsets/counts/sizes that
actually changed — everything else passes through as raw original bytes. An
unmodified round-trip is then identity by construction.

PyKotor remains useful as a format reference and cross-check oracle.

Design & implementation plan: [`docs/BYTE_SURGICAL_DESIGN.md`](docs/BYTE_SURGICAL_DESIGN.md).
