"""OBJ import and export for a single mesh node.

OBJ is the simplest interchange format that carries what a KOTOR mesh needs:
positions, texture coordinates, normals and triangles.

Two mismatches have to be handled explicitly:

* **Index streams.** OBJ lets a face reference position, UV and normal by
  independent indices. The MDX has one index stream, so a vertex is defined by
  the *combination*. On import, each distinct ``v/vt/vn`` triple becomes one
  vertex; this is what splits vertices along UV seams, exactly as vanilla meshes
  already are.
* **Coordinates.** Values are written and read verbatim, with no axis or UV
  flip. A mesh exported by this tool and re-imported is therefore unchanged.
  Anything authored elsewhere must already be in KOTOR's space (Z up), which
  ``kmdlswap replace`` reports on so a mistake is visible rather than silent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


class ObjError(Exception):
    pass


@dataclass
class ObjMesh:
    name: str = "mesh"
    positions: list[tuple[float, float, float]] = field(default_factory=list)
    uvs: list[tuple[float, float]] = field(default_factory=list)
    normals: list[tuple[float, float, float]] = field(default_factory=list)
    faces: list[tuple[int, int, int]] = field(default_factory=list)
    # Optional per-face material values. An OBJ cannot express them, but a
    # transplant from another model can carry the donor's across, and vanilla
    # meshes vary them face to face.
    materials: list[int] = field(default_factory=list)

    @property
    def vertex_count(self) -> int:
        return len(self.positions)

    @property
    def has_uvs(self) -> bool:
        return len(self.uvs) == len(self.positions)

    @property
    def has_normals(self) -> bool:
        return len(self.normals) == len(self.positions)


def write_obj(
    path: str | Path,
    positions: list[tuple[float, ...]],
    faces: list[tuple[int, int, int]],
    uvs: list[tuple[float, ...]] | None = None,
    normals: list[tuple[float, ...]] | None = None,
    name: str = "mesh",
) -> None:
    lines = [
        "# exported by kmdlswap",
        "# KOTOR coordinates, written verbatim: no axis or UV flip is applied.",
        f"o {name}",
    ]
    # 9 significant digits round-trips a float32 exactly, so extract -> replace
    # does not quietly move vertices.
    for p in positions:
        lines.append(f"v {p[0]:.9g} {p[1]:.9g} {p[2]:.9g}")
    if uvs:
        for t in uvs:
            lines.append(f"vt {t[0]:.9g} {t[1]:.9g}")
    if normals:
        for n in normals:
            lines.append(f"vn {n[0]:.9g} {n[1]:.9g} {n[2]:.9g}")

    for f in faces:
        parts = []
        for vi in f:
            i = vi + 1  # OBJ is 1-indexed
            if uvs and normals:
                parts.append(f"{i}/{i}/{i}")
            elif uvs:
                parts.append(f"{i}/{i}")
            elif normals:
                parts.append(f"{i}//{i}")
            else:
                parts.append(str(i))
        lines.append("f " + " ".join(parts))

    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parse_ref(token: str) -> tuple[int, int | None, int | None]:
    bits = token.split("/")
    v = int(bits[0])
    vt = int(bits[1]) if len(bits) > 1 and bits[1] else None
    vn = int(bits[2]) if len(bits) > 2 and bits[2] else None
    return v, vt, vn


def _resolve(index: int, count: int, kind: str, line_no: int) -> int:
    """OBJ indices are 1-based, and may be negative (relative to the end)."""
    if index > 0:
        resolved = index - 1
    elif index < 0:
        resolved = count + index
    else:
        raise ObjError(f"line {line_no}: {kind} index 0 is not valid in OBJ")
    if not 0 <= resolved < count:
        raise ObjError(f"line {line_no}: {kind} index {index} out of range (have {count})")
    return resolved


def read_obj(path: str | Path) -> ObjMesh:
    """Read an OBJ, welding each distinct v/vt/vn triple into one vertex."""
    raw_v: list[tuple[float, float, float]] = []
    raw_vt: list[tuple[float, float]] = []
    raw_vn: list[tuple[float, float, float]] = []
    mesh = ObjMesh(name=Path(path).stem)

    combined: dict[tuple[int, int | None, int | None], int] = {}

    def vertex_for(ref, line_no: int) -> int:
        if ref in combined:
            return combined[ref]
        v, vt, vn = ref
        idx = len(mesh.positions)
        mesh.positions.append(raw_v[_resolve(v, len(raw_v), "vertex", line_no)])
        if vt is not None:
            mesh.uvs.append(raw_vt[_resolve(vt, len(raw_vt), "texcoord", line_no)])
        if vn is not None:
            mesh.normals.append(raw_vn[_resolve(vn, len(raw_vn), "normal", line_no)])
        combined[ref] = idx
        return idx

    for line_no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tag, _, rest = line.partition(" ")
        rest = rest.strip()
        if tag == "v":
            vals = [float(x) for x in rest.split()[:3]]
            raw_v.append((vals[0], vals[1], vals[2]))
        elif tag == "vt":
            vals = [float(x) for x in rest.split()[:2]]
            raw_vt.append((vals[0], vals[1] if len(vals) > 1 else 0.0))
        elif tag == "vn":
            vals = [float(x) for x in rest.split()[:3]]
            raw_vn.append((vals[0], vals[1], vals[2]))
        elif tag == "o" and rest:
            mesh.name = rest
        elif tag == "f":
            refs = [_parse_ref(t) for t in rest.split()]
            if len(refs) < 3:
                raise ObjError(f"line {line_no}: face with {len(refs)} vertices")
            corner = [vertex_for(r, line_no) for r in refs]
            # Fan-triangulate any polygon. Vanilla meshes are triangles already.
            for i in range(1, len(corner) - 1):
                mesh.faces.append((corner[0], corner[i], corner[i + 1]))

    if not mesh.positions:
        raise ObjError(f"{path}: no vertices found")
    if not mesh.faces:
        raise ObjError(f"{path}: no faces found")
    if mesh.uvs and not mesh.has_uvs:
        raise ObjError(f"{path}: some faces carry texture coordinates and some do not")
    if mesh.normals and not mesh.has_normals:
        raise ObjError(f"{path}: some faces carry normals and some do not")
    return mesh
