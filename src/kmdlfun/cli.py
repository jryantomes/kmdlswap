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
    tp.add_argument("--node", nargs="*", help="host node(s); default every matching node")
    tp.add_argument("--out", required=True)
    tp.add_argument("--fit", action="store_true", help="scale the donor part to the host part's size")
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


def _import(args) -> int:
    """Read a .glb and write a head pack beside it."""
    from pathlib import Path as _Path

    from kmdlswap import obj as kobj

    from . import gltf, headpack

    source = _Path(args.file)
    if not source.is_file():
        print(f"kmdlfun: no such file {source}", file=sys.stderr)
        return 1
    try:
        imported = gltf.read_glb(source)
    except gltf.GltfError as exc:
        print(f"kmdlfun: {exc}", file=sys.stderr)
        return 1

    print(f"{source.name}")
    print(f"  vertices  {len(imported.positions)}")
    print(f"  triangles {len(imported.faces)}")
    print(f"  normals   {'yes' if imported.normals else 'no (will be computed)'}")
    print(f"  uvs       {'yes' if imported.uvs else 'NO - the head will be untextured'}")
    print(f"  texture   {imported.image_mime or 'none embedded'}"
          + (f", {len(imported.image)} bytes" if imported.image else ""))
    for note in imported.notes:
        print(f"  note: {note}")

    out = _Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    kobj.write_obj(
        out / "head.obj",
        imported.positions,
        imported.faces,
        uvs=imported.uvs or None,
        normals=imported.normals or None,
        name=out.name,
    )

    texture_name = None
    if imported.image:
        try:
            from PIL import Image
        except ImportError:
            print("  texture: Pillow is not installed, so it was not converted",
                  file=sys.stderr)
        else:
            import io

            with Image.open(io.BytesIO(imported.image)) as img:
                img = img.convert("RGB")
                if args.texture_size:
                    n = args.texture_size
                    if img.size != (n, n):
                        print(f"  texture: {img.size[0]}x{img.size[1]} -> {n}x{n}")
                        img = img.resize((n, n), Image.LANCZOS)
                # The resref is the filename, and it has to fit a 16-character
                # field, so keep it short and predictable.
                texture_name = out.name.lower()[:14] + "01"
                img.save(out / f"{texture_name}.tga")

    headpack.write_template(out, name=args.name or out.name)
    manifest = out / headpack.MANIFEST_NAME
    import json

    data = json.loads(manifest.read_text(encoding="utf-8"))
    # glTF is Y-up with -Z forward; after the Y-up conversion that lands on +Y,
    # which is where KOTOR characters look.
    data["up"] = "y"
    data["facing"] = "+y"
    data["notes"] = f"imported from {source.name}"
    manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    print(f"\nwrote {out}/head.obj"
          + (f", {texture_name}.tga" if texture_name else "")
          + f" and {headpack.MANIFEST_NAME}")
    print("Check it with:  kmdlfun head " + str(out)
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


if __name__ == "__main__":
    raise SystemExit(main())


def _transplant(args) -> int:
    from pathlib import Path

    from kmdlswap import layout as kl
    from kmdlswap import validate as kv

    from . import transplant as ktp
    from .library import ModelLibrary

    lib = ModelLibrary(args.install)
    for name in (args.host, args.donor):
        if not lib.has(name):
            print(f"kmdlfun: no model {name!r} in that install", file=sys.stderr)
            return 1

    mdl, mdx = lib.read(args.host)
    donor_layout = kl.parse(*lib.read(args.donor))
    host_layout = kl.parse(mdl, mdx)

    if args.node:
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
    results = []
    for host_node, donor_node in pairs:
        mdl2, mdx2, r = ktp.transplant_node(
            mdl, mdx, donor_layout, args.donor, host_node, donor_node,
            fit=args.fit, max_influences=args.max_influences, reshape=args.reshape,
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

    if args.hide_unmatched and left:
        from . import visibility as kvis

        mdl, hidden = kvis.hide_nodes(kl.parse(mdl, mdx), mdl, left)
        print(f"hid {len(hidden)} node(s) the donor does not have: {', '.join(hidden)}")

    final = kv.check(kl.parse(mdl, mdx))
    if not final.ok:
        print("kmdlfun: result failed validation; refusing to write it", file=sys.stderr)
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{args.host}.mdl").write_bytes(mdl)
    (out_dir / f"{args.host}.mdx").write_bytes(mdx)
    print()
    print(f"{len(done)}/{len(pairs)} node(s) transferred")
    print(f"wrote {out_dir / args.host}.mdl and .mdx")
    print("Copy both into the game's Override directory. Verify in-game.")
    return 0


def _head(args) -> int:
    """Check a custom head pack, and optionally build it into a model."""
    from pathlib import Path

    from kmdlswap import obj as kobj

    from . import headpack, headspec

    if args.template:
        path = headpack.write_template(args.pack)
        print(f"wrote {path}; fill it in and run again without --template")
        return 0

    pack = headpack.load(args.pack)
    print(f"{pack.name}   ({pack.root})")
    for problem in pack.problems:
        print(f"  [FAIL] pack: {problem}")
    if pack.mesh_path is None:
        return 1
    print(f"  mesh    {pack.mesh_path.name}")
    print(f"  texture {pack.texture_path.name if pack.texture_path else '(none - keeps the host texture)'}")
    print()

    try:
        mesh = kobj.read_obj(pack.mesh_path)
    except kobj.ObjError as exc:
        print(f"  [FAIL] mesh: {exc}", file=sys.stderr)
        return 1

    if args.crop:
        from . import repair as krepair

        axis = 1 if pack.up == "y" else 2
        mesh, cut = krepair.crop_below(mesh, args.crop, axis=axis)
        print(f"  cropped: {cut} face(s) below {args.crop:.0%} of the height removed"
              if cut else "  cropped: nothing was below the cut")

    if args.decimate:
        from . import decimate as kdecimate

        result = kdecimate.simplify(mesh, args.decimate)
        if result.after < result.before:
            mesh = result.mesh
            print(f"  decimated: {result.summary()}")
        else:
            print(f"  decimate: already {result.before} triangles, left alone")

    if args.repair:
        from . import repair as krepair

        mesh, flipped = krepair.unify_winding(mesh)
        print(f"  winding: {flipped} face(s) rewound to agree with their neighbours"
              if flipped else "  winding: already consistent")
        print(f"           {krepair.facing_report(mesh)}")

    verdict = headspec.check_mesh(mesh)
    for line in verdict.lines():
        print("  " + line)

    if pack.texture_path:
        tex = headspec.check_texture(pack.texture_path)
        for line in tex.lines():
            print("  " + line)
        verdict.findings.extend(tex.findings)

    layout = node = None
    if args.install and args.host:
        from kmdlswap import layout as kl

        from .library import ModelLibrary

        lib = ModelLibrary(args.install)
        if not lib.has(args.host):
            print(f"kmdlfun: no model {args.host!r} in that install", file=sys.stderr)
            return 1
        layout = kl.parse(*lib.read(args.host))
        wanted = args.node or pack.target
        try:
            node = layout.node_by_name(wanted)
        except KeyError as exc:
            print(f"kmdlfun: {exc}", file=sys.stderr)
            return 1
        if args.fit:
            mesh = _fit_mesh(mesh, pack, layout, node)

        target = headspec.check_against_target(mesh, layout, node)
        for line in target.lines():
            print("  " + line)
        verdict.findings.extend(target.findings)

        placement = headspec.check_placement(mesh, layout, node)
        for line in placement.lines():
            print("  " + line)
        verdict.findings.extend(placement.findings)

    print()
    if verdict.failures:
        print(f"REJECTED: {len(verdict.failures)} blocking problem(s), "
              f"{len(verdict.warnings)} warning(s)")
        if not args.decimate and any(f.check == "density" for f in verdict.failures):
            print("Too dense is the one failure the tool can fix itself: "
                  "add --decimate")
        return 1
    print(f"ACCEPTED with {len(verdict.warnings)} warning(s)")

    if not args.out:
        return 0
    if layout is None or node is None:
        print("kmdlfun: --out needs --install and --host too", file=sys.stderr)
        return 1

    from kmdlswap import edit as ke
    from kmdlswap import validate as kv
    from kmdlswap import layout as kl2

    from . import reshape as kreshape
    from kmdlswap.swap import build_replacement

    host_positions = ke.extract(layout, node).positions

    if args.reshape:
        # Opt-in now. This used to be forced for every skinned head, because a
        # changing vertex count appeared to break facial animation; that was a
        # stale pointer in our own writer, since fixed and confirmed in game
        # (reports/SKIN_ROOT_POINTER_FINDINGS.md). It survives because keeping
        # the host's UVs and weights is sometimes what you actually want.
        host_geo = ke.extract(layout, node)
        moved = kreshape.snap_to_surface(host_geo.positions, mesh.positions, mesh.faces)
        shaped = kobj.ObjMesh(name=node.name)
        shaped.positions = moved
        shaped.faces = [f.vertices for f in host_geo.faces]
        shaped.materials = [f.material for f in host_geo.faces]
        if "uv1" in host_geo.columns:
            shaped.uvs = [tuple(u) for u in host_geo.columns["uv1"]]
        shaped.normals = kreshape.recompute_vertex_normals(moved, shaped.faces)
        geo, report = build_replacement(
            layout, node, shaped, influences=host_geo.influences or None
        )
        print("reshaped onto the host's topology")
    else:
        geo, report = build_replacement(layout, node, mesh)
        if node.is_skin:
            print(f"weights transferred from the host's {len(host_positions)} "
                  f"vertices onto the pack's {mesh.vertex_count}")

    mdl, mdx = ke.replace_geometry(
        layout, node, geo, texture=pack.texture_resref
    )

    if args.hide is not None:
        from . import parts as kparts
        from . import visibility as kvis

        after = kl2.parse(mdl, mdx)
        if args.hide:
            wanted = list(args.hide)
        else:
            # Everything visible except the node we just replaced. These are
            # shaped for the face that is gone, so they float.
            wanted = [n.name for n in kparts.mesh_nodes(after)
                      if n.name.lower() != node.name.lower()]
        mdl, hidden = kvis.hide_nodes(after, mdl, wanted)
        if hidden:
            print(f"hidden (host parts that no longer fit): {', '.join(hidden)}")
    if not kv.check(kl2.parse(mdl, mdx)).ok:
        print("kmdlfun: result failed validation; nothing written", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{args.host}.mdl").write_bytes(mdl)
    (out / f"{args.host}.mdx").write_bytes(mdx)
    if pack.texture_path:
        import shutil

        shutil.copy2(pack.texture_path, out / pack.texture_path.name)
    for line in report.lines():
        print("  " + line)
    print(f"wrote {out / args.host}.mdl, .mdx"
          + (f" and {pack.texture_path.name}" if pack.texture_path else ""))
    print("Copy them into Override. A successful build is not proof.")
    return 0


def _fit_mesh(mesh, pack, layout, node):
    """Orient, scale and place a foreign mesh onto a node.

    Nothing outside KOTOR knows what scale or origin a head node uses, so a raw
    export always needs this. The pack's hints say which way it was authored;
    the node's own geometry says where it has to end up.
    """
    from kmdlswap import edit as ke

    from . import headgen

    host = ke.extract(layout, node)
    hlo = [min(p[i] for p in host.positions) for i in range(3)]
    hhi = [max(p[i] for p in host.positions) for i in range(3)]
    size = [hhi[i] - hlo[i] for i in range(3)]
    centre = [(hhi[i] + hlo[i]) / 2 for i in range(3)]

    positions = headgen.orient(mesh.positions, facing=pack.facing, up=pack.up)
    if pack.scale != 1.0:
        size = [s * pack.scale for s in size]
    positions = headgen.fit_to(positions, size, centre, anchor=pack.anchor)

    before = mesh.positions
    mesh.positions = positions
    mesh.normals = headgen.vertex_normals(positions, mesh.faces) if mesh.normals else []
    b_lo = [min(p[i] for p in before) for i in range(3)]
    b_hi = [max(p[i] for p in before) for i in range(3)]
    a_lo = [min(p[i] for p in positions) for i in range(3)]
    a_hi = [max(p[i] for p in positions) for i in range(3)]
    fmt = lambda s: "x".join(f"{c:.3f}" for c in s)  # noqa: E731
    print(f"  fitted: {fmt([b_hi[i]-b_lo[i] for i in range(3)])} -> "
          f"{fmt([a_hi[i]-a_lo[i] for i in range(3)])}"
          f"   facing {pack.facing}, up {pack.up}, anchor {pack.anchor}")
    return mesh
