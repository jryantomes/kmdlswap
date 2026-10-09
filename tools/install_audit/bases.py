"""What the OTHER installed mods leave of a file - the base a mod of ours should build its edit on.

    others_copy("override", "k_hxor_dialog.dlg") -> bytes

From the game's own copy (chitin, or the module's .rim for a file inside a module), every mod in
mods.toml that is not ours, in install order: its whole-file install of this file (Replace; File when
nothing of a mod is there yet), then its patches of it (GFFList, run with PyKotor's TSLPatcher code -
what HoloPatcher did). 2026-10-09: install_xor.py built Xor's dialogue on the vanilla copy and
wiped the K1 Community Patch's 75 fixes to it; this gives it the copy with them.

A patch that needs a token another of that mod's sections set (2DAMEMORY / StrRef) cannot be replayed
alone: refused, with the mod named.
"""
import contextlib
import io
import tomllib
from pathlib import Path, PureWindowsPath

from pykotor.common.misc import Game
from pykotor.extract.installation import Installation, SearchLocation
from pykotor.resource.type import ResourceType
from pykotor.tslpatcher.config import PatcherConfig
from pykotor.tslpatcher.logger import PatchLogger
from pykotor.tslpatcher.memory import PatcherMemory
from pykotor.tslpatcher.reader import ConfigReader

HERE = Path(__file__).resolve().parent
GAME = Path(r"E:\SteamLibrary\steamapps\common\swkotor")
OURS = ("GH0-RFK", "Ebon Hawk Crew at Work")


def _dest(p):
    d = str(PureWindowsPath(p.destination)).strip("\\").lower()
    return "override" if d in ("", ".", "override") else d


def _vanilla(dest, filename):
    resref, ext = filename.rsplit(".", 1)
    rtype = ResourceType.from_extension(ext)
    if dest == "override":
        r = Installation(str(GAME)).resource(resref, rtype, [SearchLocation.CHITIN])
        return None if r is None else r.data
    from pykotor.resource.formats.rim import read_rim
    module = PureWindowsPath(dest).stem
    for rim in (f"{module}_s.rim", f"{module}.rim"):
        p = GAME / "modules" / rim
        if p.exists():
            for r in read_rim(p.read_bytes()):
                if str(r.resref).lower() == resref.lower() and r.restype == rtype:
                    return r.data
    return None


def others_copy(dest, filename, mods_toml=HERE / "mods.toml"):
    dest, filename = dest.lower(), filename.lower()
    data, from_mod = _vanilla(dest, filename), False
    for m in tomllib.loads(Path(mods_toml).read_text(encoding="utf-8"))["mod"]:
        if any(o.lower() in m["name"].lower() for o in OURS):
            continue
        ini = Path(m["ini"])
        with contextlib.redirect_stdout(io.StringIO()):
            cfg = ConfigReader.from_filepath(ini, PatchLogger(), ini.parent).load(PatcherConfig())
        for f in cfg.install_list:
            if f.saveas.lower() == filename and _dest(f) == dest and (f.replace_file or not from_mod):
                data, from_mod = (ini.parent / (getattr(f, "sourcefolder", ".") or ".") / f.sourcefile).read_bytes(), True
        for g in cfg.patches_gff:
            if g.saveas.lower() == filename and _dest(g) == dest:
                if data is None:
                    raise SystemExit(f"{m['name']} patches {dest}\\{filename}, which has no base copy")
                try:
                    data = g.patch_resource(data, PatcherMemory(), PatchLogger(), Game.K1)
                except Exception as e:                       # noqa: BLE001
                    raise SystemExit(f"{m['name']}'s patch of {filename} cannot be replayed alone: {e}") from e
                from_mod = True
    if data is None:
        raise SystemExit(f"no copy of {dest}\\{filename} in the game or the mods")
    return data
