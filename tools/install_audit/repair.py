"""Puts back what the install audit found missing from a mod's work - the files no other mod explains.

For every FAIL the audit reported for the chosen mods (files missing, or changed by nothing in the
audited mods; template and dialogue fields their patches set, entries they added), the file is rebuilt
as the installed mods' installers would leave it: the game's own copy, then each mod's whole-file
install and patches of it, in install order (bases.others_copy - PyKotor's TSLPatcher code, what
HoloPatcher runs). Not a reinstall: a reinstall would add every entry and untagged row its patches add
a second time, and put its whole files back over later mods'.

Left alone, and listed:
  * files our own mods install or patch (GH0-RFK, the crew package) - they build on these files;
  * a module's copy that an Override copy shadows (the game does not read it);
  * patches that need a token another of the mod's sections set (cannot be replayed alone);
  * findings marked CLOBBERED or superseded - two mods' versions, a merge, not a repair.

Run on the harness mirror first, audit it, then on the dev copy. Every file written is backed up
(or listed as added) in the backup folder's manifest; --remove puts them back.

usage: repair.py <game folder> <backup dir> [--mod <name part>]... [--dry-run]
       repair.py <game folder> <backup dir> --remove
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path, PureWindowsPath

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import audit                                                                     # noqa: E402
import bases                                                                     # noqa: E402

from pykotor.resource.formats.erf import ERF, ERFType, bytes_erf, read_erf       # noqa: E402

OURS = bases.OURS
MANIFEST = "repair.json"


def running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq swkotor.exe"], capture_output=True, text=True).stdout
    return "swkotor.exe" in out.lower()


def split(item):
    """'override\\x.utc ...' / 'modules\\m.mod\\x.dlg ...' -> (dest, filename)."""
    path = item.split(" ")[0]
    dest, name = path.rsplit("\\", 1)
    return dest.lower(), name.lower()


def ours_touch(mods):
    """(dest, filename) our own mods install or patch."""
    out = set()
    for m in mods:
        if not any(o.lower() in m["name"].lower() for o in OURS):
            continue
        c = m["cfg"]
        for f in list(c.install_list) + [x for lst in (c.patches_2da, c.patches_gff, c.patches_ncs,
                                                         c.patches_nss, c.patches_ssf) for x in lst]:
            out.add((audit.dest_of(f), f.saveas.lower()))
    return out


def write(game, dest, name, data, backup, manifest):
    rel_dest = "Override" if dest == "override" else dest
    if dest.endswith((".mod", ".erf")):
        cap = game / rel_dest
        keep = backup / rel_dest
        if not keep.exists():
            keep.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cap, keep)
            manifest["replaced"].append(rel_dest)
        old = read_erf(cap.read_bytes())
        new = ERF(ERFType.from_extension(cap))
        resref, ext = name.rsplit(".", 1)
        from pykotor.resource.type import ResourceType
        for r in old:
            if not (str(r.resref).lower() == resref and r.restype.extension.lower() == ext):
                new.set_data(str(r.resref), r.restype, r.data)
        new.set_data(resref, ResourceType.from_extension(ext), data)
        cap.write_bytes(bytes(bytes_erf(new)))
        return
    target = game / rel_dest / name
    rel = str(Path(rel_dest) / name)
    if target.exists():
        keep = backup / rel
        if not keep.exists():
            keep.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, keep)
            manifest["replaced"].append(rel)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        manifest["added"].append(rel)
    target.write_bytes(data)


def remove(game, backup):
    m = json.loads((backup / MANIFEST).read_text(encoding="utf-8"))
    for rel in m["added"]:
        (game / rel).unlink(missing_ok=True)
    for rel in m["replaced"]:
        shutil.copy2(backup / rel, game / rel)
    print(f"removed {len(m['added'])}, restored {len(m['replaced'])}")


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    game, backup = Path(argv[0]), Path(argv[1])
    if running():
        raise SystemExit("KOTOR is running - game files are not written while it runs")
    if "--remove" in argv:
        return remove(game, backup)
    only = [argv[i + 1] for i, a in enumerate(argv) if a == "--mod"]
    dry = "--dry-run" in argv
    bases.GAME = game                         # the game's own copies: the same in every copy of it
    mods = audit.load_mods()
    report = json.loads(audit.report_path(game, ".json").read_text(encoding="utf-8"))
    skip_ours = ours_touch(mods)
    todo, left = {}, []
    for name, results in report.items():
        if only and not any(o.lower() in name.lower() for o in only):
            continue
        for r in results:
            if r["status"] != audit.FAIL or r["area"] not in ("files", "GFF"):
                continue
            dest, fname = split(r["item"])
            if dest.startswith("saves"):
                continue
            if (dest, fname) in skip_ours:
                left.append((dest, fname, "our own mods build on this file"))
            elif "shadowed" in r["detail"]:
                left.append((dest, fname, "an Override copy shadows the module's"))
            else:
                todo.setdefault((dest, fname), []).append(name)
    game_obj = audit.Game(game)
    plan = []
    for (dest, fname), who in sorted(todo.items()):
        try:
            data = bases.others_copy(dest, fname)
        except SystemExit as e:
            left.append((dest, fname, str(e)))
            continue
        if dest.endswith((".mod", ".erf")) and not (game / dest).exists():
            left.append((dest, fname, "the module has no .mod in this install"))
            continue
        if game_obj.file(dest, fname) == data:
            continue
        plan.append((dest, fname, data, sorted(set(who))))
    print(f"{len(plan)} file(s) to put back, {len(left)} left alone")
    for dest, fname, _d, who in plan:
        print(f"  {dest}\\{fname}  ({', '.join(who)})")
    for dest, fname, why in sorted(set(left)):
        print(f"  left: {dest}\\{fname} - {why}")
    if dry or not plan:
        return
    backup.mkdir(parents=True, exist_ok=True)
    manifest = {"game": str(game), "added": [], "replaced": [], "files": []}
    for dest, fname, data, who in plan:
        write(game, dest, fname, data, backup, manifest)
        manifest["files"].append({"dest": dest, "file": fname, "mods": who})
    (backup / MANIFEST).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"written: {len(plan)} (backups and manifest in {backup})")


if __name__ == "__main__":
    main(sys.argv[1:])
