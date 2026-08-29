"""Tkinter desktop app for kmdlfun.

Tkinter ships with Python, so the app adds no dependency. It drives exactly the
same library the CLI does - nothing here reimplements the geometry work.

The build runs on a worker thread so the window stays responsive; Tk is not
thread-safe, so the worker only posts messages to a queue that the UI drains on
a timer.
"""

from __future__ import annotations

import queue
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import effects as keffects
from . import roster
from .library import build

DEFAULT_INSTALLS = [
    r"E:\SteamLibrary\steamapps\common\swkotor",
    r"C:\Program Files (x86)\Steam\steamapps\common\swkotor",
    r"C:\GOG Games\Star Wars - KotOR",
]


def guess_install() -> str:
    for p in DEFAULT_INSTALLS:
        if (Path(p) / "chitin.key").is_file():
            return p
    return ""


class App(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master, padding=12)
        self.grid(sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        self.events: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None

        self._build_paths()
        self._build_effect()
        self._build_companions()
        self._build_log()
        self._build_actions()

        self.after(100, self._drain)
        self._on_effect_change()

    # ---- sections ---------------------------------------------------------

    def _build_paths(self):
        box = ttk.LabelFrame(self, text="Folders", padding=8)
        box.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        box.columnconfigure(1, weight=1)

        ttk.Label(box, text="KOTOR install").grid(row=0, column=0, sticky="w")
        self.install = tk.StringVar(value=guess_install())
        ttk.Entry(box, textvariable=self.install).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(box, text="Browse", command=self._pick_install).grid(row=0, column=2)

        ttk.Label(box, text="Output folder").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.out_dir = tk.StringVar(value=str(Path.cwd() / "out_fun"))
        ttk.Entry(box, textvariable=self.out_dir).grid(
            row=1, column=1, sticky="ew", padx=6, pady=(6, 0)
        )
        ttk.Button(box, text="Browse", command=self._pick_out).grid(
            row=1, column=2, pady=(6, 0)
        )
        ttk.Label(
            box,
            text="Nothing is ever written into the game install. Copy results into Override yourself.",
            foreground="#666",
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))

    def _build_effect(self):
        box = ttk.LabelFrame(self, text="Effect", padding=8)
        box.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        box.columnconfigure(1, weight=1)

        self.effect = tk.StringVar(value=keffects.EFFECTS[0].key)
        row = ttk.Frame(box)
        row.grid(row=0, column=0, columnspan=3, sticky="w")
        for e in keffects.EFFECTS:
            ttk.Radiobutton(
                row, text=e.label, value=e.key, variable=self.effect,
                command=self._on_effect_change,
            ).pack(side="left", padx=(0, 10))

        self.effect_desc = ttk.Label(box, text="", wraplength=560, foreground="#333")
        self.effect_desc.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.effect_caution = ttk.Label(box, text="", wraplength=560, foreground="#a35")
        self.effect_caution.grid(row=2, column=0, columnspan=3, sticky="w")

        ttk.Label(box, text="Intensity").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.intensity = tk.DoubleVar(value=1.0)
        ttk.Scale(
            box, from_=0.1, to=2.0, variable=self.intensity, orient="horizontal",
            command=lambda _=None: self._on_effect_change(),
        ).grid(row=3, column=1, sticky="ew", padx=6, pady=(8, 0))
        self.intensity_label = ttk.Label(box, text="1.00x", width=8)
        self.intensity_label.grid(row=3, column=2, sticky="w", pady=(8, 0))

    def _build_companions(self):
        box = ttk.LabelFrame(self, text="Companions", padding=8)
        box.grid(row=2, column=0, sticky="ew", pady=(0, 8))

        self.selected: dict[str, tk.BooleanVar] = {}
        grid = ttk.Frame(box)
        grid.pack(fill="x")
        for i, c in enumerate(roster.COMPANIONS):
            var = tk.BooleanVar(value=True)
            self.selected[c.key] = var
            ttk.Checkbutton(grid, text=c.name, variable=var).grid(
                row=i // 3, column=i % 3, sticky="w", padx=(0, 16)
            )
        btns = ttk.Frame(box)
        btns.pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="All", command=lambda: self._set_all(True)).pack(side="left")
        ttk.Button(btns, text="None", command=lambda: self._set_all(False)).pack(
            side="left", padx=6
        )

    def _build_log(self):
        box = ttk.LabelFrame(self, text="Log", padding=8)
        box.grid(row=3, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        self.log = tk.Text(box, height=12, wrap="word", state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(box, command=self.log.yview)
        bar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=bar.set)

    def _build_actions(self):
        row = ttk.Frame(self)
        row.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        row.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(row, mode="determinate")
        self.progress.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.build_btn = ttk.Button(row, text="Build", command=self._start)
        self.build_btn.grid(row=0, column=1)
        ttk.Button(row, text="Open output", command=self._open_out).grid(
            row=0, column=2, padx=(6, 0)
        )

    # ---- behaviour --------------------------------------------------------

    def _set_all(self, value: bool):
        for var in self.selected.values():
            var.set(value)

    def _pick_install(self):
        d = filedialog.askdirectory(title="Select the KOTOR install folder")
        if d:
            self.install.set(d)

    def _pick_out(self):
        d = filedialog.askdirectory(title="Select an output folder")
        if d:
            self.out_dir.set(d)

    def _open_out(self):
        import os
        import subprocess

        d = Path(self.out_dir.get())
        if not d.is_dir():
            messagebox.showinfo("kmdlfun", "Nothing built yet.")
            return
        if os.name == "nt":
            os.startfile(d)  # noqa: S606
        else:
            subprocess.run(["xdg-open", str(d)], check=False)

    def _on_effect_change(self):
        e = keffects.resolve(self.effect.get())
        scales = e.scaled(self.intensity.get())
        detail = ", ".join(f"{k} x{v:.2f}" for k, v in scales.items())
        self.effect_desc.config(text=f"{e.description}\nScales: {detail}")
        self.effect_caution.config(text=e.caution)
        self.intensity_label.config(text=f"{self.intensity.get():.2f}x")

    def _say(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _start(self):
        if self.worker and self.worker.is_alive():
            return
        install = self.install.get().strip()
        if not (Path(install) / "chitin.key").is_file():
            messagebox.showerror(
                "kmdlfun",
                "That folder does not look like a KOTOR install "
                "(no chitin.key inside it).",
            )
            return
        keys = [k for k, v in self.selected.items() if v.get()]
        if not keys:
            messagebox.showinfo("kmdlfun", "Pick at least one companion.")
            return

        self.build_btn.config(state="disabled")
        self.progress.config(value=0, maximum=100)
        effect = keffects.resolve(self.effect.get())
        self._say(f"\n=== {effect.label} @ {self.intensity.get():.2f}x ===")

        args = (install, self.effect.get(), keys, self.out_dir.get(), self.intensity.get())
        self.worker = threading.Thread(target=self._work, args=args, daemon=True)
        self.worker.start()

    def _work(self, install, effect_key, keys, out_dir, intensity):
        def progress(i, total, label):
            self.events.put(("progress", (i, total, label)))

        try:
            report = build(
                install, effect_key, keys, out_dir,
                intensity=intensity, progress=progress,
            )
            self.events.put(("done", report))
        except Exception as exc:  # noqa: BLE001
            self.events.put(("error", f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}"))

    def _drain(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "progress":
                    i, total, label = payload
                    self.progress.config(value=100 * i / max(total, 1))
                    if label != "done":
                        self._say(f"  [{i + 1}/{total}] {label}")
                elif kind == "done":
                    self._finish(payload)
                elif kind == "error":
                    self._say("ERROR: " + payload)
                    self.build_btn.config(state="normal")
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def _finish(self, report):
        self.progress.config(value=100)
        self.build_btn.config(state="normal")
        self._say(f"\nWrote {report.written} model(s), {report.total_nodes} node(s) changed.")
        if report.missing:
            self._say("Not in this install: " + ", ".join(report.missing))
        for m in report.failed:
            self._say(f"FAILED {m.model}: {m.error}")
        for m in report.models:
            for s in m.skipped[:3]:
                self._say(f"skipped {m.model}: {s}")
        self._say(f"Output: {report.out_dir}")
        self._say("Copy the .mdl/.mdx files into the game's Override folder.")
        self._say("A successful build is not proof - check it in-game.")


def run() -> int:
    root = tk.Tk()
    root.title("kmdlfun - KOTOR companion effects")
    root.geometry("640x720")
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
