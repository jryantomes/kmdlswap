"""Shared fixtures. The vanilla K1 install is the corpus AND the oracle, so the
tests run against real game data rather than synthetic fixtures."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Override with KOTOR1_PATH if the install lives elsewhere.
DEFAULT_INSTALLS = [
    r"E:\SteamLibrary\steamapps\common\swkotor",
    r"C:\Program Files (x86)\Steam\steamapps\common\swkotor",
    r"C:\GOG Games\Star Wars - KotOR",
]


def find_install() -> Path | None:
    candidates = [os.environ["KOTOR1_PATH"]] if "KOTOR1_PATH" in os.environ else DEFAULT_INSTALLS
    for c in candidates:
        p = Path(c)
        if (p / "chitin.key").is_file():
            return p
    return None


@pytest.fixture(scope="session")
def install_path() -> Path:
    p = find_install()
    if p is None:
        pytest.skip("no vanilla K1 install found (set KOTOR1_PATH)")
    return p


@pytest.fixture(scope="session")
def resources(install_path: Path) -> dict:
    from pykotor.extract.installation import Installation
    from pykotor.resource.type import ResourceType

    inst = Installation(str(install_path))
    index: dict[str, dict] = {}
    for r in inst.chitin_resources():
        if r.restype() in (ResourceType.MDL, ResourceType.MDX):
            index.setdefault(r.resname().lower(), {})[r.restype().extension] = r
    return {k: v for k, v in index.items() if "mdl" in v and "mdx" in v}


@pytest.fixture(scope="session")
def pair(resources):
    def _get(name: str) -> tuple[bytes, bytes]:
        entry = resources[name.lower()]
        return entry["mdl"].data(), entry["mdx"].data()

    return _get
