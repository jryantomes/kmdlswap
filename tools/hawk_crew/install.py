"""Ebon Hawk Crew at Work - installed into the dev copy (or the test mirror's overlay). A package of
its own, not part of GH0-RFK (user, 2026-10-08: "Anything not explicit to the rfk mod should get it's
own package or .kpatch"); build_package.py makes its HoloPatcher package.

What it is (user, 2026-10-07: "have the crew on the Ebon Hawk look like they are doing different
tasks when you get on the ship"; "Bastila should meditate and Jolee should be laying back in bed";
"For fun, make a datapad equipable for Jolee and equip it to that hand"):
  scripts/hcw_work.nss     each crew member's routine at stations near their spot (see its header)
  jolee_bed.py             Jolee lying back on the medical bed (his body models' "dance"), and
                           Jolee's Datapad (hcw_jolee_pad, its model w_stunbaton_050)

How it starts: the Module Load Scripts patch for Kotor Patch Manager (tools/kpm_patches) runs
hcw_work whenever the Hawk loads - a modloadscripts.2da row, ebo_m12aa -> hcw_work. Not a module.ifo
hook: a save keeps the module.ifo of every module it has been to, so a hook there never reaches a
game that has already boarded the Hawk (harness ifoprobe/hubprobe, 2026-10-08) - the user chose the
patch ("A Patch Manager .kpatch"). Without the patch nothing starts the routine.

Writes (backed up first):
  Override   hcw_work (.ncs/.nss); hcw_jolee_pad.uti; w_stunbaton_050 and Jolee's body models
             (P_JoleeBB, PMBCM..PMBJM .mdl/.mdx); globalcat.2da (+ HCW_GEN, a number);
             modloadscripts.2da (+ ebo_m12aa -> hcw_work; made if missing)
and takes away what earlier builds left: GH0-RFK's (rfk_crew_work, rfk_jdpad_i.uti in Override) and
this package's first trigger (hcw_enter in Override, ebo_m12aa.mod's Mod_OnClientEntr = hcw_enter).
With --overlay <dir>: the same into that folder's Override and nothing of the dev copy.

usage: install.py <backup dir> | --overlay <dir>
"""
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ghorfk_scene"))      # the dev tools' paths and compiler

from install_commentary import GAME, OVERRIDE, compile_nss, refuse_if_running   # noqa: E402
import jolee_bed                                                                 # noqa: E402

SCRIPTS = ["hcw_work"]
GLOBAL = ("HCW_GEN", "Number")
MODULE = "ebo_m12aa"
TABLE = "modloadscripts.2da"
ROW = {"module": MODULE, "script": "hcw_work"}
LEGACY = ["rfk_crew_work.ncs", "rfk_crew_work.nss", "rfk_jdpad_i.uti", "hcw_enter.ncs", "hcw_enter.nss"]
OLD_HOOK_FIELD, OLD_HOOK = "Mod_OnClientEntr", "hcw_enter"


def override_files():
    """{file name: bytes} for Override (the 2DAs aside)."""
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        shutil.copy2(OVERRIDE / "nwscript.nss", tmp / "nwscript.nss")
        for name in SCRIPTS:
            src = (HERE / "scripts" / f"{name}.nss").read_text(encoding="ascii")
            out[f"{name}.ncs"] = compile_nss(name, src, tmp)
            out[f"{name}.nss"] = src.encode("ascii")
    for name, (mdl, mdx, _dropped) in jolee_bed.build().items():
        out[f"{name.lower()}.mdl"], out[f"{name.lower()}.mdx"] = mdl, mdx
    mdl, mdx = jolee_bed.pad_model()
    out[f"{jolee_bed.PAD_MODEL}.mdl"], out[f"{jolee_bed.PAD_MODEL}.mdx"] = mdl, mdx
    out[f"{jolee_bed.PAD_ITEM}.uti"] = jolee_bed.pad_uti()
    return out


def globalcat(current: bytes) -> bytes:
    from pykotor.resource.formats.twoda import bytes_2da, read_2da
    t = read_2da(current)
    if any(t.get_row(i).get_string("name") == GLOBAL[0] for i in range(t.get_height())):
        return current
    t.add_row(str(t.get_height()), {"name": GLOBAL[0], "type": GLOBAL[1]})
    return bytes_2da(t)


def base_table() -> bytes:
    """modloadscripts.2da with no rows - the Module Load Scripts patch's own (its additional files)."""
    from pykotor.resource.formats.twoda import TwoDA, bytes_2da
    return bytes(bytes_2da(TwoDA(["module", "script"])))


def load_table(current: bytes | None) -> bytes:
    """modloadscripts.2da with the crew's row (once; other mods' rows kept)."""
    from pykotor.resource.formats.twoda import bytes_2da, read_2da
    t = read_2da(current if current is not None else base_table())
    if any(t.get_row(i).get_string("module").lower() == ROW["module"]
           and t.get_row(i).get_string("script").lower() == ROW["script"] for i in range(t.get_height())):
        return current
    t.add_row(str(t.get_height()), dict(ROW))
    return bytes(bytes_2da(t))


def unhooked_module(mod_bytes: bytes) -> bytes | None:
    """The module with this package's first trigger (Mod_OnClientEntr = hcw_enter) taken out, or None."""
    from pykotor.common.misc import ResRef
    from pykotor.resource.formats.erf import ERF, ERFType, bytes_erf, read_erf
    from pykotor.resource.formats.gff import bytes_gff, read_gff
    from pykotor.resource.type import ResourceType
    erf = read_erf(mod_bytes)
    ifo = next(r for r in erf if r.restype == ResourceType.IFO)
    g = read_gff(ifo.data)
    if str(g.root.acquire(OLD_HOOK_FIELD, ResRef(""))).lower() != OLD_HOOK:
        return None
    g.root.set_resref(OLD_HOOK_FIELD, ResRef(""))
    out = ERF(ERFType.MOD)
    for r in erf:
        out.set_data(str(r.resref), r.restype, bytes_gff(g) if r is ifo else r.data)
    return bytes(bytes_erf(out))


def main(argv):
    if len(argv) == 2 and argv[0] == "--overlay":
        root, backup = Path(argv[1]), None
    elif len(argv) == 1:
        refuse_if_running()
        root, backup = GAME, Path(argv[0])
        backup.mkdir(parents=True, exist_ok=True)
    else:
        raise SystemExit(__doc__)
    over = root / ("Override" if backup is None else "override")
    over.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")

    def put(target, data):
        if target.exists() and target.read_bytes() == data:
            return
        if backup is not None and target.exists():
            shutil.copy2(target, backup / f"{target.name}.before-hawk-crew-{stamp}")
        target.write_bytes(data)

    for name, data in override_files().items():
        put(over / name, data)
    put(over / "globalcat.2da", globalcat((OVERRIDE / "globalcat.2da").read_bytes()))
    table = over / TABLE
    put(table, load_table(table.read_bytes() if table.exists() else
                          (OVERRIDE / TABLE).read_bytes() if (OVERRIDE / TABLE).exists() else None))
    removed = []
    if backup is not None:
        for name in LEGACY:
            p = OVERRIDE / name
            if p.exists():
                shutil.copy2(p, backup / f"{name}.before-hawk-crew-{stamp}")
                p.unlink()
                removed.append(name)
        mod = GAME / "modules" / f"{MODULE}.mod"
        unhooked = unhooked_module(mod.read_bytes()) if mod.exists() else None
        if unhooked is not None:
            put(mod, unhooked)
            removed.append(f"{MODULE}.mod {OLD_HOOK_FIELD}")
    print(f"Ebon Hawk Crew at Work -> {root}: {', '.join(SCRIPTS)}, Jolee's bed and datapad, "
          f"{GLOBAL[0]}, {TABLE} {MODULE} -> {ROW['script']}"
          + (f"; taken out: {', '.join(removed)}" if removed else ""))


if __name__ == "__main__":
    main(sys.argv[1:])
