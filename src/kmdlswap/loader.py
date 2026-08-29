"""Getting an MDL/MDX pair in, from either loose files or a game install.

Never writes into the install. Reads only.
"""

from __future__ import annotations

from pathlib import Path

from .layout import Layout, parse


def load_files(mdl_path: str | Path) -> Layout:
    """Load a loose ``.mdl`` and its sibling ``.mdx``."""
    mdl_path = Path(mdl_path)
    mdx_path = mdl_path.with_suffix(".mdx")
    if not mdl_path.is_file():
        raise FileNotFoundError(mdl_path)
    if not mdx_path.is_file():
        raise FileNotFoundError(f"{mdx_path} (an MDL is useless without its MDX)")
    return parse(mdl_path.read_bytes(), mdx_path.read_bytes())


def load_from_install(install: str | Path, resname: str) -> Layout:
    """Load a model by resource name out of a game install's BIFs."""
    from pykotor.extract.installation import Installation
    from pykotor.resource.type import ResourceType

    inst = Installation(str(install))
    want = resname.lower()
    found: dict[ResourceType, bytes] = {}
    for r in inst.chitin_resources():
        if r.resname().lower() == want and r.restype() in (ResourceType.MDL, ResourceType.MDX):
            found[r.restype()] = r.data()
    if ResourceType.MDL not in found:
        raise KeyError(f"no model named {resname!r} in {install}")
    if ResourceType.MDX not in found:
        raise KeyError(f"{resname!r} has no MDX")
    return parse(found[ResourceType.MDL], found[ResourceType.MDX])


def load(target: str, install: str | Path | None = None) -> Layout:
    """Load by path, or by resource name when ``install`` is given."""
    if install and not target.lower().endswith(".mdl"):
        return load_from_install(install, target)
    return load_files(target)
