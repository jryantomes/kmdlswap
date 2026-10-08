"""Builds a Kotor Patch Manager patch of ours (a folder here) into a .kpatch, the way the Patch Manager's
own patches are built: a fresh copy in its source tree's Patches folder, create-patch.bat there (Visual
Studio x86 found by it). Lane's code is not changed - a patch only adds its own folder.

    python build.py ModuleLoadScripts        -> builds/kpm/ModuleLoadScripts.kpatch
                                                (+ "ModuleLoadScripts additional files", if the patch has any,
                                                 and the Patch Manager's licence, LICENSE-KotorPatchManager.txt)
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PATCHES = Path(r"D:\Downloads\kpm\src\LaneDibello-Kotor-Patch-Manager-5cafa6a\Patches")
OUT = HERE.parents[1] / "builds" / "kpm"


def build(name):
    if not (PATCHES / "create-patch.bat").exists():
        raise SystemExit(f"no Patch Manager source tree at {PATCHES}")
    work = PATCHES / name
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(HERE / name, work)
    r = subprocess.run(["cmd", "/c", f"..\\create-patch.bat {name} < nul"], cwd=work, capture_output=True, text=True)
    kpatch = work / f"{name}.kpatch"
    if not kpatch.exists():
        raise SystemExit(f"create-patch.bat did not produce {name}.kpatch:\n" + r.stdout[-3000:] + r.stderr[-2000:])
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(kpatch, OUT / kpatch.name)
    # the dll links the Patch Manager's GameAPI library (MIT): its notice goes with every build
    shutil.copy2(HERE / "LICENSE-KotorPatchManager.txt", OUT / "LICENSE-KotorPatchManager.txt")
    extra = HERE / name / "additional"
    if extra.exists():                                   # the layout Patch Manager releases use
        dest = OUT / f"{name} additional files"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(extra, dest)
    return OUT / kpatch.name


if __name__ == "__main__":
    for n in sys.argv[1:] or ["ModuleLoadScripts"]:
        k = build(n)
        print(f"{k}: {k.stat().st_size} bytes")
