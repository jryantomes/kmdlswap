"""Install the Ebon Hawk Crew at Work package into throwaway game folders and check it.

Each fake game holds only what the installer needs (chitin.key, dialog.tlk, swkotor.exe; globalcat.2da
comes from the BIFs). PyKotor's ModInstaller (HoloPatcher is built on it) runs the package, and:
  fresh       every Override file lands byte-identical; globalcat.2da gains HCW_GEN (Number) once;
              modloadscripts.2da appears with exactly the row ebo_m12aa -> hcw_work
  reinstall   the same install again: still one HCW_GEN, still one row
  shared      a modloadscripts.2da already there with another mod's rows: kept, ours added once
and the package itself: the Module Load Scripts .kpatch beside it (its hook, its id), its additional
modloadscripts.2da readable with the columns module/script, no module files, nothing private.

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

KOTOR = Path(r"E:\SteamLibrary\steamapps\common\swkotor")
SCRATCH = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    r"C:\Users\jryan\AppData\Local\Temp\claude\C--Users-jryan-mdl-swap\ed46b223-3c72-4d3a-8e2f-c66cbc102752\scratchpad\hcw_test")
OTHER_ROWS = [{"module": "tar_m02af", "script": "othermod_a"}, {"module": "all", "script": "othermod_b"}]

results = []


def check(ok, what):
    results.append((bool(ok), what))
    print(f"  [{'ok' if ok else 'FAIL'}] {what}")


def fake_game(name, table=None):
    fake = SCRATCH / name
    if fake.exists():
        shutil.rmtree(fake)
    (fake / "Override").mkdir(parents=True)
    (fake / "modules").mkdir()
    for f in ("chitin.key", "dialog.tlk", "swkotor.exe"):
        shutil.copy2(KOTOR / f, fake / f)
    if table is not None:
        (fake / "Override" / "modloadscripts.2da").write_bytes(table)
    return fake


def rows(path):
    t = read_2da(path.read_bytes())
    return t.get_headers(), [{h: t.get_row(i).get_string(h) for h in t.get_headers()} for i in range(t.get_height())]


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


def main():
    base_glob = Installation(str(KOTOR)).resource("globalcat", ResourceType.TwoDA, [SearchLocation.CHITIN]).data
    base_glob_rows = rows_of(base_glob)

    print("package:")
    check((pkg.DATA / "globalcat.2da").read_bytes() == base_glob, "its globalcat.2da is the BIFs' copy")
    names = listed_files()
    staged = sorted(p.name for p in pkg.DATA.iterdir() if p.is_file())
    expect = sorted(names + ["modloadscripts.2da", "globalcat.2da", "changes.ini", "info.rtf"])
    check(staged == expect, f"tslpatchdata holds the {len(names)} listed files, the tables, changes.ini, info.rtf")
    check(not any(n.lower().startswith("rfkp_") for n in staged), "nothing private (rfkp_*)")
    check(not any(n.lower().endswith((".mod", ".rim", ".erf")) for n in staged), "no module files")
    kp = pkg.OUT / "Kotor Patch Manager" / f"{pkg.PATCH}.kpatch"
    with zipfile.ZipFile(kp) as z:
        zn = {n.replace("\\", "/"): n for n in z.namelist()}
        hooks = z.read(zn["kotor1.hooks.toml"]).decode()
        manifest = z.read(zn["manifest.toml"]).decode()
        check("binaries/windows_x86.dll" in zn, f"{kp.name} carries its dll")
    check("0x004C5215" in hooks and "consumed_exit_address = 0x004C5417" in hooks, f"{kp.name}: the module load hook")
    check('id = "module-load-scripts"' in manifest, f"{kp.name}: id module-load-scripts")
    extra = pkg.OUT / "Kotor Patch Manager" / f"{pkg.PATCH} additional files" / "modloadscripts.2da"
    h, r = rows(extra)
    check(h == ["module", "script"] and not r, "its additional modloadscripts.2da: columns module, script; no rows")
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

    print("\nreinstall:")
    install(fake)
    after2 = rows(fake / "Override" / "globalcat.2da")[1]
    check(sum(x["name"] == "HCW_GEN" for x in after2) == 1, "globalcat.2da: still one HCW_GEN")
    h, r = rows(fake / "Override" / "modloadscripts.2da")
    check(r == [{"module": "ebo_m12aa", "script": "hcw_work"}], f"modloadscripts.2da: still one row ({len(r)})")

    print("\nshared table:")
    t = TwoDA(["module", "script"])
    for i, row in enumerate(OTHER_ROWS):
        t.add_row(str(i), row)
    fake = fake_game("shared", bytes(bytes_2da(t)))
    install(fake)
    h, r = rows(fake / "Override" / "modloadscripts.2da")
    check(r == OTHER_ROWS + [{"module": "ebo_m12aa", "script": "hcw_work"}],
          f"modloadscripts.2da: the other mod's {len(OTHER_ROWS)} rows kept, ours added ({len(r)} rows)")

    failed = [w for ok, w in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        raise SystemExit(1)


def rows_of(data):
    t = read_2da(data)
    return [{h: t.get_row(i).get_string(h) for h in t.get_headers()} for i in range(t.get_height())]


if __name__ == "__main__":
    main()
