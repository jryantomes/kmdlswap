"""Carry K1 saves from the old Party Roster Limit 32 save format to the KPM 0.7.3 one.

Before KPM 0.7.3, PartyRosterLimit32K1 (0.7.2 and earlier builds) saved party slots
9-31 in PARTYTABLE.res as PRK1_VER (1) + PRK1_DATA: "PRK1", then 23 x {DWORD available,
BYTE selectable, BYTE reserved}. 0.7.3's patch reads only PT_AVAIL_NPCS, extended to 32 entries,
and never reads PRK1_DATA - so on 0.7.3 an old save loses everyone in slots 9-31 (found
2026-10-10: a slot-10 companion listed in the party but unavailable; the next area change crashed).

This extends PT_AVAIL_NPCS to 32 entries from PRK1_DATA. PRK1_VER/PRK1_DATA stay, so the save
still loads on the old patch. Saves already with 32 entries, or without PRK1_DATA, are left alone.

usage: migrate_prk1.py <saves folder> [--dry-run]
"""
import struct
import subprocess
import sys
from pathlib import Path

from pykotor.resource.formats.gff import bytes_gff, read_gff

STOCK, MAX = 9, 32
MAGIC = b"PRK1"


def old_slots(blob):
    if len(blob) != 4 + 6 * (MAX - STOCK) or blob[:4] != MAGIC:
        raise ValueError(f"unexpected PRK1_DATA ({len(blob)} bytes, starts {blob[:4]!r})")
    return [struct.unpack_from("<IBB", blob, 4 + 6 * i)[:2] for i in range(MAX - STOCK)]


def migrate(path, dry_run):
    gff = read_gff(path.read_bytes())
    root = gff.root
    if not root.exists("PRK1_DATA"):
        return "no PRK1_DATA"
    lst = root.get_list("PT_AVAIL_NPCS")
    if len(lst) >= MAX:
        return f"already {len(lst)} entries"
    if len(lst) != STOCK:
        raise ValueError(f"PT_AVAIL_NPCS has {len(lst)} entries")
    slots = old_slots(root.get_binary("PRK1_DATA"))
    struct_id = lst.at(0).struct_id
    for available, selectable in slots:
        s = lst.add(struct_id)
        s.set_uint8("PT_NPC_AVAIL", 1 if available else 0)
        s.set_uint8("PT_NPC_SELECT", 1 if selectable else 0)
    root.set_list("PT_AVAIL_NPCS", lst)
    if not dry_run:
        path.write_bytes(bytes_gff(gff))
    on = [STOCK + i for i, (a, _) in enumerate(slots) if a]
    return f"converted; available in slots 9-31: {on or 'none'}"


def main(args):
    if not args:
        raise SystemExit(__doc__)
    saves, dry_run = Path(args[0]), "--dry-run" in args
    running = subprocess.run(["tasklist", "/FI", "IMAGENAME eq swkotor.exe"], capture_output=True, text=True).stdout
    if "swkotor.exe" in running.lower():
        raise SystemExit("KOTOR is running - close it first (it rewrites saves)")
    for d in sorted(p for p in saves.iterdir() if p.is_dir()):
        pt = next((f for f in d.iterdir() if f.name.lower() == "partytable.res"), None)
        if pt is None:
            continue
        try:
            print(f"{d.name}: {migrate(pt, dry_run)}")
        except ValueError as exc:
            print(f"{d.name}: SKIPPED - {exc}")


if __name__ == "__main__":
    main(sys.argv[1:])
