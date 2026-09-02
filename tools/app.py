"""The entry point a bundled build starts from.

A one-line launcher rather than pointing the bundler at `kmdlfun/gui.py`
directly, because a frozen app has no console: anything that reaches stderr
before the window exists is lost, and the app looks like it silently failed to
start. So the import happens inside a guard that can still put a message
somewhere a person will find it.
"""

from __future__ import annotations

import sys
import traceback


def selftest() -> int:
    """Prove the bundled app can actually do the work, not merely start.

    A frozen build fails at *runtime*, not at build time: anything resolved by
    name rather than imported by name is invisible to the bundler's analysis,
    and pykotor picks its format readers by resource type. So this exercises
    one of each risky thing and writes the result somewhere findable, because
    a windowed app has no console to print to.
    """
    from pathlib import Path

    lines = []
    ok = True

    def check(what, fn):
        nonlocal ok
        try:
            lines.append(f"[ok  ] {what}: {fn()}")
        except Exception as exc:                        # noqa: BLE001
            ok = False
            lines.append(f"[FAIL] {what}: {type(exc).__name__}: {exc}")

    check("numpy", lambda: __import__("numpy").__version__)
    check("Pillow", lambda: __import__("PIL").__version__)
    check("tkinter", lambda: __import__("tkinter").TkVersion)

    def two_da():
        from pykotor.resource.formats.twoda import TwoDA, bytes_2da, read_2da
        table = TwoDA(["label"])
        table.add_row("0", {"label": "x"})
        return f"{read_2da(bytes_2da(table)).get_height()} row round-trip"

    def gff():
        from pykotor.resource.formats.gff import GFF, bytes_gff, read_gff
        g = GFF()
        g.root.set_string("Tag", "x")
        return f"{read_gff(bytes_gff(g)).root.value('Tag')!r} round-trip"

    def lip():
        from pykotor.resource.formats.lip import LIP, bytes_lip, read_lip
        return f"{read_lip(bytes_lip(LIP())).length} length round-trip"

    check("pykotor 2da", two_da)
    check("pykotor gff", gff)
    check("pykotor lip", lip)
    check("our own reader", lambda: __import__(
        "kmdlswap.layout", fromlist=["parse"]).parse.__name__)
    check("jade reader", lambda: __import__(
        "kmdlfun.jade", fromlist=["catalogue"]).SCALE)
    check("finding games", lambda: ", ".join(
        f"{k}" for k in __import__(
            "kmdlfun.installs", fromlist=["detect"]).detect().paths) or "none")

    report = "\n".join(lines)
    out = Path(sys.executable).parent / "kmdlfun-selftest.txt"
    try:
        out.write_text(report + "\n", encoding="utf-8")
    except OSError:
        pass
    print(report)
    return 0 if ok else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    try:
        from kmdlfun.gui import run

        return run()
    except Exception:                                   # noqa: BLE001
        report = traceback.format_exc()
        try:
            import tkinter as tk
            from tkinter import scrolledtext

            root = tk.Tk()
            root.title("kmdlfun could not start")
            root.geometry("760x420")
            box = scrolledtext.ScrolledText(root, wrap="word")
            box.pack(fill="both", expand=True)
            box.insert("1.0", "kmdlfun could not start.\n\n" + report)
            box.configure(state="disabled")
            root.mainloop()
        except Exception:                               # noqa: BLE001
            # No Tk either. A frozen app has no console, so leave the trace
            # beside the executable rather than nowhere.
            from pathlib import Path

            crash = Path(sys.executable).parent / "kmdlfun-crash.txt"
            try:
                crash.write_text(report, encoding="utf-8")
            except OSError:
                pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
