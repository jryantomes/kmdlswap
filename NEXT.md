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

## 1. Tests: all run

Probe E is done. Growing `tongue` - skinned, but not the mesh the facial bones
deform and not the last MDX block - broke facial animation, while growing the
unskinned `hair` did not. **The discriminator is skinning**, so the guard's
existing scope (any skinned mesh in a head model) was already right.

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
- ~~**Nothing copies the texture file itself.**~~ **SOLVED.** A custom texture
  dropped into `Override/` as an uncompressed TGA and referenced by name loads
  and maps correctly - verified on HK-47 with Tripo's 4096x4096 atlas resized to
  512x512. No V-flip was needed. See `reports/CUSTOM_TEXTURE_FINDINGS.md`.
  `kmdlswap replace --texture <resref>` sets the field; the `.tga` ships beside
  the model.
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

- ~~**Expose `transplant` in the GUI.**~~ **DONE.** The app is now two tabs -
  Effects and Transplant - sharing the folder settings, log and build button.
  The Transplant tab has host/donor pickers populated by *Scan install*, the
  four options (reshape, donor texture, hide unmatched, fit), and a **Preview**
  that reports matches, fit ratios and what the donor lacks without writing
  anything. Its worker logic is exercised headlessly as well, so the path is not
  only tested by clicking it.
- **Verify the five effects in-game.** All five are rebuilt in `out_fun/` with
  the current pivot code and validate. Only `bighead` on HK-47 has ever been
  seen in-game. Two things to know before testing:
  - Node counts are much lower than the old builds (`bighead` 66 rather than
    170) because effects now target *visible* meshes only. That is the render
    flag working, not a regression.
  - `bigmitts` writes only 2 models. A human body draws its hands as part of the
    torso and arm meshes, so there is no hand node to scale - only droids have
    one. The preset says so, and the build now matches the caution.
  - `chibi` is the one expected to look wrong: shrinking a body cannot shorten
    the character, because height is in the bones.
- ~~**Auto decimation.**~~ **DONE.** `kmdlfun head --decimate [N]` reduces an
  over-budget mesh instead of rejecting it (quadric error edge collapse, default
  budget 690). Density was the only rejection the tool could fix on its own, so
  it now does. The real Tripo head goes 3312 -> 690 and comes out ACCEPTED with
  zero warnings; without the flag it is rejected, and the message names the
  flag. Design notes in `docs/CUSTOM_HEAD_SPEC.md`.
- ~~**Texture preview.**~~ **DONE.** `--textured` / the Textured checkbox.
  Resolves in the engine's order (loose beats packed, caller's folders beat
  both), so a custom head's own `.tga` shows before it is installed. It found
  that **every render this project had made was of the back of the head**:
  characters face +Y, not -Y. Fixed in both renderers;
  `reports/FACING_FINDINGS.md` has the evidence and why the earlier check
  failed to catch it.
- ~~**A previewer in the app.**~~ **DONE.** Preview tab plus `kmdlfun render`.
  numpy software rasteriser (`src/kmdlfun/render.py`), Tk widget in
  `viewport.py`. Draws the posed model out of MDL/MDX bytes, so it checks the
  output. Vanilla-vs-build side by side with shared framing is the useful mode.
  Geometry only - no texture, no animation, so it cannot see the facial-animation
  failure. Camera convention and shared framing are pinned by tests; both fail
  silently by eye.
- **Regenerate the catalogue.** Every image in it shows the back of the
  character's head - see below. `python tools/render_catalogue.py --install
  "<K1 root>"` with the fixed camera.
- **A foreign mesh into a *skinned* node.** Still the largest untested path.
  HK-47's head is unskinned, so weight transfer from genuinely authored geometry
  is proven only by the synthetic box probe. Needs a mesh.
- ~~**Repo hygiene.**~~ **DONE.** `out_fun/`, `out_caps/`, `out_tripo/` and
  `out_probe2/` are untracked and ignored; zero binaries are tracked now.
- ~~**Retire the PyKotor harnesses.**~~ **DONE.** Moved to `tools/legacy/` rather
  than deleted - they are the evidence behind the decision to write our own
  reader, and that is worth keeping re-runnable.

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
