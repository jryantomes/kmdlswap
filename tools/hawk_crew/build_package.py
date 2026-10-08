"""Ebon Hawk Crew at Work - its HoloPatcher package (a package of its own, not part of GH0-RFK).

    builds/hawk-crew-holopatcher/
      tslpatchdata/        changes.ini, info.rtf and the files: hcw_work, Jolee's bed models, the
                           datapad's item and model, an empty modloadscripts.2da and the vanilla
                           globalcat.2da (patched only where Override has none)
      Kotor Patch Manager/ ModuleLoadScripts.kpatch, its additional files and licence - what starts
                           the routine (tools/kpm_patches; python build.py ModuleLoadScripts first)
      README.txt

The installer:
  Override   every file Replaced (a reinstall updates them), except modloadscripts.2da: File - put in
             only where none exists, so other mods' rows stay
  globalcat.2da      + HCW_GEN (a number; once - ExclusiveColumn)
  modloadscripts.2da + ebo_m12aa -> hcw_work (once - ExclusiveColumn script: no other mod names hcw_work)
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

ROOT = HERE.parents[1]
OUT = ROOT / "builds" / "hawk-crew-holopatcher"
DATA = OUT / "tslpatchdata"
KPM = ROOT / "builds" / "kpm"
PATCH = "ModuleLoadScripts"
VERSION = "0.1.0"

README = f"""Ebon Hawk Crew at Work {VERSION} - KotOR I

The crew standing aboard the Ebon Hawk get on with things while you are away: Carth at the cockpit
console, T3-M4 welding and at the holotable, Zaalbar, Mission and Canderous at consoles near their
spots, HK-47 keeping watch, Bastila and Juhani meditating, and Jolee lying back on the medical bed
with his datapad. Each moves between a few stations near their own spot.
They stop for conversations and fights, never stand in your way, and party members are left alone.

NEEDS Kotor Patch Manager (Lane Dibello's) with the Module Load Scripts patch - it is what starts the
routine whenever the Hawk loads, including in games already under way. Without it the mod does
nothing.

Install
  1. Run HoloPatcher on tslpatchdata (this folder's installer) and pick your KotOR I folder.
  2. In Kotor Patch Manager, add "Kotor Patch Manager\\{PATCH}.kpatch" from this folder,
     tick "Module Load Scripts (KotOR I)" and apply. KotOR I 1.03 (GOG or Steam).
  3. Load any save - new or old. The crew start on the next boarding (or at once, if you are aboard).

Either order works. The patch manager step is shared: if another mod already had you install Module
Load Scripts, skip it.

Notes
  * Jolee's Datapad is a real item (Jedi Consulars only). He holds it while he is on the bed and
    you are near; otherwise it is gone and his own weapon is back in his hand, so it never leaves
    the ship with him.
  * Works alongside the K1 Community Patch and GH0-RFK. Another mod that changes Jolee's body models
    (P_JoleeBB, PMBCM..PMBJM) loses his lying-back pose, or this mod overrides it - whichever is
    installed last.
  * Uninstall: delete the Override files the installer added (its log lists them) and untick the
    patch. The HCW_GEN row in globalcat.2da and the row in modloadscripts.2da can stay.

The Module Load Scripts patch (Kotor Patch Manager): after a module's own load script, it runs every
script modloadscripts.2da names for that module (columns: module, script; "all" for every module).
Any mod can add rows. The patch links the Patch Manager's GameAPI library - see
LICENSE-KotorPatchManager.txt.
"""


def changes_ini(names):
    L = []
    add = L.append
    add("[Settings]")
    add("FileExists=1")
    add(f"WindowCaption=Ebon Hawk Crew at Work {VERSION}")
    add("ConfirmMessage=Installs Ebon Hawk Crew at Work. It needs Kotor Patch Manager with the Module "
        "Load Scripts patch (in this mod's folder) to start the crew's routine. Continue?")
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
    for i, name in enumerate(names):
        add(f"Replace{i}={name}")
    add(f"File0={install.TABLE}")            # File: an existing table (other mods' rows) is kept
    add("")
    add("[2DAList]")
    add("Table0=globalcat.2da")
    add(f"Table1={install.TABLE}")
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
    return "\r\n".join(L)


INFO = (r"{\rtf1\ansi{\fonttbl{\f0 Arial;}}\f0\fs20 Ebon Hawk Crew at Work " + VERSION + r"\par\par "
        r"The crew aboard the Ebon Hawk work at stations near their spots - consoles, the workbench, "
        r"the holotable - Bastila and Juhani meditate, and Jolee lies back on the medical bed with "
        r"his datapad.\par\par "
        r"NEEDS Kotor Patch Manager with the Module Load Scripts patch (Kotor Patch Manager folder, "
        r"beside this installer): it starts the routine whenever the Hawk loads, in new and old games "
        r"alike. See README.txt.\par}")


def main():
    kpatch = KPM / f"{PATCH}.kpatch"
    if not kpatch.exists():
        raise SystemExit(f"{kpatch} is missing - run tools/kpm_patches/build.py {PATCH} first")
    if OUT.exists():
        shutil.rmtree(OUT)
    DATA.mkdir(parents=True)
    files = install.override_files()
    for name, data in files.items():
        (DATA / name).write_bytes(data)
    (DATA / install.TABLE).write_bytes(install.base_table())
    # the vanilla globalcat.2da: HoloPatcher patches Override's copy, else this one - never the BIFs
    # (build_holopatcher.py stage_base_files; an Override without one skipped the HCW_GEN row)
    from pykotor.extract.installation import Installation, SearchLocation
    from pykotor.resource.type import ResourceType
    res = Installation(str(install.GAME)).resource("globalcat", ResourceType.TwoDA, [SearchLocation.CHITIN])
    (DATA / "globalcat.2da").write_bytes(res.data)
    names = sorted(files)
    # UTF-8 without a BOM (build_holopatcher.py: a BOM broke HoloPatcher's ini reader)
    (DATA / "changes.ini").write_text(changes_ini(names), encoding="utf-8", newline="")
    (DATA / "info.rtf").write_text(INFO, encoding="cp1252")
    kp = OUT / "Kotor Patch Manager"
    kp.mkdir()
    shutil.copy2(kpatch, kp / kpatch.name)
    shutil.copytree(KPM / f"{PATCH} additional files", kp / f"{PATCH} additional files")
    shutil.copy2(KPM / "LICENSE-KotorPatchManager.txt", OUT / "LICENSE-KotorPatchManager.txt")
    (OUT / "README.txt").write_text(README, encoding="utf-8", newline="\r\n")
    staged = sorted(p for p in OUT.rglob("*") if p.is_file())
    print(f"staged {len(staged)} files in {OUT}")


if __name__ == "__main__":
    main()
