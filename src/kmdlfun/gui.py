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
        self.rowconfigure(2, weight=1)

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
        ttk.Label(
            box,
            text=("Builds go to the output folder. \"Install to Override\" copies them into "
                  "the game, and \"Remove\" puts it back to vanilla."),
            foreground="#666",
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))

    def _build_tabs(self):
        self.tabs = ttk.Notebook(self)
        self.tabs.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self._build_effect_tab()
        self._build_transplant_tab()

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
        self.opt_reshape = tk.BooleanVar(value=True)
        self.opt_texture = tk.BooleanVar(value=True)
        self.opt_hide = tk.BooleanVar(value=True)
        self.opt_fit = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            opts, text="Reshape (required for heads)", variable=self.opt_reshape
        ).grid(row=0, column=0, sticky="w", padx=(0, 14))
        ttk.Checkbutton(
            opts, text="Take donor's texture", variable=self.opt_texture
        ).grid(row=0, column=1, sticky="w", padx=(0, 14))
        ttk.Checkbutton(
            opts, text="Hide parts the donor lacks", variable=self.opt_hide
        ).grid(row=1, column=0, sticky="w", padx=(0, 14), pady=(4, 0))
        ttk.Checkbutton(
            opts, text="Fit donor to host's size", variable=self.opt_fit
        ).grid(row=1, column=1, sticky="w", pady=(4, 0))

        ttk.Label(
            page,
            text=(
                "A skinned mesh in a head model must keep its vertex count, or the "
                "mouth and eyebrows stop moving in-game. Reshape keeps it."
            ),
            wraplength=620,
            foreground="#a35",
        ).grid(row=3, column=0, columnspan=5, sticky="w", pady=(8, 0))

        ttk.Button(page, text="Preview", command=lambda: self._start(preview=True)).grid(
            row=4, column=0, sticky="w", pady=(10, 0)
        )

    # ---- shared bottom -----------------------------------------------------

    def _build_log(self):
        box = ttk.LabelFrame(self, text="Log", padding=8)
        box.grid(row=2, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        self.log = tk.Text(box, height=14, wrap="word", state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(box, command=self.log.yview)
        bar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=bar.set)

    def _build_actions(self):
        row = ttk.Frame(self)
        row.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        row.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(row, mode="determinate")
        self.progress.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.build_btn = ttk.Button(row, text="Build", command=self._start)
        self.build_btn.grid(row=0, column=1)
        ttk.Button(row, text="Open output", command=self._open_out).grid(
            row=0, column=2, padx=(6, 0)
        )
        ttk.Button(row, text="Install to Override", command=self._install).grid(
            row=0, column=3, padx=(6, 0)
        )
        ttk.Button(row, text="Remove", command=self._uninstall).grid(
            row=0, column=4, padx=(6, 0)
        )

    # ---- behaviour ---------------------------------------------------------

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

    def _refresh_donors(self):
        """Offer only donors that can actually pair with the chosen host."""
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
        p = kinstall.plan(install, self.out_dir.get())
        if not p.total:
            messagebox.showinfo("kmdlfun", "Nothing built to install yet.")
            return

        names = [f.name for f in (p.new + p.ours + p.foreign)]
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
            done = kinstall.apply(install, self.out_dir.get(), allow_foreign=True)
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

    def _say(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

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
            self.worker = threading.Thread(
                target=self._transplant_work, args=(host, donor, preview), daemon=True
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

    def _transplant_work(self, host, donor, preview):
        try:
            from kmdlswap import layout as kl
            from kmdlswap import validate as kv

            from . import parts as kparts
            from . import transplant as ktp
            from . import visibility as kvis
            from .library import ModelLibrary

            lib = ModelLibrary(self.install.get().strip())
            for name in (host, donor):
                if not lib.has(name):
                    self.events.put(("error", f"no model named {name!r} in that install"))
                    return

            mdl, mdx = lib.read(host)
            donor_layout = kl.parse(*lib.read(donor))
            host_layout = kl.parse(mdl, mdx)
            pairs = ktp.match_nodes(host_layout, donor_layout)
            if not pairs:
                self.events.put(("error",
                                 f"{host} and {donor} share no mesh node names, "
                                 f"so there is nothing to move between them"))
                return

            lines = [f"{len(pairs)} matching node(s)"]
            taken = {h for h, _ in pairs}
            left = [n.name for n in kparts.mesh_nodes(host_layout) if n.name not in taken]
            if left:
                lines.append(f"donor has no: {', '.join(left)}"
                             + ("  (will hide)" if self.opt_hide.get() else ""))

            reshape = self.opt_reshape.get() or self.opt_texture.get()
            ok = 0
            for i, (host_node, donor_node) in enumerate(pairs):
                self.events.put(("progress", (i, len(pairs), f"{host_node} <- {donor_node}")))
                new_mdl, new_mdx, r = ktp.transplant_node(
                    mdl, mdx, donor_layout, donor, host_node, donor_node,
                    fit=self.opt_fit.get(), reshape=reshape,
                    with_texture=self.opt_texture.get(),
                )
                if not r.ok:
                    lines.append(f"  {host_node}: REFUSED {r.error}")
                    continue
                ok += 1
                a = r.alignment
                lines.append(f"  {host_node} <- {donor_node}   fit {a.worst_ratio:.2f}x"
                             f"   drift {a.drift:.3f}")
                if not preview:
                    mdl, mdx = new_mdl, new_mdx

            if preview:
                lines.append(f"preview only: {ok}/{len(pairs)} would transfer")
                self.events.put(("done_text", lines))
                return

            if self.opt_hide.get() and left:
                mdl, hidden = kvis.hide_nodes(kl.parse(mdl, mdx), mdl, left)
                lines.append(f"hid {len(hidden)}: {', '.join(hidden)}")

            if not kv.check(kl.parse(mdl, mdx)).ok:
                self.events.put(("error", "result failed validation; nothing written"))
                return

            out = Path(self.out_dir.get())
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{host}.mdl").write_bytes(mdl)
            (out / f"{host}.mdx").write_bytes(mdx)
            lines.append(f"wrote {out / host}.mdl and .mdx")
            lines.append("Copy both into Override. A successful build is not proof.")
            self.events.put(("done_text", lines))
        except Exception as exc:  # noqa: BLE001
            self.events.put(("error", f"{type(exc).__name__}: {exc}\n"
                                      f"{traceback.format_exc(limit=3)}"))

    def _drain(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "progress":
                    i, total, label = payload
                    self.progress.config(value=100 * i / max(total, 1))
                    if label != "done":
                        self._say(f"  [{i + 1}/{total}] {label}")
                elif kind == "index":
                    self.index = payload
                    self.models = payload.names
                    self.host_box.config(values=self.models)
                    self._say(f"indexed {len(self.models)} character models")
                    self._refresh_donors()
                    self.build_btn.config(state="normal")
                elif kind == "done_effect":
                    self._finish_effect(payload)
                elif kind == "done_text":
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
    root.geometry("720x820")
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
