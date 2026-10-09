"""K1 Community Patch fixes merged into the whole dialogues later mods installed over them.

The install audit (2026-10-09) found 571 of K1CP's fixes CLOBBERED: Sleheyron and RC-K1CP ship whole copies
of some dialogues (in Override), made from the vanilla ones, so K1CP's fixes to those dialogues - patched
into the module copies, which the Override copy hides - are not in the game.

A three-way merge per dialogue, field by field:
    vanilla  - the game's own copy (the module's .rim)
    fixed    - what K1CP leaves of it (bases.others_copy: vanilla + K1CP's installs and patches)
    live     - the copy the game reads now (the later mod's, in Override)
  a field K1CP changed and the later mod left as vanilla  -> K1CP's value goes into the live copy;
  a field both changed (to different values)               -> the later mod's stays: a conflict, listed;
  a link list K1CP changed and the later mod did not       -> K1CP's list (when every node it points to exists);
  nodes K1CP added (past vanilla's end)                    -> not merged: listed.
Only when the live copy keeps vanilla's nodes in vanilla's order (each node's text the same string
reference); otherwise the dialogue is left alone and listed.

Run on the harness mirror, audit, then the dev copy; backups and a manifest (--remove puts them back).

usage: merge.py <game folder> <backup dir> [--dry-run]
       merge.py <game folder> <backup dir> --remove
"""
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import audit                                                                     # noqa: E402
import bases                                                                     # noqa: E402

from pykotor.resource.formats.gff import GFFFieldType, bytes_gff, read_gff      # noqa: E402

K1CP = "K1 Community Patch"
LISTS = {"EntryList": "RepliesList", "ReplyList": "EntriesList"}
SIMPLE = {GFFFieldType.UInt8, GFFFieldType.Int8, GFFFieldType.UInt16, GFFFieldType.Int16, GFFFieldType.UInt32,
          GFFFieldType.Int32, GFFFieldType.Int64, GFFFieldType.UInt64, GFFFieldType.Single, GFFFieldType.Double,
          GFFFieldType.String, GFFFieldType.ResRef}
MANIFEST = "merge.json"


def fields(s):
    return {label: (ftype, value) for label, ftype, value in s}


def links(s, field):
    return [(int(l.acquire("Index", 0)), str(l.acquire("Active", "")), int(l.acquire("IsChild", 0)))
            for l in s.acquire(field, [])]


def strref(s):
    t = s.acquire("Text", None)
    return getattr(t, "stringref", None)


def merge(vanilla, fixed, live):
    """(merged bytes or None, notes) - see the module's docstring."""
    V, F, L = read_gff(vanilla).root, read_gff(fixed).root, read_gff(live)
    notes = {"applied": 0, "conflicts": [], "skipped": []}
    for kind, lf in LISTS.items():
        v, f, l = V.acquire(kind, []), F.acquire(kind, []), L.root.acquire(kind, [])
        if len(l) < len(v):
            return None, {"why": f"{kind}: the live copy has fewer nodes than vanilla"}
        for i in range(len(v)):
            if strref(v[i]) != strref(l[i]):
                return None, {"why": f"{kind}[{i}]: the live copy's nodes are not in vanilla's order"}
        if len(f) > len(v):
            notes["skipped"].append(f"{kind}: {len(f) - len(v)} node(s) K1CP added - not merged")
    for kind, lf in LISTS.items():
        v, f = V.acquire(kind, []), F.acquire(kind, [])
        lst = L.root.get_list(kind)
        n_vanilla = {k: len(V.acquire(k, [])) for k in LISTS}    # links may only reach vanilla's nodes:
                                                                   # past its end the live copy's are another mod's
        for i in range(len(v)):
            fv, ff, fl = fields(v[i]), fields(f[i]), fields(lst.at(i))
            node = lst.at(i)
            for label, (ftype, fval) in ff.items():
                if label == lf or ftype not in SIMPLE:
                    continue
                vval = fv.get(label, (None, None))[1]
                if str(fval) == str(vval):
                    continue                                 # K1CP did not change it
                lval = fl.get(label, (None, None))[1]
                if label in fl and str(lval) != str(vval):
                    if str(lval) != str(fval):
                        notes["conflicts"].append(f"{kind}[{i}].{label}: K1CP {fval!r}, live {lval!r}")
                    continue
                getattr(node, f"set_{ftype.name.lower()}")(label, fval)     # set_uint32, set_resref, ...
                notes["applied"] += 1
            # link list
            vl, fl_, ll = links(v[i], lf), links(f[i], lf), links(node, lf)
            if fl_ != vl:
                target = "ReplyList" if kind == "EntryList" else "EntryList"
                if ll != vl:
                    if ll != fl_:
                        notes["conflicts"].append(f"{kind}[{i}].{lf}: both changed its links")
                elif all(t < n_vanilla[target] for t, _a, _c in fl_):
                    node.set_list(lf, f[i].acquire(lf, None))
                    notes["applied"] += 1
                else:
                    notes["skipped"].append(f"{kind}[{i}].{lf}: K1CP links to a node it added - not merged")
        L.root.set_list(kind, lst)
    return (bytes(bytes_gff(L)) if notes["applied"] else None), notes


def clobbered(report):
    """{(dest, file)}: the K1CP findings CLOBBERED by a later mod's whole file."""
    out = set()
    for r in report.get(next(k for k in report if K1CP.lower() in k.lower()), []):
        if r["status"] == audit.CLOBBERED and r["area"] == "GFF":
            path = r["item"].split(" ")[0]
            dest, name = path.rsplit("\\", 1)
            if name.lower().endswith(".dlg"):
                out.add((dest.lower(), name.lower()))
    return out


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    game, backup = Path(argv[0]), Path(argv[1])
    if "--remove" in argv:
        import repair
        return repair.remove(game, backup)
    bases.GAME = game
    report = json.loads(audit.report_path(game, ".json").read_text(encoding="utf-8"))
    g = audit.Game(game)
    plan = []
    for dest, name in sorted(clobbered(report)):
        live, shadowed = g.effective(dest, name)
        vanilla = bases._vanilla(dest, name)
        try:
            fixed = bases.others_copy(dest, name, only=(K1CP,))
        except SystemExit as e:
            print(f"  {dest}\\{name}: left alone - {e}")
            continue
        if live is None or vanilla is None:
            print(f"  {dest}\\{name}: left alone - no live or vanilla copy")
            continue
        merged, notes = merge(vanilla, fixed, live)
        where = "override" if shadowed or dest == "override" else dest
        if merged is None:
            print(f"  {dest}\\{name}: left alone - {notes.get('why', 'nothing to merge')}"
                  + (f"; {len(notes.get('conflicts', []))} conflict(s)" if notes.get("conflicts") else ""))
            continue
        print(f"  {where}\\{name}: {notes['applied']} K1CP fix(es) merged, {len(notes['conflicts'])} conflict(s) "
              f"kept the later mod's" + (f"; {'; '.join(notes['skipped'])}" if notes["skipped"] else ""))
        for c in notes["conflicts"][:6]:
            print(f"      conflict {c}")
        plan.append((where, name, merged, notes))
    if "--dry-run" in argv or not plan:
        print(f"{len(plan)} dialogue(s) to merge" + (" (dry run)" if "--dry-run" in argv else ""))
        return
    if audit_running():
        raise SystemExit("KOTOR is running - game files are not written while it runs")
    import repair
    backup.mkdir(parents=True, exist_ok=True)
    manifest = {"game": str(game), "added": [], "replaced": [], "files": []}
    for where, name, merged, notes in plan:
        repair.write(game, where.lower(), name, merged, backup, manifest)
        manifest["files"].append({"where": where, "file": name, "applied": notes["applied"],
                                  "conflicts": notes["conflicts"], "skipped": notes["skipped"]})
    (backup / repair.MANIFEST).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"merged {len(manifest['files'])} dialogue(s); backups and manifest in {backup} (repair.py <game> <backup> --remove undoes)")


def audit_running():
    import subprocess
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq swkotor.exe"], capture_output=True, text=True).stdout
    return "swkotor.exe" in out.lower()


if __name__ == "__main__":
    main(sys.argv[1:])
