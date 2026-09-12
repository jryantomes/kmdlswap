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

# KOTOR 2 is a *reading* capability - a source of donors. Nothing writes a K2
# file. Override with KOTOR2_PATH.
K2_INSTALLS = [
    r"E:\SteamLibrary\steamapps\common\Knights of the Old Republic II",
    r"C:\Program Files (x86)\Steam\steamapps\common\Knights of the Old Republic II",
    r"C:\GOG Games\Star Wars - KotOR2",
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


# Neverwinter Nights is a *reading* capability too - a source of heads and
# props. Nothing writes an NWN file. Override with NWN_PATH.
NWN_INSTALLS = [
    r"E:\SteamLibrary\steamapps\common\Neverwinter Nights",
    r"C:\Program Files (x86)\Steam\steamapps\common\Neverwinter Nights",
    r"C:\GOG Games\Neverwinter Nights Enhanced Edition",
]


def find_nwn() -> Path | None:
    for c in [os.environ["NWN_PATH"]] if "NWN_PATH" in os.environ else NWN_INSTALLS:
        p = Path(c)
        if (p / "data" / "nwn_base.key").is_file() or (p / "nwn_base.key").is_file():
            return p
    return None


@pytest.fixture(scope="session")
def nwn_path() -> Path:
    p = find_nwn()
    if p is None:
        pytest.skip("no Neverwinter Nights install found (set NWN_PATH)")
    return p


@pytest.fixture(scope="session")
def nwn_index(nwn_path) -> dict:
    """The install's resource index, read once - it lists 113,483 resources."""
    from kmdlfun import nwn

    return nwn.index_of(str(nwn_path))


# The Old Republic is a *reading* capability too - a source of heads. Nothing
# writes one of its files. Override with SWTOR_PATH.
SWTOR_INSTALLS = [
    r"E:\SteamLibrary\steamapps\common\Star Wars - The Old Republic",
    r"C:\Program Files (x86)\Steam\steamapps\common\Star Wars - The Old Republic",
    r"C:\Program Files (x86)\Electronic Arts\Star Wars - The Old Republic",
]


def find_swtor() -> Path | None:
    for c in [os.environ["SWTOR_PATH"]] if "SWTOR_PATH" in os.environ else SWTOR_INSTALLS:
        p = Path(c)
        if (p / "Assets" / "swtor_main_global_1.tor").is_file():
            return p
    return None


@pytest.fixture(scope="session")
def swtor_path() -> Path:
    p = find_swtor()
    if p is None:
        pytest.skip("no Old Republic install found (set SWTOR_PATH)")
    return p


@pytest.fixture(scope="session")
def swtor_heads(swtor_path) -> list:
    """The head archive's index, read once - the scan costs four seconds."""
    from kmdlfun import swtor

    return swtor.index_of(str(swtor_path))


@pytest.fixture(scope="session")
def swtor_head(swtor_heads):
    """One human head, by name, so a test does not depend on scan order."""
    from kmdlfun import swtor

    wanted = "head_human_bmn_caucasian_a01"
    for entry in swtor_heads:
        if entry.name == wanted:
            return entry
    pytest.skip(f"{wanted} is not in this install")
    return None                     # unreachable; keeps the type honest


def find_k2() -> Path | None:
    for c in [os.environ["KOTOR2_PATH"]] if "KOTOR2_PATH" in os.environ else K2_INSTALLS:
        p = Path(c)
        if (p / "chitin.key").is_file():
            return p
    return None


@pytest.fixture(scope="session")
def k2_path() -> Path:
    p = find_k2()
    if p is None:
        pytest.skip("no KOTOR 2 install found (set KOTOR2_PATH)")
    return p


@pytest.fixture(scope="session")
def k2(k2_path):
    from kmdlfun.library import ModelLibrary

    return ModelLibrary(str(k2_path))
