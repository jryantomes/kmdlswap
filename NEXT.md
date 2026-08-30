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

## 1. One 5-minute test, ready to run

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

## 2. Guard rail added

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

## 3. Open work, roughly in order of value

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

## 4. Housekeeping

Still in `Override/` from testing:

- `p_carthh` — Carth with the reshaped Rodian head
- `p_bastilabb` — Bastila's cap-1 armor body

Both are safe to delete; vanilla lives in the BIFs. **`p_hkrfk.mdl`/`.mdx` are
yours** (HK recruit mod, June) and have not been touched all session — do not
delete those.

## 5. What is genuinely unknown

Why a head's vertex count matters. Every candidate the file exposes was measured
and eliminated: bone slots, weight distribution and its spatial fidelity, MDX
values, the whole skin subheader, `mdx_data_buffer_offset`, the geometry-header
unknowns, and the model header. The engine depends on something not visible in
the format as this project understands it. `--reshape` is a workaround, not a
fix.
