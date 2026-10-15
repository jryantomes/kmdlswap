"""Install the Ebon Hawk Crew at Work package into throwaway game folders and check it.

Each fake game holds only what the installer needs (chitin.key, dialog.tlk, swkotor.exe; the 2DAs come
from the package's vanilla copies). PyKotor's ModInstaller (HoloPatcher is built on it) runs the
package, and:
  fresh       every Override file lands byte-identical; globalcat.2da gains HCW_GEN (Number) once;
              modloadscripts.2da appears with exactly the row ebo_m12aa -> hcw_work; animations.2da
              gains hcw_bedlie (dance's flags) and hcw_bedsit (sitdown's) once each, and hcw_work.ncs -
              otherwise the package's copy byte for byte - carries those rows in CW_BEDLIE_RAW's and
              CW_BEDSIT_RAW's constants
  reinstall   the same install again: still one of each row, the same rows in hcw_work.ncs
  shared      another mod's rows already there - modloadscripts.2da kept, ours added once;
              animations.2da with two rows more: ours land after them and hcw_work.ncs says so
and the package itself: both .kpatch files beside it (their hooks and ids), Module Load Scripts'
empty table, Jolee's models with "hcw_bedlie" and "hcw_bedsit" and no "dance" of their own (the vanilla dance stays the
supermodel's), no module files, nothing private.

usage: validate_package.py [scratch folder]
"""
import filecmp
import shutil
import sys
import zipfile
from pathlib import Path

from pykotor.extract.installation import Installation, SearchLocation
from pykotor.resource.formats.twoda import TwoDA, bytes_2da, read_2da
from pykotor.resource.type import ResourceType

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_package as pkg                                                      # noqa: E402
import install as inst_mod                                                       # noqa: E402
import jolee_bed                                                                 # noqa: E402
from kmdlswap.layout import parse                                                # noqa: E402

KOTOR = Path(r"E:\SteamLibrary\steamapps\common\swkotor")
SCRATCH = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    r"C:\Users\jryan\AppData\Local\Temp\claude\C--Users-jryan-mdl-swap\ed46b223-3c72-4d3a-8e2f-c66cbc102752\scratchpad\hcw_test")
OTHER_ROWS = [{"module": "tar_m02af", "script": "othermod_a"}, {"module": "all", "script": "othermod_b"}]

results = []


def check(ok, what):
    results.append((bool(ok), what))
    print(f"  [{'ok' if ok else 'FAIL'}] {what}")


def fake_game(name, table=None, anims=None):
    fake = SCRATCH / name
    if fake.exists():
        shutil.rmtree(fake)
    (fake / "Override").mkdir(parents=True)
    (fake / "modules").mkdir()
    for f in ("chitin.key", "dialog.tlk", "swkotor.exe"):
        shutil.copy2(KOTOR / f, fake / f)
    if table is not None:
        (fake / "Override" / "modloadscripts.2da").write_bytes(table)
    if anims is not None:
        (fake / "Override" / "animations.2da").write_bytes(anims)
    return fake


def rows(path):
    t = read_2da(path.read_bytes())
    return t.get_headers(), [{h: t.get_row(i).get_string(h) for h in t.get_headers()} for i in range(t.get_height())]


def rows_of(data):
    t = read_2da(data)
    return [{h: t.get_row(i).get_string(h) for h in t.get_headers()} for i in range(t.get_height())]


def install(fake):
    from pykotor.tslpatcher.patcher import ModInstaller
    ModInstaller(pkg.DATA, fake, pkg.DATA / "changes.ini").install()


def listed_files():
    ini = (pkg.DATA / "changes.ini").read_text(encoding="utf-8")
    out, section = [], None
    for line in ini.splitlines():
        if line.startswith("["):
            section = line.strip("[]")
        elif section == "install_folder0" and line.startswith("Replace"):
            out.append(line.split("=", 1)[1])
    return out


def check_script(fake, want_rows, label):
    """hcw_work.ncs in place: the package's copy with want_rows ({animation: row}) in their constants,
    nothing else changed."""
    src = (pkg.DATA / pkg.SCRIPT).read_bytes()
    got = (fake / "Override" / pkg.SCRIPT).read_bytes()
    same = len(got) == len(src)
    marks = sorted((inst_mod.row_offset(src, name), name) for name in want_rows)
    last = 0
    for at, name in marks:
        same = same and got[last:at] == src[last:at]
        last = at + 4
        value = int.from_bytes(got[at:at + 4], "big")
        row = value // 65536 if value >= 65536 else value   # hcw_work's CW_AnimRow: either installer's write
        check(row == want_rows[name], f"{label}: hcw_work.ncs carries {name} row {row} (want {want_rows[name]}; constant {value:#x})")
    check(same and got[last:] == src[last:], f"{label}: hcw_work.ncs otherwise as packaged")


def our_rows(fake):
    """{our animation: [its rows]} in the fake game's animations.2da."""
    r = rows(fake / "Override" / "animations.2da")[1]
    return {name: [i for i, x in enumerate(r) if x["name"] == name] for name, _ in jolee_bed.ROWS}


def main():
    base_glob = Installation(str(KOTOR)).resource("globalcat", ResourceType.TwoDA, [SearchLocation.CHITIN]).data
    base_anims = Installation(str(KOTOR)).resource("animations", ResourceType.TwoDA, [SearchLocation.CHITIN]).data
    base_glob_rows, base_anim_rows = rows_of(base_glob), rows_of(base_anims)

    print("package:")
    check((pkg.DATA / "globalcat.2da").read_bytes() == base_glob, "its globalcat.2da is the BIFs' copy")
    check((pkg.DATA / "animations.2da").read_bytes() == base_anims, "its animations.2da is the BIFs' copy")
    names = listed_files()
    staged = sorted(p.name for p in pkg.DATA.iterdir() if p.is_file())
    expect = sorted(names + [pkg.SCRIPT, "modloadscripts.2da", "globalcat.2da", "animations.2da", "changes.ini", "info.rtf"])
    check(staged == expect, f"tslpatchdata holds the {len(names)} listed files, hcw_work.ncs, the tables, changes.ini, info.rtf")
    check(not any(n.lower().startswith("rfkp_") for n in staged), "nothing private (rfkp_*)")
    check(not any(n.lower().endswith((".mod", ".rim", ".erf")) for n in staged), "no module files")
    for name, mark in inst_mod.PLACEHOLDERS.items():
        check((pkg.DATA / pkg.SCRIPT).read_bytes().count(mark) == 1, f"hcw_work.ncs: {name}'s row placeholder, once")
    for model in jolee_bed.TARGETS:
        anims = parse((pkg.DATA / f"{model.lower()}.mdl").read_bytes(), (pkg.DATA / f"{model.lower()}.mdx").read_bytes()).animation_names
        check(jolee_bed.SLOT in anims and jolee_bed.SIT_SLOT in anims and "dance" not in anims,
              f"{model}: '{jolee_bed.SLOT}' and '{jolee_bed.SIT_SLOT}', no 'dance' of its own")
    want = {"ModuleLoadScripts": ("module-load-scripts", ["0x004C5215", "consumed_exit_address = 0x004C5417"], True),
            "AnimationRows": ("animation-rows", ["0x005406F6", 'type = "replace"'], False)}
    for patch, (pid, marks, dll) in want.items():
        kp = pkg.OUT / "Kotor Patch Manager" / f"{patch}.kpatch"
        with zipfile.ZipFile(kp) as z:
            zn = {n.replace("\\", "/"): n for n in z.namelist()}
            hooks = z.read(zn["kotor1.hooks.toml"]).decode()
            manifest = z.read(zn["manifest.toml"]).decode()
            check(("binaries/windows_x86.dll" in zn) == dll, f"{kp.name}: {'a dll' if dll else 'byte hooks only'}")
        check(all(m in hooks for m in marks), f"{kp.name}: its hook")
        check(f'id = "{pid}"' in manifest, f"{kp.name}: id {pid}")
    extra = pkg.OUT / "Kotor Patch Manager" / "ModuleLoadScripts additional files" / "modloadscripts.2da"
    h, r = rows(extra)
    check(h == ["module", "script"] and not r, "Module Load Scripts' additional modloadscripts.2da: columns module, script; no rows")
    check((pkg.OUT / "LICENSE-KotorPatchManager.txt").is_file() and (pkg.OUT / "README.txt").is_file(),
          "README.txt and the Patch Manager's licence beside it")

    print("\nfresh install:")
    fake = fake_game("fresh")
    install(fake)
    bad = [n for n in names if not (fake / "Override" / n).is_file()
           or not filecmp.cmp(pkg.DATA / n, fake / "Override" / n, shallow=False)]
    check(not bad, f"{len(names)} Override files byte-identical" + (f" - bad: {bad}" if bad else ""))
    after = rows(fake / "Override" / "globalcat.2da")[1]
    new = after[len(base_glob_rows):]
    check(after[:len(base_glob_rows)] == base_glob_rows, "globalcat.2da: the base rows untouched")
    check([(x["name"], x["type"]) for x in new] == [("HCW_GEN", "Number")], f"globalcat.2da +{len(new)}: HCW_GEN Number")
    h, r = rows(fake / "Override" / "modloadscripts.2da")
    check(h == ["module", "script"] and r == [{"module": "ebo_m12aa", "script": "hcw_work"}],
          f"modloadscripts.2da: {r}")
    arows = rows(fake / "Override" / "animations.2da")[1]
    dance = next(x for x in base_anim_rows if x["name"] == "dance")
    like = [{**next(x for x in base_anim_rows if x["name"] == like_name), "name": name} for name, like_name in jolee_bed.ROWS]
    n = len(base_anim_rows)
    check(arows[:n] == base_anim_rows and arows[n:] == like,
          f"animations.2da +{len(arows) - n}: rows {n}, {n + 1} = {', '.join(x['name'] for x in arows[n:])} with their vanilla rows' flags")
    fresh = {name: n + i for i, (name, _) in enumerate(jolee_bed.ROWS)}
    check_script(fake, fresh, "fresh")

    print("\nreinstall:")
    install(fake)
    after2 = rows(fake / "Override" / "globalcat.2da")[1]
    check(sum(x["name"] == "HCW_GEN" for x in after2) == 1, "globalcat.2da: still one HCW_GEN")
    h, r = rows(fake / "Override" / "modloadscripts.2da")
    check(r == [{"module": "ebo_m12aa", "script": "hcw_work"}], f"modloadscripts.2da: still one row ({len(r)})")
    check(our_rows(fake) == {k: [v] for k, v in fresh.items()}, f"animations.2da: still one of each ({our_rows(fake)})")
    check_script(fake, fresh, "reinstall")

    print("\nshared tables:")
    t = TwoDA(["module", "script"])
    for i, row in enumerate(OTHER_ROWS):
        t.add_row(str(i), row)
    a = read_2da(base_anims)
    for n in ("othermod_pose1", "othermod_pose2"):
        a.add_row(str(a.get_height()), {**dance, "name": n})
    fake = fake_game("shared", bytes(bytes_2da(t)), bytes(bytes_2da(a)))
    install(fake)
    h, r = rows(fake / "Override" / "modloadscripts.2da")
    check(r == OTHER_ROWS + [{"module": "ebo_m12aa", "script": "hcw_work"}],
          f"modloadscripts.2da: the other mod's {len(OTHER_ROWS)} rows kept, ours added ({len(r)} rows)")
    shared = {k: v + 2 for k, v in fresh.items()}
    check(our_rows(fake) == {k: [v] for k, v in shared.items()}, f"animations.2da: ours after the other mod's two, {our_rows(fake)}")
    check_script(fake, shared, "shared")

    failed = [w for ok, w in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
