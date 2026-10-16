"""Build, adopt and reset vanilla KOTOR 1 test installs for HoloPatcher / mod testing.

    python make_test_install.py build  D:\\KOTOR_Test   # copy a vanilla install from Steam
    python make_test_install.py adopt  D:\\KOTOR_GOG    # fingerprint a fresh install as its baseline
    python make_test_install.py reset  D:\\KOTOR_GOG    # back to the baseline
    python make_test_install.py verify D:\\KOTOR_GOG    # report only

Vanilla reference: Steam's depot manifest for the installed build (file list +
SHA-1). `build` copies each file from the live Steam install where it still
matches the manifest, else from a known vanilla backup (VANILLA_BACKUPS), else
from the live install flagged NOT VANILLA. swkotor.exe/ini are deliberately
the live ones (Steamless-unpacked 4GB exe: the SteamStub exe relaunches
through Steam, i.e. would start the LIVE install).

Every test install carries a baseline (.k1_testinstall.json: path -> size,
sha1) and, in _baseline\\, copies of the baseline files the live Steam install
cannot supply. `reset` restores changed files from those two sources and moves
every file not in the baseline (mod installs) into _reset_removed\\<time>\\ -
nothing is deleted. saves\\ is never touched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from steam_manifest import read_manifest  # noqa: E402

LIVE = Path(r"E:\SteamLibrary\steamapps\common\swkotor")
MANIFEST = Path(r"C:\Program Files (x86)\Steam\depotcache\32371_4122010938027300909.manifest")
VANILLA_BACKUPS = {
    "dialog.tlk": Path(r"D:\Downloads\K1_Community_Patch_v1.10.0\backup\2025-11-07_18.00.28\dialog.tlk"),
    "texturepacks\\swpc_tex_gui.erf": Path(r"D:\KOTOR_GOG\TexturePacks\swpc_tex_gui.erf"),
}
DELIBERATE = {"swkotor.exe", "swkotor.ini"}   # build takes these from the live install
MARKER = ".k1_testinstall.json"
STASH = "_baseline"
REMOVED = "_reset_removed"
SKIP_TOP = {"saves", STASH, REMOVED, MARKER}


def sha1(p: Path) -> str:
    h = hashlib.sha1()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def same(p: Path, size: int, digest: str) -> bool:
    return p.is_file() and p.stat().st_size == size and sha1(p) == digest


def tracked(dest: Path):
    for p in sorted(dest.rglob("*")):
        rel = p.relative_to(dest)
        if p.is_file() and rel.parts[0] not in SKIP_TOP:
            yield str(rel), p


def check_dest(dest: Path, must_be_ours: bool) -> None:
    live = LIVE.resolve()
    if dest == live or live in dest.parents or dest in live.parents:
        sys.exit("refusing: destination overlaps the live Steam install")
    if must_be_ours and not (dest / MARKER).is_file():
        sys.exit(f"refusing: {dest} has no {MARKER} (build or adopt it first)")


def write_baseline(dest: Path, info: dict) -> None:
    """Hash every tracked file; stash those the live install cannot restore."""
    live_ok = {f.name.lower(): f for f in read_manifest(MANIFEST) if not f.is_dir}
    files, stashed = {}, 0
    for rel, p in tracked(dest):
        size, digest = p.stat().st_size, sha1(p)
        files[rel] = [size, digest]
        m = live_ok.get(rel.lower())
        if not (m and m.sha1 == digest and same(LIVE / m.name, size, digest)):
            (dest / STASH / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest / STASH / rel)
            stashed += 1
    info.update(files=files, stashed=stashed, baseline_time=time.strftime("%Y-%m-%d %H:%M:%S"))
    (dest / MARKER).write_text(json.dumps(info, indent=1), encoding="utf-8")
    print(f"baseline: {len(files)} files, {stashed} stashed in {STASH}\\")


def build(dest: Path) -> None:
    if dest.exists() and any(dest.iterdir()) and not (dest / MARKER).is_file():
        sys.exit(f"refusing: {dest} is not empty and has no {MARKER}")
    not_vanilla = []
    for f in (f for f in read_manifest(MANIFEST) if not f.is_dir):
        key, live, out = f.name.lower(), LIVE / f.name, dest / f.name
        bk = VANILLA_BACKUPS.get(key)
        if key in DELIBERATE:
            src = live
        elif same(live, f.size, f.sha1):
            src = live
        elif bk and same(bk, f.size, f.sha1):
            src = bk
        else:
            src = live
            not_vanilla.append(f.name)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
        if key not in DELIBERATE and f.name not in not_vanilla and not same(out, f.size, f.sha1):
            sys.exit(f"copy failed verification: {f.name}")
    for d in ("Override", "saves", "logs"):
        (dest / d).mkdir(exist_ok=True)
    for n in not_vanilla:
        print("NOT VANILLA (no vanilla source found):", n)
    write_baseline(dest, {"origin": "steam-copy", "not_vanilla": not_vanilla})


def reset(dest: Path, dry: bool) -> None:
    info = json.loads((dest / MARKER).read_text(encoding="utf-8"))
    files = info["files"]
    lower = {k.lower() for k in files}
    bin_ = dest / REMOVED / time.strftime("%Y%m%d-%H%M%S")
    extra = [(rel, p) for rel, p in tracked(dest) if rel.lower() not in lower]
    changed = 0
    missing = []
    for rel, (size, digest) in files.items():
        out = dest / rel
        if same(out, size, digest):
            continue
        changed += 1
        if dry:
            print("DIFFERS:" if out.exists() else "MISSING:", rel)
            continue
        for src in (dest / STASH / rel, LIVE / rel):
            if same(src, size, digest):
                if out.exists():
                    (bin_ / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(out, bin_ / rel)
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, out)
                break
        else:
            missing.append(rel)      # finish the reset first: a half reset leaves earlier runs' files
    for rel, p in extra:
        if dry:
            print("EXTRA:", rel)
            continue
        (bin_ / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.move(p, bin_ / rel)
    verb = "differ" if dry else "restored"
    print(f"{len(files)} baseline files: {changed} {verb}; {len(extra)} extra files"
          + ("" if dry or not (changed or extra) else f" moved to {bin_.relative_to(dest)}"))
    if missing:
        sys.exit("no source matches the baseline for " + ", ".join(missing)
                 + f" - put a vanilla copy in {STASH}\\")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["build", "adopt", "reset", "verify"])
    ap.add_argument("dest", type=Path)
    a = ap.parse_args()
    dest = a.dest.resolve()
    check_dest(dest, must_be_ours=a.action in ("reset", "verify"))
    if a.action == "build":
        build(dest)
    elif a.action == "adopt":
        if (dest / MARKER).is_file():
            sys.exit(f"{dest} already has a baseline; delete {MARKER} and {STASH}\\ to re-adopt")
        write_baseline(dest, {"origin": "adopted"})
    else:
        reset(dest, dry=a.action == "verify")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
