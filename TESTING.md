# Testing owed

Everything here has been built and passes its tests, and none of it has been
watched by a person. Two kinds of thing are on the list and they fail
differently:

* **In the game** - a build that validates is not a build that works. Lighting,
  facial animation and whether a head sits on a neck are exactly what a
  validator cannot check.
* **In the app** - the tests drive the widgets headlessly, which proves the
  wiring and says nothing about whether the thing is usable: how it looks, how
  long it makes you wait, whether the layout survives your window size.

Copy a build's `.mdl`/`.mdx` into `Override/`, load a save, and look. Delete
them afterwards; vanilla lives in the BIFs.

**Never delete these from Override.** They are the HK recruit mod, not ours:
`p_hkrfk.*`, `hkrfkjr.*`, `c_rfk_hk47.*`, `po_phkrfk.tpc`, `recruit_hkrfkjr.*`,
and anything matching `rfk_*`, `c_rfk_*`, `q_rfk_*`.

---

# Part one: in the game

## 1. Tangent lighting — tested 2026-09-02, and the risk was overstated

**Result: three destructive perturbations, nothing visible.** Not the
confirmation that was expected, and a more useful answer than one would have
been.

| what was installed | what changed on screen |
|---|---|
| every tangent negated | nothing |
| every tangent replaced with one constant direction | nothing |
| the bump map declaration removed from the texture | nothing anyone could call |

Vanilla `n_selkath`, vanilla geometry, one variable at a time. If our tangent
values were capable of looking wrong in game, *destroying* them would have
looked wrong.

The engine is not indifferent to bump mapping — it validated a hand-made bump
texture and refused it by name, `"Invalid Bumpmap!"` — so it has a live path
that reads those textures. The likeliest reading is that it derives its own
tangent basis and never reads the MDX column.

**What this settles.** Filling the column is not a risk. The values agree
positively with BioWare's at better than +0.8, the stride and headers are
untouched, and the 21 tangent-carrying heads stay reachable. The claim that a
flipped tangent "renders wrongly in game" was inherited from the reverse
engineering, never tested, and is not supported.

**What it does not settle.** Whether bump mapping reaches the screen at all on
this machine — a 2003 effect on a modern GPU. The `.txi` control that would
have answered it was inconclusive by eye, and the pixel comparison failed
because the dialogue camera moves between takes: 47–52% of pixels differ
between *every* pair of screenshots, including two we know look identical. A
conclusive version needs a fixed camera and a model with dramatic bump detail,
and is low value now the practical question is answered.

**The kit is kept** in `out_tangent_test/`; `tools/flip_tangents.py --mode
flip|wreck` rebuilds it for any model.

- [ ] *Optional, low priority.* If a Selkath ever looks wrong in normal play,
      that is the signal this testing could not produce, and worth reopening.

## 2. The heads that were unreachable until now

Eleven K1 and ten K2 heads were refused outright before this session.

```bash
kmdlfun transplant --install "<K1>" --host p_carthh --donor twilek_m --out out_fun/
```

- [ ] **`twilek_m` onto Carth.** Measured clean at 0.2% with its own weights,
      so this should be near-perfect. Check the head turns and the mouth moves.
- [ ] **`n_selkath` onto Carth** — 4.8%, needs `--fit`, brings six extra parts
      (eyes, lids, teeth). Check the eyes land in the sockets.

## 3. Heads onto a unified body (HK-47)

New this session: naming a single host node instead of pairing whole models.

- [ ] **Carth's head into `p_hk47:head`.** Built and validating. Check the
      **droid body is still there** - if HK-47 is a floating head, the
      hide-suppression regressed.
- [ ] Does the head animate with the droid's own animations, or sit rigid?
      Either is informative; HK-47's head node is unskinned, so rigid is the
      expected answer.

## 4. Custom head packs from the app

The Custom head tab is new; the underlying path is the one that put a Tripo
head on HK-47 months ago, so this is checking the tab rather than the format.

- [ ] Build a pack onto `p_hk47` from the app and load it.
- [ ] Build one onto a **skinned** host (`p_carthh`) and check the face still
      animates.

## 5. The 42 heads the app could not see

Player-creation and commoner heads have never been built as donors by this
tool, because until this session they were not offered.

- [ ] **`pfhc01` or `pmhc01` onto a companion.** These pair whole-model at
      seven parts, so they should be the *easiest* swaps in the game. If one of
      these looks wrong, something systematic is wrong.
- [ ] A `comm_*` head, which are lower-detail and may sit differently.

## 6. Body swaps

New, and never seen running. A body host now offers body donors, and arms
transfer where only the torso used to.

```bash
kmdlfun transplant --install "<K1>" --host p_carthbb --donor p_bastilabb --out out_fun/
```

- [ ] **Bastila's outfit on Carth.** Torso and both arms should move. In the
      preview the arms sit on the shoulders; the thing to check in game is that
      they still do once the character *animates*, since nothing offline poses
      the model.
- [ ] Watch for **left and right**. Aliasing pairs `LArm` with `ArmL`, and the
      failure mode if that ever goes wrong is a mirrored arm - elbows bending
      the wrong way - which reads as a broken rig rather than a naming bug.
- [ ] The torso solidity warning is real: Bastila's outfit reports 70%, below
      the 77% floor, so expect some see-through around the thin flaps.

## 7. KOTOR 2 donors

Partly proven - the Quarren works - but only that one.

- [ ] A K2 head with its own weights (`n_duros`, `n_wookiem`) onto a K1 host.
- [ ] A K2 head needing `--fit` (`c_ithorian`, 1.7x).

## 8. Older work still unverified

From `NEXT.md`, predating this session:

- [ ] **The five effects.** Only `bighead` on HK-47 has ever been seen running.
      `chibi` is expected to look wrong - shrinking a body cannot shorten a
      character, since height lives in the bones - so confirming that is
      confirming the caution is honest.
- [ ] `bigmitts` writes only two models. A human draws hands as part of the
      torso and arm meshes, so only droids have a hand node to scale.

---

# Part two: in the app

Faster to check and worth doing first, since a broken list makes the in-game
tests harder to set up.

## 9. The donor list of faces

Brand new, and already revised twice from your feedback: the faces were being
clipped to a fifth of their height by a Treeview row, and a list of them showed
four at a time out of a hundred and forty-four. It is a grid now.

Open the Transplant tab and pick a host.

- [ ] Faces appear beside the names. **The first time is slow** - about a third
      of a second per face, so a list of 144 takes the better part of a minute,
      arriving gradually. After that it is instant, from a cache in
      `~/.kmdlfun/thumbs`.
- [ ] Clicking a face selects that donor, and Preview then builds *that* model.
- [ ] Change the **Show** filter to female, then droid. The list narrows and
      the faces still match their names - a face on the wrong row is the
      specific failure the background drawing could cause.
- [ ] Is seven rows enough to browse, or does the list want to be taller?

## 10. The rest of the Transplant tab

- [ ] **Rank for this host** - reorders best-first and labels each entry with a
      grade. Takes about ten seconds; the log says what it found.
- [ ] **Into** - with `p_hk47` as host it should say "pairs with nothing
      whole-model, choose 'head'". Choosing `head` fills the list.
- [ ] **Donor from: KOTOR 2** - the list should repopulate from K2, with faces.
- [ ] **Preview** with a head-model host draws the head **on its body**, before
      and after, at one shared scale. That is the view that shows whether a
      head is the right size and sits on the neck, so it is worth a look before
      any of the in-game tests above - a head that is obviously wrong here does
      not need loading to find out.
- [ ] Preview with `p_hk47` as host draws HK-47 alone. It *is* its own body, so
      there is nothing to put it on.

## 11. The Custom head tab

- [ ] Browse to a pack folder, **Check only**, and read the verdict. The
      scanned head in `packs/scanhead` should be REJECTED at 53% solid.
- [ ] Build one and confirm it lands in the output folder as a named build.

## 12. The Builds tab

- [ ] Builds are listed newest first and say what they came from.
- [ ] **Install to Override** and **Remove** do what they say. This is the only
      action that writes into the game - check it does not touch anything of
      yours.

## 13. Making a new character

All new, and the part with the most riding on it: this is the difference
between replacing a vanilla character and adding one.

- [x] **The whole chain works, 2026-09-01.** `rfk_broker` was replaced with a
      new character: new model, new `heads.2da` row, new `appearance.2da` row,
      new blueprint. He spawned, kept his conversation, and his lips moved.

      Two things learned by doing it. **The build has to be installed** - the
      first attempt looked like a failure and was simply five files still
      sitting in the output folder, which the chain diagnosis found in seconds
      by walking utc -> appearance -> heads -> model against what was actually
      in Override. And **`--with-texture` is not optional** when the donor is a
      different species: without it the model keeps the *host's* texture name,
      so Bith geometry came out wearing Carth's hair smeared over the skull. It
      read as a broken model and was a correct model with the wrong texture.

- [ ] **Save as.** Build with `Save as: p_myhead` and confirm the folder holds
      `p_myhead.mdl/.mdx` and *not* `p_carthh.mdl`. Install it and check Carth
      is still Carth - the whole point is that nothing was replaced.
- [ ] **Make it a: NPC.** No tables should be written, just a `.utc`.
- [ ] **Make it a: NPC that talks.** Then write the `.dlg` and see whether the
      conversation starts.
- [ ] **Make it a: companion.** Check the portrait row appears; the recruit
      script is still yours, so this one cannot be finished by the tool alone.
- [ ] Installing now touches `appearance.2da`, which is **yours**. The install
      planner should report it as *foreign* and ask before replacing it. Say no
      once and confirm it does not write.

## 14. The broker's animation — a specific hypothesis

`rfk_broker.utc` has `ScriptSpawn = k_def_ambmob`. Across all 205 vanilla
creature blueprints, 52 use that script and **none of them hold a
conversation**; its company is `c_bantha`, `c_brith` and `c_dewback`. Every
vanilla NPC that talks uses `k_def_spawn01`.

- [x] **Confirmed in game, 2026-09-01: his head animates.** The diagnosis
      holds - `k_def_ambmob` was making a conversational NPC run the wandering
      -animal behaviour - and the same mistake is designed out of the
      generator, which now uses `k_def_spawn01` for NPCs and `k_hen_spawn01`
      for companions.

## 15. Does a lip file play without audio?

Set up 2026-09-01. **This is the only thing in this project that has written
into the game install**, so exactly what changed is recorded here.

Mouth movement comes from a `.lip` file, not from the model or the dialog, and
the engine finds it by the line's `VO_ResRef`. Every line in `rfk_broker.dlg`
had that field empty, so there was nothing for a lip to be named after.

**Changed in `Override/`:**

| file | what |
|---|---|
| `rfk_broker.dlg.backup-before-lip-test` | **new** - byte copy of the dialog as it was (14,350 bytes, 19 Jul) |
| `rfk_broker.dlg` | `EntryList[0].VO_ResRef` set from `''` to `rfk_brk_01`. One field, one entry; the other ten still have it empty |
| `rfk_brk_01.lip` | **new** - 151 bytes, 3.90s, 27 keyframes. A byte copy of `nm35aacarth2002_` out of `lips/korr_m35aa_loc.mod` |

Nothing else was touched. `rfk_broker.utc` also has today's date because of
your own `ScriptSpawn` fix.

Entry 0 is his opening line, *"Hold on. Before you run off..."*.

- [x] **Confirmed in game, 2026-09-01: his mouth moved.**

**So the engine plays a lip file with no `.wav` behind it.** That was the open
question and it could not be answered offline. Mouth movement does not need
recorded audio - it needs a `.lip` and a `VO_ResRef` to hang it on.

It also means the community's blocker does not apply here. The usual tool needs
the CSLU toolkit to derive phonemes from a recording, and CSLU is effectively
unobtainable; but with no audio to sync to, there is nothing to derive. A lip
file is a duration and a list of mouth shapes, and PyKotor writes the format.

If the timing looks wrong, that is expected and not the point: it is Carth's
mouth shapes for a different sentence.

**To undo:** delete `rfk_brk_01.lip` and rename the backup back over
`rfk_broker.dlg`.

## 16. Generated lips

Built on the result above. `kmdlfun lips <dlg> --out <dir> --assign --replies`
writes a `.lip` per line and, where a line had no `VO_ResRef`, an updated copy
of the dialogue beside them. **The original dialogue is never edited.**

**Already installed for you, 2026-09-01.** What is in `Override/` now:

| file | what |
|---|---|
| `rfk_broker.dlg.backup-before-generated-lips` | **new** - the dialogue as it was a moment before (14,360 bytes, with only entry 0 named) |
| `rfk_broker.dlg` | replaced, 14,360 → 14,685 bytes. All 26 spoken lines now have a `VO_ResRef` |
| 26 × `rfk_brok*.lip` | **new** (25) and replaced (1 - `rfk_brk_01.lip`, which was the borrowed Carth one and is now generated like the rest) |

Verified after copying: all 26 spoken lines have a `VO_ResRef` *and* a lip file
on disk. Your other 19 `rfk_*` files were not touched.

- [x] Installed and ready - just talk to him.
- [x] **Confirmed in game, 2026-09-01: his lips move throughout the
      conversation**, not just on the one line that had a borrowed lip.

So the whole path works: shapes derived from a line's own text, a `VO_ResRef`
assigned where there was none, and 26 generated files driving a conversation
nobody recorded. Nothing here came from a phoneme engine or a recording.

If you record the lines, pass `--audio <folder>` and each lip is made exactly
as long as its own recording - name the files after the line's `VO_ResRef`.
Audio headers here are not honest, in three different ways. **The one that
matters for your own recordings** is the decoy the modding guide has you
prepend: the real WAV ends up nested inside it, so `rfk_carth_a1.wav` opens
claiming 8-bit 22 kHz with a data chunk of zero while 58 bytes in sits the
truth - 16-bit 32 kHz, 5.76 seconds. Shipped ambient sound nests the same way
behind a 470-byte preamble. Shipped *voice* is different again - a WAV header
over MP3 - and is refused rather than guessed at, since a confident wrong
length silently makes a lip that does not match. Run those through SithCodec
first and they read like anything else.

Without recordings, timing is estimated from word count at two and a half words
a second, so a long line gets a long lip: `rfk_brokere01.lip` runs 13.6 seconds over 110 keyframes.
If you click past it the mouth stops with the line; if you linger, it stops
moving before you do. Watch whether that reads as natural or as him running
out. That rate is the single number to change.

**To undo everything:** delete `Override/rfk_brok*.lip`, then rename
`rfk_broker.dlg.backup-before-lip-test` back over `rfk_broker.dlg` - that one
is the dialogue as it was before any of this, with no VO_ResRefs at all.

## 17. The catalogue

- [ ] `python tools/render_catalogue.py --install "<K1 root>"` - 233 models in
      about a minute. Spot-check a few faces are the right way round.

## 18. What the character is wearing

Vex spawned undressed on the first run. Diagnosed offline: his appearance row
was copied from Carth, and `modela` — the body used when nothing is equipped —
is `P_CarthBA`, Carth's underwear. Party members have a real body per equipment
slot; plain NPCs repeat one body across all nine, which is why the Czerka
officer is `N_CzerkaOff` nine times and never undresses. The Transplant tab now
has a **Wearing** box holding the 117 outfits the game already uses.

- [ ] Rebuild Vex with **Wearing** left on `same body as the host`. He should
      now be dressed in Carth's jacket rather than the underwear — that alone
      is the fix.
- [ ] Rebuild with **Wearing** set to `N_CzerkaOff`. He should be in the Czerka
      officer's uniform with the transplanted head on top.
- [ ] Try one where model and texture differ — `N_CommF (Commoner Dirty Fem
      Asian)` wears `N_CommFD`. A wrong texture here shows as a white or
      missing body, so this is the one that proves the pairing is read rather
      than assumed.
- [ ] Check he still animates and his mouth still moves after the change. The
      clothing slots should not touch either, but the head and body are the
      same model at runtime.

## 19. The Lips tab

The engine behind this is already confirmed in game twice (§15, §16). What is
new is that it has a tab instead of a command line, and that the `--assign`
path no longer crashes — it wrote every lip and then died reaching for a
variable the loop had overwritten, which is why the broker's VO_ResRefs had to
be assigned in a separate step at the time.

Output goes to a `lips/` folder inside your output folder. Nothing is installed
and your dialogue is never edited.

- [ ] Point it at `rfk_broker.dlg.backup-before-lip-test` — the copy with no
      VO_ResRefs at all — with **Name the lines** ticked. Expect 26 lips plus
      an updated `rfk_broker.dlg` beside them. This is the case that used to
      crash.
- [ ] Untick **Name the lines** and run the same file. Expect zero lips and a
      line saying 26 were skipped, rather than silence.
- [ ] Point it at the current `rfk_broker.dlg`, which already names its lines.
      Expect 26 lips and *no* dialogue copy, because nothing changed.
- [ ] Tick **Force every line to** 3 seconds and confirm every lip comes out
      the same length. That is the control for the timing path.
- [ ] Point **Recordings** at a folder holding `rfk_carth_a1.wav`. Only the
      line whose VO_ResRef matches its name should be timed; the log should
      say so and estimate the rest.
- [ ] The run is kept as a build (`lips_<dialogue>/`), so install it from the
      **Builds** tab rather than copying by hand, and confirm his mouth still
      moves in game. Same result as §16, through the window this time.
- [ ] Because your Override already holds `rfk_broker.dlg`, installing should
      report it as **foreign** and refuse until you allow it. That guard is the
      thing to watch here — it is the first time a `.dlg` has been installable
      at all, and a dialogue is the most likely file to already be someone's.

## 20. Importing a .glb from the window

The Custom head tab has an **Import .glb** button. It writes a pack into
`<output>/packs/<name>/` and then selects it, so the next click is Build.

Nothing about the conversion changed — this is the same code the Tripo head
came through, moved out of the CLI so both call it. What is worth checking is
the handover.

- [ ] Import any `.glb` and confirm the **Head pack** field fills itself in
      with the folder it just wrote. That is the whole point of the button.
- [ ] Build that pack onto `p_carthh` straight after, without touching the
      path. Should behave exactly like a hand-made pack.
- [ ] Import a `.glb` exported without a UV map. It should still write a pack
      and say the head will be untextured, rather than failing or going quiet.
- [ ] Import something that is not a `.glb` at all. The error belongs in the
      log, not in a console nobody is looking at.
- [ ] Check the texture that lands in the pack keeps its alpha if the source
      had any — that is what cost a ported Quarren its eyes.

## 21. The Character tab

Pick a **body**, a **wardrobe** and a **head**, each in its own grid with
thumbnails. Nothing here writes geometry: a KOTOR humanoid is a base body, a
clothed body per equipment slot and a row of `heads.2da`, and all three already
exist. A new character is two table rows and a blueprint.

30 bodies, 117 outfits, 106 heads — and none of the pairings are guessed. Every
`modeltype B` row names both a `race` and a `normalhead`, so a tick means the
game itself already puts that part on that body. Unticked combinations are
offered anyway, because those are the reason to open the tool at all.

- [ ] Pick only a body, e.g. `N_CommM`. The wardrobe and head should fill
      themselves in with something the game already pairs with it, so you never
      get a naked headless character by doing nothing.
- [ ] Check the ticked entries sort to the front of the head and wardrobe grids
      once a body is chosen, and that unticked ones are still listed.
- [ ] Pick `N_TwilekF` with `p_CarthH`. It should warn that nothing in the game
      pairs them — then build it anyway and see whether the neck meets the
      collar. This is the combination the warning exists for.
- [ ] Filter the wardrobe to female. It should shrink, not empty. (It emptied
      before outfits were classified — an outfit is a body model and has a sex
      the same way a body does.)
- [ ] Create an NPC and install it from the Builds tab. Confirm in game that it
      spawns clothed, with the head you picked.
- [ ] Create one using a **vanilla** head and confirm no `heads.2da` is written
      at all — the head already has a row, and adding a second would grow the
      table every time somebody reused a face.
- [ ] Compare against the Transplant tab: that one is for when no existing head
      will do. If this tab covers what you wanted, it is the cheaper route.

## 22. Settings, and finding the games

The Folders panel is gone from the top of the window. It is a one-line summary
plus a **Settings** menu, and the games are detected at startup from Steam's
own `libraryfolders.vdf` - which is what lets it find an install on a second
drive, the case the old hardcoded list of three paths could never cover.

Found paths are remembered in `~/.kmdlfun/installs.json`, so the search is a
once-per-machine job.

- [ ] Launch it. All three games should already be filled in, with **no log
      output about it** - the status line is the whole report. Anything chatty
      here defeats the point.
- [ ] Check the status line reads `KOTOR: swkotor   KOTOR II: ...   output:
      out_fun` - names, not paths.
- [ ] Open **Settings > Folders...**, confirm the four boxes are there (KOTOR,
      output, KOTOR II, Jade Empire) and that editing one updates the line
      behind it.
- [ ] Delete `~/.kmdlfun/installs.json` and relaunch. It should find everything
      again from Steam, in well under a second.
- [ ] Rename your KOTOR folder to something else and use **Find my games**. It
      should still find it: identification is by `swkotor.exe`, not by name.
- [ ] Point the KOTOR box at your **KOTOR II** folder by hand and relaunch.
      Detection must not overwrite it - losing a path somebody typed is worse
      than not helping.
- [ ] Try **Search every drive** once, to see how long it takes on your
      machine. It only runs when asked, and only for games still missing.
- [ ] **Non-Steam installs.** Detection no longer depends on Steam: it reads
      the Windows uninstall entries, GOG Galaxy's game list, Epic's manifests
      and the `BioWare\SW\KOTOR` key the retail disc leaves behind. On this
      machine that is 234 recorded install locations, of which exactly three
      are games, all found in 0.02s. If you can get hold of a GOG or disc copy
      of any of the three, that is the case worth checking.
- [ ] A game **copied rather than installed** has no record anywhere, and only
      **Search every drive** can find it. Worth confirming once if you keep a
      copy on an external drive.

## 23. Jade Empire heads on KOTOR bodies

**From Jade Empire** on the Custom head tab. It reads the 1028 archives once
(a moment), then shows a grid of faces — 158 heads or 112 bodies — and picking
one writes a head pack into `<output>/packs/jade_<name>/` and selects it.

Confirmed offline: `h_common01_` converts to 742 vertices and 1137 triangles
with UVs, and builds onto `p_carthh` with weights transferred across all 16
bones and placement within 0.013. **None of it has been in the game.**

- [ ] **Decimation is now off for a Jade head, and should stay off.** The 690
      default suits a photogrammetry head of three or four thousand triangles;
      a Jade head arrives at about 1100, which is inside what the game ships
      (vanilla heads run 440-796, and the check allows 1500). Reducing it
      anyway destroys the geometry the eyes and mouth sit on, and the result
      looks like a texture fault rather than a resolution one. The importer
      sets the box for you now - if you tick it back on, expect a smeared face.
- [ ] Convert `h_common01_` and build it onto `p_carthh` with **Fit ticked**.
      Fit is needed here and is not the shrink you saw on transplants — the
      head arrives at 93% of the node's size, so fitting is a 0.98× nudge that
      does the placement. Without it the build fails outright, saying the head
      would float.
- [ ] Look at it in the Preview tab before installing. The rotation was settled
      by rendering rather than reasoning, and the first attempt produced a head
      that was upright, correctly sized, and facing backwards — which no number
      in the checks would have caught.
- [ ] Install it and see it in game. **This is the one that matters**: the
      0.83 scale is measured, disagrees in direction with the format author's
      own figure, and has never been tested against the engine.
- [ ] Try the **scale** box in the Jade window at 1.0 and at 0.7 and compare.
      If 0.83 is wrong, this is how you find the number that is right.
- [ ] Convert something with no UVs if you can find one. It should still build
      and say plainly that it will render untextured.
- [ ] **136 of 148 heads build**, swept offline — see
      [reports/JADE_SWEEP.md](reports/JADE_SWEEP.md), regenerate with
      `python tools/jade_sweep.py`. The twelve that do not are content, not
      bugs: six are the wrong *shape* for a head node (hats, pigtails,
      troglodytes) and six fold back on themselves, usually layered hair. If
      you hit one, the preview is the place to judge it.
- [ ] Masks are their own kind now (`H_Mask01`-`09`, plus the `H_Decap01`
      stump). They convert but will not pass head checks, because an open
      shell is not meant to be closed or to face outward. Worth trying one
      anyway to see what the game makes of it.
- [ ] **Textures now come across.** A mesh names a material by number, the
      material names the texture, and the `.txb` is decoded to a `.tga` in the
      pack. Confirmed offline on three heads: skin, hair, eyes and facial hair
      all land where they belong. Check one in game — if a face looks like it
      is wearing its texture sideways, the V axis is the thing to suspect,
      since it runs opposite to ours and is flipped on the way in.
- [ ] Some heads are **greyscale** (`h_old01gh_` is). That is Jade's own
      texture, not a conversion fault — the `GH` in the name appears to mark
      them.

## 24. The standalone build

`python tools/build_app.py` produces `dist/kmdlfun/`, 77 MB, which needs no
Python installed. The build script self-tests it and refuses one that starts
but cannot work.

Confirmed here: it builds, the self-test passes on all nine checks including
pykotor's dynamically resolved format readers, and the window opens. **What has
not been confirmed is the only thing that matters** — that it runs on a machine
that is not this one.

- [ ] Zip `dist/kmdlfun/` and copy it to a machine with **no Python** on it.
      Run `kmdlfun.exe`. This is the whole point and the only test that counts;
      everything works here because everything is already installed here.
- [ ] On that machine, run `kmdlfun.exe --selftest` first. It writes
      `kmdlfun-selftest.txt` beside the executable, and it will name what is
      missing far more clearly than a window that fails to open.
- [ ] Check it finds the games on that machine, or that Settings can be pointed
      at them by hand if the games are not installed there.
- [ ] Expect Windows SmartScreen or antivirus to complain about an unsigned
      executable. That is normal for an unsigned PyInstaller build and not a
      sign anything is wrong; signing it needs a certificate.
- [ ] Watch how long the window takes to appear from a cold start. If it is
      slow enough to be annoying, say so — the folder layout was chosen to
      avoid exactly that and it is worth knowing if it did not.

## 25. Basic and advanced mode

The window opens in **basic** mode. It hides the Transplant tab, the Upcoming
tab, the Custom head options block (decimate, fit, repair, hide, reshape), the
crop row, the head-node box and the Lips forced-length row. `Settings ▸ Mode ▸
Advanced` shows everything and is remembered in `~/.kmdlfun/prefs.json`.

Hidden is not switched off: the defaults behind those controls still apply, and
they are the ones the app's own routes rely on.

- [ ] **You will land in basic mode on the next launch** and the Transplant tab
      will be missing. That is the feature, not a fault — switch to Advanced
      once and it stays.
- [ ] Switch to Advanced and back. Transplant should return to the **front**
      of the tabs and Upcoming to the end, not both appended — a notebook that
      reorders itself when you change a setting is worse than one with a tab
      missing.
- [ ] In basic mode, import a Jade head and build it. The whole path should
      work without the hidden options, because their defaults are right.
- [ ] Sit somebody who has never modded in front of basic mode and see how far
      they get on the Character tab without asking you. That is the only test
      of this that means anything, and it is the one I cannot run.

## 26. A real head off the internet

Tested end to end on the Lee Perry-Smith scan (CC-BY, Infinite Realities) from
the three.js repository: 9,279 vertices, 17,684 triangles, with its colour map
as a separate file. It built onto Carth and it looks like a person.

It took three corrections, and **none of them could be worked out from the
file**:

1. It is a **bust** - head, neck and shoulders - so its bounding box is far
   wider than a head node and fitting shrank it to 57%. **Crop below 0.45**
   removes the shoulders. That option exists for exactly this and this is the
   first time it has been needed.
2. It **faces away**. `facing` had to become `-y` in the pack's manifest.
3. Its 17,684 triangles need decimating to 690, which the importer now sets
   automatically because the pack is over budget.

- [ ] Repeat it: `kmdlfun import <a .glb> --out packs/x`, then build with crop
      and fit. Any CC-licensed head scan will do.
- [ ] **Look at the Preview tab before building.** Two of the three corrections
      above are only visible there - a head that arrives backwards or lying
      down is not something any check can catch, because a bounding box is the
      same whichever way it faces.
- [ ] If a `.glb` has no embedded texture, drop a single `.tga` into the pack
      folder yourself. Its filename becomes the resref.
- [ ] Try a bare head rather than a bust and confirm it needs no crop.

### Why the app does not guess `up` and `facing`

Both were tried during this test and both were withdrawn, which is worth
knowing before anybody tries again:

- *"The longest extent is up"* holds for every KOTOR head and every Jade head -
  two whole corpora - and fails on the first real file, because a bust's
  shoulders are wider than it is tall.
- *"The point furthest from the vertical axis at mid-height is the nose"* gives
  the right answer on a KOTOR head and a Jade head, and picks the **ear** on
  any scan with ears.

glTF declares Y-up, that is usually right, and the preview is where a wrong
guess gets caught. A heuristic that is right on the models you already have and
wrong on the next one is worse than no heuristic.

---

## Housekeeping

**Cleared 2026-09-02**, twice over. Everything installed during the tangent
testing — `n_selkath.mdl/.mdx`, `N_Selkath01b.tga/.txi`, `N_Selkath01.txi` — is
out, and Override holds nothing of ours.

`p_carthh` had been sitting in `Override/` since the
head-swap testing on 2026-08-30, so Carth had a Quarren head for three days.
It read small and bare because that build hid hair, eyes, teeth and tongue —
2 visible meshes against vanilla's 9 — rather than because of its size.

Pulled out and kept in `out_rescued/quarren_carth/` in case it is wanted again.
`p_bastilabb` was already gone.

The lesson worth keeping: a test model installed into the game stays installed.
Nothing in this project removes one, and there is no reason to expect the person
who put it there to remember three days later. Anything installed for a test
belongs in this section the moment it goes in.

## Already verified, for contrast

Not owed, recorded so the list above is not read as "nothing works":

- The splice engine and a no-op swap, 76,703/76,703 mesh nodes identical.
- The resize probe, in game.
- **The `+168` node pointer fix** (2026-08-30) - the probe that had broken every
  previous time. This is the one that unlocked skinned heads.
- A Quarren head on Carth: animates, own weights carried, two of four tentacles
  hung wrong.
- A Tripo-generated head on Carth: head turns, mouth moves, brows do not.
- `bighead` on HK-47.
