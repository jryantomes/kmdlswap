# Start here

Written 2026-08-29, end of session. Everything below is committed and green
(77 tests, corpus 2832/2832).

## Where things stand

`kmdlswap` is complete against its brief — all five milestones, definition of
done met in-game. `kmdlfun` adds companion effects and a swap engine on top.

The last session found and bounded a real engine constraint:

> **A skinned head mesh's vertex count cannot change**, or the character's mouth
> and eyebrows stop moving in dialogue. Its vertices can move freely.

`kmdlfun transplant --reshape` works within that and is verified in-game.
Full write-up: `reports/HEAD_ANIMATION_FINDINGS.md`.

## 1. One test still to run (~5 minutes)

### a) ~~Textures~~ — DONE, verified in-game

Carth reshaped onto Dustil's head with Dustil's texture: shape, colouring and
facial animation all correct, skin continuous into the neck, no UV smearing.
**The texture half of a character creator is solved.**

### b) The mechanism probe — still to run

`out_probe2/E_tongue_skinned/p_carthh.mdl` + `.mdx` are built and waiting.

This grows `tongue` — which is **skinned**, like `Head`, but sits at MDX block 24
of 26 rather than last — by 3 unreferenced vertices. `Head` itself is untouched
and byte-identical.

Copy both into `Override/`, talk to Carth, watch his mouth and eyebrows.

| Result | What it means |
|---|---|
| **Animation breaks** | The trigger is resizing *any skinned mesh in a head model*, not the Head specifically. The guard below should widen to all skinned meshes in head models. |
| **Animation works** | The trigger is specific to the `Head` mesh — the one the facial bones actually deform. The guard is correctly scoped as-is. |

Either answer sharpens `HEAD_ANIMATION_FINDINGS.md` from "we know the rule" to
"we know its shape". Nothing else in the project is blocked on it.

## 2. Texture swapping — what is now known and built

- A texture reference is a **fixed 32-byte field** in the trimesh header at
  `+88` (`+120` is the lightmap, empty on characters). Changing it is a patch in
  place: nothing moves, no offset needs fixing. Far safer than geometry.
- **All meshes in a head model share one texture** (`P_CarthH01`,
  `N_DustilH01`), so it is one decision per model, not per node.
- Head textures live in `swpc_tex_tpa`, not `chitin.key` — all four checked
  resolve there.
- `snap_to_surface` already computed barycentric coordinates on the donor
  surface and discarded them. It now uses them to interpolate the **donor's UV**
  where each host vertex lands, which is what makes a donor texture usable with
  host topology.

`kmdlfun transplant --with-texture` does all of it (and implies `--reshape`).
Verified on file: vertex count, faces and per-vertex weights byte-identical to
vanilla, file sizes unchanged, UVs replaced, texture field now `N_DustilH01`.

### Known limitation: nodes the donor does not have

`n_dustilh` has no `hair` node, so Carth's hair was left untouched — still shaped
for Carth's skull and still using `P_CarthH01` while the head around it became
Dustil's shape and `N_DustilH01`. In-game it reads as wrong hair, and it is the
one visible flaw in an otherwise correct swap.

This is inherent to node-matched swapping rather than a bug: only nodes the host
already has can be filled, and the hierarchy is never touched, so a node the
donor lacks cannot be removed or hidden. `transplant` now lists these before
writing:

```
  left as p_carthh's own: hair
  (n_dustilh has no node of that name. These keep their original
   shape and texture, so they may not sit right on the new head.)
```

**Solved with `--hide-unmatched`.** Byte 313 of the trimesh subheader is the
render flag, and vanilla clears it on 18,058 of its 76,767 mesh nodes - it is how
a body carries invisible `_g` skeleton boxes. Clearing it on an unmatched node
tells the engine not to draw it: a **one-byte patch**, no geometry change, no
vertex count change, hierarchy untouched. Verified on file: exactly one byte
differs, sizes identical, visible meshes 9 -> 8.

`out_swap/carth_dustil_full/` (Dustil's head, Dustil's texture, hair hidden) is
in Override for test (a).

Still worth considering: preferring donors whose node set already covers the
host's, which the catalogue knows how to answer.

### Still open on textures

- **Body models use several textures** (`n_rodian` has `N_Rodian01` on the head
  and `N_Rodian02` on torso and arms), so a body swap needs per-node texture
  decisions rather than one per model.
- **Nothing copies the texture file itself.** The swap points at a texture that
  already ships with the game. Using a *custom* texture means writing a TPC/TGA
  into Override alongside the model, which this tool does not do.
- **Skin tone and lighting will not match** across donors, so a head from one
  character on another's body can show a seam at the neck.

## 3. Guard rail added

`transplant` now **refuses** to change a head model's skinned vertex count and
points at `--reshape`:

```
Head <- Head   REFUSED: 'Head' is a skinned mesh in a head model and the donor
has 562 vertices rather than 565. Changing a head's vertex count stops the mouth
and eyebrows moving in-game. Use --reshape to keep the host's topology and move
its vertices onto the donor's surface instead.
```

Scoped to head models deliberately: body meshes are unaffected — HK-47's
`TorsoHoses` went 124 → 24 vertices and still animated. Probe E may widen this.

## 4. Open work, roughly in order of value

- **Expose `transplant` in the GUI.** It is CLI-only. The parts-bin artifact
  (https://claude.ai/code/artifact/cdc78304-bbe2-4fc4-a7e5-fae58f0bcf28) shows
  what is swappable; the GUI should let you pick host + donor + parts and build.
- **Verify the five `kmdlfun` effects in-game.** Only `bighead` on HK-47 has ever
  been checked. `chibi` is expected to show joint gaps and says so, but nobody
  has looked. Note the pivot rework in `space.py` landed after the last builds in
  `out_fun/`, so rebuild before testing.
- **A foreign mesh into a *skinned* node.** Still the largest untested path:
  HK-47's head is unskinned, so weight transfer from genuinely authored geometry
  is proven only by the synthetic box probe.
- **Repo hygiene.** `out_fun/` binaries were committed by an early `git add -A`
  of mine — 80+ model files that should be gitignored like `out_m3/` and
  `out_fbx/`. Needs `git rm --cached` plus a `.gitignore` line.
- **Retire `tools/roundtrip_eval.py` and `tools/diff_anatomy.py`.** They existed
  only to evaluate PyKotor and inform nothing now.

## 5. Housekeeping

Still in `Override/` from testing:

- `p_carthh` — Carth reshaped onto Dustil's head, with Dustil's texture (test a)
- `p_bastilabb` — Bastila's cap-1 armor body

Both are safe to delete; vanilla lives in the BIFs. **`p_hkrfk.mdl`/`.mdx` are
yours** (HK recruit mod, June) and have not been touched all session — do not
delete those.

## 6. What is genuinely unknown

Why a head's vertex count matters. Every candidate the file exposes was measured
and eliminated: bone slots, weight distribution and its spatial fidelity, MDX
values, the whole skin subheader, `mdx_data_buffer_offset`, the geometry-header
unknowns, and the model header. The engine depends on something not visible in
the format as this project understands it. `--reshape` is a workaround, not a
fix.
