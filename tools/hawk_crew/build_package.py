"""Ebon Hawk Crew at Work - its HoloPatcher package (a package of its own, not part of GH0-RFK).

    builds/hawk-crew-holopatcher/
      tslpatchdata/        changes.ini, info.rtf and the files: hcw_work, Jolee's bed models, the
                           datapad's item and model, an empty modloadscripts.2da and the vanilla
                           globalcat.2da and animations.2da (patched only where Override has none)
      Kotor Patch Manager/ ModuleLoadScripts.kpatch (starts the routine) and AnimationRows.kpatch
                           (plays Jolee's bed pose), their additional files (tools/kpm_patches;
                           python build.py ModuleLoadScripts AnimationRows first)
      README.txt, LICENSE-KotorPatchManager.txt

The installer:
  Override   every file Replaced (a reinstall updates them), except modloadscripts.2da: File - put in
             only where none exists, so other mods' rows stay - and hcw_work.ncs, which HACKList installs
  globalcat.2da      + HCW_GEN (a number; once - ExclusiveColumn)
  modloadscripts.2da + ebo_m12aa -> hcw_work (once - ExclusiveColumn script: no other mod names hcw_work)
  animations.2da     + hcw_bedlie (dance's flags; once - ExclusiveColumn name), its row kept as 2DAMEMORY1
  hcw_work.ncs       HACKList: that row into CW_BEDLIE_RAW's constant (placeholder 0x12340000). HoloPatcher
                     (PyKotor) writes 2DAMEMORY tokens as 32 bits there, TSLPatcher as 16 - row, or
                     row * 65536 over the placeholder's zero low half; hcw_work reads both
No module is touched: a module.ifo hook would not reach a save that has been aboard, and this
PyKotor's Capsule.add drops patches made inside a .mod (validate_holopatcher.py's workaround).

usage: build_package.py
"""
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import install                                                                   # noqa: E402
import jolee_bed                                                                 # noqa: E402

ROOT = HERE.parents[1]
OUT = ROOT / "builds" / "hawk-crew-holopatcher"
DATA = OUT / "tslpatchdata"
KPM = ROOT / "builds" / "kpm"
PATCHES = {"ModuleLoadScripts": "Module Load Scripts (KotOR I)", "AnimationRows": "Animation Rows (KotOR I)"}
SCRIPT = "hcw_work.ncs"
VERSION = "0.2.0"

README = f"""Ebon Hawk Crew at Work {VERSION} - KotOR I

The crew standing aboard the Ebon Hawk get on with things while you are away: Carth at the cockpit
console, T3-M4 welding and at the holotable, Zaalbar, Mission and Canderous at consoles near their
spots, HK-47 keeping watch, Bastila and Juhani meditating, and Jolee lying back on the medical bed
with his datapad. Each moves between a few stations near their own spot.
They stop for conversations and fights, never stand in your way, and party members are left alone.

NEEDS Kotor Patch Manager (Lane Dibello's) with two patches from this folder:
  * Module Load Scripts - starts the routine whenever the Hawk loads, including in games already
    under way. Without it the mod does nothing.
  * Animation Rows - plays Jolee's lying-back pose, an animation of its own. Without it he stands at
    the foot of the bed instead.

Install
  1. Run HoloPatcher on tslpatchdata (this folder's installer) and pick your KotOR I folder.
  2. In Kotor Patch Manager, add both .kpatch files from this folder's "Kotor Patch Manager" folder,
     tick "Module Load Scripts (KotOR I)" and "Animation Rows (KotOR I)" and apply.
     KotOR I 1.03 (GOG or Steam).
  3. Load any save - new or old. The crew start on the next boarding (or at once, if you are aboard).

Either order works. The patch manager step is shared: if another mod already had you install either
patch, skip it.

Notes
  * Jolee's Datapad is a real item (Jedi Consulars only). He holds it while he is on the bed and
    you are near; otherwise it is gone and his own weapon is back in his hand, so it never leaves
    the ship with him.
  * His pose is a new animation ("hcw_bedlie") added to his body models - no animation the game
    already has is changed, so nobody else who shares those bodies (the player included) is
    affected.
  * Works alongside the K1 Community Patch and GH0-RFK. Another mod that replaces Jolee's body models
    (P_JoleeBB, PMBCM..PMBJM) loses his lying-back pose, or this mod replaces theirs - whichever is
    installed last.
  * Uninstall: delete the Override files the installer added (its log lists them) and untick the
    patches. The rows added to globalcat.2da, modloadscripts.2da and animations.2da can stay.

The patches (Kotor Patch Manager):
  * Module Load Scripts: after a module's own load script, it runs every script modloadscripts.2da
    names for that module (columns: module, script; "all" for every module). Any mod can add rows.
  * Animation Rows: PlayAnimation / ActionPlayAnimation with 20000 + an animations.2da row plays that
    row - so a mod can add animations under names of its own.
Module Load Scripts links the Patch Manager's GameAPI library - see LICENSE-KotorPatchManager.txt.
"""


def anim_row_values():
    """The hcw_bedlie row: the vanilla ROW_LIKE row's flags under the new name."""
    from pykotor.resource.formats.twoda import read_2da
    t = read_2da(base_animations())
    names = [t.get_row(i).get_string("name").lower() for i in range(t.get_height())]
    like = t.get_row(names.index(jolee_bed.ROW_LIKE))
    return {**{h: like.get_string(h) for h in t.get_headers()}, "name": jolee_bed.SLOT}


def base_animations():
    from pykotor.extract.installation import Installation, SearchLocation
    from pykotor.resource.type import ResourceType
    return Installation(str(install.GAME)).resource("animations", ResourceType.TwoDA, [SearchLocation.CHITIN]).data


def changes_ini(names, row_offset):
    L = []
    add = L.append
    add("[Settings]")
    add("FileExists=1")
    add(f"WindowCaption=Ebon Hawk Crew at Work {VERSION}")
    add("ConfirmMessage=Installs Ebon Hawk Crew at Work. It needs Kotor Patch Manager with the Module "
        "Load Scripts and Animation Rows patches (in this mod's folder). Continue?")
    add("LogLevel=3")
    add("InstallerMode=1")
    add("BackupFiles=1")
    add("PlaintextLog=0")
    add("LookupGameFolder=0")
    add("LookupGameNumber=1")
    add("SaveProcessedScripts=0")
    add("")
    add("[InstallList]")
    add("install_folder0=Override")
    add("")
    add("[install_folder0]")
    for i, name in enumerate(n for n in names if n != SCRIPT):
        add(f"Replace{i}={name}")
    add(f"File0={install.TABLE}")            # File: an existing table (other mods' rows) is kept
    add("")
    add("[2DAList]")
    add("Table0=globalcat.2da")
    add(f"Table1={install.TABLE}")
    add("Table2=animations.2da")
    add("")
    add("[globalcat.2da]")
    add("AddRow0=hcw_global")
    add("")
    add("[hcw_global]")
    add("ExclusiveColumn=name")
    add(f"name={install.GLOBAL[0]}")
    add(f"type={install.GLOBAL[1]}")
    add("")
    add(f"[{install.TABLE}]")
    add("AddRow0=hcw_load")
    add("")
    add("[hcw_load]")
    add("ExclusiveColumn=script")
    add(f"module={install.ROW['module']}")
    add(f"script={install.ROW['script']}")
    add("")
    add("[animations.2da]")
    add("AddRow0=hcw_anim_bedlie")
    add("")
    add("[hcw_anim_bedlie]")
    add("ExclusiveColumn=name")
    for k, v in anim_row_values().items():
        add(f"{k}={v}")
    add("2DAMEMORY1=RowIndex")
    add("")
    add("[HACKList]")
    add(f"Replace0={SCRIPT}")
    add("")
    add(f"[{SCRIPT}]")
    add(f"{row_offset}=2DAMEMORY1")          # CW_BEDLIE_RAW: Jolee's bed pose's animations.2da row
    add("")
    return "\r\n".join(L)


INFO = (r"{\rtf1\ansi{\fonttbl{\f0 Arial;}}\f0\fs20 Ebon Hawk Crew at Work " + VERSION + r"\par\par "
        r"The crew aboard the Ebon Hawk work at stations near their spots - consoles, the workbench, "
        r"the holotable - Bastila and Juhani meditate, and Jolee lies back on the medical bed with "
        r"his datapad.\par\par "
        r"NEEDS Kotor Patch Manager with the Module Load Scripts and Animation Rows patches (Kotor "
        r"Patch Manager folder, beside this installer): the first starts the routine whenever the Hawk "
        r"loads, in new and old games alike; the second plays Jolee's pose. See README.txt.\par}")


def main():
    for patch in PATCHES:
        if not (KPM / f"{patch}.kpatch").exists():
            raise SystemExit(f"{KPM / patch}.kpatch is missing - run tools/kpm_patches/build.py {patch} first")
    if OUT.exists():
        shutil.rmtree(OUT)
    DATA.mkdir(parents=True)
    files = install.override_files()          # hcw_work.ncs with the placeholder: HACKList writes the row
    for name, data in files.items():
        (DATA / name).write_bytes(data)
    row_offset = install.row_offset(files[SCRIPT])
    (DATA / install.TABLE).write_bytes(install.base_table())
    # the vanilla tables: HoloPatcher patches Override's copy, else this one - never the BIFs
    # (build_holopatcher.py stage_base_files; an Override without one skipped the HCW_GEN row)
    from pykotor.extract.installation import Installation, SearchLocation
    from pykotor.resource.type import ResourceType
    res = Installation(str(install.GAME)).resource("globalcat", ResourceType.TwoDA, [SearchLocation.CHITIN])
    (DATA / "globalcat.2da").write_bytes(res.data)
    (DATA / "animations.2da").write_bytes(base_animations())
    names = sorted(files)
    # UTF-8 without a BOM (build_holopatcher.py: a BOM broke HoloPatcher's ini reader)
    (DATA / "changes.ini").write_text(changes_ini(names, row_offset), encoding="utf-8", newline="")
    (DATA / "info.rtf").write_text(INFO, encoding="cp1252")
    kp = OUT / "Kotor Patch Manager"
    kp.mkdir()
    for patch in PATCHES:
        shutil.copy2(KPM / f"{patch}.kpatch", kp / f"{patch}.kpatch")
        extra = KPM / f"{patch} additional files"
        if extra.exists():
            shutil.copytree(extra, kp / f"{patch} additional files")
    shutil.copy2(KPM / "LICENSE-KotorPatchManager.txt", OUT / "LICENSE-KotorPatchManager.txt")
    (OUT / "README.txt").write_text(README, encoding="utf-8", newline="\r\n")
    staged = sorted(p for p in OUT.rglob("*") if p.is_file())
    print(f"staged {len(staged)} files in {OUT}; hcw_work.ncs row at offset {row_offset}")


if __name__ == "__main__":
    main()
