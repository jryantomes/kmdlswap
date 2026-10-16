# tools/swtor_hk47

The scripts behind `reports/SWTOR_HK47_PORT_FINDINGS.md`: The Old Republic's
HK-47 on KOTOR's `p_hk47`. Research scripts, not part of `kmdlfun`. Run them
with the project venv, `.venv/Scripts/python.exe`, which has `zstandard`.

Install paths are hard-coded to `E:\SteamLibrary\steamapps\common\swkotor` and
`...\Star Wars - The Old Republic\Assets`. Scripts find each other and their
data folders next to themselves (`Path(__file__).parent`).

## Data folders the scripts expect beside them (not in git)

They hold game-derived files, so they are not committed. Recreate them:

| Folder | Made by |
|---|---|
| `hk_skel/` | `build_hk3.py hk_skel`, plus `tor_hk47.tga` and `.txi` copied in |
| `hk_tex/` | the weak-reflection texture: diffuse entry 208, alpha 255 - 0.3 x gloss (entry 210) luma, top-down TGA, `envmaptexture mycube` TXI |
| `gui/` | vanilla `po_phk47`, `po_phk472`, `po_phk473` from `swpc_tex_gui.erf`, saved as `<name>_up.png` flipped upright |

## Reproducing the shipped build

1. `tex_out.py hk_skel/tor_hk47.tga` - diffuse from entry 208 (edit for the alpha you want)
2. `build_hk3.py hk_skel` - skeleton fitted to TOR's joints
3. build `hk_tex/` as above
4. `build_hk5.py hk_neck` - whole armour pieces, neck straightened, grip hooks, weak reflection
5. `apply_hook.py hk_neck hk_grip grip_opt_t5.json` - rifle slide and tilt in the right hand
6. `portrait_posed.py hk_grip portraits_final_a final 25` - party image from `pause1`
7. `HEAD_TURN=25 icon_level.py hk_grip portraits_turn25` - icon and silhouette, head top on row 11
8. `gui_bottom_up.py <the three po_*.tga>` - GUI row order (portrait_render now does this itself)
9. copy into `tslpatchdata/` with `changes.ini` and `info.rtf`; check with
   `validate_tslpatcher.py <tslpatchdata> <game> <scratch>`

## What each script is

| Script | Role |
|---|---|
| `build_hk2.py` | shared core: bone map, skeleton, joint finding, donor reader, bounds widening; also the donor-positions and joint-aligned builds |
| `build_hk3.py` | skeleton fitted to donor joints |
| `build_hk4.py` | whole armour pieces, three assignment rules |
| `build_hk5.py` | shipped model logic |
| `build_hk6.py` | finger curl experiment, did not help, not shipped |
| `pieces_probe.py` | connected armour pieces and which were split |
| `jointfind.py` | blend vs contact joint estimates |
| `gaps.py` | minimum gap at every join |
| `pose_render.py` | draw a build at a real animation frame |
| `grip_render.py`, `two_hand_probe.py` | weapon on the hook; both hands against the rifle through an animation |
| `grip_fit.py`, `grip_opt.py`, `apply_hook.py` | hook placement, slide/tilt search, apply to a build |
| `neck_probe.py`, `torso_hand_probe.py` | measurements behind the neck and torso fixes |
| `tex_out.py` | texture extraction and top-down TGA writer |
| `portrait_render.py`, `portrait_posed.py`, `icon_level.py`, `gui_bottom_up.py` | portraits |
| `validate_tslpatcher.py` | parse and test-install a tslpatchdata folder with PyKotor |
