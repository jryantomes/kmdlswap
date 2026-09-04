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

- [x] **Confirmed in game, 2026-09-02: Vex is dressed.** His row 510 had the
      bug live — `modela` was `P_CarthBA`, Carth's underwear — and rewriting
      the nine clothing slots to `P_CarthBB` put him in the jacket. One row,
      one file, and the outcome was binary rather than a judgement call.

      **This also validates the appearance-row writing underneath §21.** The
      Character tab builds its rows the same way, so `dress()` and the
      slot-filling are now proven against the engine rather than only against
      tests.
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
- [x] **Confirmed in game, 2026-09-02, on Vex.** A Jade head built onto his
      `p_brokerhd` — his appearance row, body and clothes untouched, so the
      head was the only variable. It sat on the neck, animated with the head,
      and looked like a person. Two things came out of it:

      **The head was slightly too small**, and it was the *fit* step, not the
      scale. Fitting resizes to the tightest axis of the host node: the Jade
      head is fractionally wider than Carth's, so the width ratio of 0.980
      bound and cost 9% of its height. Placing and resizing are separate
      operations now, resizing is off by default, and the head went from 91% to
      96% of the node — **confirmed better in game on the rebuild**. The Jade scale is also per kind now — 0.86 for heads,
      0.83 for bodies, which is what was measured rather than one figure for
      both.

      **His mouth does not open.** Not a wiring failure: the jaw bone has 182
      weighted vertices, more than vanilla's 63. The heads are built
      differently. A KOTOR head has *no* mouth opening — its lips are
      continuous surface that the jaw stretches apart, with separate teeth and
      tongue nodes behind. A Jade head has a real hole with two rims, 14
      vertices each, at 35% and 38% of its height. Weight transfer works by
      proximity and the two rims are a fraction of a unit apart, so both get
      bound alike and move together. A KOTOR donor shares the host's lip
      topology, which is why the Bith head's mouth moved on this same
      character. Fixing it means telling the rims apart, which proximity
      cannot do.

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
- **A Jade Empire head on Vex, with a working mouth** (2026-09-03): dressed,
  scaled, animated, and opening onto its own teeth and interior. §23 to §47.

## 27. Facial weights: the upper lip bound to the skull

**Status: built, measured, awaiting in-game confirmation.**

Reported in §23: a Jade Empire head on Vex animates at the brows and eyes but
"his mouth is glued shut".

**What it is not.** Two explanations were tested and both were wrong.

*Not borrowed teeth.* The host's `teethUa01`, `teethLa01` and `tongue` sit in
their own coordinate spaces and are placed by their node transforms, so they
land inside a converted head's mouth correctly — confirmed by render in
`reports/jade_mouth.png`. But they are then visible permanently, because they
are larger than the Jade head's own mouth bag. The Jade head already has teeth;
it does not need to borrow any.

*Not a mouth opening.* An early reading claimed KOTOR heads are sealed while
converted heads carry an open mouth, and a whole module was written against it.
It was wrong. Read across islands, a separate lip piece's own edge is
indistinguishable from the rim of a hole. In welded topology `h_common01_` is
six islands — a 475-vertex face shell with exactly one hole (the neck, same as
Carth), two eyes, two closed lip pieces and a mouth bag.

**What it is.** Measured by which bone *leads* each vertex, on the same bands:

| band | vanilla `p_carthh` | plain transfer | after the fix |
|---|---|---|---|
| upper lip led by skull | 26% | **41%** | 23% |
| upper lip led by mouth | 48% | 25% | 39% |
| lower lip led downward | 88% | 97% | 97% |

The **lower** lip was never wrong — it arrives better bound than vanilla. Two
fifths of the **upper** lip is led by `head_g`, which never moves. Proximity
transfer inherits from the nearest host *triangle*, and wherever the converted
face sits off Carth's surface that triangle is skull.

Mean weight shares said the opposite — that the whole mouth was skull-heavy and
the lower lip starved. That reading averages over bands containing both lips and
is an artefact. **Dominance, not mean share, is the metric that predicts
movement.**

`kmdlswap/facerig.py` re-samples only vertices where the skull leads *and* the
host's anatomy at the same normalised position has a mobile bone leading. A
blanket version of the same pass fixed the upper lip and dragged the lower lip
from 97% to 84% while leaking upper-lip weight onto it; the targeted version
leaves it at 97%. 58 of 285 lower-face vertices qualified on `h_common01_`.

**To validate:** install `out_vex_facerig/` and talk to Vex on Taris. The rest
pose is unchanged by design — `reports/jade_facerig.png` shows before and after
as identical — so the only thing to look for is whether the upper lip now moves
with speech. Nothing else about the head should differ.

## 28. The lips are separate pieces, and that is why the mouth stayed shut

**Status: built, measured, awaiting in-game confirmation. Supersedes §27's
conclusion, which was correct in itself but not the cause.**

§27 corrected the upper lip's *region* from 41% skull-led to 23% and was
installed. In-game result: **no visible change.** The weights it fixed were not
the ones holding the mouth shut.

**Why it was missed.** Every measurement had been taken over geometric bands.
The visible mouth is two 14-vertex lip islands; a band around the mouth holds
285 vertices. 28 inside 285 vanish into the average. Measuring the islands
themselves, on the installed build:

| island | led by |
|---|---|
| upper lip (14) | `head_g` 9, `f_um_g` 5 |
| lower lip (14) | `f_um_g` 4, `f_jaw_g` 4, `head_g` 4 |
| mouth bag (11) | `head_g` 5, `f_jaw_g` 5 |

The upper lip is led by a bone that never moves; the lower lip has as much
weight lifting it as dropping it, so the two cancel. Proximity transfer fails
here specifically because separate lip pieces sit *recessed behind* the face
shell, and the nearest host surface to a point tucked under Carth's lip is skull,
not lip. `facerig` could not reach them for the same reason.

**Also settled: the `.lip` route cannot work.** A KOTOR `.lip` file is a list of
`(time, shape)` pairs into 16 shapes the engine owns — `AH`, `EE`, `EH`, `FV`,
`KG`, `L`, `MPB`, `NEUTRAL`, `NG`, `OH`, `OOH`, `SH`, `STS`, `TD`, `TH`, `Y`. It
carries no geometry and no bone transforms, so there is nowhere to put imported
animation, and what each shape *looks like* is decided by the head's weights.
The Jade head model also reports zero animations. The `.lip` file can still
change how *much* a mouth moves (denser keyframes, more extreme shapes) — that
is a separate, open idea.

`kmdlswap/lips.py` finds the lip pieces as welded islands and binds them to the
profile measured across 101 vanilla heads. After it:

| island | after |
|---|---|
| upper lip | `f_um_g` 14/14 |
| lower lip | `f_llm_g` 8, `f_rlm_g` 6 (split by side) |
| mouth bag | `f_jaw_g` 11/11 |

**To validate:** installed as `out_vex_lips/`; previous build backed up at
`out_vex_lips/backup-before-lips/`. Talk to Vex on Taris. The rest pose is
unchanged, so the only question is whether the mouth now opens. A head whose
mouth is part of the face shell (every vanilla KOTOR head) has no lip islands
and is untouched.

**Method note worth keeping:** dominance beats mean share, and *islands* beat
regions. Two passes in a row measured something true about a region and missed
the handful of vertices that actually mattered.

## 29. The mouth interior was being hidden

**Status: built, installed, awaiting in-game confirmation. This is the actual
cause of §23's "glued shut".**

Reported after §28: *"The movements work but there's no teeth or tongue like
with the KOTOR models."* The lips animate correctly — §28 did its job — and the
mouth opens onto nothing, which reads as taped shut.

**Cause.** A KOTOR head is several nodes: `Head` is the face, and the mouth
interior is two or three separate nodes beside it. They are near-universal —
across 106 K1 head models, 104 carry a `tongue` and essentially all carry teeth
under three naming schemes (`teethua`/`teethla` on 54, `teethupper`/`teethlower`
on 44, `teethua01`/`teethla01` on 3, which is Carth). When a converted head
replaces `Head`, the build hid *every* other visible node. Right for hair and
eyelids, which are shaped for the vanished face and would float. Wrong for the
mouth interior, which sits inside the head and still belongs there.

**Why keeping them naively also fails.** They are placed for the host's face.
Measured in model space at mouth height:

| | face surface | teeth front | clearance |
|---|---|---|---|
| vanilla Carth | y +0.1185 | +0.1100 | **+0.0085 (inside)** |
| Jade build, before | y +0.1048 | +0.1100 | **−0.0052 (through the lips)** |

The Jade face is 0.0137 shallower at the mouth, so Carth's teeth protrude. That
is what an early attempt at this looked like — `reports/jade_mouth.png` — and it
is why the idea was dismissed the first time round, on the strength of a static
render, before the real symptom was known.

`kmdlfun/mouthparts.py` keeps the mouth interior and moves it back to the
clearance the host itself had, measured from both heads rather than nudged by a
constant. After: teeth clearance +0.0085, matching Carth exactly; tongue
+0.0125. `reports/jade_mouthparts.png` shows no teeth visible at rest.

Only depth is corrected. The teeth already bracket the mouth vertically (z
0.0702–0.0922 against lips at 0.0783–0.0864) and are narrow enough to fit, so
moving them in z or scaling them would be inventing a correction.

**First attempt failed in game — the teeth stuck out like tusks**
(`20260903000522_1.jpg`). The correction was real in the file and discarded by
the engine: `teethUa01` and `teethLa01` both carry a **position controller
(type 8)**, and the engine takes the controller's value over the node header
field that was edited. `tongue` is skinned, so its node position is bypassed
too.

The move now goes into the **geometry** — vertex positions offset in node space,
with the stored bounding box transported alongside via `UniformScale(1.0, …)`,
since the engine culls and sorts by that box. Nothing can override vertex data.
Verified: header positions come out byte-identical to vanilla, clearance
+0.0085, model validates.

**To validate:** installed as `out_vex_teeth/`; previous build backed up at
`out_vex_teeth/backup-before-teeth/`. Talk to Vex — teeth and tongue should show
when his mouth opens, and nothing should be visible at rest.

**Method note.** Three passes in a row fixed something real and missed the cause,
because the symptom was described as "glued shut" and read as a movement problem.
It was never movement. The lesson is to ask what a symptom *looks like* before
deciding what it *is* — the render that would have settled this existed from the
first hour and was misread.

## 30. The face shell had no mouth at all

**Status: built, installed, awaiting in-game confirmation. This is the cause of
§29's remaining symptom.**

Reported after §29: teeth no longer stick out, movement looks fine, *"it's like
the texture is glued shut, not allowing to see the inside of the mouth."*

**The texture is innocent.** The Jade atlas carries teeth along its top edge and
a pink mouth interior at the bottom right (`reports/mouth_textures.png`). The
artwork is all present.

**The shell covers everything.** Measured in model space at the mouth, by how
far forward each surface reaches:

| surface | front edge |
|---|---|
| **face shell skin** | **+0.1048** |
| lip pieces | +0.1005, +0.0962 |
| teeth | +0.0963, +0.0941 |
| tongue | +0.0923 |
| mouth interior bag | +0.0883 |

The shell is an unbroken sheet of skin in front of every other surface; its only
hole is the neck. Nothing behind it can ever be seen, at any weighting or pose.
It also means the lip pieces bound in §28 were themselves hidden behind the
shell and never visible.

**Carth needs no equivalent.** His face is also one surface across the mouth,
but his lips are *part of it*, weighted to bones that pull them apart, with no
second surface in the way. Checked directly: none of the 126 duplicated
positions in his `Head` is split between an upward-driven and a downward-driven
copy, so there is no hidden seam either. A converted head fails because it has
*both* a solid shell and separate lips.

`kmdlswap/aperture.py` cuts the shell open inside the ellipse the lip rims
enclose, front faces only, leaving every other island intact.

**Sizing was decided by rendering, not by argument.** At full rim height the cut
takes the whole 0.0204 gap, and geometry does not close — the result is a face
that sits at rest with its teeth bared (`reports/aperture_rest.png`, panels 3
and 4). At 0.25 it reads as an ordinary closed mouth with a dark lip line and
opens onto the interior when the lips part (`reports/aperture_open.png`). 19
shell faces removed on `h_common01_`.

**To validate:** installed as `out_vex_open/`; previous build backed up at
`out_vex_open/backup-before-open/`. At rest his mouth should look normal — if
his teeth show while he is standing there saying nothing, the aperture is too
tall and `mouth_height` wants lowering.

**Method note.** The jaw-open renders in this section come from a hand-rolled
simulation that rotates jaw-weighted vertices; its rotation sign was initially
backwards, which made an open mouth look clamped shut. It is useful for seeing
whether an opening exists, and worthless as a guide to how far the engine
actually moves anything.

## 31. The mouth was there all along, closed to zero width

**Status: built, installed, awaiting in-game confirmation. Supersedes §30, whose
cut is now off by default.**

The user's reading was right and mine was wrong: *"the place where you would see
the mouth was welded shut during conversion."*

**What §30 got wrong.** It concluded the face shell had no mouth because every
boundary analysis reported one hole (the neck). All of those analyses **weld by
position** — which they must, since welding is what stops a UV seam looking like
a hole — and Jade Empire models a mouth as an aperture whose two rims sit on
*identical coordinates*. Welding merges them and the hole vanishes from the
measurement. The face is not solid; the mouth has zero width.

**Proof.** On `h_common01_`, 26 duplicated positions between 32% and 43% of head
height have one copy used only by faces *above* and another only by faces
*below*. That is a rim pair, not a seam — an ordinary UV seam has every copy on
the same side (18 of the 44 duplicates there are exactly that).

**Why it could never open.** `weights.transfer` samples the host surface *by
position*, and the two rims occupy the same position, so it assigns them
identical weights by construction. Measured on the installed build: 26 rim
pairs, **all 26** bound to the same kind of bone. They move together, so the
aperture stays at zero width no matter how the face is animated, and nothing
behind it is ever visible.

`lips.split_rims` finds the pairs and `lips.bind` weights them apart, upper rim
to the upper-lip profile and lower to the lower-lip profile. After: 26 pairs,
0 sharing a bone, 26 parted. 54 upper and 49 lower rim vertices bound.

**§30's cut is now off by default** (`mouth=False`). It removed real geometry to
make a hole that already existed, which left a permanent gap at rest. The module
stays for a head that genuinely has no aperture.

**Method note, and the important one.** Four passes in a row measured the mouth
with a tool that could not see it, and each time the measurement agreed with the
previous wrong conclusion. Welding by position is correct for finding islands
and fatal for finding apertures; both readings were needed and only one was ever
taken. The user supplied the hypothesis that broke the loop.


## 32. The seam binding tore the head open

**Status: fixed and installed, awaiting in-game confirmation. Corrects §31.**

Reported from the game with screenshots: the mouth opens onto a dark interior —
§31 worked — but *"he has a whole ass seam around his head when he talks"*, and
`20260903212642_1.jpg` shows a gash across the **back** of the skull at ear
height.

**Cause, and it was mine.** `split_rims` filtered on the height band alone: no
front/back test and no lateral limit. Jade heads carry a coincident-vertex seam
running right around the skull at jaw height, and the "one copy above, one copy
below" test cannot tell it from a lip rim. So it bound the whole ring apart.

Measured on the build that shipped:

| | bound by `split_rims` | the actual mouth |
|---|---|---|
| vertices | **103** | 26 |
| lateral span | **x ±0.068** (head half-width 0.085) | x ±0.023 |
| depth span | **y −0.046 … +0.113** (back to front) | y +0.070 … +0.102 |

30 of the 103 were on the back of the head.

**Fix.** `split_rims` now requires a `near` box — centre and half-extent taken
from the lip pieces — and the front half of the head regardless. With no mouth
to aim at it returns nothing rather than guessing. After: 26 vertices, 0 on the
back, x ±0.020. The mouth still opens: 13 pairs part, and the 13 skull-seam
pairs correctly stay shut.

**Lesson.** §31's detector was validated only on *whether it found the mouth*,
never on *what else it found*. A test that a detector fires is half a test; the
other half is that it does not fire elsewhere. `tests/test_lips.py` now carries
a fixture with both a mouth seam and a skull seam, and asserts nothing on the
back of the head is bound.

**To validate:** installed as `out_vex_seam2/`; previous build backed up at
`out_vex_seam2/backup-before/`. The mouth should behave as it did in the last
screenshots, and the seam around the skull should be gone.


## 33. The interior swung out through the mouth, and a flaw in how it was checked

**Status: built and installed, awaiting in-game confirmation.**

Reported: *"it looks like you split the top lip and bottom lip and they are
moving with the mouth pieces"* — the seam works and the mouth opens, but the
pieces behind the face move independently of it.

**Cause.** §31 bound the lip pieces and the mouth bag to *idealised* profiles
(the bag at 70% jaw, 30% lower lip). Those swing on the jaw pivot far harder
than the shell they sit behind, so as the mouth opened the interior sailed out
through the opening. A piece tucked behind a lip has to move with that lip,
whatever it is doing. `lips.bind` now gives each of the 39 interior vertices the
weights of its nearest shell vertex — after the seam correction has been applied
to those — so they cannot diverge by construction.

**A flaw in the method, which matters more.** `render.py` does **no backface
culling** and uses two-sided lighting (deliberately: the head spec tolerates 5%
of faces winding against their normals). The engine culls. So every render of an
*open* mouth in §29–§32 was showing the inside of the head — a large flesh-
coloured slab the game never draws — and I read it as geometry doing something
wrong. Rendered with `cull=True`, the same build shows a closed mouth at rest
and teeth over a dark interior when open.

**Rule from now on: any render that looks into an opening must pass `cull=True`.**
The no-cull default is right for judging a surface and actively misleading for
judging a cavity. `krender.strip(..., cull=True)` is the switch; it is described
in `render.py` as "the preview that can see that class of bug", and this is that
class of bug.

**To validate:** installed as `out_vex_follow/`; previous build backed up at
`out_vex_follow/backup-before/`. The mouth should behave as it did, without the
interior separating from the lips as it opens.


## 34. §31 was wrong: there is no welded aperture, and the shell must stretch

**Status: built and installed, awaiting in-game confirmation. Retracts §31.**

Reported: *"his top lip and bottom lip are split in the middle and are opening
and closing with the mouth movements. The center where his two lips would
separate do not and still look welded together."*

That is the symptom of binding the wrong line apart, and it is exactly what §31
did.

**The retraction.** §31 claimed the shell carried an aperture closed to zero
width, on the evidence of coincident positions with "one copy used only by faces
above, another only by faces below". That test compares the mean height of each
copy's *face centroids*, which measures the local **slope of the surface**, not
its topology. Two checks settle it:

- The welded shell has **no boundary vertex anywhere near the mouth** — it is
  genuinely continuous, exactly like Carth's.
- At the mouth line (z −1.618, 36% of head height) there are 16 coincident
  positions, and **every copy has all of its faces below it**. Three UV copies
  pointing the same way. Not a rim pair.

So the pairs being bound apart were at 32–35% and 38–39% — the **outer outline
of the lips**, where they meet the face. Splitting those detached the lips and
left the mouth line welded. The description above is that failure exactly.

**What is true instead.** A KOTOR mouth opens by *stretching*. The face is one
closed surface; vertices above the lip line lift with `f_um_g`, those below drop
with the jaw and lower-lip bones, and the skin between them pulls apart to line
the cavity — which is why Carth's texture paints the mouth interior onto that
stretched skin. `lips.mouth_region` now does the same to a converted shell: 43
vertices above the lip line lift, 72 below it drop. `split_rims` is deleted.

**A second flaw in the checking, carried over from §33.** Every render of an
open mouth before this was made without backface culling, so it showed the
inside of the head as a flesh-coloured slab the engine never draws. All renders
of a cavity now pass `cull=True`.

**To validate:** installed as `out_vex_stretch/`; previous build backed up at
`out_vex_stretch/backup-before/`. The lips should stay one surface with the
face, and the mouth line itself should part.

**Method note.** Three separate conclusions in this thread came from a detector
that could not distinguish what it claimed to. The pattern each time: a test
that fires on the right geometry was treated as proof it fires *only* there, and
the topology was never checked directly. "Are there boundary edges here?" would
have answered this in one query at any point.


## 35. Stretching is necessary but not sufficient — the shell has to be opened too

**Status: built and installed, awaiting in-game confirmation.**

Reported after §34: *"all of the animations work, but the horizontal line where
his mouth opening would be just stretches instead of showing the teeth and mouth
like in other textures."*

§34 was right that a KOTOR mouth opens by stretching, and right that the shell
is closed. What it missed is why that works on Carth and not here: **on Carth
the skin that stretches into the cavity is UV-mapped to the mouth interior he
has painted there.** The Jade head paints its interior somewhere else entirely —
on the lip pieces and the mouth bag, which sit behind the shell. So the same
stretch smears *skin* across the opening, which is precisely what was seen.

So both are needed. The stretch weighting from §34 stays; the aperture cutter
from §30 comes back on, at a height chosen by rendering **with culling** this
time:

| aperture height | at rest | open |
|---|---|---|
| 0.40, 0.25 | a band of teeth on a resting face | fine |
| **0.10** | **faint specks at the lip line** | **teeth and interior** |

6 shell faces removed, an aperture 0.0456 wide by 0.0020 tall.

The tension is structural and cannot be designed away: a hole in geometry does
not close, so anything cut is visible at rest as well. 0.10 is the point where
what shows at rest is a glint rather than a grin.

**To validate:** installed as `out_vex_open2/`; previous build backed up at
`out_vex_open2/backup-before/`. At rest the lip line should read as a line, not
a set of teeth. Talking, the interior should show instead of smeared skin. If
teeth are visible while he stands there saying nothing, `mouth_height` wants
dropping further; if the mouth still smears, the aperture is too small to matter
and it wants raising.


## 36. Face deletion cannot make a mouth line at this resolution

**Status: cut reverted. The mouth remains unsolved; the route to solving it is
now clear.**

Reported: *"the top lip is cut into triangles where you can see the teeth."*

**Arithmetic, not judgement.** Triangles near the mouth average **0.0067** tall.
The aperture is **0.0020**. The slit is a third of a triangle, so deleting any
whole face leaves a hole three times too big and shaped like a triangle. No
choice of `mouth_height` fixes that — below one triangle the cut is jagged, at
one triangle it bares teeth at rest. `mouth` is off again.

**A correction that has been wrong all session.** The two 14-vertex pieces I
have been calling *lip islands* sample **u 0.012–0.182, v 0.015–0.071** — the
teeth strip along the top of the Jade atlas. **They are the head's own upper and
lower teeth.** The 11-vertex bag samples u 0.879–0.982, v 0.831–0.972, the pink
patch: the mouth interior. So this head carries its own teeth and interior all
along, behind a closed face, and it never needed Carth's borrowed ones.

**What the head actually is.** A closed face shell, with teeth and a mouth
interior modelled behind it and mapped to their own corner of the texture. For
any of it to show, the shell has to part along the lip line.

**The route that remains.** Not deletion — a **topological split**: duplicate
the vertices along the lip line so the shell has two coincident boundaries
there, exactly the zero-width aperture §31 wrongly believed already existed.
Then the §34 stretch weighting parts them, with no gap at rest and no jagged
triangles, because nothing is removed. That is real mesh surgery — identifying
the loop, duplicating it, reassigning the faces above it — and is not a small
change.

**State:** installed as `out_vex_nocut/` — stretch weighting, mouth interior
seated, interior following the shell, no cut. Animations work and the mouth line
smears rather than opening, which is where §34 left it.


## 37. The topological split

**Status: built and installed, awaiting in-game confirmation.**

The mouth is parted rather than cut. The vertices along the lip line are
duplicated, the faces above the line point at the copies, and the two halves sit
on identical coordinates — invisible at rest, no gap, nothing removed, so none
of §36's triangular holes. Weighted apart by §34's stretch, they separate and
the head's own teeth and mouth interior become visible.

This is the zero-width aperture §31 wrongly believed was already in the mesh.
It was not there; now it is.

**Split by plane, not by row.** The rows of vertices near the lip line are
ragged — scattered over 0.008 in z, two to twelve vertices apiece — so there is
no clean loop to walk. Faces are classified against the lip-line plane and the
vertices that end up on both sides are duplicated, which follows the existing
edges wherever they run.

**Two guards keep it from running away**, both learned from failures already in
this file:

- Only a vertex whose *every* face is inside the mouth box is duplicated. One
  that also touches a face outside anchors the end of the slit, so the mouth
  corners stay joined.
- The box is **1.0×** the teeth's own half-width. At 1.6× the split ran past the
  lips and parted the cheek: rendered, a dark slash out to either side of the
  face.

12 vertices duplicated, 742 → 765. Rendered with culling: closed at rest, and
opening onto a dark interior with teeth.

**To validate:** installed as `out_vex_topo/`; previous build backed up at
`out_vex_topo/backup-before/`. At rest the mouth should look shut with no line
or gap. Talking, it should part and show teeth and interior rather than smearing
skin — and nothing should tear at the corners or run into the cheeks.


## 38. Where the split stands

**Status: installed. Top lip working, bottom lip not.**

Reported on §37: *"the top lip is mostly working, there is still some jagged
lines and the teeth are poking through oddly, but the bottom lip is stretching
instead of showing the inside of his mouth."*

**Fixed: the teeth poking through.** Each interior piece took the weights of its
nearest shell vertex, and the two halves of a split lip line sit on *identical*
coordinates — so "nearest" is ambiguous exactly where it must not be, and a
lower tooth could end up following the upper lip and ride up through it. Each
piece now inherits only from shell vertices on its own side of the line.

**Not fixed: the bottom lip stretching.** The obvious cause is that only the 12
split vertices carry lip weights, while the lower lip below them keeps whatever
the transfer gave it. Weighting the whole lip area by height as well — which is
what §34 did before the split existed — **tears the mouth into triangular
fangs**, because the strong lip profiles then apply to vertices the surface is
not split along, so faces span from a lifted vertex to a dropped one with
nothing between them to give. Aligning the weighting box to the split box did
not help; the problem is the breadth of the weighting, not where its edge falls.

Both attempts are rendered with culling. Reverted to split-only, which is clean
in the preview and is what §37 was reported on.

**What this points at.** To weight a broad lip area, the surface has to be split
along the *whole* boundary of that area, not just a line across the middle of
it. The current split runs one line at the lip; a broader weighted region needs
a correspondingly broader parting, or a graded falloff so no two adjacent
vertices ever differ enough to tear. The second is likely the smaller change.

**To validate:** installed as `out_vex_topo2/` — the §37 split plus the teeth
fix. Backup at `out_vex_topo2/backup-before/`. Expect the top lip as before and
the bottom lip still stretching; the teeth should no longer poke through.


## 39. The lower rim needs the jaw, and the preview cannot tell

**Status: installed, untested. The preview is blind to this change by
construction.**

Screenshots of §38 magnified show the split working: a thin sliver of teeth
appears at the lip line, so the upper half lifts. What does not happen is the
lower half dropping — below the sliver is stretched lower lip, not interior.

**The profile was the problem.** The lower rim was given the measured vanilla
lower-lip profile, which carries `f_jaw_g` at only **5%**. That is correct for a
vanilla head and wrong here. A vanilla lower lip needs no jaw weight because it
sits on a mandible that is already swinging and is carried along; measured on
Carth, his chin is 0.52 jaw while his lower-lip band is 0.04. A converted head
parted along a single line has no such carry — its rim is weighted like a lip
and travels like one.

`SPLIT_LOWER_PROFILE` puts the jaw in charge of the rim: jaw 0.55, near
lower-mouth 0.35, near corner 0.10. Strong jaw weighting is safe *here
specifically* because this is the one line the surface is parted along, so there
is no neighbour on the far side to tear away from — which is what went wrong
every time a broad region was weighted this hard.

**The preview cannot check it.** The jaw-open simulation sums every "down" bone
into a single rotation, so `f_jaw_g` and `f_llm_g` are the same thing to it and
the two builds render identically. Only the engine distinguishes them, because
only the engine moves those bones differently. Recorded because it is a real
limit on the whole method: **the simulation can test where a vertex is bound,
never which of several moving bones it is bound to.**

**To validate:** installed as `out_vex_jawrim/`; backup at
`out_vex_jawrim/backup-before/`. The upper sliver should stay and the lower lip
should now drop away from it rather than stretching. If the lower lip drops too
far, or drags the chin with it, the jaw share is too high.


## 40. The interior is at the right depth; it is the wrong colour

**Status: a measurement, not a change. The depth correction was a no-op and has
been removed.**

Asked to compare the source topology against ours. The comparison is worth
keeping, and it retracts a claim made one section earlier.

**Carth's mouth interior** is a recessed pocket: 8 vertices, 6 faces, 0.0251 to
0.0515 behind his lip surface, every one sampling the same flat dark patch of
his texture — luminance **33.7**, weighted `f_jaw_g` low, `f_um_g` high,
`head_g` around, so it opens with the mouth.

**The Jade head's** is 11 vertices at **0.0160 to 0.0494**, luminance **~127**.

| | Carth | Jade |
|---|---|---|
| nearest edge behind the lips | 0.0251 | 0.0160 |
| deepest point | 0.0515 | **0.0494** |
| texture luminance | **33.7** | **~127** |

**The depth claim was wrong.** §39's note that the Jade interior sat "three
times shallower" compared Carth's *deepest* vertices against the Jade bag's
*frontmost* point — not the same quantity. Measured like for like they are
within a few thousandths. The correction written against that reading moved the
interior by 0.0004 and has been removed rather than left looking useful.

**What actually differs is the paint.** Carth's cavity is flat near-black; the
Jade one is mid-tone pink. Geometry in the right place, four times too bright,
so an opening mouth reveals something that reads as lip rather than as a hole.
That is a texture difference and not a conversion fault — the head looks the way
its artist painted it — so darkening it is a choice about intent, not a fix.

**Method note.** Two measurements of "the same" thing taken from different ends
of an object agreed with a hypothesis and were not checked against each other.
The tell was available immediately: the correction it justified moved the mesh
by 0.0004.


## 41. The cavity is dark now, and it probably does not matter

**Status: installed. Correct on its own terms; the preview shows no visible
difference, and the reason is worth more than the change.**

Asked for the interior UVs to be remapped to a dark spot. Done: `darkest_uv`
scores every patch of the head's own atlas on brightness *and* uniformity — a
patch that is half shadow and half hair smears when a whole cavity is mapped
onto it — and `darken_interior` points all 11 interior vertices at the winner.
They now sample a flat **12.3** where they sampled ~127; Carth's cavity is 33.7.
Flat is authentic: all 8 of Carth's cavity vertices sample one patch, to the
decimal.

**The render does not change, and that is the finding.** If darkening the
interior made no visible difference, the interior is not what fills the opening.
What shows through the parted lips is stretched *shell* — the lower lip's own
outer surface — which is exactly what has been reported from the game
throughout: "the bottom lip is stretching instead of showing the inside of his
mouth."

So the interior's colour was never the lever, and neither was its depth (§40).
**The lower lip not travelling is the whole problem**, and it has survived: the
vanilla lip profile, the jaw-led rim profile (§39), the topological split, and
now this. Each of those was a real defect and none was *the* defect.

What has not been tried is the one thing every attempt has skirted: the lower
lip's *own surface*, below the split line, is weighted by proximity transfer and
nothing has ever corrected it — §38 established that weighting it broadly tears
the mesh, so it needs a graded falloff from the rim outward rather than a region
assignment. That is the next thing to build, and it should be built against a
measurement of how far the lower lip actually travels, not against a render.

**To validate:** installed as `out_vex_dark/`; backup at
`out_vex_dark/backup-before/`. Expect no visible change from the last build. If
the mouth interior *does* look darker, that is worth knowing too - it would mean
the bag is visible after all and the preview is wrong about which surface fills
the opening.


## 42. The graded falloff does not work, and why

**Status: tried, rendered, reverted. Nothing installed from it.**

The lower lip below the split rim keeps its transferred weights, so the rim
travels and the lip under it does not. §38 established that assigning the whole
area the rim's profile tears the mesh into fangs. A graded falloff — full
strength at the rim, easing to nothing with distance — was the obvious remedy:
no two neighbouring vertices then differ by more than a step, so the surface
should carry the motion instead of ripping where the assignment stops.

**It grows fangs anyway.** Rendered with culling at falloff radii of 0.5, 1.0
and 2.0 times the mouth's half-height, every one of them. The rest pose is clean
in all three; the open pose is worse than doing nothing.

Two attempts, both wrong:

- Grading the **lower** side alone moved the discontinuity rather than removing
  it. The upper rim stayed at full strength against unmanaged neighbours, and
  the fangs simply hung from the upper lip instead.
- Grading **both** sides did not help either, at any radius.

**What the spikes actually are.** They are cream-coloured — the head's own
**teeth pieces**, not shell. Those pieces take their weights from the nearest
shell vertex, and the falloff makes the shell around them strongly mobile. A
14-vertex island whose few vertices inherit sharply different weights does not
deform, it spikes.

So the falloff is not wrong in principle; it is applied to a head whose interior
pieces follow the very surface being graded. Any future attempt has to settle
what the teeth do **before** grading the shell they inherit from — most likely
by binding them rigidly to one bone each, upper and lower, rather than letting
them sample a field that is now steep.

Reverted to the §41 build, which is what was last installed and tested.


## 43. The head's own teeth were never seated

**Status: installed as `out_vex_teethback/`. THERE IS SOMETHING TO TEST.**

Reported: *"a white bar still pokes through the top lip."*

`mouthparts.seat` moves the **host's** teeth, which are separate nodes, and has
done since §29. A converted head carries its own teeth as islands *inside* the
mesh, and those had never been touched at all. Measured on the installed build:

| | clearance behind the lip surface |
|---|---|
| host's teeth (seated by §29) | 0.0085 |
| the head's own upper teeth | **0.0030** |
| the head's own lower teeth | 0.0063 |

0.0030 holds at rest — the diagnostic confirms none of the 14 sat in front of
the shell — and fails the moment the upper lip lifts, because any relative
motion over three thousandths puts them through. Which is a white bar across
the top lip.

`mouthparts.seat_islands` moves each piece back as one, by the difference
between its tightest clearance and the host's. Both now clear by 0.0085.

**The lesson is the same one as §28.** A fix was written for the host's parts and
assumed to cover the converted head's equivalents. It did not, and nothing said
so, because the two live in different places: one in nodes, one in mesh islands.
Every mouth pass in this file that touches "the teeth" should be read twice —
once for each.

**To test:** the white bar should be gone from the top lip. Everything else
should look as it did — this moves two pieces of geometry back by 0.0055 and
0.0022 and changes nothing about weights. The bottom lip will still stretch;
that is §42 and is not addressed here.


## 44. Two sets of teeth

**Status: installed as `out_vex_oneset/`. THERE IS SOMETHING TO TEST.**

The white bar survived §43's clearance fix because it was never the head's own
teeth. It was the **host's**, and they should not have been there at all.

§29 kept the host's teeth and tongue on the belief that a converted head had no
mouth interior of its own. §36 disproved that — this head's 14-vertex pieces
sample the teeth strip of its atlas and its 11-vertex bag samples the interior
patch — and nothing went back to undo §29. So both sets have been drawn in the
same small space ever since, and the host's, being sized for the host, sits
furthest forward:

| | reaches forward to |
|---|---|
| **host `teethUa01`** | **y +0.0963** |
| the head's own upper teeth | y +0.0950 |

Thirteen ten-thousandths in front, right behind the upper lip. A white bar.

The build now keeps the host's mouth interior **only when the replacement has
none of its own**, and skips seating parts it is about to hide. On this head the
visible mesh list is `['Head']` alone.

**This is the third time in this file** that a fix has been left standing after
the belief behind it was withdrawn: §30's cut after §31, §31's rims after §34,
and now §29's teeth after §36. Retracting a diagnosis has to include hunting
down what was built on it.

**To test:** the white bar across the top lip should be gone. The mouth should
still have teeth in it — the head's own, cream rather than white. The bottom lip
will still stretch (§42, unsolved).


## 45. The texture is intact; the UV remap was not safe

**Status: remap reverted, installed as `out_vex_nodark/`. THERE IS SOMETHING TO
TEST.**

Reported that the texture looked messed up "from how many times we kept cutting
at it". Checked first, because that would be a serious defect:

- the installed `j01.tga` is **byte-identical** to a fresh conversion from the
  Jade source (md5 `1ab39e7c…`, 262,162 bytes). Nothing accumulates: the pack is
  regenerated from the archive on every build;
- every one of the 754 UVs is finite and inside 0..1.

So no damage. But there was one deliberate texture-space change, §41's remap of
the interior onto the darkest flat patch of the atlas, and **it picked pixel
(3, 3)** — three texels from the corner. That is not a safe place to sample.
At distance the engine reads a low mip level whose corner texel is the average
of a large region, so the cavity's colour drifts with the camera, and edge
filtering can bleed the wrap-around.

Reverted. It was speculative, it was predicted in §41 to change nothing visible
(the interior is not what fills the opening — stretched shell is), and it
carried a real artefact. `darkest_uv` is removed with it; anything revisiting
this has to keep clear of the atlas edges *and* have reason to believe the
surface it recolours is the one being seen.

**To test:** whatever looked off about the texture should be gone. The white bar
fix from §44 stays. The bottom lip still stretches (§42).


## 46. Cutting the lip line so the seam is dense enough to be a mouth

**Status: installed as `out_vex_cutline/`. THERE IS SOMETHING TO TEST.**

Reported: *"2 little triangles you can see through the texture to the teeth on
the upper lip"* — **only while talking**, which was the answer.

Three hypotheses checked and cleared first:

- **texture damaged by repeated builds** — no; `j01.tga` is byte-identical to a
  fresh conversion and all 754 UVs are finite and in range;
- **the split causing inverted faces** — no; the 25 backward-facing faces at the
  mouth are in the raw conversion (26 before repair, 25 after) and unchanged by
  placing or splitting;
- **those faces being culled and seen through** — no; all 25 have other geometry
  in front of them, so they are an inner fold facing correctly inward.

**It was resolution.** Splitting only at existing vertices gave **twelve** points
across the whole mouth, and twelve points on geometry this coarse open into a
row of triangles rather than a mouth. Visible only while talking is exactly what
that predicts: at rest the halves coincide and there is nothing to see.

`mouthsplit.cut_along_line` now subdivides every edge crossing the lip line
inside the mouth, putting a vertex exactly on the line before anything is
duplicated. The seam went from **12 points to 32**; the head from 765 vertices
to 807, 1137 triangles to 1203.

**Cut by edge, not by face.** Subdividing a face without subdividing its
neighbour leaves a T-junction, and a T-junction is a crack. Every face using a
subdivided edge is retriangulated whether or not it was inside the mouth box,
and a test asserts no edge straddles the line where a cut point already exists.

Tests also assert the cut points land exactly on the line, that retriangulation
preserves total face area to 1e-6 (a dropped sliver is a hole, an overlapping
one z-fights), and that UVs are interpolated along the edge rather than invented.

**To test:** the two triangles should be a continuous mouth line. At rest,
nothing should have changed at all. The bottom lip still stretches (§42).


## 47. The bottom lip: rigid teeth, then the falloff

**Status: CONFIRMED IN GAME, 2026-09-03.** The mouth opens. Reported after
install: "You finally fixed it."

§42 left the falloff failing and named the reason: the interior pieces follow
the shell, so grading the shell made them sample a steep field, and a
14-vertex island whose vertices inherit sharply different weights spikes rather
than deforms. Fangs.

**The host settles it.** Carth's teeth are not skinned at all — `teethUa01` is
parented to `head_g`, `teethLa01` to `f_jaw_g`, one bone each. So the head's own
teeth are now bound the same way, rigidly, and cannot spike whatever the shell
does. 40 vertices.

With that in place the falloff works: **112 vertices either side of the rim**
eased toward its profile over 0.0183, fading to nothing, so the lip travels with
the rim instead of stretching from it. No fangs at any angle.

**The bag is *not* rigid**, and that was found the hard way. Bound to the jaw it
swings down and the top of the opening unseals — rendered against a green
background, daylight straight through the head. It lines the whole cavity, so
each of its vertices follows whichever part of the face is nearest. The host's
own tongue is skinned rather than parented, for the same reason.

**A known limit, unfixed.** With the mouth open past about four degrees of jaw
there is still a gap at the top of the cavity: this head's interior is a bag
lining the floor and sides, with nothing between the upper lip's inner edge and
the top of it. `mouthsplit.seal_cavity` was written to bridge that and is **not
called** — the bridge spans the whole opening and draws in front of the teeth
and tongue, so the mouth seals but stops having anything in it. Sealing properly
needs a strip following the palate rather than a flat span.

**Confirmed.** The bottom lip drops instead of stretching, and the mouth opens
onto its teeth and interior.

**What it took, and what that says.** The mouth thread ran from §23 to here and
the single fix was four things that each had to be right at once:

1. the face **parted** along its lip line (§37), because a converted head is
   closed there and has no seam to open - nothing was removed, so nothing
   showed at rest;
2. the line **cut first** (§46), because parting at existing vertices gave
   twelve points across the mouth and twelve points open as triangles;
3. the head's own teeth **bound rigidly**, one bone each, as the host binds its
   own - without this any weighting of the lip made them spike;
4. the lip **eased** either side of the rim, so it travels with the rim rather
   than stretching from it.

Every one of those was tried on its own at some point and failed, and each
failure was read as evidence the approach was wrong rather than incomplete.
The order mattered too: 3 had to precede 4, and 2 had to precede everything.

**Still open:** the cavity gap at wide openings (§47 above), and this is one
head. Nothing here is confirmed to generalise to the other 135 that convert.


## 48. A second head, and how far the mouth work generalises

**Status: `h_mercf01_` installed as `out_vex_mercf01/`. THERE IS SOMETHING TO
TEST.**

§47 was confirmed on one head. Swept across the whole Jade catalogue:

| | |
|---|---|
| heads | 148 |
| **teeth pieces found, so the mouth can be located** | **142** |
| **parted successfully** | **142** |
| no teeth pieces found | 6 |
| errored | 0 |

Seam density after cutting the line: minimum 10 points, median 35, maximum 64.
The minimum is worth watching — 12 points is what produced the row of triangles
in §46, so `h_bandit02_` at 10 may show that failure even with the cut.

Installed for testing: **`h_mercf01_`**, a female head, deliberately chosen to
differ structurally from `h_common01_`. 882 vertices against 765, 35 seam points
either side, 121 vertices eased around the rim, 34 bound rigidly.

**A collision found on the way.** Both heads name their texture **`j01`**, with
different content (md5 `1ab39e7c` against `269c6906`). Installing two converted
Jade heads at once means the second silently overwrites the first's texture and
one of them wears the other's face. The texture resref comes from the Jade
material and is not unique per head; it needs deriving from the head's own
resref instead. Not fixed here.

**To test:** does her mouth work the way his does — parting rather than
stretching, teeth and interior showing? That is what says the mouth work is a
property of the pipeline rather than of one model.


## 49. Eyes on the surface, and no blinking

**Status: both fixed, installed as `out_vex_eyes/` (`h_mercf01_`). THERE IS
SOMETHING TO TEST.**

Reported on both converted heads: the eyes sit on the surface of the face rather
than behind the eyeline, and neither head has ever blinked.

**Blinking.** A KOTOR head blinks with separate eyelid *meshes* — `eyeLlid` and
`eyeRlid`, 18 vertices each, **not skinned**, parented to `head_g` and moved by
the engine. The face does not deform to blink: the host's eye region is **88%
`head_g`**. The build hid those lids along with everything else that was not the
replaced node, so no converted head could ever blink. They are now always kept.

Keeping them where they were is not enough. Measured on `h_mercf01_`, the lids
sat at y +0.0977 while the head's own eyeballs reached +0.1162 — lids *behind*
eyes, 0.0396 back from a face reaching +0.1373. They would have blinked inside
the skull. `seat_eyelids` moves them to the clearance the host gives its own:
forward 0.0254, to 0.0142 behind the new face, which puts them in front of the
eyeballs where a lid belongs. Geometry rather than node position, because lids
carry a position controller and the engine reads that over the header — the same
trap as §29's teeth.

**Eyes on the surface.** The replacement's own eyeballs cleared the face by
**−0.0017** at their tightest — through it — against the **+0.0153** the host
keeps. Exactly the teeth failure from §43, on a different part. `seat_islands`
already existed for it; the eyes now go through the same path, moved back 0.0170.

**This is the fourth part of a converted head found sitting at the wrong depth**
— host teeth (§29), the head's own teeth (§43), the mouth interior (§40, which
turned out to be right), and now the eyes. Anything a head carries *behind* its
face surface should be checked against the host's clearance for it as a matter
of routine, not discovered from a screenshot.

**The first attempt removed her eyes entirely**, and the mistake is the same
one as §40. The host's clearance was measured **globally** — the frontmost point
of the face over the whole eye-height band, which sweeps in the brow and the
nose ridge — and applied against a **local** measurement taken at each eye
vertex's own spot. Carth's eyeballs read 0.0153 that way and **0.0023** locally,
seven times too much, so the eyes went 0.0170 back instead of 0.0040 and ended
up inside the skull.

`_local_clearance` now measures both sides the same way, vertex by vertex, and
every seating decision uses it. Eyes back 0.0040, teeth 0.0047, lids forward
0.0263. A `want` from one method and a `have` from another cannot be compared,
and this is the second time that exact error has cost a build.

**To test:** do her eyes sit behind the eyeline now, and does she blink?


## 50. The square mouth

**Status: fixed, installed with §49 as `out_vex_eyes2/`.**

Reported on `h_mercf01_`: the mouth *"looks square opening and closing almost
like a South Park Canadian"*.

The whole seam was weighted alike, so it opened as a rectangle. A mouth is
widest at the middle and closed at the corners. The rim's strength now tapers
with the square of the distance from the centre line — full at the centre,
nothing at the ends — and the eased region either side tapers with it.

Measured on the seam pairs, as net downward pull separating the two halves:

| | centre | corners |
|---|---|---|
| taper on | **1.03** | **0.09** |

A lens rather than a rectangle. The visual check was useless here — two
successive crops framed her chin and then her lips too closely to show the
shape - and the numbers settled it.

`h_common01_` was built and confirmed before the taper existed, so its mouth
opened as a rectangle too and was not noticed. Worth a look next time it is
installed.


## 51. Blinking is a rotation, so the pivot has to move too

**Status: installed as `out_vex_blink/` (`h_mercf01_`). THERE IS SOMETHING TO
TEST.**

The eyelids were kept (§49) and still did not blink.

**Blinking is a rotation.** In `pause1`, `eyeLlid` and `eyeRlid` carry exactly
one controller each: **type 20, orientation**. The lid turns about its node
pivot to close over the eye.

§49 moved the lid's *geometry* forward 0.0263 and left the pivot behind, so the
lid swung through an arc centred 0.0263 back instead of closing over the eye.
Moving geometry is right for the teeth, which are placed rather than turned, and
wrong for anything that rotates.

**Header and controller both, always.** Checked across every mesh node of
`p_carthh`: the header position and the position-controller value are identical
to 1e-6 on all nine. Editing one leaves the model disagreeing with itself, and
that is precisely §29 — the header was moved, the controller was not, the engine
read the controller and the teeth did not budge. `_shift_position_controller`
now writes both, and the lids come out with the two agreeing.

**A measurement trap this exposed.** `space.rest_pose` reads the *header*. For
any node with a position controller, a model-space measurement taken through it
is only as good as the two agreeing — which they do in vanilla and did not in
anything this project edited header-only. Every measurement of a controller-
carrying node before this is suspect.

**To test:** does she blink? Eyes and mouth should be unchanged from the last
build.


## 52. The eyelids are hidden again, and blinking is given up on

**Status: installed as `out_vex_nolids/`. THERE IS SOMETHING TO TEST — and it is
a rollback, not a fix.**

Reported on `out_vex_blink`: the whole eye moves around the face, still no
blinking, **and the game freezes after talking to her**.

The freeze is the reason this stops here. It was never explained. The controller
edit reads as structurally correct against vanilla's own layout — `p_carthh`'s
eyelid position controller is `type 8, rows 1, datakey 1, columns 3` over data
`[time, x, y, z]`, which is exactly what was written, and the model validated.
An unexplained hard failure in someone's game is not worth a blink.

**Why keeping the host's lids cannot work anyway.** They are rigid meshes placed
*and pivoted* for the host's eyes. A converted head's eyes are elsewhere. Seated
by geometry, the lid swings about a pivot left behind (§51). Seated by pivot as
well, the eye roams. There is no placement of a lid built for one face that fits
another.

**So a converted head does not blink, and the reason is in the source.** Jade
heads carry eyeballs but no eyelid geometry, and the face does not deform to
blink either — the host's eye region is 88% `head_g`. Blinking would need lids
*built for this head*, which is authoring, not conversion.

**What was kept from the eye work:** the eyes are still seated behind the
eyeline (§49, corrected in §50), which was the other half of the report and does
work.

**Rolled back:** `is_eyelid` and `seat_eyelids` remain in the source, unused,
with the reasoning attached. Visible mesh on a converted head is `Head` alone.

**To test:** no freeze, and no eye wandering across her face. She will not blink.


## 53. The eyeballs were following the brow

**Status: installed as `out_vex_rigideyes/`. THERE IS SOMETHING TO TEST.**

Reported after §52: the brow appears to sit at the eyes, and the *eyes* move
around the face when only the brow should.

Measured on the installed build, the head's own eyeballs were bound:

| | |
|---|---|
| eye 1 | **`f_lbrw_g` 47%**, `head_g` 40%, `f_mdbrw_g` 13% |
| eye 2 | **`f_rbrw_g` 49%**, `head_g` 38%, `f_mdbrw_g` 13% |

Nearly half of each eyeball on a brow bone. Proximity transfer takes the bone
nearest a vertex, and at the eye line that is the brow — so every brow movement
swung the eyes.

The host does not do this: `eyeLA` and `eyeRA` are **not skinned**, parented to
`head_g`. An eyeball does not deform and does not follow a brow. The head's own
eyes are now bound the same way, rigidly to the skull, through the path the
teeth already use. Both come out `head_g` 100%.

**Third part of a converted head found taking whatever bone was nearest**, after
the teeth (which spiked into fangs) and the mouth interior (which sailed out
through the opening). Proximity transfer is right for a surface and wrong for
every rigid piece behind one. The rule is now explicit in `lips.bind`: anything
the head carries as its own island — teeth, eyes — is bound rigidly to the bone
the host uses for it, and only the face itself is transferred.

**To test:** do her eyes stay put when her brows move?
