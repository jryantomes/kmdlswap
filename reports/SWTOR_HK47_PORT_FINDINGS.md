# Porting The Old Republic's HK-47 onto KOTOR's p_hk47

**Dates:** 2026-09-11 to 2026-09-13
**Result:** working in game. TOR HK-47's model and texture on KOTOR's `p_hk47`,
with his vanilla animations, new party portraits, and a TSLPatcher package.
**One open problem:** the left hand does not reach the rifle foregrip.
**Scripts:** `tools/swtor_hk47/` (see its README).
**Package:** `builds/hk47-tor-tslpatcher/` and `builds/hk47-tor-tslpatcher.zip` (gitignored).

Every claim below was either measured or confirmed in a game screenshot. Where
something was believed and turned out wrong, the wrong version is recorded too,
because each one cost a test cycle.

---

## 1. Reading The Old Republic's files

Everything `src/kmdlfun/swtor.py` already documents for heads still holds: MYP
v6 archives, Zstandard payloads, hashed entry names, `.gr2` read by content.

- **Use the project venv.** `.venv/Scripts/python.exe` has `zstandard`. The
  system Python does not, and `read_block` then fails on every entry. A first
  scan reporting "0 models" in an archive is this, not an empty archive.
- **Where droids are.** `swtor_main_art_creature_a_1.tor`, `_b_1`, `_c_1`:
  715 models between them. A droid-name sweep finds 153, including
  `assassin_hk47_a01`, `assassin_hk51_a01/a02`, `assassin_hk55_a02`, about 26
  humanoid assassin droids, 25 battle droids, 11 astromechs, 46 probe droids.
  `creature_npc` holds only 58 models, none of them droids.
- **Naming.** Creature models are `<family>_<variant>_aNN`, and the model names
  its own material `<model>_v01`.

### The skinned vertex layout

`swtor.py` never needed skin data for heads. In a 32-byte skinned vertex
(flags `0x12f`):

| Offset | Contents |
|---|---|
| 0 | position, 3 float32 |
| 12 | 4 weight bytes, always summing to 255 |
| 16 | 4 bone index bytes, into the mesh's bone list |
| 20 | packed normal (see `normal_offset`) |
| 28 | UV0 as two float16 |

Checked on HK-47: weights sum to 255 on 100% of vertices, indices are all below
the bone count. Reading 12 as indices and 16 as weights gives garbage.

### Droids are rigid

TOR droids are one skinned mesh, but the skin is effectively rigid:

| Model | Vertices bound to one bone at 0.99+ | Triangles inside one bone |
|---|---|---|
| assassin_hk47_a01 | 90.4% | 90.6% |
| battledroid_combat_a01 | 97.7% | 98.1% |
| astromech_t7_a01 | 98.1% | 94.7% |

So splitting a droid into KOTOR's rigid parts is a dominant-bone partition,
the same rule `jade.partition` uses.

### Bones

HK-47 has 40 bones, a plain biped: `Root, Pelvis, LowerBack, Chest, Chest1,
Chest2, Neck, Neck1, Head`, and per side `Hip, Knee, Ankle, Toe, Collar,
Shoulder, Elbow, Wrist, ThumbFinger, IndexFinger/1/2, MiddleFinger/1/2`.
The mesh stores only a flat name list; the hierarchy is inferred from the names
(`PARENT` in `build_hk2.py`).

### Axes and scale

- `swtor.mesh()` returns KOTOR axes and metres. It faces **-y**, as heads do.
- KOTOR bodies face **+y**, so a body needs a **180-degree yaw**: negate x and
  y on positions and normals. This is a rotation, so winding survives.
- The yaw also swaps sides: TOR `Left*` bones land on KOTOR `L_*` nodes.
- **Humanoid droids are 1:1.** TOR HK-47 is 2.08 m, KOTOR's 1.99 m. No
  `HEAD_SCALE`-style fudge. Astromechs are not: TOR's T7 is 1.50 m, KOTOR's
  about 0.8 m.
- **Rest pose matches.** Both skeletons stand with arms straight down, so no
  arm-swing correction like Jade's.

A head render once looked backwards. It wasn't: `head_three.png`-style strips
(vanilla / donor as read / built, four yaws) settled it. The dark texture of the
first build made a face read as the back of a helmet.

---

## 2. Textures

### Finding the right file

Entry names are hashed and DDS files carry no name, so the path in a material
cannot be looked up directly. What is in the archive:

- The model names its material (`assassin_hk47_a01_v01`, a string in the `.gr2`).
- The material is plaintext XML in the same archive, naming its textures:
  `DiffuseMap` `..._d`, `RotationMap1` `..._n` (normal), `GlossMap` `..._s`,
  `PaletteMaskMap`. For droids the palette mask is `art\defaultassets\black`
  (244 of 316 creature materials), so **no palette recolouring**: the diffuse is
  the final colour.
- Around HK-47 the archive stores each asset as an **11-entry block**:

| Entry | Contents |
|---|---|
| 200 | model `assassin_hk47_a01` |
| 201 | material XML |
| 202-204 | three TextureObject XMLs |
| 205-207 | diffuse 128, normal 128, gloss 64 |
| 208-210 | **diffuse 1024**, normal 1024, gloss 512 |

HK-51's model is 211 and its textures follow it the same way.

**The textures follow their model.** The first build took entries 197-199,
the three before the model. Those belong to `assassin_enforcer_a01`, and HK-47
came out dark grey with a cyan chest emblem. The user caught it against a real
SWTOR screenshot.

**How it was confirmed:** paint each candidate onto the real UVs and render.
Entry 208 put panel lines, knee discs and the chest plate on the matching
geometry; 197 smeared them. A UV-coverage mask cannot discriminate (the atlas
fills 78% of the sheet), so rendering is the test.

**The block rule is not general.** Across 536 models in `creature_a` and
`creature_c`, exactly 56 are followed by the full block. HK-47 sits in a tidy
run of assassin droids. For other droids, render candidates or lift the SWTOR
Slicers name hash.

Entry 208 is DXT5 but its alpha is 255 everywhere. UVs run to u 1.98 on some
parts: that is genuine wrap tiling, fine in KOTOR.

### Row order: the engine ignores the TGA origin flag

This cost two test cycles, one per texture type, and the two types need
**opposite** orders:

| Texture | Row order the file must use | Symptom when wrong |
|---|---|---|
| Model texture (sampled by UV) | first row in file = **top** of image | head samples a dark panel from the bottom of the atlas; body stays roughly orange but smeared |
| GUI portraits (`po_*`) | first row in file = **bottom** of image | portrait and party image drawn upside down |

- Pillow writes TGAs bottom row first with the matching flag, and honours the
  flag on read. So a Pillow round trip always looks right, and offline renders
  can never catch this.
- The model-texture symptom was diagnosed by rendering with the atlas rows
  reversed, which reproduced the screenshot exactly. Head mean colour upright
  (101, 54, 42), mirrored (57, 43, 40).
- The silhouette was diagnosed by correlating the in-game slot crop with our
  file: 0.927 flipped, -0.09 upright.
- Writers: `write_tga` in `tex_out.py` (top down, descriptor `0x28`) for model
  textures; `write_tga` in `portrait_render.py` and `gui_bottom_up.py`
  (bottom up, descriptor `0x08`) for GUI.

### Reflection

- **Vanilla droid textures do carry alpha.** `P_HK47_01` and `C_DrdWar01` are
  TPC DXT5 with a real alpha channel (HK-47: 256 distinct values, mean 192)
  and a TXI of `envmaptexture mycube` / `CM_Baremetal`. The alpha masks the
  environment map: bright is matte, dark is mirror.
- **`textures._decode_tpc` converts to RGB and hides the alpha.** An early
  claim that vanilla droid textures had no alpha came from this. Use
  `read_tpc(...).convert(TPCTextureFormat.RGBA)` when alpha matters.
- A full-strength gloss-derived mask was tried first (alpha = 255 - gloss luma,
  mean 212). The user then asked for no shine (TXI removed, alpha 255), then a
  very weak one. **Shipped:** alpha = 255 - 0.3 x gloss luma from entry 210,
  mean 242, min 178, with `envmaptexture mycube`.
- An earlier theory that missing alpha caused the grey head was wrong; that
  was the row-order bug above.

---

## 3. KOTOR's p_hk47

- 3,672 nodes, 45 drawn mesh nodes, **all rigid, none skinned**, 2,467
  triangles, one texture `P_HK47_01`.
- **No supermodel.** All 75 animations are inside the file. So "make the
  supermodel work" means editing this file's own skeleton.
- Spine: `rootdummy -> InnerTorso -> Fore_body -> Neck -> Hturn_g -> head`,
  with `Pelvis` a sibling of `InnerTorso` under `rootdummy`. Hooks: `rhand`
  under `L_hand01` (the right hand, misnamed), `lhand` under `L_hand`,
  `Impact`, `lforearm`, `handconjure`, `talkdummy`.
- **Animation position keys on limb and torso nodes are all zero.** Only
  `rootdummy` carries real positions. Animations turn limbs and never place
  them, so **a node's rest position alone decides its pivot.** This is what
  made fitting the skeleton safe.
- Rest position lives in the node header **and** a single-key position
  controller, and the engine reads the controller. Move both:
  `mouthparts._shift_position_controller`.
- Header quaternion is stored **w, x, y, z**; controller rows **x, y, z, w**
  (`pose_render.header_order` detects it).
- Rotation keys are uncompressed 4-column quaternions throughout this model.
- Spine swing, degrees: walk InnerTorso 15.8, attack `b5a1` 37.9, `g1z1` 73.
  Neck up to 66 (`g8a1`), head up to 77 (`castout1`).
- Right-hand finger nodes hold identical angles in every animation; left-hand
  fingers move 10-20 degrees in rifle stances. Vanilla does not close its hands
  by animation.

---

## 4. The build, and what failed on the way

Final build logic: `build_hk5.py`, then `apply_hook.py` with `grip_opt_t5.json`.

### Partition and mapping

Vertex to its dominant bone, triangle to the node most corners agree on,
explicit bone-to-node `MAP` in `build_hk2.py`. Right-hand fingers:
thumb `F-10`, index `F-07/F_07/RTrgrFngr`, middle `F-08/F_08` (TOR's third
middle segment rides with the second). Left mirrors with `F-5`, `F-1/F_1/LTrgrFngr`,
`F-2/F_2`. Unmatched nodes are hidden with `visibility.hide_nodes`: `Mesh01`,
spare fingers, `L_hose`, `R_hose`, `TorsoHoses`.

Rebuilt geometry leaves vanilla's stored bounding boxes by up to 19 cm.
`widen_bounds` grows box and radius, never shrinking vanilla's slack.

### Placement: three attempts

| Attempt | What | Result in game |
|---|---|---|
| Donor positions (`build_hk2 none`) | geometry where TOR puts it, host pivots | perfect standing, arms detach when walking. Mean pivot error 11.3 cm, worst 15.2 |
| Joint-aligned (`build_hk2 joint`) | move each part onto the host's joint | pivots exact, joins open to 3 cm, wider stance. User rejected: "don't graft old HK bones onto new HK" |
| **Skeleton fitted** (`build_hk3`) | geometry stays at donor positions; each node's rest position moved to TOR's joint | worked; much closer |

A single global transform was also measured and rejected: a uniform fit only
brings mean pivot error to 8.0 cm, and a per-axis fit's y scale is
ill-conditioned (joints have almost no y spread).

### Finding TOR's joints

Two methods, preferring the first:

1. **Blend:** vertices carrying over 0.15 weight from a bone and one of its
   ancestors sit on the joint; take their mean.
2. **Contact:** for rigid joints with no blend, the mean of the child chunk's
   vertices in the nearest 15% to the parent chunk.

They agree to 42 mm mean over the 20 joints that have both, worst 16 cm at the
knee. Shoulders, elbows, wrists, ankles, toes and thumbs have no blend and use
contact. A part spanning several bones hangs from the highest bone in the chain
(`anchor_of`).

### Torso tear: keep armour pieces whole

TOR skins single armour pieces across several bones: the waist ring stack
across five spine bones, each finger across three joints, each knee cap across
thigh and shin. The triangle vote cut **22 of the donor's 59 connected pieces**
across nodes the animations turn independently, so they tore.

Each piece now goes wholly to one node. Pieces are found by shared vertices
plus coincident positions (`pieces_probe.pieces`). Three rules were rendered at
real animation frames (`pose_render.py`):

| Rule | Outcome |
|---|---|
| majority of triangles | fingers splayed off the hand |
| rootmost node | knees broke in the attack |
| **region**: node whose vanilla geometry box holds most of the piece | waist whole at walk, attack, and the 73-degree twist. Shipped |

Consequence: fingers and toes are now rigid with the hand and foot.

### Neck

The neck column was a single piece given to `head`, so nods dragged its base
across the chest. And the pivots were scattered: Neck 6.6 cm behind centre,
`Hturn_g` 5.6 cm behind and 5 cm above the head. Fix in `build_hk5.py`: the
column goes to `Neck`, and `Neck`, `Hturn_g`, `talkdummy` and `head` all sit on
the column's own measured axis, x 0, y -0.095. **Move chain nodes in file
index order**; the first attempt moved them in list order and left `talkdummy`
off the line.

### Validation used throughout

`kmdlswap.validate.check` (identity round trip, no gaps, overlaps, dangling
offsets); header/controller agreement on all 57 nodes; `gaps.py` minimum
distance at every join; `pose_render.py` for real animation frames.

---

## 5. Weapon grip (partly open)

- Weapons hang from `rhand`. The hook kept vanilla's wrist offset, so the rifle
  sat beside TOR's hand. `grip_fit.py` moves both hooks so the weapon line
  passes as close to the hand centre as vanilla's (1.7 cm right, 1.6 cm left):
  moves of 3.0 and 4.3 cm, in the hand's frame (`grip_fit.json`).
- The rifle animations place the left hand for vanilla's arms, not TOR's.
  `grip_opt.py` searched slide and tilt of the rifle in the right hand over
  64 two-handed frames of `g7r1, g7w1, b7a1-4`:

| Tilt cap | Slide | Tilt | Left hand along the barrel, RMS error vs vanilla |
|---|---|---|---|
| none | - | - | 7.4 cm |
| 0 | +5.0 cm | 0 | 3.1 cm |
| **5 (shipped)** | +5.0 cm | 3.2 | 3.2 cm |
| 12 | +5.0 cm | 14.8 | 3.2 cm |

  Tilt is capped because pistols share the hook.
- **Finger curl failed** (`build_hk6.py`, not shipped). Baking a grip into TOR's
  skinned fingers with linear blend skinning bent them cleanly, but at every
  strength from 0 to 1 the fingertips stayed about as far from the grip:
  right middle 2.2 to 1.6 cm, left index 8.6 to 7.5, left thumb 8.2 to 8.9.
  Fingers are not the problem; hand position is.
- **Open:** the left hand stops 6-9 cm short of the foregrip in game. The
  likely fix is changing the left arm's rest angles so unchanged animations
  deliver the hand to the foregrip. That alters the arm in every animation and
  was not attempted. Also, TOR hands are modelled open, so fingers never wrap.

---

## 6. Party portraits

- `portraits.2da` row 34: `baseresref po_phk47`. Three textures, in
  `TexturePacks/swpc_tex_gui.erf`:

| File | Size | Use |
|---|---|---|
| `po_phk47` | 64 | colour icon |
| `po_phk472` | 64 | silhouette (black on blue scanlines) |
| `po_phk473` | 256 | full body, party selection, red haze |

- Vanilla TPCs decode upside down in Pillow terms (stored bottom first);
  `gui/*_up.png` are flipped copies.
- **Rendering with clean edges:** render twice, on black and on white;
  alpha = 1 - mean(white - black), colour = black / alpha
  (`portrait_render.render_rgba`). Backgrounds are rebuilt from vanilla: the
  red haze with the old figure painted out by a weighted blur of the outer
  thirds plus scattered grain; slate gradient from the icon's corner; scanline
  colours per row from the old silhouette.
- **Renderer yaw and pitch are radians.** An early pass passed degrees, so a
  "35" turned the camera 35 radians.
- Shipped poses (`portrait_posed.py`, `icon_level.py`):
  - **Icon:** first frame of `g7r1` (rifle ready) with a textured
    `w_blstrrfl_001` on `rhand`; camera yaw -35 degrees, pitch -6; extra head
    turn +25 degrees (the user asked 35, then "10 to his right", which is
    -10 with this sign); radius 0.25; frame lowered until the head top sits on
    **row 11**, vanilla's silhouette row.
  - **Silhouette:** the icon's coverage over vanilla's scanlines.
  - **Party image:** first frame of `pause1` (idle), front on, lower legs
    fading into the haze.

---

## 7. TSLPatcher package

`builds/hk47-tor-tslpatcher/tslpatchdata/`: `changes.ini`, `info.rtf`, and
seven files installed to Override with `Replace` entries:
`p_hk47.mdl/.mdx`, `tor_hk47.tga/.txi`, `po_phk47/472/473.tga`.
`LookupGameNumber=1`, no 2DA or GFF edits.

Tested with PyKotor's `pykotor.tslpatcher` `ConfigReader` and `ModInstaller`
into a throwaway game folder (`validate_tslpatcher.py`): all seven land
byte-identical. HoloPatcher runs on PyKotor, but a released HoloPatcher exe was
not run. Note: the model and texture are The Old Republic's assets, and the
MDL is built on BioWare's `p_hk47`.

---

## 8. Working practice that mattered

- **Game screenshots** are in
  `C:\Program Files (x86)\Steam\userdata\64841303\760\remote\32370\screenshots\`.
  When the user says "took screenshots", read the newest there.
- **Compare screenshot times with install times.** Two "still upside down"
  shots were taken seconds before the fix reached Override.
- **Brighten and crop before judging.** Shadow read as a seam once; the chrome
  wash hid joins for a whole cycle.
- **Offline renders cannot see:** row-order bugs (Pillow always reads upright),
  environment maps, or engine lighting. Reproduce the symptom deliberately
  instead, as the reversed-atlas render did.
- Install with `kmdlfun.install.apply` (manifest-tracked, refuses to overwrite
  files it did not install); `install.remove` restores vanilla.
