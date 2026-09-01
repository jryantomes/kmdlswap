"""A `.glb` from anywhere, turned into a head pack this tool can build.

This is the route in for geometry the game never had - a sculpt, a photo scan,
a generated head, or something pulled out of another engine through Blender.
Confirmed in game: a Tripo-generated head on Carth turns with the neck and
opens its mouth.

The pack it writes is a folder, not a model: an `.obj`, its texture, and a
manifest saying which way is up. Nothing is decided about a host here, because
the same pack goes onto different bodies and the fitting belongs to the build.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# glTF is Y-up with -Z forward; after the Y-up conversion that lands on +Y,
# which is where KOTOR characters look.
UP = "y"
FACING = "+y"
DEFAULT_TEXTURE = 512
RESREF_STEM = 14         # the field is 16 and the suffix takes two


class ImportError_(RuntimeError):
    """Named with a trailing underscore so it cannot shadow the builtin."""


@dataclass
class Imported:
    """What came out of the file, and what was made of it."""

    pack: Path
    vertices: int = 0
    triangles: int = 0
    has_normals: bool = False
    has_uvs: bool = False
    texture: str | None = None
    texture_note: str = ""
    notes: list[str] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)


def has_alpha(img) -> bool:
    """Does this image carry anything in its alpha channel worth keeping?

    Dropping alpha is what cost a ported Quarren its eyes, so a texture that
    has one is written out as 32-bit. An all-opaque channel carries nothing and
    is not worth the extra bytes.
    """
    if img.mode not in ("RGBA", "LA", "PA") and "transparency" not in img.info:
        return False
    lo, _ = img.convert("RGBA").getchannel("A").getextrema()
    return lo < 255


def run(file, out, *, name: str | None = None,
        texture_size: int = DEFAULT_TEXTURE) -> Imported:
    """Read `file` and write a head pack folder at `out`."""
    import json

    from kmdlswap import obj as kobj

    from . import gltf, headpack

    source = Path(file)
    if not source.is_file():
        raise ImportError_(f"no such file: {source}")
    try:
        mesh = gltf.read_glb(source)
    except gltf.GltfError as exc:
        raise ImportError_(str(exc)) from exc

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    result = Imported(
        pack=out,
        vertices=len(mesh.positions),
        triangles=len(mesh.faces),
        has_normals=bool(mesh.normals),
        has_uvs=bool(mesh.uvs),
        notes=list(mesh.notes),
    )

    kobj.write_obj(
        out / "head.obj", mesh.positions, mesh.faces,
        uvs=mesh.uvs or None, normals=mesh.normals or None, name=out.name,
    )
    result.files.append(out / "head.obj")

    if mesh.image:
        result.texture, result.texture_note = _write_texture(
            mesh, out, texture_size)
        if result.texture:
            result.files.append(out / f"{result.texture}.tga")

    headpack.write_template(out, name=name or out.name)
    manifest = out / headpack.MANIFEST_NAME
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["up"] = UP
    data["facing"] = FACING
    data["notes"] = f"imported from {source.name}"
    manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    result.files.append(manifest)

    return result


def _write_texture(mesh, out: Path, size: int) -> tuple[str | None, str]:
    try:
        from PIL import Image
    except ImportError:
        return None, "Pillow is not installed, so the texture was not converted"

    import io

    note = ""
    with Image.open(io.BytesIO(mesh.image)) as img:
        img = img.convert("RGBA" if has_alpha(img) else "RGB")
        if size and img.size != (size, size):
            note = f"{img.size[0]}x{img.size[1]} -> {size}x{size}"
            img = img.resize((size, size), Image.LANCZOS)
        # The resref is the filename, and it has to fit a 16-character field,
        # so keep it short and predictable.
        name = out.name.lower()[:RESREF_STEM] + "01"
        img.save(out / f"{name}.tga")
    return name, note


def summarise(result: Imported, source) -> list[str]:
    """The same account for the terminal and the window."""
    source = Path(source)
    out = [
        f"{source.name}",
        f"  vertices  {result.vertices}",
        f"  triangles {result.triangles}",
        f"  normals   {'yes' if result.has_normals else 'no (will be computed)'}",
        f"  uvs       {'yes' if result.has_uvs else 'NO - the head will be untextured'}",
    ]
    if result.texture:
        out.append(f"  texture   {result.texture}.tga"
                   + (f"  ({result.texture_note})" if result.texture_note else ""))
    elif result.texture_note:
        out.append(f"  texture   {result.texture_note}")
    else:
        out.append("  texture   none embedded")
    out.extend(f"  note: {n}" for n in result.notes)
    out.append(f"\nwrote a head pack to {result.pack}")
    return out
