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

## kmdlfun — the app

Built on the kmdlswap engine. Every edit goes through the same validated splice
path, so the same coverage, offset-closure and identity checks guard these as
guard a real geometry swap. Nothing here writes into the game except one
explicit action on the Builds tab.

```bash
kmdlfun gui                     # the desktop app; no extra dependencies

kmdlfun effects                 # list effects
kmdlfun companions              # list companions and their models
kmdlfun preview   --install "<K1>" --companion hk47 --effect bighead
kmdlfun build     --install "<K1>" --effect bighead --companion all --out out_fun/

kmdlfun transplant --install "<K1>" --host p_carthh --donor n_dustilh --out out_fun/
kmdlfun rank       --install "<K1>" --host p_carthh --who female --notes
kmdlfun head       packs/myhead --install "<K1>" --host p_hk47 --node head --decimate --fit
kmdlfun import     model.glb --out packs/myhead
kmdlfun builds     --out out_fun/ --verify
kmdlfun render     p_hk47 --install "<K1>" --textured --turntable 24 --out spin.png
```

### The app

**Basic and advanced.** The window opens in basic mode, which hides the parts
that assume you already know the format: the Transplant tab, which asks for a
host, a donor and two node names, and the per-build options for decimation,
cropping, winding repair and reshaping. What is left is the path a new modder
wants — pick a body, a wardrobe and a head, or bring one in from a `.glb` or
from Jade Empire, and build it. `Settings ▸ Mode ▸ Advanced` shows everything,
and the choice is remembered. Nothing is switched off by hiding it; the
defaults behind those controls are the ones the app relies on anyway.

Seven tabs sharing the log and build button. The folders live behind
**Settings** rather than on screen: the app finds the games itself at startup, from
Windows' own record of what is installed — uninstall entries, GOG Galaxy's
list, Epic's manifests and the `BioWare\SW\KOTOR` key the retail disc still
writes — then Steam's library index, then, on request, a walk of every drive.
Nothing is trusted by name: every candidate is checked for the right
executable, so a Steam install, a GOG one and a folder copied off an old
machine all resolve the same way. What is left at the top is one line saying which games it
found, and it says so by name rather than by path.

**Effects** — **bighead**, **smallhead**, **bobblehead**, **chibi**,
**bigmitts**, each a uniform scale of a part with an adjustable intensity,
previewed as a whole character rather than a headless body.

**Transplant** — geometry from one model into another. The donor list shows
**faces rather than names**, because `n_shaardanh` and `n_lashoweh` are both
clean fits on Carth and one of them is the one you meant. It can be sorted by
measured fit, filtered to male / female / droid, pointed at KOTOR 2, and aimed
at a **single named node** when whole-model pairing finds nothing — which is
what a unified body like HK-47 always did, since it shares exactly one node name
with any head model.

It also decides what a new character *wears*. An appearance row carries a body
model per equipment slot and the game uses the unequipped one, which on a party
member's row is their underwear — so a character copied from Carth and given no
clothes spawns in `P_CarthBA`. Vanilla NPCs sidestep this by repeating one body
across all nine slots, and the **Wearing** box offers the 117 outfits the game
already dresses somebody in.

**Character** — a body, a wardrobe and a head, each picked from its own grid of
thumbnails. Nothing here writes geometry: a KOTOR humanoid is a base body, a
clothed body per equipment slot and a row of `heads.2da`, so a new character is
two table rows and a blueprint. 30 bodies, 117 outfits and 106 heads, and the
pairings are read rather than guessed — every `modeltype B` row names both a
`race` and a `normalhead`, so the tool can say which combinations the game
already ships while still offering the ones it does not.

The triangle budget follows the pack rather than a fixed default: a mesh
already inside what the game ships is not reduced. Decimating a 1100-triangle
head to 690 leaves the texture correct and the surface too coarse to carry it,
which looks like a texture fault and is not one.

**Custom head** — a mesh from outside the game into one node, with decimation,
fitting, winding repair and cropping. A pack is checked before anything is
built, and a failure names the check. **Import .glb** turns a sculpt, a scan or
a Blender export into a pack and selects it, so anything that can reach glTF
can reach KOTOR. A `.glb` arrives with glTF's declared Y-up and `+y` facing,
which is usually right and sometimes not: whether a head is upright and which
way it looks cannot be read off its geometry, so the Preview tab is where a
wrong one is caught and the pack's manifest is where it is corrected. **From
Jade Empire** does the same for that game's own models
— 158 heads and 112 bodies, picked from a grid of faces, rotated upright and
scaled on the way in.

**Lips** — a `.lip` for every line of a dialogue, so an NPC nobody recorded
still moves its mouth while the subtitle is up. Shapes come from the line's own
text; point it at a folder of recordings and each lip is made exactly as long
as its own line. Your dialogue is never edited — lines that need a `VO_ResRef`
get one in a copy written beside the lips.

**Preview** — draws the result out of the built MDL/MDX bytes, so it checks the
output rather than re-displaying the input. A head model is drawn **on its
body**, before and after at one shared scale.

**Builds** — named, kept folders with a manifest recording what went in, so a
good result can be reproduced. Installing points at one of these.

### Jade Empire

Jade runs on the same engine lineage and shares almost nothing about its file
layout: a 60-byte node header against KOTOR's 80, 28-byte faces against 32,
controllers moved out of the node entirely. The splice engine will never touch
a Jade model, and there is no reason it should — what Jade has that KOTOR does
not is *geometry*, and geometry already had a route in.

So a Jade head becomes a head pack, and from there it is the ordinary path:
decimation, winding repair, the solidity check, the weight transfer. Reading
the format is [somebody else's code](src/kmdlfun/vendor/jade/), vendored from
JadeBlender under the GPL; everything on top of it is in `kmdlfun/jade.py`.

Three corrections happen on the way in, none of them guessable from the
numbers and all three settled by rendering: a Jade model's height runs along X
where KOTOR's runs along Z, its V texture axis runs the opposite way to ours,
and Jade models are about a sixth larger. Textures come too — a mesh names a
material by number, the material names the texture, and the `.txb` is decoded
into the pack. None of it has been in front of the engine yet; see
[reports/JADE_FINDINGS.md](reports/JADE_FINDINGS.md).

Creating *characters* is still KOTOR only. Jade is a source of parts.

### What the models forced

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

It is a software rasteriser in numpy, not Blender. A full HK-47 body is 2,467
triangles and draws in about 76 ms, which is fast enough to drag with the mouse
- and a preview you have to wait for is a preview you stop using.
`tools/render_catalogue.py` used to shell out to Blender and no longer does:
every image it had produced was of the back of someone's head, so they all had
to be redrawn anyway, and redoing them through a second camera convention that
no test covers would have been a strange way to fix a camera bug. It now draws
all 233 models in about a minute with the same renderer the app uses.

The **comparison** is the part that earns it. A single untextured render tells
you little — vanilla heads look strange without their texture too. Vanilla drawn
beside your build, framed by one shared ruler, shows at a glance whether a head
landed at the right size and in the right place. Its first real use showed the
decimated Tripo head sitting noticeably smaller than HK-47's own, which had
previously taken a trip into the game to notice.

`--textured` paints each mesh with the texture its own header names, resolved
in the engine's order: loose files beat packed ones, so a custom head's `.tga`
wins exactly as it does in Override, and a folder passed in wins over both so a
head can be previewed before it is installed anywhere. TPC decoding is
PyKotor's — unlike its MDL reader it is trustworthy here, the format being a
header and a pixel block. Texturing is affine in the barycentrics with no
perspective correction, which is exact rather than approximate under an
orthographic projection.

**Turning textures on immediately found a real bug: every render this project
had ever made was of the back of the character's head.** The `-Y` facing
inherited from `blender_render.py` had the sign backwards, and an untextured
low-poly head looks equally plausible from either side, so nothing had
contradicted it — including a marker check that felt like verification and
wasn't. Settled two ways and now fixed in both renderers:
[`reports/FACING_FINDINGS.md`](reports/FACING_FINDINGS.md).

Conventions pinned by tests, because each fails silently by eye: characters face
**+Y**, verified from the position of every eye, teeth and tongue node rather
than from a texture; and a before-and-after must share one framing, or a head
that changed size looks unchanged.

Backface culling is **off by default and available**, which is the right way
round for two different jobs. Two-sided drawing is kinder to a preview, since
the head spec tolerates 5% of faces winding against their normals and culling
those would punch holes in meshes we accept. But the engine draws front faces
only, so a mesh that folds back on itself renders full of holes in game and
looks perfect two-sided - which is why the catalogue and the solidity check
both cull, and why solidity is reported as a number rather than trusted to the
eye.

The V axis runs down the image with no flip. That one rests on visual
inspection: no cheap automated check separates the two conventions on real
data — a head's UV islands are too uniform for mean texel colour to tell them
apart, which was measured rather than assumed — so the test pins the sampler
and the docstring records how the orientation was actually established.

There is still no animation, no lightmap and no transparency, so a preview
cannot see the failures that only appear once a model moves or is lit: whether
facial animation survives, and whether a reverse-engineered tangent basis lights
the right way round. A preview is not proof. [TESTING.md](TESTING.md) is the
list of what still has to be watched in the game itself.

(This paragraph used to end "the one failure this project knows is real — that
a skinned head's vertex count must not change". That rule was wrong; it was a
node pointer at model header `+168` our writer never relocated. See
[`reports/SKIN_ROOT_POINTER_FINDINGS.md`](reports/SKIN_ROOT_POINTER_FINDINGS.md).)

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

## A standalone build

```
python tools/build_app.py
```

Produces `dist/kmdlfun/` — about 77 MB, 35 MB zipped — which runs on a Windows
machine with no Python on it at all. Zip the folder and hand it over; there is
nothing to install.

It is a folder rather than a single `.exe` deliberately. A one-file build
unpacks itself into a temporary directory on every launch, and with numpy and
Tk inside that is several seconds of nothing visible happening, which reads as
a hang and would be the first thing anybody reported as a bug.

The size is almost entirely other people's libraries: numpy and its BLAS, then
Pillow, then pykotor — which is the one out of proportion to its use, since it
is there for four file formats (2DA, GFF, LIP, TPC) and brings five transitive
packages with it. Replacing it with readers of our own is the only real way to
make this smaller, and everything else in the bundle is load-bearing.

`kmdlfun.exe --selftest` exercises every bundled dependency and writes the
result beside the executable. That check matters more than it sounds: a bundled
app fails at *runtime*, not at build time, because anything resolved by name
rather than imported by name is invisible to the bundler — and pykotor picks
its format readers by resource type. The build script runs it automatically and
refuses a build that starts but cannot work.

## Licence

GPL-3.0-or-later. The full text is in `LICENSE`.

The choice is deliberate rather than incidental. The nearest prior art for this
work — KotorBlender and the JadeBlender fork that reads Jade Empire models — is
GPL, and matching it means their code can be borrowed rather than only their
findings. File-format facts are not copyrightable and were never the
constraint; being able to lift an implementation is.

None of that touches the game's own data. This repository carries no BioWare
assets, and a build's output is yours and stays on your disk.
