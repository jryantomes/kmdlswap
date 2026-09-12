"""Answers about a whole install, kept between launches.

Three questions cost real time to answer, and all three are asked before the
window can offer a list to pick from:

  * which models are heads, bodies or neither (`library.classify`),
  * who each model looks like (`who.looks`),
  * which models are droids and what parts they carry (`droidbuild.catalogue`).

Each one has to open and parse thousands of models, because none of it can be
told from a name. On this machine's KOTOR that is about four seconds, two
seconds and twelve seconds - and until now every one of them was paid again on
every launch, and some of them on every click.

The answers only change when the install does, and the tool never writes into
an install. So they go on disk under a fingerprint of the folder, and a second
launch reads them back in a millisecond. A fingerprint that does not match is
simply a miss: the file is rewritten and nothing has to be migrated, which is
the same bargain `prefs.py` makes.

Everything stored here is plain JSON - lists, strings and dicts of them - so a
survey that wants to keep a set has to hand over something JSON can hold.
`sets` and `unsets` do that round trip for the droid catalogue, which is the
one caller that keeps sets.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

HOME = Path.home() / ".kmdlfun" / "surveys"

# What the fingerprint looks at. `chitin.key` changes if the packs are
# repacked, and Override is where a mod puts a model or a table that changes
# what any of these scans would say.
_KEY = "chitin.key"
_OVERRIDE = "Override"


def stamp(install) -> str:
    """A short string that changes when the install does.

    Not a hash of every file: an install is several gigabytes and this has to
    be cheap enough to do before deciding whether the cache is worth reading.
    The key file's size and date, and the Override folder's date and count,
    catch the two things that actually change what a scan finds.
    """
    root = Path(install)
    bits: list[str] = []
    try:
        st = (root / _KEY).stat()
        bits.append(f"{st.st_size}:{int(st.st_mtime)}")
    except OSError:
        bits.append("no-key")
    over = root / _OVERRIDE
    try:
        names = sorted(p.name.lower() for p in over.iterdir())
        bits.append(f"{len(names)}:{int(over.stat().st_mtime)}")
        bits.append(hashlib.sha1(  # noqa: S324 - naming a folder, not a secret
            "\n".join(names).encode("utf-8")).hexdigest()[:12])
    except OSError:
        bits.append("no-override")
    return "|".join(bits)


def _file(install) -> Path:
    """One file per install, named after the path so two games do not collide.

    Hashed rather than sanitised: a Windows path has a colon and backslashes in
    it, and a readable-but-mangled name is one collision away from serving
    KOTOR II's models as KOTOR's.
    """
    digest = hashlib.sha1(  # noqa: S324 - naming a file, not a secret
        str(Path(install)).lower().encode("utf-8")).hexdigest()[:16]
    return HOME / f"{digest}.json"


def _read(install) -> dict:
    try:
        found = json.loads(_file(install).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(found, dict) or found.get("stamp") != stamp(install):
        return {}                    # the install moved on; start again
    kept = found.get("surveys")
    return kept if isinstance(kept, dict) else {}


def recall(install, name: str):
    """What was worked out last time, or None if it has to be worked out."""
    return _read(install).get(name)


def remember(install, name: str, value) -> None:
    """Keep one answer. A cache that cannot be written is not an error - the
    app still works, it is just slow, and failing to start over a read-only
    home folder would be a worse trade."""
    kept = _read(install)
    kept[name] = value
    try:
        HOME.mkdir(parents=True, exist_ok=True)
        _file(install).write_text(
            json.dumps({"install": str(install), "stamp": stamp(install),
                        "surveys": kept}),
            encoding="utf-8")
    except (OSError, TypeError, ValueError):
        return


def cached(install, name: str, work, *, to_disk=None, from_disk=None):
    """`work()`, unless the same question was already answered for this install.

    `to_disk` and `from_disk` convert between what the caller wants and what
    JSON can hold; without them the value is stored as it is.
    """
    found = recall(install, name)
    if found is not None:
        return from_disk(found) if from_disk else found
    made = work()
    remember(install, name, to_disk(made) if to_disk else made)
    return made


def sets(value: dict) -> dict:
    """`{name: {"head", "torso"}}` as something JSON can hold."""
    return {k: sorted(v) for k, v in value.items()}


def unsets(value: dict) -> dict:
    """The other way back."""
    return {k: set(v) for k, v in value.items()}


def forget(install=None) -> None:
    """Throw the answers away, for an install or for every one of them."""
    if install is not None:
        _file(install).unlink(missing_ok=True)
        return
    for path in HOME.glob("*.json"):
        path.unlink(missing_ok=True)
