"""CLI for kmdlfun. The GUI drives exactly this logic.

    kmdlfun effects
    kmdlfun companions
    kmdlfun preview --install <K1> --companion hk47 --effect bighead
    kmdlfun build --install <K1> --effect bighead --companion all --out out/
"""

from __future__ import annotations

import argparse
import sys

from . import apply as kapply
from . import effects as keffects
from . import parts as kparts
from . import roster


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="kmdlfun")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("effects", help="list available effects")
    sub.add_parser("companions", help="list companions and their models")

    prev = sub.add_parser("preview", help="show what would change, without writing")
    prev.add_argument("--install", required=True)
    prev.add_argument("--companion", nargs="*", default=["all"])
    prev.add_argument("--effect", required=True)
    prev.add_argument("--intensity", type=float, default=1.0)

    b = sub.add_parser("build", help="write modified models to a directory")
    b.add_argument("--install", required=True)
    b.add_argument("--companion", nargs="*", default=["all"])
    b.add_argument("--effect", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--intensity", type=float, default=1.0)
    b.add_argument(
        "--pivot", choices=list(kapply.PIVOTS), default="joint",
        help="where each node grows from: joint (default, keeps a multi-node "
             "part registered), node (its own origin), bounds (its own bbox centre)",
    )

    tp = sub.add_parser("transplant", help="move one model's geometry into another")
    tp.add_argument("--install", required=True)
    tp.add_argument("--host", required=True, help="model that keeps its hierarchy and animations")
    tp.add_argument("--donor", required=True, help="model to take geometry from")
    tp.add_argument("--donor-install",
                    help="a second game to take the donor from - a KOTOR 2 head "
                         "into a KOTOR 1 host, say. Only the donor's geometry "
                         "crosses over; the host is written in its own format")
    tp.add_argument("--node", nargs="*", help="host node(s); default every matching node")
    tp.add_argument("--no-auto-merge", action="store_true",
                    help="do not fold in donor parts the host has no node for. "
                         "By default they are folded in when their bone exists "
                         "on the host, which is what carries a Quarren's mouth "
                         "tentacles without anyone having to name them")
    tp.add_argument("--merge", action="append", default=[], metavar="NODE",
                    help="fold this donor node into the mesh being replaced, "
                         "bound to the bone it hung from. For parts a host has "
                         "no equivalent of: a Quarren's mouth tentacles hang "
                         "from its lip bones, and no node of Carth's does")
    tp.add_argument("--pair", action="append", default=[], metavar="HOST=DONOR",
                    help="put a named donor node into a named host node, even "
                         "when the names differ. A host cannot gain nodes, but "
                         "it usually has spare ones - Carth's hair and eyelids "
                         "can carry a Quarren's mouth tentacles. Repeatable; the "
                         "first pair anchors the alignment for the rest")
    tp.add_argument("--out", required=True, help="where builds are kept")
    tp.add_argument("--name", help="name this build; defaults to host-donor")
    tp.add_argument("--as-character", metavar="RESREF",
                    help="also write a creature blueprint so the model is "
                         "somebody the game can place, not just a file")
    tp.add_argument("--kind", choices=["npc", "talker", "companion"], default="npc",
                    help="how much a character needs: an npc is a blueprint and "
                         "nothing else, a talker is wired for conversation, a "
                         "companion adds a portrait, henchman scripts and "
                         "NoPermDeath (default: npc)")
    tp.add_argument("--character-name", metavar="NAME",
                    help="what it is called in game; a literal string, so no "
                         "dialog.tlk patching")
    tp.add_argument("--register", nargs="?", const=True, metavar="LABEL",
                    help="also write the heads.2da and appearance.2da rows that "
                         "make the game offer this as a character. Needs "
                         "--save-as. Rows are appended to whatever is installed, "
                         "so other mods' entries survive")
    tp.add_argument("--save-as", metavar="RESREF",
                    help="write the result as a NEW model with this name rather "
                         "than overwriting the host. The name inside the model "
                         "is changed to match, so it sits beside the originals "
                         "instead of replacing one")
    tp.add_argument("--fit", action="store_true",
                    help="scale the donor part down to the host part's size. "
                         "Usually wrong for a head: a Bith fitted to Carth "
                         "stands 0.242 tall and floats above the collar, where "
                         "left alone it stands 0.400 and meets the neck. Use it "
                         "when a donor is genuinely the wrong scale, not by "
                         "default")
    tp.add_argument("--place", action="store_true",
                    help="move the donor onto the host part without resizing it, "
                         "so it keeps the size it was authored at. Use instead of "
                         "--fit when the donor is genuinely a different shape")
    tp.add_argument("--scale", type=float, default=1.0,
                    help="multiply the fitted size, for a donor whose "
                         "proportions differ from the host's and so comes out "
                         "smaller than the part it replaces")
    tp.add_argument("--max-influences", type=int, default=4)
    tp.add_argument("--reshape", action="store_true",
                    help="keep the host's vertices and move them onto the donor's surface; "
                         "required for heads, whose facial animation breaks if the vertex "
                         "count changes")
    tp.add_argument("--hide-unmatched", action="store_true",
                    help="stop drawing host nodes the donor does not have, so the swap "
                         "does not leave the old character's hair or accessories behind")
    tp.add_argument("--with-texture", action="store_true",
                    help="also take the donor's texture, sampling its UVs where each "
                         "host vertex lands (implies --reshape)")
    tp.add_argument("--dry-run", action="store_true", help="report matches and fit, write nothing")

    hd = sub.add_parser("head", help="check or install a custom head pack")
    hd.add_argument("pack", help="folder holding head.obj, and optionally head.tga")
    hd.add_argument("--install", help="game install, needed to check against a target")
    hd.add_argument("--host", help="model the head is going into, e.g. p_carthh")
    hd.add_argument("--node", help="node in that model (default: the pack's target)")
    hd.add_argument("--out", help="build it here; omit to only check")
    hd.add_argument("--decimate", nargs="?", type=int, const=690, default=None,
                    metavar="TRIANGLES",
                    help="reduce the mesh to a triangle budget before anything else "
                         "(default 690, vanilla's median head)")
    hd.add_argument("--reshape", action="store_true",
                    help="keep the host's topology, UVs and weights and move its "
                         "vertices onto the pack's surface, instead of replacing "
                         "the mesh. No longer required for skinned heads, but "
                         "still useful when you want the host's own UVs")
    hd.add_argument("--fit", action="store_true",
                    help="scale and place the mesh onto the target node, using the "
                         "pack's facing, up, scale and anchor hints")
    hd.add_argument("--crop", type=float, metavar="FRACTION",
                    help="drop geometry below this fraction of the mesh's height, "
                         "for a source that is a bust rather than a head")
    hd.add_argument("--repair", action="store_true",
                    help="wind every triangle the same way round and outward. "
                         "Scans and generated meshes often arrive mixed, which "
                         "looks fine in a viewer and full of holes in game")
    hd.add_argument("--hide", nargs="*", metavar="NODE", default=None,
                    help="stop drawing these of the host's own nodes. With no "
                         "names, hides every other visible mesh in the head "
                         "model - hair, eyes, lids, teeth, tongue - which is "
                         "usually what a whole custom head wants, since those "
                         "are shaped for the face being replaced")
    hd.add_argument("--template", action="store_true",
                    help="write a head.json template into the folder and stop")

    im = sub.add_parser("import", help="turn a .glb into a head pack folder")
    im.add_argument("file", help="the .glb to read")
    im.add_argument("--out", required=True, help="pack folder to create")
    im.add_argument("--name", help="display name for the pack")
    im.add_argument("--texture-size", type=int, default=512,
                    help="resize the embedded texture to this, 0 to leave it")

    rn = sub.add_parser("render", help="draw a model to a PNG, without the game")
    rn.add_argument("model", help="a model name in the install, or a path to a .mdl")
    rn.add_argument("--install")
    rn.add_argument("--out", default="render.png")
    rn.add_argument("--compare", metavar="MODEL",
                    help="draw this one beside it, framed identically")
    rn.add_argument("--highlight", nargs="*", default=[], metavar="NODE",
                    help="draw these nodes in the accent colour")
    rn.add_argument("--yaw", type=float, default=0.0, help="degrees, 0 is front")
    rn.add_argument("--pitch", type=float, default=0.0, help="degrees, + looks down")
    rn.add_argument("--size", type=int, default=640)
    rn.add_argument("--turntable", type=int, default=0, metavar="N",
                    help="write N frames around the model instead of one image")
    rn.add_argument("--textured", action="store_true",
                    help="paint each mesh with the texture its header names")
    rn.add_argument("--texture-dir", action="append", default=[], metavar="DIR",
                    help="look here for loose textures first; repeatable")
    rn.add_argument("--cull", action="store_true",
                    help="draw only front-facing triangles, as the engine does. "
                         "An inside-out mesh looks perfect in the normal "
                         "two-sided preview and full of holes in game")
    rn.add_argument("--show-hidden", action="store_true",
                    help="draw meshes the render flag turns off, in grey")

    bl = sub.add_parser("builds", help="list the builds in an output folder")
    bl.add_argument("--out", required=True)
    bl.add_argument("--verify", action="store_true",
                    help="check each build's files against its own manifest")

    rk = sub.add_parser("rank", help="sort donors by how well they fit a host")
    rk.add_argument("--install", required=True, help="the host's game")
    rk.add_argument("--host", required=True, help="model to put a head on, e.g. p_carthh")
    rk.add_argument("--donor-install", help="where donors come from (default: --install)")
    rk.add_argument("--donors", nargs="*",
                    help="donor names; default is every model a head can come from")
    rk.add_argument("--who",
                    choices=["male", "female", "droid", "either", "unknown"],
                    help="only donors of this kind. Droid is decided structurally "
                         "- a rigid head with no facial bones - and the rest from "
                         "the game's own tables where they can be trusted. "
                         "male and female both include heads that are either, "
                         "like Revan's")
    rk.add_argument("--top", type=int, default=25, help="how many to show (0 for all)")
    rk.add_argument("--notes", action="store_true",
                    help="say what the number does not, for each donor")
    rk.add_argument("--json", help="also write the full ranking here")

    lp = sub.add_parser("lips", help="make mouths move for an unvoiced dialogue")
    lp.add_argument("dialogue", help="a .dlg file")
    lp.add_argument("--out", required=True, help="where to write the .lip files")
    lp.add_argument("--prefix", help="resref stem for lines that have no "
                                     "VO_ResRef yet (default: the dialogue's name)")
    lp.add_argument("--assign", action="store_true",
                    help="give lines that have no VO_ResRef one, and write the "
                         "updated dialogue alongside the lips. Without this, "
                         "only lines that already name a VO get a lip")
    lp.add_argument("--replies", action="store_true",
                    help="also do the player's lines")
    lp.add_argument("--audio", metavar="DIR",
                    help="a folder of recordings. A line whose VO_ResRef has a "
                         "matching .wav or .mp3 gets a lip as long as the "
                         "recording, so the mouth moves for exactly as long as "
                         "the voice does. Lines without one fall back to an "
                         "estimate from the word count")
    lp.add_argument("--seconds", type=float, metavar="N",
                    help="force every lip to this length, for when the timing "
                         "is known but the files are not here")

    jd = sub.add_parser("jade",
                        help="turn a Jade Empire model into a head pack")
    jd.add_argument("resref", nargs="?",
                    help="the model to convert; omit to list what is there")
    jd.add_argument("--install", help="the Jade Empire folder (found "
                                      "automatically if left out)")
    jd.add_argument("--out", help="pack folder to create")
    jd.add_argument("--kind", choices=["head", "body", "all"], default="head",
                    help="which models to list (default: heads)")
    jd.add_argument("--no-texture", action="store_true",
                    help="skip the texture; the head then wears the host's")
    jd.add_argument("--scale", type=float,
                    help="size correction; the measured default is 0.83, and "
                         "it is a measurement rather than a fact - see "
                         "reports/JADE_FINDINGS.md")

    sub.add_parser("gui", help="launch the desktop app")

    args = p.parse_args(argv)
    try:
        if args.cmd == "effects":
            return _effects()
        if args.cmd == "companions":
            return _companions()
        if args.cmd == "preview":
            return _preview(args)
        if args.cmd == "build":
            return _build(args)
        if args.cmd == "transplant":
            return _transplant(args)
        if args.cmd == "head":
            return _head(args)
        if args.cmd == "import":
            return _import(args)
        if args.cmd == "render":
            return _render(args)
        if args.cmd == "builds":
            return _builds(args)
        if args.cmd == "rank":
            return _rank(args)
        if args.cmd == "lips":
            return _lips(args)
        if args.cmd == "jade":
            return _jade(args)
        if args.cmd == "gui":
            from .gui import run

            return run()
    except KeyError as exc:
        print(f"kmdlfun: {exc}", file=sys.stderr)
        return 1
    return 2


def _load_layout(name: str, install: str | None):
    """A model by name from the install, or by path to a built .mdl."""
    from pathlib import Path as _Path

    from kmdlswap import layout as kl

    if name.lower().endswith(".mdl") or _Path(name).is_file():
        mdl = _Path(name)
        mdx = mdl.with_suffix(".mdx")
        if not mdx.is_file():
            raise SystemExit(f"{mdx.name} is missing; an MDL cannot be read without it")
        return kl.parse(mdl.read_bytes(), mdx.read_bytes())
    if not install:
        raise SystemExit(f"{name!r} is not a file, so --install is needed to look it up")
    from .library import ModelLibrary

    return kl.parse(*ModelLibrary(install).read(name))


def _builds(args) -> int:
    """What is in an output folder, and what each thing is."""
    from . import builds as kbuilds

    found = kbuilds.find(args.out)
    if not found:
        print(f"no builds in {args.out}")
        return 0

    print(f"{len(found)} build(s) in {args.out}\n")
    for build in found:
        print(f"  {build.summary}")
        if build.manifest.get("unmanaged"):
            print("      (no manifest - made before builds were named, or dropped in)")
            continue
        merged = build.manifest.get("merged") or []
        if merged:
            print(f"      folded in: {', '.join(merged)}")
        options = build.manifest.get("options") or {}
        on = [k for k, v in options.items() if v is True]
        scale = options.get("scale")
        if scale and scale != 1.0:
            on.append(f"scale {scale:g}")
        if on:
            print(f"      {', '.join(on)}")
        if args.verify:
            problems = build.check()
            print("      " + ("verified" if not problems else "; ".join(problems)))
    return 0


def _import(args) -> int:
    """Read a .glb and write a head pack beside it."""
    from . import glbimport

    try:
        result = glbimport.run(args.file, args.out, name=args.name,
                               texture_size=args.texture_size)
    except glbimport.ImportError_ as exc:
        print(f"kmdlfun: {exc}", file=sys.stderr)
        return 1

    for line in glbimport.summarise(result, args.file):
        print(line)
    print("Check it with:  kmdlfun head " + str(result.pack)
          + " --install \"<K1 root>\" --host p_carthh --node Head --decimate --fit")
    return 0


def _render(args) -> int:
    import math
    from pathlib import Path as _Path

    from . import render as krender

    highlight = frozenset(args.highlight)
    lookup = None
    cache = None
    if args.textured:
        from . import textures as ktextures

        extra = [_Path(d) for d in args.texture_dir]
        # A build's own texture sits beside it, and is the one the game will use
        # once both are in Override - so look there before anything installed.
        for candidate in (args.model, args.compare):
            if not candidate:
                continue
            folder = _Path(candidate).parent
            if folder.is_dir() and folder not in extra:
                extra.insert(0, folder)
        cache = ktextures.TextureCache(args.install, extra=extra)
        lookup = cache.get

    layout = _load_layout(args.model, args.install)
    scene = krender.from_layout(
        layout, highlight=highlight, include_hidden=args.show_hidden,
        texture_lookup=lookup,
    )
    if args.textured:
        named = {krender.node_texture(layout, n) for n in kparts.mesh_nodes(layout)}
        found = len(scene.textures)
        print(f"  textures: {found} of {len(named - {''})} resolved"
              f" ({', '.join(sorted(named - {''}))})")
        for problem in (cache.problems if cache else []):
            print(f"  texture problem: {problem}")
        if not found:
            print("  nothing resolved, so this is drawing untextured grey")
    print(f"{args.model}: {scene.triangles} triangles across {len(scene.groups)} meshes")
    if highlight:
        missing = highlight - set(scene.groups)
        if missing:
            print(f"  not drawn (absent or hidden): {', '.join(sorted(missing))}")

    scenes = [scene]
    if args.compare:
        other = krender.from_layout(
            _load_layout(args.compare, args.install),
            highlight=highlight,
            include_hidden=args.show_hidden,
            texture_lookup=lookup,
        )
        print(f"{args.compare}: {other.triangles} triangles across "
              f"{len(other.groups)} meshes")
        scenes.append(other)

    # One shared framing, or the comparison lies about relative size.
    bounds = krender.shared_bounds(scenes)
    out = _Path(args.out)

    if args.turntable:
        stem, suffix = out.stem, out.suffix or ".png"
        for i in range(args.turntable):
            yaw = 2.0 * math.pi * i / args.turntable
            frame = krender.strip(scenes, yaw=yaw,
                                  pitch=math.radians(args.pitch),
                                  size=args.size, bounds=bounds, cull=args.cull)
            krender.to_png(frame, out.with_name(f"{stem}_{i:03d}{suffix}"))
        print(f"wrote {args.turntable} frames to {out.parent}/{stem}_NNN{suffix}")
        return 0

    frame = krender.strip(scenes, yaw=math.radians(args.yaw),
                          pitch=math.radians(args.pitch),
                          size=args.size, bounds=bounds)
    out.parent.mkdir(parents=True, exist_ok=True)
    krender.to_png(frame, out)
    print(f"wrote {out}")
    print("No animation" + ("" if args.textured else ", no texture")
          + ". A preview is not proof.")
    return 0


def _effects() -> int:
    for e in keffects.EFFECTS:
        scales = ", ".join(f"{k} x{v:g}" for k, v in e.scales.items())
        print(f"{e.key:<12} {e.label}")
        print(f"             {e.description}")
        print(f"             scales: {scales}")
        if e.caution:
            print(f"             CAUTION: {e.caution}")
    return 0


def _companions() -> int:
    for c in roster.COMPANIONS:
        note = f"   ({c.note})" if c.note else ""
        print(f"{c.key:<11} {c.name:<18} {', '.join(c.models)}{note}")
    return 0


def _preview(args) -> int:
    from kmdlswap import layout as kl

    from .library import ModelLibrary

    effect = keffects.resolve(args.effect)
    scales = effect.scaled(args.intensity)
    lib = ModelLibrary(args.install)

    print(f"effect: {effect.label}  ({', '.join(f'{k} x{v:.2f}' for k, v in scales.items())})")
    if effect.caution:
        print(f"CAUTION: {effect.caution}")
    for c in roster.resolve(args.companion):
        print(f"\n{c.name}")
        for model in c.models:
            if not lib.has(model):
                print(f"  {model:<16} not in this install")
                continue
            layout = kl.parse(*lib.read(model))
            hits = []
            for part_key in scales:
                for index in kapply.targets(layout, part_key):
                    hits.append((layout.nodes[index].name, part_key))
            kind = "head model" if kapply.is_head_model(layout) else "body model"
            if not hits:
                print(f"  {model:<16} {kind}: nothing matches")
                continue
            names = ", ".join(n for n, _ in hits[:8])
            more = f" (+{len(hits) - 8} more)" if len(hits) > 8 else ""
            print(f"  {model:<16} {kind}: {len(hits)} nodes -> {names}{more}")
    return 0


def _build(args) -> int:
    from .library import build

    def progress(i, total, label):
        if i < total:
            print(f"  [{i + 1}/{total}] {label}", file=sys.stderr)

    report = build(
        args.install, args.effect, args.companion, args.out,
        intensity=args.intensity, pivot=args.pivot, progress=progress,
    )
    effect = keffects.resolve(args.effect)
    print(f"\n{effect.label} @ {args.intensity:g}x -> {args.out}")
    print(f"  models written : {report.written}")
    print(f"  nodes changed  : {report.total_nodes}")
    if report.missing:
        print(f"  not in install : {', '.join(report.missing)}")
    for m in report.failed:
        print(f"  FAILED {m.model}: {m.error}", file=sys.stderr)
    skipped = [(m.model, s) for m in report.models for s in m.skipped]
    for model, s in skipped[:10]:
        print(f"  skipped {model}: {s}", file=sys.stderr)
    print("\nCopy the .mdl/.mdx files into the game's Override directory to use them.")
    print("A successful build is not proof; verify in-game.")
    return 0 if not report.failed else 1


def _transplant(args) -> int:
    from pathlib import Path

    from kmdlswap import layout as kl
    from kmdlswap import validate as kv

    from . import transplant as ktp
    from .library import ModelLibrary

    lib = ModelLibrary(args.install)
    donor_lib = ModelLibrary(args.donor_install) if args.donor_install else lib
    if not lib.has(args.host):
        print(f"kmdlfun: no model {args.host!r} in the host install", file=sys.stderr)
        return 1
    if not donor_lib.has(args.donor):
        where = "the donor install" if args.donor_install else "that install"
        print(f"kmdlfun: no model {args.donor!r} in {where}", file=sys.stderr)
        return 1

    mdl, mdx = lib.read(args.host)
    donor_layout = kl.parse(*donor_lib.read(args.donor))
    host_layout = kl.parse(mdl, mdx)
    if donor_layout.game != host_layout.game:
        # Only geometry crosses. The host keeps its own hierarchy, skeleton and
        # animations, and is written back in its own format, so the games'
        # header differences never leave the reader.
        print(f"  donor is a {donor_layout.game} model, host is "
              f"{host_layout.game}: geometry only")

    if args.pair:
        hosts = {n.name.lower(): n.name for n in ktp.kparts.mesh_nodes(
            host_layout, visible_only=False)}
        donors = {n.name.lower(): n.name for n in ktp.kparts.mesh_nodes(donor_layout)}
        pairs = []
        for spec in args.pair:
            if "=" not in spec:
                print(f"kmdlfun: --pair wants HOST=DONOR, got {spec!r}", file=sys.stderr)
                return 1
            h, d = (s.strip() for s in spec.split("=", 1))
            if h.lower() not in hosts:
                print(f"kmdlfun: {args.host} has no node {h!r}", file=sys.stderr)
                return 1
            if d.lower() not in donors:
                print(f"kmdlfun: {args.donor} has no node {d!r}", file=sys.stderr)
                return 1
            pairs.append((hosts[h.lower()], donors[d.lower()]))
    elif args.node:
        donors = {n.name.lower(): n.name for n in ktp.kparts.mesh_nodes(donor_layout)}
        pairs = []
        for wanted in args.node:
            match = donors.get(wanted.lower())
            if not match:
                print(f"kmdlfun: {args.donor} has no node matching {wanted!r}", file=sys.stderr)
                return 1
            pairs.append((wanted, match))
    else:
        pairs = ktp.match_nodes(host_layout, donor_layout)

    if not pairs:
        print(
            f"kmdlfun: {args.host} and {args.donor} share no mesh node names, "
            f"so there is nothing to move between them",
            file=sys.stderr,
        )
        return 1

    print(f"{args.host}  <-  {args.donor}   ({len(pairs)} node(s))")
    print()

    # Nodes the donor does not have keep the host's geometry AND the host's
    # texture, so they end up shaped for the old head and coloured from the old
    # texture. Carth's hair on Dustil's skull is exactly this. Say so before the
    # model is written, not after it has been loaded.
    taken = {h for h, _ in pairs}
    left = [n.name for n in ktp.kparts.mesh_nodes(host_layout) if n.name not in taken]
    if left and not args.hide_unmatched:
        print(f"  left as {args.host}'s own: {', '.join(left)}")
        print(f"  ({args.donor} has no node of that name. These keep their original")
        print("   shape and texture, so they may not sit right on the new head.")
        print("   Use --hide-unmatched to stop drawing them.)")
        print()
    elif left:
        print(f"  will hide (donor has no such node): {', '.join(left)}")
        print()
    # With explicit pairs the parts have to keep their positions relative to one
    # another - four tentacles centred individually on four unrelated host nodes
    # would land in four wrong places. So the first pair anchors a single shift,
    # worked out in model space, and every part moves by the same amount.
    model_offset = None
    if args.pair and len(pairs) > 1 and not args.fit:
        anchor_host, anchor_donor = ktp.anchor_pair(pairs, host_layout)
        model_offset = ktp.model_alignment(
            donor_layout, donor_layout.node_by_name(anchor_donor),
            host_layout, host_layout.node_by_name(anchor_host),
        )
        print(f"  aligned on {anchor_host} <- {anchor_donor}; every part moves "
              f"by the same amount")
        print()

    # Parts the host has no node for, that its own skeleton can still drive.
    anchor = ktp.anchor_pair(pairs, host_layout)
    auto = []
    if not args.no_auto_merge and not args.merge and anchor:
        h, d = anchor
        auto = ktp.auto_merge_candidates(
            donor_layout, donor_layout.node_by_name(d),
            host_layout, host_layout.node_by_name(h),
        )
        if auto:
            print(f"  folding in {len(auto)} donor part(s) {args.host} has no node "
                  f"for: {', '.join(auto)}")
            print()

    results = []
    for host_node, donor_node in pairs:
        mdl2, mdx2, r = ktp.transplant_node(
            mdl, mdx, donor_layout, args.donor, host_node, donor_node,
            fit=args.fit, scale=args.scale, place=args.place,
            model_offset=model_offset,
            merge=(args.merge or auto) if (host_node, donor_node) == anchor else None,
            max_influences=args.max_influences, reshape=args.reshape,
            with_texture=args.with_texture,
        )
        results.append(r)
        if r.ok and not args.dry_run:
            mdl, mdx = mdl2, mdx2
        line = f"  {host_node:<16} <- {donor_node:<16}"
        if not r.ok:
            print(f"{line} REFUSED: {r.error}")
            continue
        a = r.alignment
        s = r.swap
        print(
            f"{line} {s.old_vertices:>5} -> {s.new_vertices:<5} verts"
            f"   fit {a.worst_ratio:.2f}x   drift {a.drift:.3f}"
        )
        for w in r.warnings:
            print(f"      ! {w}")

    done = [r for r in results if r.ok]
    if args.dry_run:
        print(f"dry run: {len(done)}/{len(pairs)} node(s) would transfer")
        return 0
    if not done:
        print("nothing transferred", file=sys.stderr)
        return 1

    hidden_names: list[str] = []
    if args.hide_unmatched and left:
        from . import visibility as kvis

        mdl, hidden = kvis.hide_nodes(kl.parse(mdl, mdx), mdl, left)
        hidden_names = list(hidden)
        print(f"hid {len(hidden)} node(s) the donor does not have: {', '.join(hidden)}")

    final = kv.check(kl.parse(mdl, mdx))
    if not final.ok:
        print("kmdlfun: result failed validation; refusing to write it", file=sys.stderr)
        return 1

    # Each build gets its own folder, so one does not overwrite the last and
    # "the Quarren one" is a thing you can point at.
    from . import builds as kbuilds

    root = Path(args.out)
    root.mkdir(parents=True, exist_ok=True)
    written_as = args.host
    if getattr(args, "save_as", None):
        from kmdlswap import rename as krename

        krename.check_name(args.save_as)
        mdl, mdx = krename.rename(mdl, mdx, args.save_as)
        written_as = args.save_as
        print(f"  saved as {written_as}: a new model, not a replacement for "
              f"{args.host}")

    name = args.name or kbuilds.unique_name(root, f"{written_as}-{args.donor}")
    out_dir = root / kbuilds.slug(name)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{written_as}.mdl").write_bytes(mdl)
    (out_dir / f"{written_as}.mdx").write_bytes(mdx)

    if args.donor_install and args.with_texture:
        # The donor's texture lives in the donor's game. Without it the model
        # loads and renders untextured grey, which looks like a modelling
        # failure and is really a missing file - so write it out rather than
        # leaving behind a build that cannot work.
        from . import textures as ktextures

        for line in ktextures.export_donor_textures(
            mdl, mdx, args.donor_install, out_dir, host_install=args.install
        ):
            print(f"  {line}")

    if getattr(args, "as_character", None):
        from . import character as kchar

        if not getattr(args, "save_as", None):
            print("kmdlfun: --as-character needs --save-as, so the character has "
                  "a model of its own to wear", file=sys.stderr)
            return 1
        try:
            ch = kchar.create(
                args.install, out_dir, resref=args.as_character, kind=args.kind,
                name=args.character_name, model=written_as, like=args.host,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"kmdlfun: {exc}", file=sys.stderr)
            return 1
        for line in ch.notes:
            print(f"  {line}")
        for line in ch.todo:
            print(f"  still yours: {line}")

    elif getattr(args, "register", None):
        from . import twoda as k2da

        if not getattr(args, "save_as", None):
            print("kmdlfun: --register needs --save-as, or it would register the "
                  "host's own name", file=sys.stderr)
            return 1
        label = args.register if isinstance(args.register, str) else written_as
        try:
            reg = k2da.register_head(args.install, out_dir, written_as,
                                     label=label, like=args.host)
        except k2da.TwoDAError as exc:
            print(f"kmdlfun: {exc}", file=sys.stderr)
            return 1
        for line in reg.notes:
            print(f"  {line}")

    build = kbuilds.adopt(out_dir, {
        "name": name,
        "kind": "transplant",
        "host": {"model": args.host, "game": host_layout.game, "install": args.install},
        "donor": {"model": args.donor, "game": donor_layout.game,
                  "install": args.donor_install or args.install},
        "nodes": [list(pair) for pair in pairs],
        "merged": list(args.merge or auto),
        "hidden": hidden_names,
        "options": {
            "fit": args.fit, "place": args.place, "scale": args.scale,
            "reshape": args.reshape, "with_texture": args.with_texture,
            "hide_unmatched": args.hide_unmatched,
            "auto_merge": not args.no_auto_merge,
        },
    })

    print()
    print(f"{len(done)}/{len(pairs)} node(s) transferred")
    print(f"build '{build.name}' in {out_dir}")
    print(f"  {', '.join(f['name'] for f in build.manifest['files'])}")
    print("Install it from the app, or copy the folder's contents into Override.")
    return 0


def _head(args) -> int:
    """Check a custom head pack, and optionally build it into a model.

    The work itself lives in `headbuild`, so the desktop app runs exactly this
    and the two cannot drift apart.
    """
    from . import headbuild, headpack

    if args.template:
        path = headpack.write_template(args.pack)
        print(f"wrote {path}; fill it in and run again without --template")
        return 0

    result = headbuild.run(
        args.pack,
        install=args.install,
        host=args.host,
        node=args.node,
        crop=args.crop,
        decimate=args.decimate,
        repair=args.repair,
        fit=args.fit,
        reshape=args.reshape,
        hide=args.hide,
        build=bool(args.out),
    )
    for line in result.lines:
        print("  " + line)
    print()
    print(result.verdict)
    if result.error:
        print(f"kmdlfun: {result.error}", file=sys.stderr)
        return 1
    if result.failures:
        return 1
    if not args.out:
        return 0

    written = headbuild.write(result, args.out, args.host)
    print("wrote " + ", ".join(str(p) for p in written))
    print("Copy them into Override. A successful build is not proof.")
    return 0


def _rank(args) -> int:
    """Which donors are worth building, best first.

    Building one to find out costs minutes, and the list is a few hundred names
    in alphabetical order. See `kmdlfun.compat` for what the grades mean - they
    are vanilla's own percentiles, not invented thresholds.
    """
    import json

    from . import compat
    from .library import (DONOR_KINDS, ModelLibrary, character_models,
                          classify)

    host_lib = ModelLibrary(args.install)
    donor_lib_path = args.donor_install or args.install
    donor_lib = ModelLibrary(args.donor_install) if args.donor_install else host_lib

    if not host_lib.has(args.host):
        print(f"kmdlfun: {args.install} has no model {args.host!r}", file=sys.stderr)
        return 1

    donors = args.donors
    if not donors:
        names = character_models(donor_lib_path, donor_lib)
        print(f"sorting {len(names)} models by what a head can come from...")
        kinds = classify(donor_lib, names)
        donors = [n for n, k in kinds.items() if k in DONOR_KINDS]

    if args.who:
        from . import who as kwho

        looked = kwho.looks(donor_lib_path, donors, library=donor_lib)
        donors = [d for d in donors
                  if kwho.matches(looked.get(d, "unknown"), args.who)]
        print(f"{len(donors)} are {args.who}")
        if not donors:
            print(f"no {args.who} donors in that install")
            return 1

    print(f"measuring {len(donors)} donors against {args.host}...")
    fits = compat.rank(*host_lib.read(args.host), donor_lib, donors,
                       host_name=args.host)
    if not fits:
        print("nothing to measure")
        return 1

    print(f"\n{compat.summarise(fits)}\n")
    shown = fits if args.top <= 0 else fits[: args.top]
    for fit in shown:
        print("  " + fit.line)
        if args.notes:
            for note in fit.notes():
                print("        - " + note)
    if len(shown) < len(fits):
        print(f"\n  ... and {len(fits) - len(shown)} more (--top 0 for all)")

    print("\n  w = keeps its own weights   d = needs decimating   "
          "+ = has extra parts to fold in")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump([{"donor": f.donor, "grade": f.grade, "far": f.far,
                        "mean": f.mean, "own_weights": f.own_weights,
                        "vertices": f.vertices, "size_ratio": f.size_ratio,
                        "extra_parts": f.extra_parts, "blocked": f.blocked}
                       for f in fits], fh, indent=1)
        print(f"  wrote {args.json}")
    return 0


def _jade(args) -> int:
    """Jade Empire geometry, out as a head pack.

    Jade's file layout shares almost nothing with KOTOR's, so the splice engine
    will never touch one of its models. What it can do is take the geometry,
    which is the same route a sculpt or a Blender export comes in by.
    """
    from pathlib import Path as _Path

    from . import installs, jade

    install = args.install or installs.detect().get(installs.JADE)
    if not install:
        print("kmdlfun: no Jade Empire install found; pass --install",
              file=sys.stderr)
        return 1

    kinds = (jade.HEAD, jade.BODY) if args.kind == "all" else (args.kind,)
    try:
        catalogue = jade.catalogue(install, kinds=kinds)
    except jade.JadeError as exc:
        print(f"kmdlfun: {exc}", file=sys.stderr)
        return 1

    if not args.resref:
        print(f"{len(catalogue)} model(s) in {install}")
        for entry in catalogue:
            print(f"  {entry.kind:<5} {entry.resref}")
        print("\nPass one of these and --out to convert it.")
        return 0

    wanted = args.resref.lower()
    entry = next((e for e in catalogue if e.resref.lower() == wanted), None)
    if entry is None:
        print(f"kmdlfun: no model named {args.resref!r} in {install}",
              file=sys.stderr)
        return 1
    if not args.out:
        print("kmdlfun: --out is required to convert", file=sys.stderr)
        return 1

    scale = args.scale if args.scale is not None else jade.SCALE
    try:
        result = jade.to_pack(entry, _Path(args.out), scale=scale,
                              install=install,
                              with_texture=not args.no_texture)
    except jade.JadeError as exc:
        print(f"kmdlfun: {exc}", file=sys.stderr)
        return 1

    print(f"{entry.resref}  ({entry.kind})")
    print(f"  vertices  {result['vertices']}")
    print(f"  triangles {result['triangles']}")
    print(f"  uvs       {result['uvs'] or 'NONE - it will render untextured'}")
    wears = result["texture"] or "none - it will wear the host's"
    print(f"  texture   {wears}")
    print(f"  scale     x{scale} , rotated upright")
    for note in result["notes"]:
        print(f"  note: {note}")
    print(f"\nwrote a head pack to {result['pack']}")
    print("Build it with:  kmdlfun head " + str(result["pack"])
          + " --install \"<K1 root>\" --host p_carthh --node Head "
            "--decimate --fit")
    return 0


def _lips(args) -> int:
    """A lip file per line, so an unvoiced NPC still moves its mouth.

    The dialogue is never edited in place: if lines need a VO_ResRef, the
    updated copy is written next to the lips and installing it is a separate
    decision.
    """
    from . import dialogue as kdlg

    try:
        job = kdlg.run(args.dialogue, args.out, prefix=args.prefix,
                       assign=args.assign, replies=args.replies,
                       audio=args.audio, seconds=args.seconds)
    except kdlg.DialogueError as exc:
        print(f"kmdlfun: {exc}", file=sys.stderr)
        return 1

    for line in kdlg.summarise(job, audio=args.audio):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
