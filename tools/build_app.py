"""Build the standalone app.

    python tools/build_app.py

Produces `dist/kmdlfun/`, a folder somebody can copy to a machine with no
Python on it at all. About 76 MB, or 30-something zipped.

It is a folder rather than a single file on purpose. A one-file build unpacks
itself into a temporary directory on every launch, and with numpy and Tk inside
that is several seconds of nothing visible happening - which reads as a hang,
and is the first thing a person would report as a bug.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist" / "kmdlfun"


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed. Add it with:\n"
              r"    .\.venv\Scripts\python.exe -m pip install pyinstaller",
              file=sys.stderr)
        return 1

    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(ROOT / "kmdlfun.spec"),
         "--noconfirm", "--distpath", str(ROOT / "dist"),
         "--workpath", str(ROOT / "build")],
        cwd=ROOT,
    )
    if result.returncode:
        return result.returncode

    exe = DIST / "kmdlfun.exe"
    if not exe.is_file():
        print(f"the build finished but {exe} is not there", file=sys.stderr)
        return 1

    # A bundled app fails at *runtime*, not at build time: anything resolved by
    # name rather than imported by name is invisible to the analysis. Proving
    # it here is the difference between shipping and finding out later.
    print("\nself-testing the build...")
    check = subprocess.run([str(exe), "--selftest"], cwd=DIST,
                           capture_output=True, text=True)
    print(check.stdout or check.stderr)
    if check.returncode:
        print("the build starts but cannot do the work - see above",
              file=sys.stderr)
        return 1

    size = sum(f.stat().st_size for f in DIST.rglob("*") if f.is_file())
    print(f"built {DIST}  ({size / 1_000_000:.0f} MB)")
    print("Zip that folder to hand it to somebody. They need nothing else.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
