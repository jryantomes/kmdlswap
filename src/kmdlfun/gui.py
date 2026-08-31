"""Tkinter desktop app for kmdlfun.

Tkinter ships with Python, so the app adds no dependency. It drives the same
library the CLI does - nothing here reimplements the geometry work.

Two tabs, because there are two genuinely different jobs: applying an effect to
whole companions, and moving one model's parts into another. They share the
folder settings, the log and the build button, since those are the same in both
cases.

Work runs on a worker thread so the window stays responsive; Tk is not
thread-safe, so the worker only posts messages to a queue the UI drains on a
timer.
"""

from __future__ import annotations

import queue
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import effects as keffects
from . import roster
from . import viewport as kviewport
from .library import build

DEFAULT_INSTALLS = [
    r"E:\SteamLibrary\steamapps\common\swkotor",
    r"C:\Program Files (x86)\Steam\steamapps\common\swkotor",
    r"C:\GOG Games\Star Wars - KotOR",
]


@dataclass(frozen=True)
class TransplantSettings:
    """A snapshot of the tab's controls, taken on the main thread.

    Tk variables must not be read from a worker; this is what gets handed over
    instead. Frozen so a worker cannot pretend to change a setting mid-run.
    """

    install: str
    donor_install: str
    out_dir: str
    auto_merge: bool
    fit: bool
    scale: float
    reshape: bool
    with_texture: bool
    hide: bool


def guess_install() -> str:
    for p in DEFAULT_INSTALLS:
        if (Path(p) / "chitin.key").is_file():
            return p
    return ""


DEFAULT_INSTALLS_2 = [
    r"E:\SteamLibrary\steamapps\common\Knights of the Old Republic II",
    r"C:\Program Files (x86)\Steam\steamapps\common\Knights of the Old Republic II",
    r"C:\GOG Games\Star Wars - KotOR2",
]


def guess_install2() -> str:
    for p in DEFAULT_INSTALLS_2:
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
        # The notebook absorbs spare height; the log keeps a fixed, always
        # visible size. It was the other way round, and adding a 420px viewport
        # to the Preview tab then pushed the log and the buttons off the bottom
        # of the window entirely - the Preview button looked like it did nothing
        # because its output was landing somewhere unreachable.
        self.rowconfigure(1, weight=1)

        self.events: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.models: list[str] = []
        self.index = None
        self.donor_labels: dict[str, str] = {}

        self._build_paths()
        self._build_tabs()
        self._build_log()
        self._build_actions()

        self.after(100, self._drain)
        self._on_effect_change()

    # ---- shared ------------------------------------------------------------

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
        ttk.Label(box, text="KOTOR 2 (optional)").grid(
            row=2, column=0, sticky="w", pady=(6, 0)
        )
        self.install2 = tk.StringVar(value=guess_install2())
        ttk.Entry(box, textvariable=self.install2).grid(
            row=2, column=1, sticky="ew", padx=6, pady=(6, 0)
        )
        ttk.Button(box, text="Browse", command=self._pick_install2).grid(
            row=2, column=2, pady=(6, 0)
        )

        ttk.Label(
            box,
            text=("Builds go to the output folder; \"Install to Override\" copies them "
                  "into the game. A KOTOR 2 folder lets you borrow its heads."),
            foreground="#666", wraplength=620,
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))

    def _build_tabs(self):
        self.tabs = ttk.Notebook(self)
        self.tabs.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        self._build_effect_tab()
        self._build_transplant_tab()
        self._build_preview_tab()
        self._build_builds_tab()

    # ---- effects tab -------------------------------------------------------

    def _build_effect_tab(self):
        page = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(page, text="Effects")
        page.columnconfigure(1, weight=1)

        self.effect = tk.StringVar(value=keffects.EFFECTS[0].key)
        row = ttk.Frame(page)
        row.grid(row=0, column=0, columnspan=3, sticky="w")
        for e in keffects.EFFECTS:
            ttk.Radiobutton(
                row, text=e.label, value=e.key, variable=self.effect,
                command=self._on_effect_change,
            ).pack(side="left", padx=(0, 10))

        self.effect_desc = ttk.Label(page, text="", wraplength=560, foreground="#333")
        self.effect_desc.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.effect_caution = ttk.Label(page, text="", wraplength=560, foreground="#a35")
        self.effect_caution.grid(row=2, column=0, columnspan=3, sticky="w")

        ttk.Label(page, text="Intensity").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.intensity = tk.DoubleVar(value=1.0)
        ttk.Scale(
            page, from_=0.1, to=2.0, variable=self.intensity, orient="horizontal",
            command=lambda _=None: self._on_effect_change(),
        ).grid(row=3, column=1, sticky="ew", padx=6, pady=(8, 0))
        self.intensity_label = ttk.Label(page, text="1.00x", width=8)
        self.intensity_label.grid(row=3, column=2, sticky="w", pady=(8, 0))

        who = ttk.LabelFrame(page, text="Companions", padding=6)
        who.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        self.selected: dict[str, tk.BooleanVar] = {}
        grid = ttk.Frame(who)
        grid.pack(fill="x")
        for i, c in enumerate(roster.COMPANIONS):
            var = tk.BooleanVar(value=True)
            self.selected[c.key] = var
            ttk.Checkbutton(grid, text=c.name, variable=var).grid(
                row=i // 3, column=i % 3, sticky="w", padx=(0, 16)
            )
        btns = ttk.Frame(who)
        btns.pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="All", command=lambda: self._set_all(True)).pack(side="left")
        ttk.Button(btns, text="None", command=lambda: self._set_all(False)).pack(
            side="left", padx=6
        )

    # ---- transplant tab ----------------------------------------------------

    def _build_transplant_tab(self):
        page = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(page, text="Transplant")
        page.columnconfigure(1, weight=1)
        page.columnconfigure(3, weight=1)

        ttk.Label(page, text="Host").grid(row=0, column=0, sticky="w")
        self.host = tk.StringVar()
        self.host_box = ttk.Combobox(page, textvariable=self.host, values=[])
        self.host_box.grid(row=0, column=1, sticky="ew", padx=6)
        self.host_box.bind("<<ComboboxSelected>>", lambda _e: self._refresh_donors())

        ttk.Label(page, text="Donor").grid(row=0, column=2, sticky="w")
        self.donor = tk.StringVar()
        self.donor_box = ttk.Combobox(page, textvariable=self.donor, values=[])
        self.donor_box.grid(row=0, column=3, sticky="ew", padx=6)

        ttk.Button(page, text="Scan install", command=self._scan).grid(row=0, column=4)

        game = ttk.Frame(page)
        game.grid(row=7, column=0, columnspan=5, sticky="w", pady=(8, 0))
        ttk.Label(game, text="Donor from").pack(side="left", padx=(0, 6))
        self.donor_game = tk.StringVar(value="K1")
        for label, value in (("this game", "K1"), ("KOTOR 2", "K2")):
            ttk.Radiobutton(game, text=label, value=value, variable=self.donor_game,
                            command=self._refresh_donors).pack(side="left", padx=(0, 10))
        self.donor_game_note = ttk.Label(game, text="", foreground="#666")
        self.donor_game_note.pack(side="left", padx=(8, 0))
        self.donor_note = ttk.Label(
            page,
            text="The host keeps its hierarchy, skeleton and animations. Only geometry moves.",
            foreground="#666", wraplength=620,
        )
        self.donor_note.grid(row=1, column=0, columnspan=5, sticky="w", pady=(6, 0))

        self.show_all = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            page, text="Show every model, including ones that cannot pair",
            variable=self.show_all, command=self._refresh_donors,
        ).grid(row=5, column=0, columnspan=5, sticky="w", pady=(8, 0))

        opts = ttk.Frame(page)
        opts.grid(row=2, column=0, columnspan=5, sticky="w", pady=(10, 0))
        # Reshape used to be forced on, because a head's vertex count was
        # thought to be fixed. It is not - that was a stale pointer in our own
        # writer - so the donor now comes across whole by default, keeping its
        # own shape, UVs and texture.
        self.opt_automerge = tk.BooleanVar(value=True)
        self.opt_reshape = tk.BooleanVar(value=False)
        self.opt_texture = tk.BooleanVar(value=True)
        self.opt_hide = tk.BooleanVar(value=True)
        self.opt_fit = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            opts, text="Take donor's texture", variable=self.opt_texture
        ).grid(row=0, column=0, sticky="w", padx=(0, 14))
        ttk.Checkbutton(
            opts, text="Hide parts the donor lacks", variable=self.opt_hide
        ).grid(row=0, column=1, sticky="w", padx=(0, 14))
        ttk.Checkbutton(
            opts, text="Fit donor to host's size (off: keep the donor's own size)",
            variable=self.opt_fit,
        ).grid(row=1, column=0, sticky="w", padx=(0, 14), pady=(4, 0))
        ttk.Checkbutton(
            opts, text="Reshape: keep host's topology and UVs instead",
            variable=self.opt_reshape,
        ).grid(row=1, column=1, sticky="w", pady=(4, 0))
        ttk.Checkbutton(
            opts, text="Fold in donor parts this host has no node for",
            variable=self.opt_automerge,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))

        size = ttk.Frame(page)
        size.grid(row=3, column=0, columnspan=5, sticky="w", pady=(8, 0))
        ttk.Label(size, text="Scale").pack(side="left")
        self.opt_scale = tk.DoubleVar(value=1.0)
        ttk.Scale(
            size, from_=0.6, to=1.8, variable=self.opt_scale, orient="horizontal",
            length=200, command=lambda _=None: self._on_scale_change(),
        ).pack(side="left", padx=6)
        self.scale_label = ttk.Label(size, text="1.00x", width=7)
        self.scale_label.pack(side="left")
        ttk.Label(size, text="nudge the fitted size", foreground="#666").pack(
            side="left", padx=(10, 0)
        )

        ttk.Button(page, text="Preview", command=lambda: self._start(preview=True)).grid(
            row=4, column=0, sticky="w", pady=(10, 0)
        )
        ttk.Label(
            page,
            text=("Preview writes nothing - it draws the result on the Preview tab "
                  "and reports how solid the donor is. Under 76% reads as holes."),
            foreground="#666", wraplength=620,
        ).grid(row=6, column=0, columnspan=5, sticky="w", pady=(6, 0))

    # ---- shared bottom -----------------------------------------------------

    # ---- builds tab --------------------------------------------------------

    def _build_builds_tab(self):
        """What has been made, kept rather than overwritten.

        Every build used to land on the last one in a single folder, so there
        was no way to keep two heads, go back to one that worked, or tell what
        a file was a day later.
        """
        page = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(page, text="Builds")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)

        top = ttk.Frame(page)
        top.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Button(top, text="Refresh", command=self._refresh_builds).pack(side="left")
        ttk.Button(top, text="Install selected", command=self._install).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(top, text="Remove installed", command=self._uninstall).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(top, text="Open folder", command=self._open_build).pack(
            side="left", padx=(6, 0)
        )

        self.build_list = tk.Listbox(page, height=7, exportselection=False)
        self.build_list.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        self.build_list.bind("<<ListboxSelect>>", lambda _e: self._on_build_select())
        bar = ttk.Scrollbar(page, command=self.build_list.yview)
        bar.grid(row=1, column=1, sticky="ns", pady=(6, 0))
        self.build_list.configure(yscrollcommand=bar.set)

        self.build_detail = ttk.Label(
            page, text="", foreground="#444", wraplength=620, justify="left"
        )
        self.build_detail.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.builds: list = []

    def _refresh_builds(self):
        from . import builds as kbuilds

        self.builds = kbuilds.find(self.out_dir.get().strip())
        self.build_list.delete(0, "end")
        for b in self.builds:
            self.build_list.insert("end", b.summary)
        if self.builds:
            self.build_list.selection_set(0)
            self._on_build_select()
        else:
            self.build_detail.config(text="Nothing built yet in this output folder.")

    def _selected_build(self):
        picked = self.build_list.curselection() if self.builds else ()
        return self.builds[picked[0]] if picked else None

    def _on_build_select(self):
        build = self._selected_build()
        if build is None:
            return
        m = build.manifest
        bits = [", ".join(f["name"] for f in m.get("files", [])) or "no files"]
        if m.get("merged"):
            bits.append("folded in: " + ", ".join(m["merged"]))
        options = m.get("options") or {}
        on = [k for k, v in options.items() if v is True]
        if options.get("scale") not in (None, 1.0):
            on.append(f"scale {options['scale']:g}")
        if on:
            bits.append(", ".join(on))
        problems = build.check()
        if problems:
            bits.append("CHANGED SINCE BUILD: " + "; ".join(problems))
        self.build_detail.config(text="\n".join(bits))

    def _open_build(self):
        import subprocess

        build = self._selected_build()
        target = build.path if build else Path(self.out_dir.get().strip())
        if target.is_dir():
            subprocess.Popen(["explorer", str(target)])

    # ---- preview tab -------------------------------------------------------

    def _build_preview_tab(self):
        """Look at a model without launching the game.

        The comparison is the point. A single render tells you little - vanilla
        heads look odd untextured too - but vanilla beside the build, framed by
        the same ruler, shows immediately whether a head landed at the right size
        and in the right place, which is otherwise a trip to the game to find out.
        """
        page = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(page, text="Preview")
        page.columnconfigure(1, weight=1)
        page.rowconfigure(3, weight=1)

        ttk.Label(page, text="Model").grid(row=0, column=0, sticky="w")
        self.preview_model = tk.StringVar()
        self.preview_box = ttk.Combobox(page, textvariable=self.preview_model, values=[])
        self.preview_box.grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(page, text="Show", command=self._show_preview).grid(row=0, column=2)

        opts = ttk.Frame(page)
        opts.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.preview_compare = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            opts, text="Compare with the build in the output folder",
            variable=self.preview_compare,
        ).pack(side="left", padx=(0, 16))
        self.preview_textured = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            opts, text="Textured", variable=self.preview_textured,
        ).pack(side="left", padx=(0, 16))
        # Off by default so the normal view stays two-sided, which is right for
        # judging shape. On, it draws only what the engine draws - the one way
        # to see an inside-out mesh before the game does.
        self.preview_cull = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            opts, text="Cull backfaces (as the engine draws)",
            variable=self.preview_cull, command=self._repaint_viewport,
        ).pack(side="left")

        ttk.Label(page, text="Highlight").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.preview_highlight = tk.StringVar(value="head")
        ttk.Entry(page, textvariable=self.preview_highlight).grid(
            row=2, column=1, sticky="ew", padx=6, pady=(6, 0)
        )
        ttk.Label(page, text="comma separated; overrides the texture",
                  foreground="#666").grid(row=2, column=2, sticky="w", pady=(6, 0))

        self.viewport = kviewport.Viewport(page, size=320)
        self.viewport.grid(row=3, column=0, columnspan=3, sticky="nsew", pady=(8, 0))

        views = ttk.Frame(page)
        views.grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))
        for label, yaw, pitch in (
            ("Front", 0, 0), ("Side", 90, 0), ("Back", 180, 0), ("Above", 0, 55),
        ):
            ttk.Button(
                views, text=label, width=7,
                command=lambda y=yaw, p=pitch: self.viewport.look(y, p),
            ).pack(side="left", padx=(0, 4))
        ttk.Button(views, text="Reset", width=7, command=self.viewport.reset).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(views, text="Save PNG", width=9, command=self._save_preview).pack(
            side="left", padx=(8, 0)
        )

        self.preview_status = ttk.Label(page, text="", foreground="#666", wraplength=600)
        self.preview_status.grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(
            page,
            text=("Drag to turn, wheel to zoom, double-click to reset. No animation, "
                  "so this cannot tell you whether a face still moves. A preview is "
                  "not proof."),
            foreground="#a35", wraplength=600,
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(4, 0))

    def _repaint_viewport(self):
        self.viewport.cull = self.preview_cull.get()
        self.viewport.repaint()

    def _show_preview(self):
        if self.worker and self.worker.is_alive():
            return
        name = self.preview_model.get().strip()
        if not name:
            self._say("pick a model to preview (press Scan install first)")
            return
        if not self._check_install():
            return
        self.viewport.clear("reading ...")
        self.preview_status.config(text="")
        highlight = frozenset(
            n.strip() for n in self.preview_highlight.get().split(",") if n.strip()
        )
        built = Path(self.out_dir.get().strip()) / f"{name}.mdl"
        compare = built if (self.preview_compare.get() and built.is_file()) else None
        self.worker = threading.Thread(
            target=self._preview_work,
            args=(self.install.get().strip(), name, highlight, compare,
                  self.preview_textured.get(), Path(self.out_dir.get().strip())),
            daemon=True,
        )
        self.worker.start()

    def _preview_work(self, install, name, highlight, compare, textured, out_dir):
        try:
            from kmdlswap import layout as kl

            from . import render as krender
            from .library import ModelLibrary

            lookup = cache = None
            if textured:
                from . import textures as ktextures

                # The build's own texture sits in the output folder, and is what
                # the game will use once both are in Override.
                cache = ktextures.TextureCache(install, extra=[out_dir])
                lookup = cache.get

            scenes, labels, notes = [], [], []
            layout = kl.parse(*ModelLibrary(install).read(name))
            scenes.append(
                krender.from_layout(layout, highlight=highlight, texture_lookup=lookup)
            )
            labels.append(f"{name} (vanilla)")

            if compare is not None:
                mdx = compare.with_suffix(".mdx")
                if not mdx.is_file():
                    notes.append(f"{compare.name} has no .mdx beside it, so it was skipped")
                else:
                    other = kl.parse(compare.read_bytes(), mdx.read_bytes())
                    scenes.append(krender.from_layout(
                        other, highlight=highlight, texture_lookup=lookup))
                    labels.append(f"{name} (your build)")

            missing = highlight - set(scenes[0].groups)
            if missing:
                notes.append(
                    f"not drawn, so absent or hidden: {', '.join(sorted(missing))}"
                )
            if textured:
                # Report per scene: a build usually carries its own head texture
                # that vanilla does not have, and one total would hide that.
                counts = " vs ".join(str(len(s.textures)) for s in scenes)
                notes.append("untextured: nothing resolved"
                             if not any(s.textures for s in scenes)
                             else f"{counts} texture(s)")
                notes.extend(cache.problems if cache else [])
            counts = " vs ".join(f"{s.triangles}" for s in scenes)
            notes.insert(0, f"{counts} triangles"
                            + (" (vanilla vs build)" if len(scenes) > 1 else ""))
            self.events.put(("scenes", (scenes, labels, "  -  ".join(notes))))
        except Exception as exc:  # noqa: BLE001
            self.events.put(("error", f"{type(exc).__name__}: {exc}"))

    def _save_preview(self):
        if not self.viewport.scenes:
            self._say("nothing to save - show a model first")
            return
        from tkinter import filedialog

        path = filedialog.asksaveasfilename(
            defaultextension=".png", filetypes=[("PNG image", "*.png")],
            initialdir=self.out_dir.get().strip() or None, initialfile="preview.png",
        )
        if not path:
            return
        from . import render as krender

        pixels = krender.strip(
            self.viewport.scenes, yaw=self.viewport.yaw, pitch=self.viewport.pitch,
            zoom=self.viewport.zoom, size=720, bounds=self.viewport.bounds,
        )
        krender.to_png(pixels, path)
        self._say(f"wrote {path}")

    def _build_log(self):
        box = ttk.LabelFrame(self, text="Log", padding=8)
        box.grid(row=2, column=0, sticky="ew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        self.log = tk.Text(box, height=6, wrap="word", state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(box, command=self.log.yview)
        bar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=bar.set)

    def _build_actions(self):
        row = ttk.Frame(self)
        row.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        row.columnconfigure(0, weight=1)

        # The most recent line of the log, where the eye already is. Long jobs
        # scroll the log away from whatever you were watching, and a progress
        # bar on its own says how far along it is but never what it is doing.
        self.status = ttk.Label(row, text="Ready", foreground="#444", anchor="w")
        self.status.grid(row=0, column=0, columnspan=5, sticky="ew", pady=(0, 4))

        self.progress = ttk.Progressbar(row, mode="determinate")
        self.progress.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        self.build_btn = ttk.Button(row, text="Build", command=self._start)
        self.build_btn.grid(row=1, column=1)
        ttk.Button(row, text="Open output", command=self._open_out).grid(
            row=1, column=2, padx=(6, 0)
        )
        ttk.Button(row, text="Install to Override", command=self._install).grid(
            row=1, column=3, padx=(6, 0)
        )
        ttk.Button(row, text="Remove", command=self._uninstall).grid(
            row=1, column=4, padx=(6, 0)
        )

    # ---- behaviour ---------------------------------------------------------

    def _set_all(self, value: bool):
        for var in self.selected.values():
            var.set(value)

    def _pick_install2(self):
        chosen = filedialog.askdirectory(title="Pick the KOTOR 2 folder")
        if chosen:
            self.install2.set(chosen)
            self.donor_game.set("K2")
            self._refresh_donors()

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

    def _k2_models(self) -> list[str]:
        """Character models in the second install, indexed once."""
        path = self.install2.get().strip()
        if not path:
            return []
        if getattr(self, "_k2_cache", (None, None))[0] != path:
            from .library import ModelLibrary

            try:
                lib = ModelLibrary(path)
            except Exception as exc:  # noqa: BLE001
                self._say(f"could not read the KOTOR 2 install: {exc}")
                self._k2_cache = (path, [])
            else:
                self._k2_cache = (path, sorted(
                    n for n in lib.index if n.startswith(("p_", "n_", "c_"))
                ))
        return self._k2_cache[1]

    def _refresh_donors(self):
        """Offer only donors that can actually pair with the chosen host."""
        if self.donor_game.get() == "K2":
            # No compatibility index for the second game - that would mean
            # scanning it as well. Preview reports what actually pairs, which is
            # the same answer a little later.
            models = self._k2_models()
            self.donor_labels = {n: n for n in models}
            self.donor_box.config(values=models)
            self.donor_game_note.config(
                text=(f"{len(models)} KOTOR 2 models; only geometry crosses over"
                      if models else "set the KOTOR 2 folder above")
            )
            return

        self.donor_game_note.config(text="")
        if self.index is None:
            return
        host = self.host.get().strip()
        if not host or host not in self.index.nodes:
            self.donor_box.config(values=[])
            return

        ranked = self.index.donors_for(host, usable_only=not self.show_all.get())
        self.donor_labels = {c.label(n): n for c, n in ranked}
        self.donor_box.config(values=list(self.donor_labels))

        usable = [c for c, _ in ranked if c.usable]
        if not usable and not self.show_all.get():
            self.donor_note.config(
                text=(
                    f"{host} has no compatible donor in the game. Its node names are "
                    f"its own, so nothing vanilla can be moved into it - custom "
                    f"geometry is the only route. Tick the box below to see every "
                    f"model anyway."
                ),
                foreground="#a35",
            )
        else:
            good = sum(1 for c, _ in ranked if c.tier == "good")
            extra = f", {good} sharing its skeleton" if good else ""
            self.donor_note.config(
                text=(
                    f"{len(usable)} donor(s) can pair with {host}{extra}. The number "
                    f"is how many of the host's parts that donor has; (?) marks a "
                    f"different skeleton, so the fit is less certain."
                ),
                foreground="#666",
            )
        if self.donor_labels:
            self.donor.set(next(iter(self.donor_labels)))

    def _selected_donor(self) -> str:
        raw = self.donor.get().strip()
        if raw in self.donor_labels:
            return self.donor_labels[raw]
        return raw.split()[0] if raw else ""

    def _install(self):
        """Copy the build into Override. The one action that touches the game."""
        from . import install as kinstall

        if not self._check_install():
            return
        install = self.install.get().strip()
        # Install one named build, not "whatever is loose in the output folder".
        # That folder now holds several builds side by side, so it is no longer
        # a thing that can be installed as a unit.
        build = self._selected_build()
        if build is None:
            self._refresh_builds()
            build = self._selected_build()
        if build is None:
            messagebox.showinfo("kmdlfun", "Nothing built to install yet.")
            return

        source = build.path
        p = kinstall.plan(install, source)
        if not p.total:
            messagebox.showinfo("kmdlfun", f"'{build.name}' has nothing to install.")
            return

        names = [f.name for f in (p.new + p.ours + p.foreign)]
        self._say(f"\ninstalling build '{build.name}'")
        preview = "\n".join("  " + n for n in names[:12])
        if len(names) > 12:
            preview += f"\n  ... and {len(names) - 12} more"

        if p.foreign:
            # Not ours - very likely another mod the user installed by hand.
            clash = ", ".join(f.name for f in p.foreign)
            if not messagebox.askyesno(
                "Overwrite files this tool did not install?",
                f"These already exist in Override and were not put there by this "
                f"tool, so they probably belong to another mod:\n\n  {clash}\n\n"
                f"Overwrite them anyway?",
                icon="warning",
            ):
                self._say("install cancelled")
                return

        if not messagebox.askokcancel(
            "Install to Override",
            f"Copy {p.total} file(s) into\n{p.override}\n\n{preview}\n\n"
            f"({p.describe()})",
        ):
            self._say("install cancelled")
            return

        try:
            done = kinstall.apply(install, source, allow_foreign=True)
        except OSError as exc:
            messagebox.showerror("kmdlfun", f"Could not install: {exc}")
            return
        self._say(f"\ninstalled {len(done)} file(s) into Override: {', '.join(done[:8])}"
                  + (" ..." if len(done) > 8 else ""))
        self._say("Load the game to check. Remove puts it back to vanilla.")

    def _uninstall(self):
        from . import install as kinstall

        if not self._check_install():
            return
        install = self.install.get().strip()
        known = kinstall.read_manifest(install)
        if not known:
            messagebox.showinfo(
                "kmdlfun",
                "This tool has not installed anything, so there is nothing to "
                "remove.\n\nFiles put in Override by hand or by other mods are "
                "deliberately left alone.",
            )
            return
        if not messagebox.askokcancel(
            "Remove from Override",
            f"Remove the {len(known)} file(s) this tool installed?\n\n"
            f"Vanilla models live in the game archives, so the originals come "
            f"back. Nothing else in Override is touched.",
        ):
            return
        removed = kinstall.remove(install)
        self._say(f"\nremoved {len(removed)} file(s) from Override; vanilla restored")

    def _on_effect_change(self):
        e = keffects.resolve(self.effect.get())
        scales = e.scaled(self.intensity.get())
        detail = ", ".join(f"{k} x{v:.2f}" for k, v in scales.items())
        self.effect_desc.config(text=f"{e.description}\nScales: {detail}")
        self.effect_caution.config(text=e.caution)
        self.intensity_label.config(text=f"{self.intensity.get():.2f}x")

    def _set_status(self, text: str):
        line = next((s.strip() for s in reversed(text.splitlines()) if s.strip()), "")
        if line:
            self.status.config(text=line[:150])

    def _say(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")
        # Progress messages route through here too, so the status line
        # follows the work without needing its own plumbing.
        self._set_status(text)

    def _check_install(self) -> bool:
        if not (Path(self.install.get().strip()) / "chitin.key").is_file():
            messagebox.showerror(
                "kmdlfun",
                "That folder does not look like a KOTOR install (no chitin.key inside it).",
            )
            return False
        return True

    def _scan(self):
        if not self._check_install() or (self.worker and self.worker.is_alive()):
            return
        self._say("\nscanning install for character models ...")
        self.build_btn.config(state="disabled")
        self.worker = threading.Thread(target=self._scan_work, daemon=True)
        self.worker.start()

    def _scan_work(self):
        """Build the compatibility index.

        A swap only fills nodes the host already has, so the donor list has to be
        filtered by what actually pairs. Without it a dewback looks as plausible
        a donor as a human head - it shares one node name, and nothing else.
        """
        try:
            from pykotor.extract.installation import Installation
            from pykotor.resource.type import ResourceType

            from kmdlswap import layout as kl
            from kmdlswap import validate as kv

            from . import catalogue as kc

            inst = Installation(self.install.get().strip())
            found: dict[str, dict] = {}
            for r in inst.chitin_resources():
                if r.restype() in (ResourceType.MDL, ResourceType.MDX):
                    found.setdefault(r.resname().lower(), {})[r.restype()] = r
            names = sorted(
                n for n, k in found.items()
                if len(k) == 2 and n.startswith(("p_", "n_", "c_"))
            )

            index = kc.ModelIndex()
            for i, name in enumerate(names):
                if i % 20 == 0:
                    self.events.put(("progress", (i, len(names), f"reading {name}")))
                e = found[name]
                try:
                    lay = kl.parse(e[ResourceType.MDL].data(), e[ResourceType.MDX].data())
                    if kv.check(lay).ok:
                        index.add(kc.describe(lay, name))
                except Exception:  # noqa: BLE001, S112
                    continue
            self.events.put(("index", index))
        except Exception as exc:  # noqa: BLE001
            self.events.put(("error", f"{type(exc).__name__}: {exc}"))

    def _start(self, preview: bool = False):
        if self.worker and self.worker.is_alive():
            return
        if not self._check_install():
            return

        tab = self.tabs.tab(self.tabs.select(), "text")
        self.build_btn.config(state="disabled")
        self.progress.config(value=0, maximum=100)

        if tab == "Effects":
            keys = [k for k, v in self.selected.items() if v.get()]
            if not keys:
                messagebox.showinfo("kmdlfun", "Pick at least one companion.")
                self.build_btn.config(state="normal")
                return
            effect = keffects.resolve(self.effect.get())
            self._say(f"\n=== {effect.label} @ {self.intensity.get():.2f}x ===")
            args = (self.install.get().strip(), self.effect.get(), keys,
                    self.out_dir.get(), self.intensity.get())
            self.worker = threading.Thread(target=self._effect_work, args=args, daemon=True)
        else:
            host, donor = self.host.get().strip(), self._selected_donor()
            if not host or not donor:
                messagebox.showinfo("kmdlfun", "Pick a host and a donor.")
                self.build_btn.config(state="normal")
                return
            if self.index is not None and host in self.index.nodes:
                c = self.index.compare(host, donor)
                if not c.usable:
                    self._say("\n" + c.why_not(host, donor))
                    self._say("Building anyway, but expect little to transfer.")
            self._say(f"\n=== {host} <- {donor}{' (preview)' if preview else ''} ===")
            # Every Tk variable is read here, on the main thread, and handed to
            # the worker as plain values. Reading them from the worker happens to
            # survive while the main loop is spinning and raises "main thread is
            # not in main loop" when it is not - the effects and preview workers
            # already take their settings as arguments; this one did not.
            settings = TransplantSettings(
                install=self.install.get().strip(),
                donor_install=(self.install2.get().strip()
                               if self.donor_game.get() == "K2" else ""),
                out_dir=self.out_dir.get(),
                auto_merge=self.opt_automerge.get(),
                fit=self.opt_fit.get(),
                scale=self.opt_scale.get(),
                reshape=self.opt_reshape.get(),
                with_texture=self.opt_texture.get(),
                hide=self.opt_hide.get(),
            )
            self.worker = threading.Thread(
                target=self._transplant_work,
                args=(host, donor, preview, settings),
                daemon=True,
            )
        self.worker.start()

    def _effect_work(self, install, effect_key, keys, out_dir, intensity):
        def progress(i, total, label):
            self.events.put(("progress", (i, total, label)))

        try:
            report = build(install, effect_key, keys, out_dir,
                           intensity=intensity, progress=progress)
            self.events.put(("done_effect", report))
        except Exception as exc:  # noqa: BLE001
            self.events.put(("error", f"{type(exc).__name__}: {exc}\n"
                                      f"{traceback.format_exc(limit=3)}"))

    def _transplant_work(self, host, donor, preview, cfg):
        try:
            from kmdlswap import layout as kl
            from kmdlswap import validate as kv

            from . import parts as kparts
            from . import transplant as ktp
            from . import visibility as kvis
            from .library import ModelLibrary

            lib = ModelLibrary(cfg.install)
            donor_lib = ModelLibrary(cfg.donor_install) if cfg.donor_install else lib
            if not lib.has(host):
                self.events.put(("error", f"no model named {host!r} in the host game"))
                return
            if not donor_lib.has(donor):
                self.events.put(("error", f"no model named {donor!r} in the donor game"))
                return

            mdl, mdx = lib.read(host)
            donor_layout = kl.parse(*donor_lib.read(donor))
            host_layout = kl.parse(mdl, mdx)
            if donor_layout.game != host_layout.game:
                lines_prefix = (f"donor is a {donor_layout.game} model, host is "
                                f"{host_layout.game}: geometry only")
            else:
                lines_prefix = None
            pairs = ktp.match_nodes(host_layout, donor_layout)
            if not pairs:
                self.events.put(("error",
                                 f"{host} and {donor} share no mesh node names, "
                                 f"so there is nothing to move between them"))
                return

            lines = [lines_prefix] if lines_prefix else []
            lines.append(f"{len(pairs)} matching node(s)")

            anchor = ktp.anchor_pair(pairs, host_layout)
            auto = []
            if cfg.auto_merge and anchor:
                h, d = anchor
                auto = ktp.auto_merge_candidates(
                    donor_layout, donor_layout.node_by_name(d),
                    host_layout, host_layout.node_by_name(h),
                )
                if auto:
                    lines.append(f"folding in {len(auto)} part(s) the host has no "
                                 f"node for: {', '.join(auto)}")
            taken = {h for h, _ in pairs}
            left = [n.name for n in kparts.mesh_nodes(host_layout) if n.name not in taken]
            if left:
                lines.append(f"donor has no: {', '.join(left)}"
                             + ("  (will hide)" if cfg.hide else ""))

            reshape = cfg.reshape
            ok = 0
            for i, (host_node, donor_node) in enumerate(pairs):
                self.events.put(("progress", (i, len(pairs), f"{host_node} <- {donor_node}")))
                new_mdl, new_mdx, r = ktp.transplant_node(
                    mdl, mdx, donor_layout, donor, host_node, donor_node,
                    # Not fitting still means putting it where the part it
                    # replaces sits. A donor left exactly where it was authored
                    # lands about 1.5 units away - inside the chest - which is
                    # never what anyone wanted.
                    fit=cfg.fit, place=not cfg.fit, scale=cfg.scale,
                    merge=(auto if (host_node, donor_node) == anchor else None),
                    reshape=reshape, with_texture=cfg.with_texture,
                )
                if not r.ok:
                    lines.append(f"  {host_node}: REFUSED {r.error}")
                    continue
                ok += 1
                a = r.alignment
                lines.append(f"  {host_node} <- {donor_node}   fit {a.worst_ratio:.2f}x"
                             f"   drift {a.drift:.3f}")
                if preview:
                    lines.append(f"      {self._solidity(donor_layout, donor_node)}")
                mdl, mdx = new_mdl, new_mdx

            if cfg.hide and left:
                mdl, hidden = kvis.hide_nodes(kl.parse(mdl, mdx), mdl, left)
                lines.append(f"hid {len(hidden)}: {', '.join(hidden)}")

            if preview:
                # The result exists in memory either way, so a preview can show
                # it rather than only describe it. Nothing is written.
                lines.append(f"preview only: {ok}/{len(pairs)} would transfer")
                try:
                    self._post_scenes(cfg.install, host, donor, mdl, mdx, lib)
                except Exception as exc:  # noqa: BLE001
                    lines.append(f"(could not draw it: {type(exc).__name__}: {exc})")
                self.events.put(("done_text", lines))
                return

            if not kv.check(kl.parse(mdl, mdx)).ok:
                self.events.put(("error", "result failed validation; nothing written"))
                return

            from . import builds as kbuilds

            root = Path(cfg.out_dir)
            root.mkdir(parents=True, exist_ok=True)
            out = root / kbuilds.unique_name(root, f"{host}-{donor}")
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{host}.mdl").write_bytes(mdl)
            (out / f"{host}.mdx").write_bytes(mdx)
            if cfg.donor_install and cfg.with_texture:
                from . import textures as ktextures

                lines.extend(ktextures.export_donor_textures(
                    mdl, mdx, cfg.donor_install, out
                ))
            build = kbuilds.adopt(out, {
                "kind": "transplant",
                "host": {"model": host, "game": host_layout.game,
                         "install": cfg.install},
                "donor": {"model": donor, "game": donor_layout.game,
                          "install": cfg.donor_install or cfg.install},
                "nodes": [list(pair) for pair in pairs],
                "merged": list(auto),
                "options": {
                    "fit": cfg.fit, "place": not cfg.fit, "scale": cfg.scale,
                    "reshape": cfg.reshape, "with_texture": cfg.with_texture,
                    "hide_unmatched": cfg.hide, "auto_merge": cfg.auto_merge,
                },
            })
            lines.append(f"build '{build.name}' kept in {out}")
            lines.append("Install it from the Builds tab. A build is not proof.")
            self.events.put(("done_text", lines))
        except Exception as exc:  # noqa: BLE001
            self.events.put(("error", f"{type(exc).__name__}: {exc}\n"
                                      f"{traceback.format_exc(limit=3)}"))

    def _post_scenes(self, install, host, donor, mdl, mdx, lib):
        """Draw the host as it is beside the host as it would be.

        Framed by one shared ruler, because two renders at two scales make a
        part that changed size look unchanged.
        """
        from kmdlswap import layout as kl

        from . import render as krender
        from . import textures as ktextures

        cache = ktextures.TextureCache(install)
        before = krender.from_layout(kl.parse(*lib.read(host)), texture_lookup=cache.get)
        after = krender.from_layout(kl.parse(mdl, mdx), texture_lookup=cache.get)
        note = (f"{before.triangles} vs {after.triangles} triangles   -   "
                f"nothing written; this is what Build would produce")
        self.events.put((
            "scenes",
            ([before, after], [f"{host} (now)", f"{host} <- {donor}"], note),
        ))

    @staticmethod
    def _solidity(layout, node_name) -> str:
        """How much of a donor node faces outward, and what that means.

        The single best predictor of whether a swap will look right. The engine
        draws front faces only, so a mesh that folds back on itself renders full
        of holes - and nothing else in the preview can see that, because a
        two-sided viewer shows it as perfect.
        """
        from kmdlswap import edit as ke
        from kmdlswap.obj import ObjMesh

        from . import headspec, repair

        geo = ke.extract(layout, layout.node_by_name(node_name))
        mesh = ObjMesh(name=node_name)
        mesh.positions = [tuple(p) for p in geo.positions]
        mesh.faces = [f.vertices for f in geo.faces]
        solid = repair.outward_fraction(mesh.positions, mesh.faces)
        if solid >= headspec.SOLID_PASS:
            verdict = "good"
        elif solid >= headspec.SOLID_REJECT:
            verdict = "marginal - some of it will be culled"
        else:
            verdict = "TOO LOW - this will render full of holes"
        return f"solid {solid:.0%} ({verdict})"

    def _on_scale_change(self):
        self.scale_label.config(text=f"{self.opt_scale.get():.2f}x")

    def _drain(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "progress":
                    i, total, label = payload
                    self.progress.config(value=100 * i / max(total, 1))
                    if label != "done":
                        self._say(f"  [{i + 1}/{total}] {label}")
                elif kind == "scenes":
                    scenes, labels, note = payload
                    self.viewport.set_scenes(scenes, labels)
                    self.preview_status.config(text=note)
                    # The viewport lives on the Preview tab, so put it in front
                    # rather than drawing where nobody is looking.
                    for i in range(len(self.tabs.tabs())):
                        if self.tabs.tab(i, "text") == "Preview":
                            self.tabs.select(i)
                            break
                elif kind == "index":
                    self.index = payload
                    self.models = payload.names
                    self.host_box.config(values=self.models)
                    self.preview_box.config(values=self.models)
                    self._say(f"indexed {len(self.models)} character models")
                    self._refresh_donors()
                    self.build_btn.config(state="normal")
                elif kind == "done_effect":
                    self._finish_effect(payload)
                elif kind == "done_text":
                    self._refresh_builds()
                    for line in payload:
                        self._say(line)
                    self.progress.config(value=100)
                    self.build_btn.config(state="normal")
                elif kind == "error":
                    self._say("ERROR: " + payload)
                    self.build_btn.config(state="normal")
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def _finish_effect(self, report):
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
    root.title("kmdlfun - KOTOR model tools")
    root.geometry("780x940")
    root.minsize(720, 600)
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
