r"""Rebuild swkotor.ini after the game has shredded it.

The game overwrites its ini in place without truncating, so a shorter write
leaves the tail of the longer one behind. Do that a few dozen times and the file
fills with orphaned fragments - "treaming=1", "ory Level=1", "04=67" - and, worse,
section headers get eaten. On the dev copy (2026-09-22) the file had grown from
169 lines to 378, EnableCheats=1 had become "leCheats=1" stranded in
[Sound Options], and the whole [Alias] header was gone, which leaves the game
without its LOGS and OVERRIDE paths.

This rebuilds the file from the vanilla layout, carrying over every setting that
is still readable. A value counts as readable only if it sits under the right
section header and names a key that belongs there, which is what rejects the
debris: "SAVES=.\saves" under [Sound Options] is not an alias, it is wreckage.

  fix_ini.py check [ini]   say what is wrong, write nothing
  fix_ini.py fix   [ini]   back the file up and rebuild it

usage: fix_ini.py check|fix [path to swkotor.ini]
"""
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

GAME = Path(r"E:\SteamLibrary\steamapps\common\swkotor")

# The vanilla layout, section order and all, with vanilla values. Anything the
# old file still holds wins over these; they only fill gaps.
TEMPLATE = r"""[Sound Options]
Sound Init=0
Music Volume=85
Voiceover Volume=85
Sound Effects Volume=85
Movie Volume=100
Force Software=1
EAX=0
Disable Sound=0
Number 3D Voices=16
Number 2D Voices=24
Environment Effects Level=0.60
2D3D Bias=1.50
Environment Effects=1
Environment Effects Nonstreaming=1
Environment Effects Streaming=1

[Game Options]
GUIsInScreenShot=1
EnableScreenShot=0
EnableCheats=1
Reverse Mouse Buttons=0
Hide InGame GUI=0
Use Small Fonts=0
Keyboard Camera Deceleration=2000.000000
Keyboard Camera Acceleration=500.000000
Keyboard Camera DPS=200.000000
Hide Unequippable=0
Tutorial Popups=1
Subtitles=1
Mini Map=1
Floating Numbers=1
Status Summary=1
Enable Mouse Teleporting To Buttons=1
Mouse Sensitivity=33
Auto Level Up NPCs=0
Mouse Look=0
AutoSave=1
Reverse Minigame YAxis=0
Combat Movement=1
Enable Tooltips=1
Difficulty Level=1
TooltipDelay Sec=1.000000
Memory Access=1
Memory Level=1

[Movies Shown]
Movie 0=100
Movie 1=100
Movie 2=100
Movie 3=100
Movie 4=100
Movie 5=100
Movie 6=100
Movie 7=100
Movie 8=100
Movie 9=100
Movie10=100

[Alias]
HD0=.\
OVERRIDE=.\Override
TEMP=.\Temp
MODULES=.\Modules
LOGS=.\Logs
LOCALVAULT=.\LocalVault
DMVAULT=.\DMVault
SERVERVAULT=.\ServerVault
STREAMMUSIC=.\StreamMusic
TEMPCLIENT=.\Tempclient
SAVES=.\saves
CURRENTGAME=.\currentgame
TEXTUREPACKS=.\texturepacks
STREAMWAVES=.\StreamWaves

[Graphics Options]
RefreshRate=60
Height=1200
Width=1600
V-Sync=1
Anisotropy=1
Frame Buffer=0
Anti Aliasing=0
Texture Quality=2
Emitters=1
Grass=0
Soft Shadows=0
Shadows=1
Brightness=57
EnableHardwareMouse=1
FullScreen=1
Disable Vertex Buffer Objects=1

[Autopause Options]
Mine Sighted=1
End Of Combat Round=0
Enemy Sighted=1
Party Killed=1
Action Menu=0
New Target Selected=1

[config]
firstrun=0

[Keymapping]
"""

# Keys the game understands that the vanilla file does not write. Without this
# list a rebuild would throw away the logging switch we rely on.
EXTRA = {"Game Options": ["EnableReleaseLogging", "AllowWindowedMode"]}

HEADER = re.compile(r"^\[(.+)\]$")
PAIR = re.compile(r"^([^=\[\]]+)=(.*)$")


def parse(text):
    """{section: {key: value}}, taking the last value for a repeated key."""
    out, section = {}, None
    for line in text.splitlines():
        line = line.strip("\ufeff").rstrip()
        m = HEADER.match(line)
        if m:
            section = m.group(1)
            out.setdefault(section, {})
            continue
        m = PAIR.match(line)
        if m and section is not None:
            out[section][m.group(1)] = m.group(2)
    return out


def belongs(section, key, wanted):
    """Is this key one that section is allowed to hold?"""
    if section not in wanted:
        return False
    return (key in wanted[section]
            or key in EXTRA.get(section, [])
            or (section == "Keymapping" and key.startswith("Action")))


def rebuild(text):
    """(new text, [settings that were thrown away])."""
    old = parse(text)
    wanted = parse(TEMPLATE)
    lines, taken = [], {}
    for block in TEMPLATE.split("\n\n"):
        rows = [r for r in block.splitlines() if r]
        if not rows:
            continue
        section = HEADER.match(rows[0]).group(1)
        taken[section] = set()
        lines.append(f"[{section}]")
        for row in rows[1:]:
            key, vanilla = PAIR.match(row).group(1, 2)
            value = old.get(section, {}).get(key, vanilla)
            lines.append(f"{key}={value}")
            taken[section].add(key)
        for key in EXTRA.get(section, []):
            if key in old.get(section, {}):
                lines.append(f"{key}={old[section][key]}")
                taken[section].add(key)
        if section == "Keymapping":
            for key, value in old.get("Keymapping", {}).items():
                if key.startswith("Action"):
                    lines.append(f"{key}={value}")
                    taken[section].add(key)
        lines.append("")
    dropped = [f"[{s}] {k}={v}" for s, keys in old.items() for k, v in keys.items()
               if not belongs(s, k, wanted) or k not in taken.get(s, ())]
    return "\n".join(lines), dropped


def debris(text):
    """[(line number, line)] for every line that belongs to no section key."""
    bad, section, wanted = [], None, parse(TEMPLATE)
    for n, line in enumerate(text.splitlines(), 1):
        line = line.rstrip()
        if not line:
            continue
        m = HEADER.match(line)
        if m:
            section = m.group(1)
            continue
        m = PAIR.match(line)
        if not m or not belongs(section, m.group(1), wanted):
            bad.append((n, line))
    return bad


def main(argv):
    what = argv[0] if argv else "check"
    path = Path(argv[1]) if len(argv) > 1 else GAME / "swkotor.ini"
    text = path.read_text(encoding="utf-8", errors="replace")
    bad = debris(text)
    if what == "check":
        print(f"{path}: {len(text.splitlines())} lines, {len(bad)} of them debris")
        for n, line in bad[:20]:
            print(f"  line {n}: {line}")
        if len(bad) > 20:
            print(f"  ... and {len(bad) - 20} more")
        gone = [s for s in parse(TEMPLATE) if f"[{s}]" not in text]
        if gone:
            print("section headers eaten: " + ", ".join(gone))
        return
    if what != "fix":
        raise SystemExit(__doc__)
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq swkotor.exe"],
                         capture_output=True, text=True).stdout
    if "swkotor.exe" in out.lower():
        raise SystemExit("KOTOR is running - close it first. Nothing was written.")
    new, dropped = rebuild(text)
    backup = path.parent / f"{path.name}.before-rebuild-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(path, backup)
    path.write_text(new, encoding="utf-8")
    print(f"{path.name}: {len(text.splitlines())} lines -> {len(new.splitlines())}, "
          f"{len(bad)} debris lines gone; backup {backup.name}")
    for row in dropped:
        print(f"  dropped {row}")


if __name__ == "__main__":
    main(sys.argv[1:])
