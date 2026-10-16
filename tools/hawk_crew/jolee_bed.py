"""Jolee lying back on the Ebon Hawk's medical bed (user, 2026-10-07: "Jolee should be laying back in
bed"), for hcw_work (Ebon Hawk Crew at Work - tools/hawk_crew).

The bed is not walkable, so no creature can stand on it. Instead he stands at its foot, facing away,
and lies back onto it: the game's own "prone" (on the back, face up, the head behind where the
creature stands - S_Male02), raised to the mattress and carried back along the bed. That is a
new animation, so it goes into his body models under a name of its own, "hcw_bedlie", with a row in
animations.2da; scripts play it through the Animation Rows patch for Kotor Patch Manager
(tools/kpm_patches/AnimationRows: ActionPlayAnimation(20000 + row)). Until 2026-10-08 it was
"dance" (ANIMATION_LOOPING_DANCE) - but the shared male bodies are the player's too, and the Star
Forge easter egg (k_psta_egg) dances the player: he lay down in mid-air instead. A name nothing
else plays changes nothing vanilla.

His body models: P_JoleeBB in his own clothes (P_JoleeBA, underclothes, inherits from it) and the
shared male medium bodies when he wears armour or a robe (PMBCM..PMBJM; his starting Jedi robe is
PMBIM). The player and the other male companions share those; only hcw_work plays "hcw_bedlie",
and only on Jolee.

And a datapad in his hand (user: "Can we give him a tablet to hang out with?", then "For fun, make a
datapad equipable for Jolee and equip it to that hand"): Jolee's Datapad, hcw_jolee_pad - a stun
baton by base item (one-handed, blunt, 1 damage) that only a Jedi Consular can equip, its model the
game's own PLC_DataPad stood upright in the fist (w_stunbaton_050: the weapon models' grip is the
origin, the handle up +z). hcw_work puts it in his right hand while he lies there with the
player nearby and gives him his own weapon back before he could leave the ship.

Writes (backed up first): Override P_JoleeBB, PMBCM..PMBJM, w_stunbaton_050 (.mdl/.mdx),
hcw_jolee_pad.uti (install.py adds the animations.2da row).
With --overlay <dir>: into that folder's Override only (the test harness's mirror overlay).

usage: jolee_bed.py <backup dir> | --overlay <dir> [--dy D] [--dz D]
"""
import shutil
import struct
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(Path(r"D:\KOTOR Companion Mod + Questline\tools") / "ghorfk_scene"))   # the dev tools' paths and compiler only

from pykotor.extract.installation import Installation, SearchLocation   # noqa: E402
from pykotor.resource.type import ResourceType                           # noqa: E402

from kmdlswap._io import MDL_BASE                                        # noqa: E402
from kmdlswap.layout import parse                                        # noqa: E402
from kmdlswap.transplant import add_animation                            # noqa: E402
from install_commentary import GAME, OVERRIDE, refuse_if_running         # noqa: E402

SLOT = "hcw_bedlie"                  # its own name: an animations.2da row (animations_table)
LEGACY_SLOT = "dance"                # the name it had until 2026-10-08: a model carrying it is rebuilt
ROW_LIKE = "dance"                   # the vanilla row whose flags the new row copies: stationary, looping
TARGETS = ["P_JoleeBB"] + [f"PMB{c}M" for c in "CDEFGHIJ"]
# the bed (ebo_m12aa room 01g, medbay_bed01): x 43.5-44.6, y 36.8-39.3, head to the north, mattress
# ~0.6 m above the floor; the pillow its last 0.3 m (y 38.98-39.28), a block up to 0.86 m (room
# 01g medbay_bed01). He stands at its foot, (44.03, 36.0) facing south (hcw_work); "prone"
# puts his pelvis 0.65 m behind him and 0.09 m off the floor - these carry it to the bed's middle and
# onto the mattress
DY = -1.85                           # further back (north, along the bed): head on the pillow (2026-10-16)
DZ = 0.66                            # up onto the mattress, the head onto the pillow block (2026-10-16)
# the bed's foot is a leg rest sloping down ~18 degrees (0.58 m to 0.31 m over its last 0.8 m - user,
# 2026-10-07: "there's definitely a slope at the end"); "prone"'s legs ran out level over it, the
# feet in the air. Each leg bone's keys turned about its parent's x axis (degrees; negative = down
# towards the foot of the bed): the right leg's thigh stays on the mattress and its shin follows the
# slope (2 -> 28 degrees down); the left knee drops from 27 to 12 degrees up and its shin reaches the
# leg rest (45 degrees down), turned 8 degrees in so the left foot stays on the bed rather than over its
# edge. The torso keeps "prone"'s half-recline (user: "half inclined would work").
LEG_PITCH = {"lthigh_g": -15.2, "lshin_g": -10.3, "rshin_g": -25.7}
LEG_IN = {"lthigh_g": -8.0}           # about the parent's y axis: towards the body's middle

# Sitting first (user, 2026-10-15: "he needs a sitting animation before laying so it doesn't look so
# jarring"): S_Male02's own "sitdown" (1.03 s, script-unreachable in vanilla) as "hcw_bedsit", its own
# animations.2da row (sitdown's flags). The pelvis ends 0.46 m behind his spot and 0.42 m down, chair
# height - in the air before the bed. SIT_BACK carries it further back as he sits, growing with the
# keys from nothing at the first (so no jump from standing) to the full amount at the last: onto the
# leg rest at y ~37.2, about 0.45 m up there. Then, in the same animation, he leans back and slides up
# the bed into the lying pose over LIE_BLEND seconds (lean_back), and "hcw_bedlie" carries on from
# there. (A longer transition time on the lying pose did nothing: the engine blended in a quarter
# second - harness joleesit, 2026-10-15.)
SIT_SLOT = "hcw_bedsit"
SIT_ROW_LIKE = "sitdown"             # the vanilla row whose flags it copies: stationary, played once
SIT_BACK = -0.74                     # metres, along the bed (north)
LIE_BLEND = 1.4                      # seconds
SIT_END = 1.03333                    # "sitdown"'s own length, seconds: its last keys


def _turn(q, degrees, axis):
    """(x, y, z, w) turned about the parent's x or y axis: r * q."""
    import math
    h = math.radians(degrees) / 2
    s, c = math.sin(h), math.cos(h)
    ax, ay = (s, 0.0) if axis == "x" else (0.0, s)
    x, y, z, w = q
    return (c * x + ax * w + ay * z, c * y + ay * w - ax * z, c * z + ax * y - ay * x, c * w - ax * x - ay * y)


def _keys(mdl, node, ctype_want, cols_want, label):
    """(time offset, data offset, rows) of one controller of an animation node, by its type."""
    pos = MDL_BASE + node.offset
    co, cn = struct.unpack_from("<2I", mdl, pos + 56)
    do = struct.unpack_from("<I", mdl, pos + 68)[0]
    for i in range(cn):
        ctype, _, rows, toff, doff, cols = struct.unpack_from("<IHHHHB", mdl, MDL_BASE + co + 16 * i)
        if ctype != ctype_want:
            continue
        if cols != cols_want:
            raise SystemExit(f"S_Male02 {label} has {cols} columns, expected {cols_want}")
        return MDL_BASE + do + 4 * toff, MDL_BASE + do + 4 * doff, rows
    raise SystemExit(f"S_Male02 {label}: no such keys")


def _width(ctype, cols):
    """32-bit words per key of a controller: a compressed orientation is one, bezier keys carry two
    tangents after the value."""
    if ctype == 20 and cols == 2:
        return 1
    return (cols & 15) * (3 if cols & 16 else 1)


def _unpack_quat(v):
    import math
    x = (v & 0x7FF) / 1023 - 1
    y = ((v >> 11) & 0x7FF) / 1023 - 1
    z = (v >> 22) / 511 - 1
    return (x, y, z, math.sqrt(max(0.0, 1 - x * x - y * y - z * z)))


def _first_values(mdl, mdx, anim):
    """{bone: {controller type: its first key}} of an animation - an orientation as (x, y, z, w)."""
    out = {}
    for n in parse(mdl, mdx).nodes:
        if n.in_animation != anim:
            continue
        pos = MDL_BASE + n.offset
        co, cn = struct.unpack_from("<2I", mdl, pos + 56)
        do = struct.unpack_from("<I", mdl, pos + 68)[0]
        for i in range(cn):
            ctype, _, rows, _toff, doff, cols = struct.unpack_from("<IHHHHB", mdl, MDL_BASE + co + 16 * i)
            at = MDL_BASE + do + 4 * doff
            if ctype == 20:
                q = _unpack_quat(struct.unpack_from("<I", mdl, at)[0]) if cols == 2 else struct.unpack_from("<4f", mdl, at)
                out.setdefault(n.name.lower(), {})[20] = q
            elif ctype == 8:
                out.setdefault(n.name.lower(), {})[8] = struct.unpack_from("<3f", mdl, at)
    return out


def lean_back(source, sit_end, lean=LIE_BLEND):
    """The keys hook for add_animation: each of the sit's position and orientation keys gains one more,
    `lean` seconds after its end, at the lying pose's first - so the sit ends as he lies and the lying
    pose follows without a jump (the engine's own blend between them is a quarter second whatever the
    animation asks: harness joleesit, 2026-10-15). Other controllers hold their last key."""
    target = _first_values(*source, "prone")
    t_end = sit_end + lean

    def keys(name, ctrls, data):
        words = struct.unpack(f"<{len(data) // 4}I", data)
        new_ctrls, new_data = bytearray(), []
        for i in range(len(ctrls) // 16):
            rec = bytearray(ctrls[16 * i:16 * i + 16])
            ctype, _, rows, toff, doff, cols = struct.unpack_from("<IHHHHB", rec)
            w = _width(ctype, cols)
            times = list(words[toff:toff + rows])
            values = [list(words[doff + w * r:doff + w * (r + 1)]) for r in range(rows)]
            last = list(values[-1])
            want = target.get(name.lower(), {}).get(ctype)
            if want is not None and ctype == 20:
                last = [_pack_quat(want)] if w == 1 else list(struct.unpack("<4I", struct.pack("<4f", *want)))
            elif want is not None and ctype == 8:
                last = list(struct.unpack("<3I", struct.pack("<3f", *want))) + [0] * (w - 3)
            times.append(struct.unpack("<I", struct.pack("<f", t_end))[0])
            values.append(last)
            struct.pack_into("<HHH", rec, 6, rows + 1, len(new_data), len(new_data) + rows + 1)
            new_data += times
            for v in values:
                new_data += v
            new_ctrls += rec
        return bytes(new_ctrls), struct.pack(f"<{len(new_data)}I", *new_data)
    return keys


def lying_source(dy, dz, sit_back=SIT_BACK, blend=LIE_BLEND):
    """S_Male02 (the game's own) with its "prone" root carried dy back and dz up, and its "sitdown"
    root carried back by up to sit_back as he sits and `blend` seconds longer (lean_back fills them)."""
    inst = Installation(str(GAME))
    mdl = bytearray(inst.resource("S_Male02", ResourceType.MDL, [SearchLocation.CHITIN]).data)
    mdx = inst.resource("S_Male02", ResourceType.MDX, [SearchLocation.CHITIN]).data
    L = parse(bytes(mdl), mdx)
    for bone, axis, degrees in [(b, "x", d) for b, d in LEG_PITCH.items()] + [(b, "y", d) for b, d in LEG_IN.items()]:
        leg = next(n for n in L.nodes if n.in_animation == "prone" and n.name.lower() == bone)
        lpos = MDL_BASE + leg.offset
        co, cn = struct.unpack_from("<2I", mdl, lpos + 56)
        do = struct.unpack_from("<I", mdl, lpos + 68)[0]
        for i in range(cn):
            ctype, _, rows, _toff, doff, cols = struct.unpack_from("<IHHHHB", mdl, MDL_BASE + co + 16 * i)
            if ctype != 20:                              # orientation
                continue
            if cols != 4:
                raise SystemExit(f"S_Male02 prone {bone} orientation has {cols} columns, expected 4")
            for r in range(rows):
                at = MDL_BASE + do + 4 * (doff + 4 * r)
                struct.pack_into("<4f", mdl, at, *_turn(struct.unpack_from("<4f", mdl, at), degrees, axis))
    sit = next(n for n in L.nodes if n.in_animation == "sitdown" and n.name.lower() == "rootdummy")
    times, data, rows = _keys(mdl, sit, 8, 3, "sitdown rootdummy position")
    end = struct.unpack_from("<f", mdl, times + 4 * (rows - 1))[0]
    for r in range(rows):
        t = struct.unpack_from("<f", mdl, times + 4 * r)[0]
        x, y, z = struct.unpack_from("<3f", mdl, data + 12 * r)
        struct.pack_into("<3f", mdl, data + 12 * r, x, y + sit_back * t / end, z)
    header = next(sp.start for sp in L.spans if sp.kind == "anim_header"
                  and mdl[sp.start + 8:sp.start + 40].split(b"\0")[0] == b"sitdown")
    struct.pack_into("<f", mdl, header + 80, end + blend)  # the length: the lean back after (lean_back)
    node = next(n for n in L.nodes if n.in_animation == "prone" and n.name.lower() == "rootdummy")
    pos = MDL_BASE + node.offset
    co, cn = struct.unpack_from("<2I", mdl, pos + 56)
    do = struct.unpack_from("<I", mdl, pos + 68)[0]
    for i in range(cn):
        ctype, _, rows, _toff, doff, cols = struct.unpack_from("<IHHHHB", mdl, MDL_BASE + co + 16 * i)
        if ctype != 8:                                   # position
            continue
        if cols != 3:
            raise SystemExit(f"S_Male02 prone rootdummy position has {cols} columns, expected 3")
        for r in range(rows):
            at = MDL_BASE + do + 4 * (doff + 3 * r)
            x, y, z = struct.unpack_from("<3f", mdl, at)
            struct.pack_into("<3f", mdl, at, x, y + dy, z + dz)
        return bytes(mdl), mdx
    raise SystemExit("S_Male02 prone has no rootdummy position keys")


PAD_ITEM = "hcw_jolee_pad"           # the item's template and tag (it was rfk_jdpad_i inside GH0-RFK's package)
PAD_VARIATION = 50                   # its model: baseitems.2da Stun_Baton's itemclass w_Stunbaton + _050
PAD_MODEL = f"w_stunbaton_{PAD_VARIATION:03d}"
PAD_SOURCE = "PLC_DataPad"           # placeables.2da 125, "DataPad": a 0.29 x 0.25 m pad lying flat
PAD_BASE_ITEM = 1                    # Stun_Baton: one-handed, blunt
PAD_TURN = (90.0, 45.0)              # degrees about x (stood up), then about z: the screen to his face
PAD_LIFT = 0.13                      # metres up the handle axis: its lower edge in the fist
CLASS_JEDI_CONSULAR = 4              # classes.2da


def _quat(x_deg, z_deg):
    """About x, then about z (parent frame): (x, y, z, w)."""
    import math
    hx, hz = math.radians(x_deg) / 2, math.radians(z_deg) / 2
    qx = (math.sin(hx), 0.0, 0.0, math.cos(hx))
    qz = (0.0, 0.0, math.sin(hz), math.cos(hz))
    ax, ay, az, aw = qz
    bx, by, bz, bw = qx
    return (aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz)


def _pack_quat(q):
    """KotOR's compressed orientation key (11-11-10 bits of x, y, z; w implied)."""
    x, y, z, w = q
    if w < 0:
        x, y, z = -x, -y, -z
    return (round((x + 1) * 1023) & 0x7FF) | ((round((y + 1) * 1023) & 0x7FF) << 11) | ((round((z + 1) * 511) & 0x3FF) << 22)


def pad_model(turn=PAD_TURN, lift=PAD_LIFT):
    """PLC_DataPad as the weapon model w_stunbaton_050: the pad stood up on its edge in the hand
    (pose and its "default" loop alike, should anything play it)."""
    from kmdlswap.rename import rename
    inst = Installation(str(GAME))
    mdl = inst.resource(PAD_SOURCE, ResourceType.MDL, [SearchLocation.CHITIN]).data
    mdx = inst.resource(PAD_SOURCE, ResourceType.MDX, [SearchLocation.CHITIN]).data
    mdl, mdx = rename(mdl, mdx, PAD_MODEL)
    mdl = bytearray(mdl)
    q = _quat(*turn)
    done = 0
    for n in parse(bytes(mdl), mdx).nodes:
        if n.name.lower() != "datapad2":
            continue
        pos = MDL_BASE + n.offset
        co, cn = struct.unpack_from("<2I", mdl, pos + 56)
        do = struct.unpack_from("<I", mdl, pos + 68)[0]
        for i in range(cn):
            ctype, _, rows, _toff, doff, cols = struct.unpack_from("<IHHHHB", mdl, MDL_BASE + co + 16 * i)
            for r in range(rows):
                if ctype == 20 and cols == 4:                    # the resting orientation
                    struct.pack_into("<4f", mdl, MDL_BASE + do + 4 * (doff + 4 * r), *q)
                elif ctype == 20 and cols == 2:                  # "default"'s keys, compressed
                    struct.pack_into("<I", mdl, MDL_BASE + do + 4 * (doff + r), _pack_quat(q))
                elif ctype == 8:                                 # position (bezier keys: value then tangents)
                    width = 9 if cols & 16 else 3
                    at = MDL_BASE + do + 4 * (doff + width * r)
                    struct.pack_into("<3f", mdl, at, 0.0, 0.0, lift)
                    if width == 9:
                        struct.pack_into("<6f", mdl, at + 12, *([0.0] * 6))
                else:
                    continue
                done += 1
    if done < 4:
        raise SystemExit(f"{PAD_SOURCE}: set {done} pose key(s), expected the pose's and the loop's")
    return bytes(mdl), mdx


def pad_uti():
    """Jolee's Datapad: g_w_stunbaton01 renamed, re-modelled and re-described, Jedi Consulars only."""
    from pykotor.common.language import LocalizedString
    from pykotor.common.misc import ResRef
    from pykotor.resource.formats.gff import GFFList, bytes_gff, read_gff
    gff = read_gff(Installation(str(GAME)).resource("g_w_stunbaton01", ResourceType.UTI).data)
    r = gff.root
    r.set_string("Tag", PAD_ITEM)
    r.set_resref("TemplateResRef", ResRef(PAD_ITEM))
    r.set_int32("BaseItem", PAD_BASE_ITEM)
    r.set_uint8("ModelVariation", PAD_VARIATION)
    r.set_locstring("LocalizedName", LocalizedString.from_english("Jolee's Datapad"))
    desc = ("Forty years of notes on the Shadowlands of Kashyyyk, most of them complaints. Jolee swears "
            "the rest are wisdom. It is weighted about like a club, and he will tell you it has settled "
            "more arguments than his lightsaber.")
    r.set_locstring("Description", LocalizedString.from_english(desc))
    r.set_locstring("DescIdentified", LocalizedString.from_english(desc))
    r.set_uint32("Cost", 1)
    r.set_uint8("Plot", 0)
    r.set_uint8("Identified", 1)
    props = GFFList()
    p = props.add(0)
    p.set_uint16("PropertyName", 44)                     # itempropdef: UseLimitationClass
    p.set_uint16("Subtype", CLASS_JEDI_CONSULAR)
    p.set_uint8("CostTable", 0)
    p.set_uint16("CostValue", 0)
    p.set_uint8("Param1", 255)
    p.set_uint8("Param1Value", 0)
    p.set_uint8("ChanceAppear", 100)
    r.set_list("PropertiesList", props)
    return bytes_gff(gff)

ROWS = [(SLOT, ROW_LIKE), (SIT_SLOT, SIT_ROW_LIKE)]     # the animations.2da rows: name, vanilla row it copies


def animations_table(current: bytes | None) -> tuple[bytes, dict]:
    """(animations.2da with the ROWS, {name: row number}): each row added once - the flags of its vanilla
    row - or the one already there. current: the install's table, or None for the game's own."""
    from pykotor.resource.formats.twoda import bytes_2da, read_2da
    if current is None:
        current = Installation(str(GAME)).resource("animations", ResourceType.TwoDA, [SearchLocation.CHITIN]).data
    t = read_2da(current)
    names = [t.get_row(i).get_string("name").lower() for i in range(t.get_height())]
    rows, added = {}, False
    for name, like_name in ROWS:
        if name in names:
            rows[name] = names.index(name)
            continue
        like = t.get_row(names.index(like_name))
        t.add_row(str(t.get_height()), {**{h: like.get_string(h) for h in t.get_headers()}, "name": name})
        names.append(name)
        rows[name], added = t.get_height() - 1, True
        if rows[name] >= 1000:
            raise SystemExit(f"animations.2da row {rows[name]}: the Animation Rows patch reaches rows below 1000")
    return (bytes(bytes_2da(t)) if added else current), rows


def build(dy=DY, dz=DZ, slot=SLOT):
    """{model: (mdl, mdx, bones left out)}: each body with the bed pose as the animation `slot` - SLOT, a
    name of its own (an animations.2da row, played through the Animation Rows patch as 20000 + row),
    which leaves every vanilla animation alone. A body that carries this pose already (or the old
    "dance" one) is rebuilt from the game's own archives."""
    inst = Installation(str(GAME))
    source = lying_source(dy, dz)
    out = {}
    for name in TARGETS:
        mdl = inst.resource(name, ResourceType.MDL).data          # as the game finds it (Override first)
        mdx = inst.resource(name, ResourceType.MDX).data
        if {LEGACY_SLOT, SLOT, SIT_SLOT, slot} & set(parse(mdl, mdx).animation_names):
            # an earlier install of this one: rebuilt from the game's own (none of these bodies was in
            # the dev copy's Override before it, 2026-10-07)
            mdl = inst.resource(name, ResourceType.MDL, [SearchLocation.CHITIN]).data
            mdx = inst.resource(name, ResourceType.MDX, [SearchLocation.CHITIN]).data
            if {slot, SIT_SLOT} & set(parse(mdl, mdx).animation_names):
                raise SystemExit(f"{name} already has {slot!r} or {SIT_SLOT!r} in the game's own archives")
        new_mdl, new_mdx, dropped = add_animation((mdl, mdx), source, "prone", slot)
        new_mdl, new_mdx, dropped_sit = add_animation((new_mdl, new_mdx), source, "sitdown", SIT_SLOT,
                                                      keys=lean_back(source, SIT_END))
        out[name] = (new_mdl, new_mdx, sorted(set(dropped) | set(dropped_sit)))
    return out


def main(argv):
    dy, dz = DY, DZ
    if "--dy" in argv:
        dy = float(argv[argv.index("--dy") + 1])
        del argv[argv.index("--dy"):argv.index("--dy") + 2]
    if "--dz" in argv:
        dz = float(argv[argv.index("--dz") + 1])
        del argv[argv.index("--dz"):argv.index("--dz") + 2]
    if len(argv) == 2 and argv[0] == "--overlay":
        dest, backup = Path(argv[1]) / "Override", None
    elif len(argv) == 1:
        refuse_if_running()
        dest, backup = OVERRIDE, Path(argv[0])
        backup.mkdir(parents=True, exist_ok=True)
    else:
        raise SystemExit(__doc__)
    dest.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for name, (mdl, mdx, dropped) in build(dy, dz).items():
        for ext, data in (("mdl", mdl), ("mdx", mdx)):
            target = dest / f"{name.lower()}.{ext}"
            if backup is not None and target.exists():
                shutil.copy2(target, backup / f"{target.name}.before-jolee-bed-{stamp}")
            target.write_bytes(data)
        print(f"{name}: '{SLOT}' = prone on the bed (dy {dy}, dz {dz}), '{SIT_SLOT}' = sitting onto its foot"
              + (f"; left out (not in this body): {', '.join(dropped)}" if dropped else ""))

    # Jolee's Datapad: its model and its template
    pad_mdl, pad_mdx = pad_model()
    for fname, data in ((f"{PAD_MODEL}.mdl", pad_mdl), (f"{PAD_MODEL}.mdx", pad_mdx), (f"{PAD_ITEM}.uti", pad_uti())):
        target = dest / fname
        if target.exists() and target.read_bytes() == data:
            continue
        if backup is not None and target.exists():
            shutil.copy2(target, backup / f"{target.name}.before-jolee-bed-{stamp}")
        target.write_bytes(data)
    print(f"{PAD_ITEM}.uti (Jolee's Datapad, Jedi Consulars only), its model {PAD_MODEL}")
    print(f"-> {dest}")


if __name__ == "__main__":
    main(sys.argv[1:])
