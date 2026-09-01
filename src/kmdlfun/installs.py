r"""Finding the games, so nobody has to type a path.

Until now the app carried three hardcoded folders per game and picked the first
that existed. That works on the machine the list was written on and nowhere
else, and it fails silently - an empty box that looks like the app is broken
rather than like it has not looked hard enough.

Four sources, cheapest and most authoritative first:

**Windows knows what is installed.** Anything with an installer writes an
uninstall entry carrying `InstallLocation`, and that covers GOG, retail discs
and the launchers alike - it is the one mechanism that does not care how the
game got there. GOG Galaxy keeps its own list too, and the retail KOTOR disc
still writes `BioWare\SW\KOTOR`, fifteen years on.

**Steam says where its libraries are.** `libraryfolders.vdf` lists every
library folder, including ones on other drives.

**GOG and retail go in a handful of known places.** Short list, quick to check,
and the fallback for a game that was copied rather than installed.

**Otherwise, look.** A shallow walk of each fixed drive, bounded in depth,
because an unbounded search of a modern drive is a minute of disk churn nobody
asked for.

None of these are asked what game they hold. Every candidate path goes through
`identify`, so a source only has to suggest somewhere to look.

Identification never relies on the folder name. `chitin.key` says "an Aurora
game" and nothing more - both KOTOR games have one - so the executable decides,
and a folder that does not carry the right one is not reported however it is
spelled.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

CONFIG = Path.home() / ".kmdlfun" / "installs.json"
MAX_DEPTH = 5              # deep enough for D:\Games\Steam\steamapps\common\x

K1 = "kotor"
K2 = "kotor2"
JADE = "jade"


@dataclass(frozen=True)
class Game:
    key: str
    label: str
    exe: tuple[str, ...]           # any one of these identifies it
    folders: tuple[str, ...]       # the names it is usually installed under
    needs: tuple[str, ...] = ("chitin.key",)


GAMES: tuple[Game, ...] = (
    Game(K1, "KOTOR", ("swkotor.exe",),
         ("swkotor", "Star Wars - KotOR",
          "Star Wars Knights of the Old Republic")),
    # K2's folder name varies more than any other here - Steam, GOG and the
    # retail disc all spell it differently - which is exactly why the
    # executable decides and the name only suggests where to look.
    Game(K2, "KOTOR II", ("swkotor2.exe",),
         ("Knights of the Old Republic II", "swkotor2", "KOTOR2",
          "Star Wars - KotOR2",
          "STAR WARS Knights of the Old Republic II - The Sith Lords")),
    Game(JADE, "Jade Empire", ("JadeEmpire.exe",),
         ("Jade Empire", "Jade Empire Special Edition")),
)

# Subkeys to enumerate, and the value under each child holding a path. The
# uninstall lists carry everything with an installer; the GOG list carries
# what GOG Galaxy manages.
REGISTRY_LISTS = (
    (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", "InstallLocation"),
    (r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
     "InstallLocation"),
    (r"SOFTWARE\GOG.com\Games", "path"),
    (r"SOFTWARE\WOW6432Node\GOG.com\Games", "path"),
)

# Single keys the games themselves wrote. The retail KOTOR installer still
# leaves `BioWare\SW\KOTOR` behind, and it is the only source that knows about
# a disc install with no launcher at all.
REGISTRY_DIRECT = (
    (r"SOFTWARE\BioWare\SW\KOTOR", "path"),
    (r"SOFTWARE\WOW6432Node\BioWare\SW\KOTOR", "path"),
    (r"SOFTWARE\LucasArts\KotOR2", "path"),
    (r"SOFTWARE\WOW6432Node\LucasArts\KotOR2", "path"),
    (r"SOFTWARE\BioWare\Jade Empire", "path"),
    (r"SOFTWARE\WOW6432Node\BioWare\Jade Empire", "path"),
)

# Epic writes one JSON manifest per installed game.
EPIC_MANIFESTS = r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests"

STEAM_ROOTS = (
    r"C:\Program Files (x86)\Steam",
    r"C:\Program Files\Steam",
)

OTHER_ROOTS = (
    r"C:\GOG Games",
    r"C:\Program Files (x86)\GOG Galaxy\Games",
    r"C:\Program Files (x86)\LucasArts",
    r"C:\Games",
)


@dataclass
class Found:
    """What was found, and how - the how matters when it is wrong."""

    paths: dict[str, str] = field(default_factory=dict)
    how: dict[str, str] = field(default_factory=dict)
    searched: list[str] = field(default_factory=list)

    def get(self, key: str) -> str:
        return self.paths.get(key, "")


def identify(folder) -> str | None:
    """Which game is this folder, if any. By executable, never by name."""
    folder = Path(folder)
    try:
        if not folder.is_dir():
            return None
        names = {p.name.lower() for p in folder.iterdir() if p.is_file()}
    except (OSError, PermissionError):
        return None
    for game in GAMES:
        if not all(n.lower() in names for n in game.needs):
            continue
        if any(exe.lower() in names for exe in game.exe):
            return game.key
    return None


def registry_paths() -> list[tuple[Path, str]]:
    """Every install location Windows has a record of.

    Read-only, and it never asks the registry *which* game a folder holds -
    `DisplayName` is localised, decorated with trademark symbols and sometimes
    just wrong. The path is a suggestion; `identify` is the test.
    """
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []

    out: list[tuple[Path, str]] = []
    seen: set[str] = set()

    def add(raw, how: str):
        if not raw or not isinstance(raw, str):
            return
        path = Path(raw.strip().strip('"'))
        key = str(path).lower()
        if key in seen:
            return
        seen.add(key)
        out.append((path, how))

    hives = ((winreg.HKEY_LOCAL_MACHINE, "HKLM"), (winreg.HKEY_CURRENT_USER, "HKCU"))
    views = (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY)

    for hive, hive_name in hives:
        for subkey, value_name in REGISTRY_LISTS:
            for view in views:
                try:
                    parent = winreg.OpenKey(hive, subkey, 0,
                                            winreg.KEY_READ | view)
                except OSError:
                    continue
                with parent:
                    index = 0
                    while True:
                        try:
                            child_name = winreg.EnumKey(parent, index)
                        except OSError:
                            break
                        index += 1
                        try:
                            with winreg.OpenKey(parent, child_name, 0,
                                                winreg.KEY_READ | view) as child:
                                value, _kind = winreg.QueryValueEx(child,
                                                                   value_name)
                        except OSError:
                            continue
                        add(value, f"{hive_name}\\{subkey}")

        for subkey, value_name in REGISTRY_DIRECT:
            for view in views:
                try:
                    with winreg.OpenKey(hive, subkey, 0,
                                        winreg.KEY_READ | view) as key:
                        value, _kind = winreg.QueryValueEx(key, value_name)
                except OSError:
                    continue
                add(value, f"{hive_name}\\{subkey}")

    return out


def epic_paths() -> list[tuple[Path, str]]:
    """Epic keeps one JSON manifest per installed game."""
    folder = Path(EPIC_MANIFESTS)
    if not folder.is_dir():
        return []
    out = []
    for manifest in folder.glob("*.item"):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8",
                                                 errors="replace"))
        except (OSError, ValueError):
            continue
        location = data.get("InstallLocation")
        if location:
            out.append((Path(location), "Epic manifest"))
    return out


def steam_libraries() -> list[Path]:
    """Every Steam library folder, including the ones on other drives.

    The file is Valve's own KeyValues format. Only the `path` entries are
    wanted, and a regex over them is steadier than a hand-rolled parser for a
    format that has changed shape twice.
    """
    out: list[Path] = []
    for root in STEAM_ROOTS:
        index = Path(root) / "steamapps" / "libraryfolders.vdf"
        if not index.is_file():
            continue
        try:
            text = index.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for raw in re.findall(r'"path"\s*"([^"]+)"', text):
            path = Path(raw.replace("\\\\", "\\"))
            if path.is_dir() and path not in out:
                out.append(path)
    return out


def drives() -> list[Path]:
    """Fixed drives worth walking, without dragging in network or optical."""
    found = []
    if os.name == "nt":
        for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            path = Path(f"{letter}:\\")
            try:
                if path.is_dir():
                    found.append(path)
            except OSError:
                continue
    else:
        found = [Path.home()]
    return found


def _candidates_from(root: Path) -> list[Path]:
    """The obvious install folders under one root, without walking it."""
    out = []
    bases = [root, root / "steamapps" / "common", root / "Games",
             root / "GOG Games"]
    for base in bases:
        for game in GAMES:
            for name in game.folders:
                out.append(base / name)
    return out


def look(*, deep: bool = False, progress=None) -> Found:
    """Find what is installed. `deep` adds the drive walk."""
    found = Found()

    def note(key: str, path: Path, how: str):
        if key in found.paths:
            return
        found.paths[key] = str(path)
        found.how[key] = how

    def consider(path: Path, how: str):
        key = identify(path)
        if key:
            note(key, path, how)

    # 1. What Windows and the launchers already record. This is the only
    # mechanism that does not care how the game got there, so it goes first.
    recorded = registry_paths() + epic_paths()
    if recorded:
        found.searched.append(f"{len(recorded)} recorded install locations")
    for path, how in recorded:
        if len(found.paths) == len(GAMES):
            break
        consider(path, how)

    # 2. Steam's own index.
    for library in steam_libraries():
        found.searched.append(str(library))
        common = library / "steamapps" / "common"
        if not common.is_dir():
            continue
        for game in GAMES:
            for name in game.folders:
                consider(common / name, f"Steam library {library}")
        # A folder renamed by hand still shows up here, and there are rarely
        # more than a couple of hundred.
        try:
            for child in common.iterdir():
                if len(found.paths) == len(GAMES):
                    break
                consider(child, f"Steam library {library}")
        except (OSError, PermissionError):
            pass

    # 3. The usual non-Steam places, for a game that was copied
    # rather than installed and so left no record anywhere.
    for root in OTHER_ROOTS:
        path = Path(root)
        if not path.is_dir():
            continue
        found.searched.append(root)
        for candidate in _candidates_from(path):
            consider(candidate, f"known location {root}")
        try:
            for child in path.iterdir():
                consider(child, f"known location {root}")
        except (OSError, PermissionError):
            pass

    if len(found.paths) == len(GAMES) or not deep:
        return found

    # 4. Look properly.
    for drive in drives():
        if len(found.paths) == len(GAMES):
            break
        found.searched.append(str(drive))
        if progress is not None:
            progress(f"searching {drive}")
        for path in _walk(drive, MAX_DEPTH):
            consider(path, f"found on {drive}")
            if len(found.paths) == len(GAMES):
                break
    return found


def _walk(root: Path, depth: int):
    """Directories under `root`, no deeper than `depth`, skipping the noise."""
    skip = {"windows", "$recycle.bin", "system volume information",
            "appdata", "node_modules", ".git", "program files (x86)",
            "programdata"}
    stack = [(root, 0)]
    while stack:
        folder, level = stack.pop()
        if level > depth:
            continue
        try:
            children = [p for p in folder.iterdir() if p.is_dir()]
        except (OSError, PermissionError):
            continue
        for child in children:
            if child.name.lower() in skip:
                continue
            yield child
            stack.append((child, level + 1))


# --- remembering it --------------------------------------------------------


def load(path: Path | None = None) -> dict:
    path = path or CONFIG
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(paths: dict, path: Path | None = None) -> Path:
    """Remember what was found, so the search happens once."""
    path = path or CONFIG
    path.parent.mkdir(parents=True, exist_ok=True)
    keep = {k: str(v) for k, v in paths.items() if v}
    path.write_text(json.dumps(keep, indent=2) + "\n", encoding="utf-8")
    return path


def remembered(key: str, path: Path | None = None) -> str:
    """A saved path, if it is still a real install of that game."""
    found = load(path).get(key, "")
    return found if found and identify(found) == key else ""


def detect(*, deep: bool = False, use_cache: bool = True,
           config: Path | None = None, progress=None) -> Found:
    """What the app should open with: what was saved, then what is there."""
    found = Found()
    if use_cache:
        for game in GAMES:
            saved = remembered(game.key, config)
            if saved:
                found.paths[game.key] = saved
                found.how[game.key] = "remembered"
    if len(found.paths) == len(GAMES):
        return found

    fresh = look(deep=deep, progress=progress)
    for key, path in fresh.paths.items():
        if key not in found.paths:
            found.paths[key] = path
            found.how[key] = fresh.how[key]
    found.searched = fresh.searched
    return found
