"""Install audit: is every installed mod's work still in the game?

Reads each mod's changes.ini (mods.toml, install order) with PyKotor's own TSLPatcher reader - what
HoloPatcher would do - and checks the dev copy for it:
  files    every [InstallList] file: still there, byte for byte the mod's copy? If not: whose copy is
           there now (another audited mod's, by hash), or patched since by a later mod's lists.
  2DA      every AddRow / CopyRow: a row with the mod's literal values (by its ExclusiveColumn value or
           RowLabel when it has one, else by all its literal cells); every ChangeRow: its target row
           holds the values; AddColumn: the column is there. Rows are found by content, never by
           number. Token values (2DAMEMORY, StrRef, high()) are not literal: not compared.
  GFF      every literal ModifyField value at its path; every AddStructToList: a struct in that list
           with the new struct's literal fields; AddField with a literal value: the field at its path.
  TLK      every appended / replaced string's text is in dialog.tlk (appends: anywhere; replacements:
           at their StrRef).
  scripts  HACKList / CompileList outputs are in place.
A finding a LATER mod in the list explains by patching the same thing (sets that row's cell, patches
that file) is "superseded" - expected, by install order. One where a later mod installed the WHOLE
file over this mod's work is CLOBBERED - that later mod's compatibility bug (it should patch, not
replace), unless known.toml accepts it (a deliberate compatibility file). One nothing explains is a
FAIL: something outside these mods (a tool, a manual copy, an earlier mod reinstalled) undid it. known.toml lists findings accepted on purpose,
each with its reason.

Writes reports/install-audit/<date>.md and .json; exit 1 if any FAIL.

usage: audit.py [--mod <name part>]... [--game <folder>]
"""
import datetime
import hashlib
import io
import json
import sys
import tomllib
from collections import defaultdict
from pathlib import Path, PureWindowsPath

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GAME = Path(r"E:\SteamLibrary\steamapps\common\swkotor")
OUT = ROOT / "reports" / "install-audit"

from pykotor.extract.installation import Installation, SearchLocation           # noqa: E402
from pykotor.resource.formats.erf import read_erf                               # noqa: E402
from pykotor.resource.formats.gff import read_gff                               # noqa: E402
from pykotor.resource.formats.rim import read_rim                               # noqa: E402
from pykotor.resource.formats.tlk import read_tlk                               # noqa: E402
from pykotor.resource.formats.twoda import read_2da                             # noqa: E402
from pykotor.resource.type import ResourceType                                  # noqa: E402
from pykotor.tslpatcher.config import PatcherConfig                             # noqa: E402
from pykotor.tslpatcher.logger import PatchLogger                               # noqa: E402
from pykotor.tslpatcher.mods import gff as gffm                                 # noqa: E402
from pykotor.tslpatcher.mods import twoda as tdm                                # noqa: E402
from pykotor.tslpatcher.reader import ConfigReader                              # noqa: E402

BS = "\\"
OK, SUPERSEDED, ACCEPTED, FAIL, SKIP = "ok", "superseded", "accepted", "FAIL", "not checked"
CLOBBERED = "CLOBBERED"      # a later mod installed the whole file over this mod's work: its compatibility bug


# --- reading the mods ------------------------------------------------------------------------------
def load_mods(only=()):
    mods = tomllib.loads((HERE / "mods.toml").read_text(encoding="utf-8"))["mod"]
    out = []
    for order, m in enumerate(mods):
        ini = Path(m["ini"])
        if not ini.exists():
            raise SystemExit(f"{m['name']}: {ini} not found (mods.toml)")
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()):          # the reader prints every section it reads
            reader = ConfigReader.from_filepath(ini, PatchLogger(), ini.parent)
            cfg = reader.load(PatcherConfig())
        out.append({"name": m["name"], "order": order, "ini": ini, "data": ini.parent, "cfg": cfg,
                    "checked": not only or any(o.lower() in m["name"].lower() for o in only)})
    return out


def dest_of(p):
    """'override', or a capsule path like 'modules\\x.mod', or another folder - lower case, \\ separators."""
    d = str(PureWindowsPath(p.destination)).strip("\\").lower()
    return "override" if d in ("", ".", "override") else d


def source_of(mod, f):
    folder = getattr(f, "sourcefolder", ".") or "."
    return mod["data"] / folder / f.sourcefile


# --- reading the game ------------------------------------------------------------------------------
class Game:
    def __init__(self, root):
        self.root = root
        self.inst = Installation(str(root))
        self._capsules = {}
        self._tlk = None

    def capsule(self, rel):
        if rel not in self._capsules:
            p = self.root / rel
            res = {}
            if p.exists():
                data = p.read_bytes()
                arc = read_rim(data) if p.suffix.lower() == ".rim" else read_erf(data)
                for r in arc:
                    res[f"{r.resref}.{r.restype.extension}".lower()] = r.data
            self._capsules[rel] = res if p.exists() else None
        return self._capsules[rel]

    def file(self, dest, name):
        """bytes of name at dest (Override, a folder, or inside a capsule), or None."""
        if dest.endswith((".mod", ".erf", ".rim", ".sav")):
            cap = self.capsule(dest)
            return None if cap is None else cap.get(name.lower())
        folder = self.root / ("Override" if dest == "override" else dest)
        p = folder / name
        return p.read_bytes() if p.exists() else None

    def effective(self, dest, name):
        """(bytes, shadowed): the copy the game reads. A file in Override wins over a module's copy, so a
        patch made inside a capsule is not seen while Override holds the same file (shadowed)."""
        if dest.endswith((".mod", ".erf", ".rim")):
            o = self.root / "Override" / name
            if o.exists():
                return o.read_bytes(), True
        return self.file(dest, name), False

    def base(self, name):
        resref, ext = name.rsplit(".", 1)
        r = self.inst.resource(resref, ResourceType.from_extension(ext), [SearchLocation.CHITIN])
        return None if r is None else r.data

    def tlk(self):
        if self._tlk is None:
            self._tlk = read_tlk((self.root / "dialog.tlk").read_bytes())
        return self._tlk


# --- the checks -------------------------------------------------------------------------------------
def literal(v):
    """The literal text of a 2DA cell value, or None for a token / computed one."""
    return v.string if isinstance(v, tdm.RowValueConstant) else None


def literal_cells(cells):
    return {k.lower(): s for k, v in cells.items() if (s := literal(v)) is not None}


def table_rows(data):
    t = read_2da(data)
    heads = [h.lower() for h in t.get_headers()]
    rows = []
    for i in range(t.get_height()):
        r = t.get_row(i)
        rows.append({"__label": t.get_label(i), **{h.lower(): r.get_string(h) for h in t.get_headers()}})
    return heads, rows


def same(a, b):
    a = "" if a in ("****", None) else str(a)
    b = "" if b in ("****", None) else str(b)
    if a.lower() == b.lower():
        return True
    try:
        return abs(float(a) - float(b)) <= 1e-4 * max(1.0, abs(float(b)))
    except ValueError:
        return False


def find_rows(rows, want, exclusive=None, label=None):
    """Rows carrying want's literal values: by the exclusive column's value, else the row label, else
    all literal cells. -> (matching rows, best partial row, its differing columns)"""
    if exclusive and exclusive.lower() in want:
        key = exclusive.lower()
        cand = [r for r in rows if same(r.get(key), want[key])]
    elif label is not None:
        cand = [r for r in rows if same(r["__label"], label)]
    else:
        cand = rows
    full = [r for r in cand if all(same(r.get(k), v) for k, v in want.items())]
    if full:
        return full, None, []
    best, diff = None, None
    for r in cand:
        d = [k for k, v in want.items() if not same(r.get(k), v)]
        if diff is None or len(d) < len(diff):
            best, diff = r, d
    if best is not None and (exclusive or label is not None or len(diff) <= max(1, len(want) // 3)):
        return [], best, diff
    return [], None, []


def target_row(rows, target):
    v = target.value
    if not isinstance(v, (str, int)):
        return "token"
    if target.target_type == tdm.TargetType.ROW_INDEX:
        i = int(v)
        return rows[i] if 0 <= i < len(rows) else None
    if target.target_type == tdm.TargetType.ROW_LABEL:
        return next((r for r in rows if same(r["__label"], v)), None)
    return next((r for r in rows if same(r.get("label"), v)), None)


def gff_walk(root, path):
    """The struct / list / value at a TSLPatcher GFF path (labels and list indices), or KeyError."""
    node = root
    for part in PureWindowsPath(path).parts:
        if isinstance(node, list):
            node = node[int(part)]
        elif part.isdigit() and not (hasattr(node, "exists") and node.exists(part)):
            raise KeyError(part)
        else:
            if not node.exists(part):
                raise KeyError(part)
            node = node.value(part)
    return node


def gff_literal(fv):
    if isinstance(fv, gffm.FieldValueListIndex):
        return None
    if isinstance(fv, gffm.FieldValueConstant):
        v = fv.stored
        if isinstance(v, (int, float, str)) or type(v).__name__ == "ResRef":
            return v
    return None


def check_mod(mod, mods, game, known):
    """[(area, item, status, detail)] for one mod."""
    cfg, out = mod["cfg"], []
    later = [m for m in mods if m["order"] > mod["order"]]

    def add(area, item, status, detail=""):
        for k in known:
            if k["mod"].lower() in mod["name"].lower() and k["item"].lower() in item.lower():
                if status in (FAIL, CLOBBERED, SUPERSEDED):
                    status, detail = ACCEPTED, f"{detail} - accepted: {k['reason']}"
                break
        out.append((area, item, status, detail))

    def later_installs(dest, name):
        """Later mods that install this whole file over what is there (Replace; File keeps an existing one)."""
        return sorted({m["name"] for m in later for f in m["cfg"].install_list
                       if f.replace_file and f.saveas.lower() == name.lower() and dest_of(f) == dest})

    def later_patches(dest, name):
        """Later mods that patch this file in place (or, for a capsule, anything inside it)."""
        whole = f"{dest}\\{name}".lower()
        return sorted({m["name"] for m in later
                       for lst in (m["cfg"].patches_2da, m["cfg"].patches_gff, m["cfg"].patches_ncs,
                                   m["cfg"].patches_nss, m["cfg"].patches_ssf)
                       for f in lst if (f.saveas.lower() == name.lower() and dest_of(f) == dest)
                       or dest_of(f) == whole})

    def explain(dest, name, status, detail):
        """A failed check on a file, explained by a later mod if one touches that file."""
        li = later_installs(dest, name)
        if li:
            return CLOBBERED, f"{detail} (the whole file was installed after it by {', '.join(li)})"
        lp = later_patches(dest, name)
        if lp:
            return SUPERSEDED, f"{detail} (patched after it by {', '.join(lp)})"
        return status, detail

    # files
    patched_here = set()
    for lst in (cfg.patches_2da, cfg.patches_gff, cfg.patches_ncs, cfg.patches_nss, cfg.patches_ssf):
        for f in lst:
            patched_here.add((dest_of(f), f.saveas.lower()))
            d = PureWindowsPath(dest_of(f))
            if d.suffix in (".mod", ".erf", ".rim"):                 # patched inside: the capsule itself changes
                patched_here.add((str(d.parent).lower(), d.name.lower()))
    for f in cfg.install_list:
        dest, name = dest_of(f), f.saveas
        if dest.startswith("saves"):                 # a save game a mod ships: not part of the install
            continue
        item = f"{dest}\\{name}"
        src = source_of(mod, f)
        if not src.exists():
            add("files", item, SKIP, "the mod's own copy is missing from its installer")
            continue
        live = game.file(dest, name)
        if live is None:
            add("files", item, FAIL, "missing")
            continue
        if live == src.read_bytes():
            add("files", item, OK)
            continue
        if (dest, name.lower()) in patched_here:
            add("files", item, OK, "patched afterwards by this mod's own lists (checked below)")
            continue
        h = hashlib.sha1(live).hexdigest()
        owner = INDEX.get((dest, name.lower(), h))
        if owner and owner != mod["name"]:
            m_owner = next(m for m in mods if m["name"] == owner)
            add("files", item, CLOBBERED if m_owner["order"] > mod["order"] else FAIL, f"now {owner}'s copy")
        elif later_installs(dest, name) or later_patches(dest, name):
            add("files", item, *explain(dest, name, FAIL, "changed"))
        elif not f.replace_file:
            add("files", item, SUPERSEDED, "a copy already there was kept (File, not Replace) - not this mod's")
        else:
            add("files", item, FAIL, "changed - by nothing in the audited mods")

    # 2DA
    for t in cfg.patches_2da:
        name = t.saveas
        data = game.file(dest_of(t), name)
        if data is None:
            add("2DA", name, FAIL, "the table is not in Override: the game uses the vanilla one - every row this mod added is gone")
            continue
        heads, rows = table_rows(data)
        for m in t.modifiers:
            if isinstance(m, tdm.AddColumn2DA):
                add("2DA", f"{name} column {m.header}", OK if m.header.lower() in heads else FAIL,
                    "" if m.header.lower() in heads else "column missing")
                continue
            want = literal_cells(m.cells)
            if isinstance(m, tdm.ChangeRow2DA):
                row = target_row(rows, m.target)
                item = f"{name} ChangeRow {m.identifier} ({m.target.target_type.name.lower()} {m.target.value})"
                if row == "token":
                    add("2DA", item, SKIP, "target is a token")
                elif row is None:
                    add("2DA", item, FAIL, "target row not found")
                else:
                    bad = {k: (v, row.get(k)) for k, v in want.items() if not same(row.get(k), v)}
                    if not bad:
                        add("2DA", item, OK)
                    else:
                        lt = later_2da_cell(later, name, row, bad)
                        add("2DA", item, SUPERSEDED if lt else FAIL,
                            "; ".join(f"{k} = {g!r}, not {w!r}" for k, (w, g) in bad.items())
                            + (f" (set by {', '.join(lt)})" if lt else ""))
                continue
            if isinstance(m, (tdm.AddRow2DA, tdm.CopyRow2DA)):
                kind = "AddRow" if isinstance(m, tdm.AddRow2DA) else "CopyRow"
                label = m.row_label if isinstance(m.row_label, str) else None
                key = want.get((m.exclusive_column or "").lower()) or label or m.identifier
                item = f"{name} {kind} {key}"
                if not want and not label:
                    add("2DA", item, SKIP, "no literal values")
                    continue
                full, best, diff = find_rows(rows, want, m.exclusive_column, label)
                if full:
                    add("2DA", item, OK, f"row {rows.index(full[0])}" + (f" (x{len(full)} - duplicates)" if len(full) > 1 else ""))
                elif best is not None:
                    bad = {k: (want[k], best.get(k)) for k in diff}
                    lt = later_2da_cell(later, name, best, bad)
                    add("2DA", item, SUPERSEDED if lt else FAIL,
                        f"row {rows.index(best)}: " + "; ".join(f"{k} = {g!r}, not {w!r}" for k, (w, g) in bad.items())
                        + (f" (set by {', '.join(lt)})" if lt else ""))
                else:
                    add("2DA", item, FAIL, "row missing")

    # GFF
    for g in cfg.patches_gff:
        dest, name = dest_of(g), g.saveas
        if dest.startswith("saves"):                 # a save game: not part of the install
            continue
        data, shadowed = game.effective(dest, name)
        if data is None:
            add("GFF", f"{dest}\\{name}", *explain(dest, name, FAIL, "file missing"))
            continue
        try:
            root = read_gff(data).root
        except Exception as e:                       # noqa: BLE001
            add("GFF", f"{dest}\\{name}", FAIL, f"unreadable: {e}")
            continue
        def gadd(area, item, status, detail="", dest=dest, name=name, shadowed=shadowed):
            if status == FAIL:
                if shadowed:
                    li = later_installs("override", name)
                    status, detail = (CLOBBERED, f"{detail} - Override's own copy, installed after it by "
                                      f"{', '.join(li)}, is what the game reads") if li else \
                        (FAIL, f"{detail} - the game reads Override's own copy, so this mod's edit in the "
                               f"module copy has no effect (shadowed)")
                else:
                    status, detail = explain(dest, name, status, detail)
            add(area, item, status, detail)
        for m in g.modifiers:
            check_gff(m, root, dest, name, gadd, later)

    # TLK
    tlk_mods = getattr(cfg.patches_tlk, "modifiers", [])
    if tlk_mods:
        tlk = game.tlk()
        texts = None
        missing, wrong = 0, []
        for m in tlk_mods:
            if not m.text and hasattr(m, "load"):
                try:
                    m.load()
                except Exception:                    # noqa: BLE001
                    pass
            if not m.text:
                continue
            if m.is_replacement:
                got = tlk.get(m.mod_index)
                if got is None or got.text != m.text:
                    wrong.append(m.mod_index)
            else:
                if texts is None:
                    texts = {e.text for _, e in tlk}
                if m.text not in texts:
                    missing += 1
        n = len(tlk_mods)
        add("TLK", f"dialog.tlk ({n} strings)", OK if not missing and not wrong else FAIL,
            ", ".join(x for x in (f"{missing} appended strings not found" if missing else "",
                                  f"replacements changed at {wrong[:8]}" if wrong else "") if x))

    # scripts
    for s in list(cfg.patches_ncs) + list(cfg.patches_nss):
        dest = dest_of(s)
        name = s.saveas if s.saveas.lower().endswith(".ncs") else s.saveas.rsplit(".", 1)[0] + ".ncs"
        live = game.file(dest, name)
        add("scripts", f"{dest}\\{name}", OK if live is not None else FAIL, "" if live is not None else "missing")
    return out


def later_2da_cell(later, name, row, bad):
    """Later mods whose ChangeRow / AddRow sets one of these cells to the value now there."""
    who = []
    for m in later:
        for t in m["cfg"].patches_2da:
            if t.saveas.lower() != name.lower():
                continue
            for mod in t.modifiers:
                cells = literal_cells(getattr(mod, "cells", {}) or {})
                if any(k in cells and same(cells[k], got) for k, (_w, got) in bad.items()):
                    who.append(m["name"])
    return sorted(set(who))


def check_gff(m, root, dest, name, add, later):
    where = f"{dest}\\{name}"
    if isinstance(m, gffm.ModifyFieldGFF):
        want = gff_literal(m.value)
        if want is None:
            return
        try:
            got = gff_walk(root, m.path)
        except (KeyError, IndexError, ValueError):
            add("GFF", f"{where} {m.path}", FAIL, "path not found")
            return
        ok = same(got, want)
        add("GFF", f"{where} {m.path}", OK if ok else FAIL, "" if ok else f"{got!r}, not {want!r}")
    elif isinstance(m, gffm.AddStructToListGFF):
        lits = {c.label: gff_literal(c.value) for c in m.modifiers if isinstance(c, gffm.AddFieldGFF)}
        lits = {k: v for k, v in lits.items() if v is not None}
        if not lits:
            return
        parts = PureWindowsPath(m.path).parts
        if parts and parts[-1].startswith(">>"):               # >>##INDEXINLIST##<<: the new entry's own slot
            parts = parts[:-1]
        if any(x.startswith(">>") for x in parts):             # inside a struct this mod added: checked there
            return
        try:
            lst = gff_walk(root, BS.join(parts))
        except (KeyError, IndexError, ValueError):
            add("GFF", f"{where} {m.path} +struct", FAIL, "list not found")
            return
        found = any(all(s.exists(k) and same(s.value(k), v) for k, v in lits.items()) for s in lst)
        shown = ", ".join(f"{k}={v}" for k, v in list(lits.items())[:3])
        add("GFF", f"{where} {m.path} +struct ({shown})", OK if found else FAIL, "" if found else "no such struct in the list")
    elif isinstance(m, gffm.AddFieldGFF):
        want = gff_literal(m.value)
        if want is None or "listindex" in str(m.path).lower() or any(p.startswith(">>") for p in PureWindowsPath(m.path).parts):
            return
        try:
            parent = gff_walk(root, m.path) if str(m.path) not in ("", ".") else root
            got = parent.value(m.label) if parent.exists(m.label) else None
        except (KeyError, IndexError, ValueError, AttributeError):
            return                                   # inside a struct this mod added: covered above
        ok = got is not None and same(got, want)
        add("GFF", f"{where} {m.path}\\{m.label}", OK if ok else FAIL, "" if ok else f"{got!r}, not {want!r}")


# --- the report -----------------------------------------------------------------------------------
INDEX = {}


def report_tag(game_root):
    return "dev" if Path(game_root).resolve() == GAME.resolve() else Path(game_root).name


def report_path(game_root, ext):
    """The latest report for that game: reports/install-audit/latest-<dev|folder name><ext>."""
    return OUT / f"latest-{report_tag(game_root)}{ext}"


def main(argv):
    only = [argv[i + 1] for i, a in enumerate(argv) if a == "--mod"]
    game_root = Path(argv[argv.index("--game") + 1]) if "--game" in argv else GAME
    mods = load_mods(only)
    known = tomllib.loads((HERE / "known.toml").read_text(encoding="utf-8")).get("accept", []) \
        if (HERE / "known.toml").exists() else []
    for m in mods:                                   # whose copy is it: every audited mod's install files
        for f in m["cfg"].install_list:
            src = source_of(m, f)
            if src.exists():
                INDEX[(dest_of(f), f.saveas.lower(), hashlib.sha1(src.read_bytes()).hexdigest())] = m["name"]
    game = Game(game_root)
    results = {}
    for m in mods:
        if m["checked"]:
            print(f"checking {m['name']} ...", flush=True)
            results[m["name"]] = check_mod(m, mods, game, known)

    stamp = datetime.date.today().isoformat()
    OUT.mkdir(parents=True, exist_ok=True)
    md = io.StringIO()
    md.write(f"# Install audit - {stamp}\n\nGame: `{game_root}`. Mods in install order (mods.toml).\n\n")
    md.write("| mod | ok | superseded | accepted | CLOBBERED | FAIL | not checked |\n|---|---|---|---|---|---|---|\n")
    for name, res in results.items():
        c = defaultdict(int)
        for r in res:
            c[r[2]] += 1
        md.write(f"| {name} | {c[OK]} | {c[SUPERSEDED]} | {c[ACCEPTED]} | {c[CLOBBERED]} | {c[FAIL]} | {c[SKIP]} |\n")
        print(f"  {name}: {c[OK]} ok, {c[SUPERSEDED]} superseded, {c[ACCEPTED]} accepted, {c[CLOBBERED]} CLOBBERED, {c[FAIL]} FAIL, {c[SKIP]} not checked")
    for name, res in results.items():
        bad = [r for r in res if r[2] in (FAIL, CLOBBERED, SUPERSEDED, ACCEPTED, SKIP)]
        md.write(f"\n## {name}\n\n")
        if not bad:
            md.write("Everything in place.\n")
            continue
        for status in (FAIL, CLOBBERED, SUPERSEDED, ACCEPTED, SKIP):
            rows = [r for r in bad if r[2] == status]
            if rows:
                md.write(f"\n**{status}** ({len(rows)})\n\n")
                for area, item, _s, detail in rows[:400]:
                    md.write(f"- {area}: `{item}`" + (f" - {detail}" if detail else "") + "\n")
                if len(rows) > 400:
                    md.write(f"- ... and {len(rows) - 400} more (see the .json)\n")
    tag = report_tag(game_root)
    name = stamp if tag == "dev" else f"{stamp}-{tag}"
    data = json.dumps({n: [dict(zip(("area", "item", "status", "detail"), r)) for r in res]
                       for n, res in results.items()}, indent=1)
    (OUT / f"{name}.md").write_text(md.getvalue(), encoding="utf-8")
    (OUT / f"{name}.json").write_text(data, encoding="utf-8")
    report_path(game_root, ".md").write_text(md.getvalue(), encoding="utf-8")
    report_path(game_root, ".json").write_text(data, encoding="utf-8")
    print(f"report: {OUT / f'{name}.md'}")
    return 1 if any(r[2] in (FAIL, CLOBBERED) for res in results.values() for r in res) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
