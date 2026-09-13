"""Check a tslpatchdata folder the way an installer would read it, then install it for real
into a throwaway game folder and compare what lands in Override against the tested files.

usage: validate_tslpatcher.py <tslpatchdata> <real game folder> <scratch folder>
"""
import filecmp
import inspect
import shutil
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\jryan\mdl swap\src")


def name_of(item):
    for attr in ("sourcefile", "saveas", "filename", "file_name", "source_file"):
        value = getattr(item, attr, None)
        if isinstance(value, str) and value:
            return value
    raise SystemExit(f"no filename field on InstallFile: {vars(item)}")


def main(tslpatchdata, game, scratch):
    tslpatchdata, game, scratch = Path(tslpatchdata), Path(game), Path(scratch)
    ini = tslpatchdata / "changes.ini"

    from pykotor.tslpatcher import reader as R
    from pykotor.tslpatcher import config as C
    from pykotor.tslpatcher import patcher as M

    # --- parse ----------------------------------------------------------------
    reader_cls = R.ConfigReader
    print("ConfigReader.from_filepath:", hasattr(reader_cls, "from_filepath"))
    reader = reader_cls.from_filepath(ini, logger=None) if "logger" in inspect.signature(reader_cls.from_filepath).parameters \
        else reader_cls.from_filepath(ini)
    config = reader.load(C.PatcherConfig())
    print(f"window caption: {config.window_title!r}" if hasattr(config, "window_title") else "")
    print(f"game number: {config.game_number}")
    print(f"install list: {len(config.install_list)} files")
    missing = []
    for item in config.install_list:
        src = tslpatchdata / getattr(item, "sourcefolder", ".") / name_of(item)
        exists = src.is_file()
        if not exists:
            missing.append(name_of(item))
        print(f"   {name_of(item):16s} -> {item.destination}  replace={next((getattr(item, a) for a in ('replace_file', 'replace_existing', 'replace') if hasattr(item, a)), vars(item))}  source present={exists}")
    if missing:
        raise SystemExit(f"missing from tslpatchdata: {missing}")

    # --- install into a throwaway game folder ---------------------------------
    fake = scratch / "fake_kotor"
    if fake.exists():
        shutil.rmtree(fake)
    (fake / "Override").mkdir(parents=True)
    for name in ("chitin.key", "dialog.tlk", "swkotor.exe"):
        if (game / name).is_file():
            shutil.copy2(game / name, fake / name)
    print("\nModInstaller signature:", inspect.signature(M.ModInstaller.__init__))
    installer = M.ModInstaller(tslpatchdata, fake, ini)
    installer.install()

    print("\ninstalled into the throwaway Override:")
    ok = True
    for item in config.install_list:
        dst = fake / "Override" / name_of(item)
        same = dst.is_file() and filecmp.cmp(dst, tslpatchdata / name_of(item), shallow=False)
        ok &= same
        print(f"   {name_of(item):16s} {'identical to the package' if same else 'MISSING OR DIFFERENT'}")
    print("\nresult:", "installs cleanly" if ok else "FAILED")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
