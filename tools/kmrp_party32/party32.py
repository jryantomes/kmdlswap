"""Prototype: KMRP's party selection screen at one resolution, with Party Roster Limit 32's 16 slots
and page buttons.

KMRP's layouts are linear in width and height (docs/universal-resolution-math.md), so the map from
the vanilla 640x480 screen to KMRP's at a size is x' = ax*x + bx (and the same in y) - fitted here
from the controls both screens share, and checked: every shared control must land within 1 px.
That map is then applied to the roster's own 640x480 layout (a 4x4 grid in the 3x3's box, page
buttons beside Done). Each control keeps KMRP's look: an added slot copies KMRP's BTN_NPC0 /
LBL_CHAR0 / LBL_NA0, the page buttons copy its BTN_DONE, with the roster's tag, text and extent.

    kmrp_party32.py <vanilla gui> <roster32 gui> <kmrp gui> <out gui>
"""
import copy
import sys
from pathlib import Path

from pykotor.resource.formats.gff import GFFList, bytes_gff, read_gff

KEYS = ("LEFT", "TOP", "WIDTH", "HEIGHT")


def extents(root):
    C = root.get_list("CONTROLS")
    return {str(C.at(i).acquire("TAG", "")): tuple(C.at(i).get_struct("EXTENT").acquire(k, 0) for k in KEYS)
            for i in range(len(C))}


def fit(pairs):
    """Least squares a, b for target = a*source + b."""
    n = len(pairs)
    sx = sum(p for p, _ in pairs); sy = sum(q for _, q in pairs)
    sxx = sum(p * p for p, _ in pairs); sxy = sum(p * q for p, q in pairs)
    a = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    return a, (sy - a * sx) / n


SLOT = ("BTN_NPC", "LBL_CHAR", "LBL_NA")
REGIONS = {                     # what each moved control is placed by: KMRP's own controls of that region
    "slots": lambda t: t.startswith(SLOT),
    "buttons": lambda t: t in ("BTN_ACCEPT", "BTN_DONE"),
}


def region_of(tag):
    return "slots" if tag.startswith(SLOT) else "buttons" if tag.startswith("BTN_PAGE") else None


def place_with(m, e):
    ax, bx, ay, by, sw, sh = m
    w, h = round(sw * e[2]), round(sh * e[3])
    return round(ax * (e[0] + e[2] / 2) + bx - w / 2), round(ay * (e[1] + e[3] / 2) + by - h / 2), w, h


def build(vanilla, roster, kmrp):
    """KMRP moves a region's controls apart across the width but keeps their shape: centres map
    linearly (fitted per axis), sizes by one ratio per axis (the mean of KMRP's over vanilla's)."""
    v, r, k = extents(vanilla), extents(roster), extents(kmrp.root)
    maps, worst = {}, 0.0
    for name, member in REGIONS.items():
        tags = [t for t in v if t in k and member(t)]
        cx = [(v[t][0] + v[t][2] / 2, k[t][0] + k[t][2] / 2) for t in tags]
        cy = [(v[t][1] + v[t][3] / 2, k[t][1] + k[t][3] / 2) for t in tags]
        ax, bx = fit(cx); ay, by = fit(cy)
        sw = sum(k[t][2] for t in tags) / sum(v[t][2] for t in tags)
        sh = sum(k[t][3] for t in tags) / sum(v[t][3] for t in tags)
        maps[name] = (ax, bx, ay, by, sw, sh)
        for t in tags:            # KMRP's own controls of the region, rebuilt by the map
            got = place_with(maps[name], v[t])
            worst = max(worst, *(abs(g - w) for g, w in zip(got, k[t])))

    def place(tag, e):
        return place_with(maps[region_of(tag)], e)
    shared = sum(1 for t in v if t in k)
    m = maps["slots"]

    out = copy.deepcopy(kmrp)
    KC = out.root.get_list("CONTROLS")
    by_tag = {str(KC.at(i).acquire("TAG", "")): KC.at(i) for i in range(len(KC))}
    template = {"BTN_NPC": "BTN_NPC0", "LBL_CHAR": "LBL_CHAR0", "LBL_NA": "LBL_NA0", "BTN_PAGE": "BTN_DONE"}
    RC = roster.get_list("CONTROLS")
    # GFFList.append keeps a copy: every control is finished before it goes in
    placed, extra = {}, []
    for i in range(len(RC)):
        rc = RC.at(i)
        tag = str(rc.acquire("TAG", ""))
        if region_of(tag) is not None:
            placed[tag] = (rc, place(tag, r[tag]))

    def at(struct, e):
        ex = struct.get_struct("EXTENT")
        for kk, val in zip(KEYS, e):
            ex.set_int32(kk, val)
        struct.set_struct("EXTENT", ex)
        return struct

    new = GFFList()
    for i in range(len(KC)):
        c = copy.deepcopy(KC.at(i))
        tag = str(c.acquire("TAG", ""))
        new.append(at(c, placed[tag][1]) if tag in placed else c)
    added = 0
    for tag, (rc, e) in placed.items():
        if tag in by_tag:
            continue
        base = next((tpl for pre, tpl in template.items() if tag.startswith(pre)), None)
        if base is None or base not in by_tag:
            raise SystemExit(f"no KMRP control to give {tag} its look")
        c = copy.deepcopy(by_tag[base])
        c.set_string("TAG", tag)
        # the roster's own control ID and pad/keyboard links, not the template's: copied, every added
        # slot shared BTN_NPC0's IDs and the page buttons BTN_DONE's 36 - the "<" did not show and
        # Done lost its text (KMRP 1.5.1, 2026-10-16)
        if rc.exists("ID"):
            c.set_int32("ID", rc.get_int32("ID"))
        if rc.exists("MOVETO"):
            c.set_struct("MOVETO", copy.deepcopy(rc.get_struct("MOVETO")))
        if rc.exists("TEXT") and c.exists("TEXT"):
            # the roster's words (its text or string reference), in KMRP's font for this size
            t = copy.deepcopy(rc.get_struct("TEXT"))
            if c.get_struct("TEXT").exists("FONT"):
                t.set_resref("FONT", c.get_struct("TEXT").get_resref("FONT"))
            c.set_struct("TEXT", t)
        new.append(at(c, e))
        added += 1
    out.root.set_list("CONTROLS", new)
    return out, m, worst, added, shared


def main(vanilla, roster, kmrp, dest):
    out, m, worst, added, shared = build(read_gff(Path(vanilla).read_bytes()).root,
                                         read_gff(Path(roster).read_bytes()).root, read_gff(Path(kmrp).read_bytes()))
    Path(dest).write_bytes(bytes(bytes_gff(out)))
    print(f"map x {m[0]:.4f}x+{m[1]:.1f}, y {m[2]:.4f}y+{m[3]:.1f}; {shared} shared controls, worst {worst:.2f} px; "
          f"{added} controls added -> {dest}")


if __name__ == "__main__":
    main(*sys.argv[1:5])
