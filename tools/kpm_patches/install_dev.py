"""Adds our own Kotor Patch Manager patches (builds/kpm/*.kpatch) to the dev copy the way the Patch
Manager's installer leaves them: a [[patches]] block in patch_config.toml (the format the harness
mirror has loaded - tools/kotor_autotest/patchset.py kpatch_block), the patch's dll in patches\\, and
its id in kpm_install_state.json's InstalledPatches (so the Patch Manager's remove/status see it).

Not the Patch Manager's own command line (KPatchLauncher <exe> --patches <dir>): that removes every
patch, reinstalls all of them from one folder of .kpatch files - the dev copy's ten came from several
builds - and then starts the game.

A later full re-apply in the Patch Manager app keeps these only if their .kpatch files are in its
patches folder and ticked.

Backups first (builds/backups/kpm-dev-<stamp>). Running it again changes nothing; refuses while the
game runs and if a hook would overlap one already configured.

usage: install_dev.py ModuleLoadScripts AnimationRows      add (or refresh) these
       install_dev.py --remove AnimationRows               take one out
"""
import json
import shutil
import sys
import time
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tools" / "kotor_autotest"))
from patchset import blocks, kpatch_block                                        # noqa: E402

GAME = Path(r"E:\SteamLibrary\steamapps\common\swkotor")
CONFIG = GAME / "patch_config.toml"
STATE = GAME / "kpm_install_state.json"
KPM = ROOT / "builds" / "kpm"


def running():
    import subprocess
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq swkotor.exe"], capture_output=True, text=True).stdout
    return "swkotor.exe" in out.lower()


def spans(config_text, skip=()):
    out = []
    for p in tomllib.loads(config_text).get("patches", []):
        if p["id"] in skip:
            continue
        for h in p.get("hooks", []):
            out.append((h["address"], h["address"] + len(h.get("original_bytes", [])), p["id"]))
    return out


def main(argv):
    remove = argv[:1] == ["--remove"]
    names = argv[1:] if remove else argv
    if not names:
        raise SystemExit(__doc__)
    if running():
        raise SystemExit("KOTOR is running - game files are not written while it runs")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = ROOT / "builds" / "backups" / f"kpm-dev-{stamp}"
    backup.mkdir(parents=True)
    for f in (CONFIG, STATE):
        shutil.copy2(f, backup / f.name)

    text = CONFIG.read_text(encoding="utf-8")
    state = json.loads(STATE.read_text(encoding="utf-8"))
    done = []
    for name in names:
        kp = KPM / f"{name}.kpatch"
        if not kp.exists():
            raise SystemExit(f"{kp} is missing - python build.py {name}")
        pid, block, dll = kpatch_block(kp)
        head, bs = blocks(text)
        text = head + "".join(b for i, b in bs if i != pid)          # the old block of this id, if any
        target = GAME / "patches" / f"{pid}.dll"
        if remove:
            if target.exists():
                shutil.copy2(target, backup / target.name)
                target.unlink()
            state["InstalledPatches"] = [i for i in state["InstalledPatches"] if i != pid]
            done.append(f"removed {pid}")
            continue
        new = tomllib.loads(block)["patches"][0]
        for h in new.get("hooks", []):
            lo, hi = h["address"], h["address"] + len(h.get("original_bytes", []))
            clash = [s for s in spans(text) if s[0] < hi and lo < s[1]]
            if clash:
                raise SystemExit(f"{pid}: hook {lo:#x} overlaps {clash} - not installed")
        text = text.rstrip() + "\n" + block
        if dll:
            if target.exists():
                shutil.copy2(target, backup / target.name)
            target.write_bytes(dll)
        if pid not in state["InstalledPatches"]:
            state["InstalledPatches"].append(pid)
        done.append(f"{pid} ({'dll + ' if dll else ''}{len(new.get('hooks', []))} hook(s))")
    tomllib.loads(text)                                   # the loader rejects what this rejects
    CONFIG.write_text(text, encoding="utf-8", newline="\n")
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(f"dev copy: {', '.join(done)}; backups in {backup}")


if __name__ == "__main__":
    main(sys.argv[1:])
