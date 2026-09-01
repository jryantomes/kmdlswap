"""Tkinter desktop app for kmdlfun.

Tkinter ships with Python, so the app adds no dependency. It drives the same
library the CLI does - nothing here reimplements the geometry work.

A tab per job, because they are genuinely different jobs: applying an effect to
whole companions, moving one model's geometry into another, and putting a mesh
from outside the game into a single node. They share the folder settings, the
log and the build button, since those are the same in every case.

The third exists because two of them were unreachable from here. Head packs
were command line only, and a unified body like HK-47 - whose head is one node
among forty-odd droid-named meshes - fails the whole-model compatibility test
that fills the donor list, so it offered nothing at all. Naming a single host
node answers the question that actually matters there.

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

# The window the app opens at. Named because a test checks the content fits
# inside it, and a magic number in two places drifts apart.
WINDOW_W, WINDOW_H = 860, 980

WHOLE_MODEL = "matching nodes (whole model)"
ANYONE = "anyone"
AUTO_NODE = "automatic"
NOT_A_CHARACTER = "just a model"
SAME_AS_HOST = "same body as the host"
# The three things a humanoid is made of, in the order somebody picks them.
# Not `PARTS`: that name already means the body parts of a mesh in `parts.py`,
# and the two are nothing like each other.
PART_KINDS = ("body", "outfit", "head")
PART_TITLES = {"body": "Body", "outfit": "Wardrobe", "head": "Head"}
SEEN_IN_GAME = "\u2713"          # this body already wears this in vanilla
PREVIEW_SIZE = 260

# What is coming, and honestly where each one is. "Command line only" means the
# work is done and tested and only the button is missing - which is worth
# saying, because it is the difference between "wait" and "here is how to do it
# today".
UPCOMING = (
    (
        "A mod other people can install",
        "planned",
        "Right now the 2DA files a build writes are yours - they carry your "
        "install's rows, so handing them to someone else overwrites their "
        "mods. A HoloPatcher changes.ini would merge instead of replace.",
        "",
    ),
    (
        "Jade Empire models",
        "use Blender for now",
        "Answered rather than pending: the structures really are different "
        "sizes - a 60-byte node header against KOTOR's 80, controllers moved "
        "out of the node entirely - so the eight-byte wrapper shift was only "
        "the wrapper. Native reading is not worth it, because JadeBlender "
        "already converts Jade models to KOTOR ones in both directions. Bring "
        "the result in as .glb on the Custom head tab, and check the scale. "
        "Measured on 270 Jade models against 200 of KOTOR's, Jade is LARGER and wants scaling DOWN by about a sixth - multiply by 0.83, the opposite of what we were told, so confirm it. Bodies give the tightest figure: height and depth agree to 0.4%. Heads also arrive lying on their side, because Jade's height axis is X where KOTOR's is Z.",
        "",
    ),
    (
        "Neverwinter Nights and SWTOR heads",
        "use Blender for now",
        "Both are readable through Blender and out as .glb, which the Custom "
        "head tab imports directly. Native reading is a bigger job than it "
        "looks and probably not worth it.",
        "",
    ),
)

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
    # One host node to fill, or "" to pair every node whose name matches. A
    # unified body needs the former: HK-47 shares exactly one node name with any
    # head model, so whole-model pairing offers nothing.
    target_node: str = ""
    # Which donor node fills it. Empty means work it out: same name, then the
    # donor's head. A model with neither has to be told.
    donor_node: str = ""
    # A new resref to save under, or "" to overwrite the host as before.
    save_as: str = ""
    # "" for a bare model, or npc / talker / companion.
    character_kind: str = ""
    character_name: str = ""
    outfit: str = ""


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
        self.host_labels: dict[str, str] = {}

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
        ttk.Label(box, text="KOTOR II (optional)").grid(
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
                  "into the game. A KOTOR II folder lets you borrow its heads."),
            foreground="#666", wraplength=620,
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))

    def _build_tabs(self):
        self.tabs = ttk.Notebook(self)
        self.tabs.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        # Transplant first because it is what the tool is for. Effects last:
        # it was written first and sat in front for that reason alone.
        self._build_transplant_tab()
        self._build_character_tab()
        self._build_head_tab()
        self._build_lips_tab()
        self._build_preview_tab()
        self._build_builds_tab()
        self._build_effect_tab()
        self._build_upcoming_tab()

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
        ttk.Button(btns, text="Preview", command=self._preview_effect).pack(
            side="left", padx=(12, 0)
        )
        ttk.Label(
            btns,
            text="draws the first companion picked, before and after",
            foreground="#666",
        ).pack(side="left", padx=(8, 0))

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

        ttk.Button(page, text="Scan install", command=self._scan).grid(row=0, column=4)

        # A name does not tell you what a face looks like. `n_shaardanh` and
        # `n_lashoweh` are both clean fits on Carth and one of them is the one
        # you meant, so the donor list shows the face beside the name. The
        # variable stays the single source of truth - the tree writes into it -
        # so everything downstream is unchanged.
        self.donor = tk.StringVar()

        # Where the donor's head goes. "Matching nodes" is the original
        # behaviour - pair everything whose names agree - and is right when
        # host and donor are the same kind of model. It finds nothing on a
        # unified body like HK-47, whose 45 droid-named meshes share exactly one
        # name with any head model, so a single node can be named instead.
        target = ttk.Frame(page)
        target.grid(row=1, column=0, columnspan=5, sticky="w", pady=(6, 0))
        ttk.Label(target, text="Into").pack(side="left", padx=(0, 6))
        self.target_node = tk.StringVar(value=WHOLE_MODEL)
        self.target_box = ttk.Combobox(target, textvariable=self.target_node,
                                       values=[WHOLE_MODEL], width=28, state="readonly")
        self.target_box.pack(side="left")
        self.target_box.bind("<<ComboboxSelected>>", lambda _e: self._refresh_donors())
        ttk.Label(target, text="from").pack(side="left", padx=(10, 6))
        # Which node of the donor. Automatic covers everything with a head:
        # same name if there is one, the donor's head otherwise. A kath hound
        # has neither, so the node has to be nameable.
        self.donor_node = tk.StringVar(value=AUTO_NODE)
        self.donor_node_box = ttk.Combobox(
            target, textvariable=self.donor_node, values=[AUTO_NODE],
            width=22, state="readonly",
        )
        self.donor_node_box.pack(side="left")
        self.target_note = ttk.Label(target, text="", foreground="#666")
        self.target_note.pack(side="left", padx=(8, 0))

        game = ttk.Frame(page)
        game.grid(row=2, column=0, columnspan=5, sticky="w", pady=(6, 0))
        ttk.Label(game, text="Donor from").pack(side="left", padx=(0, 6))
        self.donor_game = tk.StringVar(value="K1")
        for label, value in (("KOTOR", "K1"), ("KOTOR II", "K2")):
            ttk.Radiobutton(game, text=label, value=value, variable=self.donor_game,
                            command=self._refresh_donors).pack(side="left", padx=(0, 10))
        # Sorting the list by measured fit is worth a button rather than being
        # automatic: it reads every donor model, which takes about ten seconds
        # for K2's 128, and most of the time the name is already known.
        self.rank_btn = ttk.Button(game, text="Rank for this host",
                                   command=self._rank_donors)
        self.rank_btn.pack(side="left", padx=(6, 0))
        ttk.Label(game, text="Show").pack(side="left", padx=(12, 4))
        self.donor_look = tk.StringVar(value=ANYONE)
        ttk.Combobox(game, textvariable=self.donor_look, width=10, state="readonly",
                     values=[ANYONE, "male", "female", "droid", "either", "unknown"],
                     ).pack(side="left")
        self.donor_look.trace_add("write", lambda *_: self._refresh_donors())
        self.donor_game_note = ttk.Label(game, text="", foreground="#666")
        self.donor_game_note.pack(side="left", padx=(8, 0))
        picker = ttk.Frame(page)
        picker.grid(row=3, column=0, columnspan=5, sticky="nsew", pady=(6, 0))
        picker.columnconfigure(0, weight=1)
        # A floor, not just a weight. The tab has a lot of controls competing
        # for the notebook's height, and without a minimum the gallery settled
        # at 142 pixels - one row of faces, which is the list problem again in
        # a different shape.
        # A floor so there is always at least a row of faces, and weight so it
        # takes everything spare - the tab's other controls need about 700
        # pixels, so browsing comfortably means a taller window, and maximising
        # gives three or four rows.
        page.rowconfigure(3, weight=1, minsize=160)
        # A grid, not a list. A list of 96-pixel rows shows four donors at a
        # time out of a hundred and forty-four; the same space holds about
        # twenty faces side by side, and picking a face is something the eye
        # does at a glance.
        from . import gallery as kgallery
        from . import thumbs as kthumbs

        self.donor_tree = kgallery.Gallery(
            picker, cell=kthumbs.SIZE, on_pick=self._on_donor_pick,
        )
        self.donor_tree.grid(row=0, column=0, columnspan=2, sticky="nsew")
        picker.rowconfigure(0, weight=1)
        # Tk drops an image the moment nothing references it, and a Treeview
        # does not count as a reference. Without this the rows go blank.
        self._donor_photos: dict[str, object] = {}
        self._thumb_job = 0

        self.donor_note = ttk.Label(
            page,
            text="The host keeps its hierarchy, skeleton and animations. Only geometry moves.",
            foreground="#666", wraplength=620,
        )
        self.donor_note.grid(row=4, column=0, columnspan=5, sticky="w", pady=(4, 0))

        self.show_all = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            page, text="Show every model, including bodies and ones that cannot pair",
            variable=self.show_all, command=self._refresh_donors,
        ).grid(row=10, column=0, columnspan=5, sticky="w", pady=(8, 0))

        opts = ttk.Frame(page)
        opts.grid(row=5, column=0, columnspan=5, sticky="w", pady=(8, 0))
        # Reshape used to be forced on, because a head's vertex count was
        # thought to be fixed. It is not - that was a stale pointer in our own
        # writer - so the donor now comes across whole by default, keeping its
        # own shape, UVs and texture.
        self.opt_automerge = tk.BooleanVar(value=True)
        self.opt_reshape = tk.BooleanVar(value=False)
        self.opt_texture = tk.BooleanVar(value=True)
        self.opt_hide = tk.BooleanVar(value=True)
        # Off by default: a donor head is the size it is meant to be, and
        # shrinking it to the host's box detaches it from the neck. Measured on
        # a Bith onto Carth - fitted it stands 0.242 tall and floats 0.019 above
        # the collar, left alone it stands 0.400 and meets it. `to_host_space`
        # made this argument about a Quarren long before the default agreed.
        self.opt_fit = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            opts, text="Take donor's texture", variable=self.opt_texture
        ).grid(row=0, column=0, sticky="w", padx=(0, 14))
        ttk.Checkbutton(
            opts, text="Hide parts the donor lacks", variable=self.opt_hide
        ).grid(row=0, column=1, sticky="w", padx=(0, 14))
        ttk.Checkbutton(
            opts, text="Shrink donor to the host's size (usually wrong - "
                       "a head is the size it is meant to be)",
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
        size.grid(row=6, column=0, columnspan=5, sticky="w", pady=(6, 0))
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

        saveas = ttk.Frame(page)
        saveas.grid(row=7, column=0, columnspan=5, sticky="w", pady=(8, 0))
        ttk.Button(saveas, text="Preview",
                   command=lambda: self._start(preview=True)).pack(side="left")
        ttk.Label(saveas, text="Save as").pack(side="left", padx=(16, 6))
        # Blank means overwrite the host, which is what every build did until
        # now. A name here makes a new model that sits beside the originals
        # instead of replacing one.
        self.save_as = tk.StringVar(value="")
        ttk.Entry(saveas, textvariable=self.save_as, width=22).pack(side="left")
        ttk.Label(saveas, text="a new resref, e.g. p_myhead - blank replaces the host",
                  foreground="#666").pack(side="left", padx=(8, 0))

        # How much a new character needs depends on what it is for, and the
        # three answers are genuinely different: a plain NPC edits no tables at
        # all, while a companion wants a portrait, henchman scripts and
        # NoPermDeath. Learned from two mods rather than guessed.
        who = ttk.Frame(page)
        who.grid(row=8, column=0, columnspan=5, sticky="w", pady=(6, 0))
        ttk.Label(who, text="Make it a").pack(side="left", padx=(0, 6))
        self.character_kind = tk.StringVar(value=NOT_A_CHARACTER)
        for label, value in ((NOT_A_CHARACTER, NOT_A_CHARACTER),
                             ("NPC", "npc"),
                             ("NPC that talks", "talker"),
                             ("companion", "companion")):
            ttk.Radiobutton(who, text=label, value=value,
                            variable=self.character_kind,
                            command=self._on_kind_change).pack(side="left", padx=(0, 10))
        ttk.Label(who, text="called").pack(side="left", padx=(10, 4))
        self.character_name = tk.StringVar(value="")
        ttk.Entry(who, textvariable=self.character_name, width=18).pack(side="left")
        self.character_note = ttk.Label(who, text="", foreground="#666")
        self.character_note.pack(side="left", padx=(8, 0))

        # What it wears. An appearance row carries a body model per equipment
        # slot, and the game uses the unequipped one for a character carrying
        # no clothes - which on a party member's row is their underwear. Carth
        # is the example: copy his row, equip nothing, and the character spawns
        # in `P_CarthBA`. Picking here fills every slot with one outfit, the
        # way vanilla NPCs do.
        wear = ttk.Frame(page)
        wear.grid(row=9, column=0, columnspan=5, sticky="w", pady=(6, 0))
        ttk.Label(wear, text="Wearing").pack(side="left", padx=(0, 6))
        self.outfit = tk.StringVar(value=SAME_AS_HOST)
        self.outfit_box = ttk.Combobox(wear, textvariable=self.outfit,
                                       width=34, state="readonly",
                                       values=[SAME_AS_HOST])
        self.outfit_box.pack(side="left")
        ttk.Label(wear, text="the game's whole wardrobe - one body in every "
                             "equipment slot, so it never undresses",
                  foreground="#666").pack(side="left", padx=(8, 0))
        ttk.Label(
            page,
            text=("Preview writes nothing - it draws the result on the Preview tab "
                  "and reports how solid the donor is. Under 76% reads as holes."),
            foreground="#666", wraplength=620,
        ).grid(row=11, column=0, columnspan=5, sticky="w", pady=(4, 0))

    # ---- shared bottom -----------------------------------------------------

    # ---- upcoming tab ------------------------------------------------------

    def _build_upcoming_tab(self):
        """What is coming, and what already works somewhere else.

        A roadmap in the app rather than in a file nobody opens. The status on
        each line is the useful part: several of these are finished and only
        missing a button, and someone waiting for a feature that already runs
        on the command line is waiting for nothing.
        """
        page = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(page, text="Upcoming")
        page.columnconfigure(0, weight=1)

        ttk.Label(
            page,
            text="Planned work. Nothing here has a button yet - where a line "
                 "says “command line only”, the command underneath "
                 "does it today. Run it from the project folder; the paths are "
                 "written so nothing has to be activated first.",
            foreground="#666", wraplength=640,
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))

        self.upcoming_rows = []
        for i, (title, status, blurb, command) in enumerate(UPCOMING, start=1):
            box = ttk.LabelFrame(page, text=f"{title}   -   {status}", padding=8)
            box.grid(row=i, column=0, sticky="ew", pady=(0, 8))
            box.columnconfigure(0, weight=1)
            ttk.Label(box, text=blurb, wraplength=620, foreground="#333").grid(
                row=0, column=0, sticky="w"
            )
            if command:
                entry = ttk.Entry(box)
                entry.insert(0, command)
                entry.configure(state="readonly")
                entry.grid(row=1, column=0, sticky="ew", pady=(6, 0))
            self.upcoming_rows.append((title, status))

    # ---- custom head tab ---------------------------------------------------

    def _build_head_tab(self):
        """Geometry from outside KOTOR, into one node.

        This was command-line only, which meant the app could not do the thing
        the project was originally built to do - put a sculpted or scanned head
        on a model. It is also the only route onto a unified body like HK-47
        whose head node takes a mesh directly.
        """
        page = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(page, text="Custom head")
        page.columnconfigure(1, weight=1)

        ttk.Label(page, text="Head pack").grid(row=0, column=0, sticky="w")
        self.pack_dir = tk.StringVar()
        ttk.Entry(page, textvariable=self.pack_dir).grid(
            row=0, column=1, columnspan=2, sticky="ew", padx=6)
        ttk.Button(page, text="Browse", command=self._pick_pack).grid(row=0, column=3)
        # A .glb was command-line only, which meant the one route in for
        # geometry the game never had - a sculpt, a scan, a generated head,
        # anything through Blender - was the one thing the window could not do.
        ttk.Button(page, text="Import .glb", command=self._import_glb).grid(
            row=0, column=4, padx=(6, 0))

        ttk.Label(page, text="Onto").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.head_host = tk.StringVar()
        self.head_host_box = ttk.Combobox(page, textvariable=self.head_host, values=[])
        self.head_host_box.grid(row=1, column=1, sticky="ew", padx=6, pady=(6, 0))
        self.head_host_box.bind("<<ComboboxSelected>>",
                                lambda _e: self._refresh_head_nodes())
        self.head_node = tk.StringVar()
        self.head_node_box = ttk.Combobox(page, textvariable=self.head_node,
                                          values=[], width=22)
        self.head_node_box.grid(row=1, column=2, sticky="ew", padx=6, pady=(6, 0))
        self.head_node_note = ttk.Label(page, text="", foreground="#666")
        self.head_node_note.grid(row=2, column=0, columnspan=5, sticky="w", pady=(4, 0))

        opts = ttk.Frame(page)
        opts.grid(row=3, column=0, columnspan=5, sticky="w", pady=(8, 0))
        self.head_decimate = tk.BooleanVar(value=True)
        self.head_fit = tk.BooleanVar(value=True)
        self.head_repair = tk.BooleanVar(value=True)
        self.head_hide = tk.BooleanVar(value=True)
        self.head_reshape = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="Decimate to", variable=self.head_decimate).grid(
            row=0, column=0, sticky="w")
        self.head_budget = tk.IntVar(value=690)
        ttk.Spinbox(opts, from_=200, to=4000, increment=10, width=6,
                    textvariable=self.head_budget).grid(row=0, column=1, sticky="w")
        ttk.Label(opts, text="triangles", foreground="#666").grid(
            row=0, column=2, sticky="w", padx=(4, 14))
        ttk.Checkbutton(opts, text="Fit to the node", variable=self.head_fit).grid(
            row=0, column=3, sticky="w", padx=(0, 14))
        ttk.Checkbutton(opts, text="Repair winding", variable=self.head_repair).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Checkbutton(opts, text="Hide the host's own hair, eyes and teeth",
                        variable=self.head_hide).grid(
            row=1, column=3, sticky="w", pady=(4, 0))
        ttk.Checkbutton(opts, text="Reshape: keep the host's topology and UVs",
                        variable=self.head_reshape).grid(
            row=2, column=0, columnspan=5, sticky="w", pady=(4, 0))

        crop = ttk.Frame(page)
        crop.grid(row=4, column=0, columnspan=5, sticky="w", pady=(6, 0))
        self.head_crop_on = tk.BooleanVar(value=False)
        ttk.Checkbutton(crop, text="Crop below", variable=self.head_crop_on).pack(
            side="left")
        self.head_crop = tk.DoubleVar(value=0.25)
        ttk.Spinbox(crop, from_=0.0, to=0.9, increment=0.05, width=6,
                    textvariable=self.head_crop).pack(side="left", padx=4)
        ttk.Label(crop, text="of the height - for a bust rather than a head",
                  foreground="#666").pack(side="left")

        ttk.Button(page, text="Check only", command=self._head_check).grid(
            row=5, column=0, sticky="w", pady=(10, 0))
        ttk.Label(
            page,
            text=("Checking writes nothing. A pack is rejected before anything is "
                  "built, and solidity below 77% is the one that matters - it "
                  "renders full of holes in game while looking fine in a viewer."),
            foreground="#666", wraplength=620,
        ).grid(row=6, column=0, columnspan=5, sticky="w", pady=(4, 0))

    # ---- character tab -----------------------------------------------------

    def _build_character_tab(self):
        """A character assembled out of parts the game already ships.

        No geometry is written here at all. A KOTOR humanoid is a base body, a
        clothed body per equipment slot and a row of `heads.2da`, and all three
        already exist - so a new character can be three table rows and a
        blueprint. That is the cheapest kind there is, and it is most of what
        anyone wants: the Transplant tab is for when no existing head will do.

        The three pickers sit in their own notebook rather than side by side.
        Three grids across this window is two faces each, and picking a face is
        something the eye does at a glance or not at all.
        """
        from . import gallery as kgallery
        from . import thumbs as kthumbs

        page = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(page, text="Character")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)

        self.part_pick = {k: tk.StringVar(value="") for k in PART_KINDS}
        self.part_labels = {k: {} for k in PART_KINDS}
        self.part_photos = {k: {} for k in PART_KINDS}
        self.part_jobs = {k: 0 for k in PART_KINDS}
        self.catalogue = None

        # What is chosen, always on screen. Flipping between three tabs to
        # remember what you picked is how a picker stops being one.
        chosen = ttk.LabelFrame(page, text="This character", padding=8)
        chosen.grid(row=0, column=0, sticky="ew")
        chosen.columnconfigure(1, weight=1)
        self.part_summary = {}
        for i, key in enumerate(PART_KINDS):
            ttk.Label(chosen, text=PART_TITLES[key]).grid(row=i, column=0,
                                                          sticky="w", padx=(0, 8))
            label = ttk.Label(chosen, text="nothing picked", foreground="#666")
            label.grid(row=i, column=1, sticky="w")
            self.part_summary[key] = label
        self.character_preview = ttk.Label(chosen, text="")
        self.character_preview.grid(row=0, column=2, rowspan=3, padx=(12, 0))
        self.character_warn = ttk.Label(chosen, text="", foreground="#a35",
                                        wraplength=520)
        self.character_warn.grid(row=3, column=0, columnspan=3, sticky="w",
                                 pady=(6, 0))

        inner = ttk.Notebook(page)
        inner.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        self.part_gallery = {}
        for key in PART_KINDS:
            frame = ttk.Frame(inner, padding=6)
            inner.add(frame, text=PART_TITLES[key])
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(1, weight=1)

            bar = ttk.Frame(frame)
            bar.grid(row=0, column=0, sticky="ew")
            ttk.Label(bar, text="Show").pack(side="left", padx=(0, 6))
            var = tk.StringVar(value=ANYONE)
            box = ttk.Combobox(bar, textvariable=var, width=12, state="readonly",
                               values=[ANYONE, "male", "female", "droid"])
            box.pack(side="left")
            box.bind("<<ComboboxSelected>>",
                     lambda _e, k=key: self._refresh_parts(k))
            setattr(self, f"part_filter_{key}", var)
            note = ttk.Label(bar, text="", foreground="#666")
            note.pack(side="left", padx=(10, 0))
            setattr(self, f"part_note_{key}", note)

            grid = kgallery.Gallery(frame, cell=kthumbs.SIZE,
                                    on_pick=lambda label, k=key:
                                    self._on_part_pick(k, label))
            grid.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
            self.part_gallery[key] = grid

        who = ttk.Frame(page)
        who.grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Label(who, text="Called").pack(side="left", padx=(0, 6))
        self.new_name = tk.StringVar(value="")
        ttk.Entry(who, textvariable=self.new_name, width=20).pack(side="left")
        ttk.Label(who, text="resref").pack(side="left", padx=(12, 6))
        self.new_resref = tk.StringVar(value="")
        ttk.Entry(who, textvariable=self.new_resref, width=16).pack(side="left")
        self.new_kind = tk.StringVar(value="npc")
        for text, value in (("NPC", "npc"), ("NPC that talks", "talker"),
                            ("companion", "companion")):
            ttk.Radiobutton(who, text=text, value=value,
                            variable=self.new_kind).pack(side="left", padx=(10, 0))

        ttk.Button(page, text="Create the character",
                   command=self._character_start).grid(row=3, column=0,
                                                       sticky="w", pady=(8, 0))
        ttk.Label(
            page,
            text=("Nothing here writes geometry - it is two table rows and a "
                  "blueprint, so it is the cheapest kind of character there is. "
                  "A tick means the game already puts that part on this body; "
                  "the rest are yours to try, which is the point of the tool."),
            foreground="#666", wraplength=780,
        ).grid(row=4, column=0, sticky="w", pady=(4, 0))

    # ---- filling the pickers ----------------------------------------------

    def _load_catalogue(self, install: str):
        """Read what the install offers, off the Tk thread."""
        if getattr(self, "_catalogue_for", None) == install:
            return
        self._catalogue_for = install

        def work():
            try:
                from . import wardrobe as kwardrobe
                from .library import ModelLibrary

                self.events.put(("catalogue", kwardrobe.build(
                    install, library=ModelLibrary(install))))
            except Exception as exc:  # noqa: BLE001
                self.events.put(("error", f"could not read the parts: {exc}"))

        threading.Thread(target=work, daemon=True).start()

    def _show_catalogue(self, cat):
        self.catalogue = cat
        self._say(f"{len(cat.bodies)} bodies, {len(cat.outfits)} outfits and "
                  f"{len(cat.heads)} heads to build a character from")
        for key in PART_KINDS:
            self._refresh_parts(key)

    def _part_items(self, key: str):
        """The parts on offer for one picker, best first."""
        cat = self.catalogue
        if cat is None:
            return []
        body = self.part_pick["body"].get()
        if key == "body":
            return list(cat.bodies)
        if key == "outfit":
            return cat.outfits_for(body or None)
        return cat.heads_for(body or None)

    def _refresh_parts(self, key: str):
        from . import who as kwho

        wanted = getattr(self, f"part_filter_{key}").get()
        body = self.part_pick["body"].get()
        items = self._part_items(key)
        if wanted != ANYONE:
            # Through the catalogue rather than the item, because an outfit is
            # a body model and has a sex, but is not the kind of object that
            # carries one.
            items = [i for i in items
                     if kwho.matches(self.catalogue.look_of(i), wanted)]

        labels = {}
        for item in items:
            mark = ""
            if key != "body" and body:
                seen = self.catalogue.pairs_with(
                    body, **{"head" if key == "head" else "outfit": item})
                mark = f"{SEEN_IN_GAME} " if seen else ""
            labels[f"{mark}{item.label}"] = item.model

        self.part_labels[key] = labels
        self.part_photos[key] = {k: v for k, v in self.part_photos[key].items()
                                 if k in labels}
        self.part_gallery[key].show(list(labels))
        getattr(self, f"part_note_{key}").config(
            text=f"{len(labels)} to choose from"
            + (f", {SEEN_IN_GAME} = the game already pairs it with this body"
               if key != "body" and body else ""))

        chosen = self.part_pick[key].get()
        for label, model in labels.items():
            if model == chosen:
                self.part_gallery[key].select(label)
                break
        self._draw_parts(key)

    def _draw_parts(self, key: str):
        """Faces and figures in the background, newest request wins."""
        self.part_jobs[key] += 1
        job = self.part_jobs[key]
        path = self.install.get().strip()
        wanted = dict(self.part_labels[key])
        if not path or not wanted:
            return

        def work():
            from pathlib import Path as _Path

            from . import textures as ktextures
            from . import thumbs as kthumbs
            from .library import ModelLibrary

            try:
                lib = ModelLibrary(path)
                look = ktextures.lookup_across([_Path(path)])
                for label, model in wanted.items():
                    if job != self.part_jobs[key]:
                        return
                    try:
                        mdl, mdx = lib.read(model)
                    except Exception:  # noqa: BLE001
                        continue
                    found = kthumbs.render(mdl, mdx, texture_lookup=look)
                    if found is not None:
                        self.events.put(
                            ("part_thumb", (key, job, label, str(found))))
            except Exception:  # noqa: BLE001
                return

        threading.Thread(target=work, daemon=True).start()

    def _show_part_thumb(self, key: str, job: int, label: str, path: str):
        if job != self.part_jobs[key] or label not in self.part_labels[key]:
            return
        try:
            photo = tk.PhotoImage(file=path)
        except tk.TclError:
            return
        self.part_photos[key][label] = photo
        self.part_gallery[key].set_image(label, photo)

    # ---- picking -----------------------------------------------------------

    def _on_part_pick(self, key: str, label: str):
        model = self.part_labels[key].get(label)
        if not model:
            return
        self.part_pick[key].set(model)

        # Picking a body re-sorts the other two and, if they are empty, fills
        # them with what the game already puts on it - so somebody who only
        # picks a body still ends up with a dressed character wearing a face.
        if key == "body":
            body = self.catalogue.body(model) if self.catalogue else None
            if body is not None:
                if not self.part_pick["outfit"].get() and body.outfits:
                    self.part_pick["outfit"].set(body.outfits[0].model)
                if not self.part_pick["head"].get() and body.heads:
                    first = next((h for h in self.catalogue.heads
                                  if h.row == body.heads[0]), None)
                    if first is not None:
                        self.part_pick["head"].set(first.model)
            for other in ("outfit", "head"):
                self._refresh_parts(other)

        self._update_character()

    def _update_character(self):
        cat = self.catalogue
        picked = {k: self.part_pick[k].get() for k in PART_KINDS}
        for key in PART_KINDS:
            self.part_summary[key].config(
                text=picked[key] or "nothing picked",
                foreground="#000" if picked[key] else "#666")

        # Say plainly when a combination is one the game never ships. It is
        # allowed - that is the whole point - but a Twi'lek head on a human
        # body can sit wrong, and finding that out in game is a slow way.
        odd = []
        if cat is not None and picked["body"]:
            if picked["head"] and not cat.pairs_with(picked["body"],
                                                     head=cat.head(picked["head"])):
                odd.append("head")
            if picked["outfit"] and not cat.pairs_with(
                    picked["body"], outfit=cat.outfit(picked["outfit"])):
                odd.append("outfit")
        self.character_warn.config(
            text=("Nothing in the game pairs this " + " or ".join(odd)
                  + f" with {picked['body']}. It will still build - check the "
                    "preview for a neck that does not meet its collar."
                  if odd else ""))
        self._draw_character()

    def _draw_character(self):
        """The figure as the game will draw it: the outfit, wearing the head.

        Not the base body. `race` is what the row declares, but what renders is
        the equipment-slot model - which is exactly how a character copied from
        Carth turned up in his underwear.
        """
        outfit = self.part_pick["outfit"].get()
        head = self.part_pick["head"].get()
        install = self.install.get().strip()
        if not install or not outfit:
            return
        self._character_job = getattr(self, "_character_job", 0) + 1
        job = self._character_job

        def work():
            from pathlib import Path as _Path

            from kmdlswap import layout as kl

            from . import render as krender
            from . import textures as ktextures
            from . import thumbs as kthumbs
            from .library import ModelLibrary

            try:
                lib = ModelLibrary(install)
                look = ktextures.lookup_across([_Path(install)])
                body = kl.parse(*lib.read(outfit))
                worn = kl.parse(*lib.read(head)) if head else None
                scene = krender.character(body, worn, texture_lookup=look)
                pixels = krender.render(scene, size=PREVIEW_SIZE, cull=True)
                # Beside the thumbnails rather than in the output folder: it is
                # a picture of a choice, not a build, and it would otherwise be
                # swept into whatever gets installed.
                out = _Path(kthumbs.cache_root()) / f"character_{job}.png"
                out.parent.mkdir(parents=True, exist_ok=True)
                krender.to_png(pixels, out)
                if job == self._character_job:
                    self.events.put(("character_drawn", (job, str(out))))
            except Exception:  # noqa: BLE001
                return          # a preview that will not draw is not an error

        threading.Thread(target=work, daemon=True).start()

    def _show_character(self, job: int, path: str):
        if job != getattr(self, "_character_job", 0):
            return
        try:
            photo = tk.PhotoImage(file=path)
        except tk.TclError:
            return
        self._character_photo = photo       # Tk drops an unreferenced image
        self.character_preview.config(image=photo)

    # ---- writing it --------------------------------------------------------

    def _character_start(self):
        if self.worker and self.worker.is_alive():
            return
        picked = {k: self.part_pick[k].get() for k in PART_KINDS}
        resref = self.new_resref.get().strip() or self.new_name.get().strip().lower()
        if not picked["body"]:
            self._say("pick a body first")
            return
        if not resref:
            self._say("a character needs a resref - it is the filename the game "
                      "spawns it by")
            return

        cfg = dict(
            resref=resref,
            name=self.new_name.get().strip() or resref,
            kind=self.new_kind.get(),
            body=picked["body"],
            outfit=picked["outfit"] or None,
            head=picked["head"] or None,
        )
        self.build_btn.config(state="disabled")
        self._say(f"\n=== {cfg['name']}: {picked['body']}"
                  + (f" in {picked['outfit']}" if picked["outfit"] else "")
                  + (f" with {picked['head']}" if picked["head"] else "") + " ===")
        self.worker = threading.Thread(
            target=self._character_work,
            args=(self.install.get().strip(), self.out_dir.get().strip(), cfg),
            daemon=True)
        self.worker.start()

    def _character_work(self, install, out_dir, cfg):
        try:
            from pathlib import Path as _Path

            from . import builds as kbuilds
            from . import character as kchar

            out = str(_Path(out_dir or ".") / f"character_{cfg['resref']}")
            ch = kchar.assemble(install, out, **cfg)
            lines = list(ch.notes)
            lines.extend(f"still yours: {x}" for x in ch.todo)
            kbuilds.adopt(out, {
                "kind": "character",
                "resref": cfg["resref"],
                "body": cfg["body"],
                "outfit": cfg["outfit"],
                "head": cfg["head"],
            })
            lines.append("Kept as a build, so it installs from the Builds tab.")
            self.events.put(("done_text", lines))
        except Exception as exc:  # noqa: BLE001
            self.events.put(("error", f"{type(exc).__name__}: {exc}"))

    # ---- lips tab ----------------------------------------------------------

    def _build_lips_tab(self):
        """A mouth for a conversation nobody recorded.

        Confirmed in game twice: a `.lip` plays with no `.wav` behind it, and
        26 generated files drove the broker's whole conversation. It was
        command-line only, which is a poor place for the one feature here that
        needs no model at all.
        """
        page = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(page, text="Lips")
        page.columnconfigure(1, weight=1)

        ttk.Label(page, text="Dialogue").grid(row=0, column=0, sticky="w")
        self.dlg_path = tk.StringVar()
        ttk.Entry(page, textvariable=self.dlg_path).grid(
            row=0, column=1, columnspan=2, sticky="ew", padx=6)
        ttk.Button(page, text="Browse", command=self._pick_dialogue).grid(
            row=0, column=3)

        # Optional, and the whole point is that it is optional. With recordings
        # each lip is made exactly as long as its own line; without them the
        # length is estimated from the word count, which is what made the
        # broker work at all.
        ttk.Label(page, text="Recordings").grid(row=1, column=0, sticky="w",
                                                pady=(6, 0))
        self.lip_audio = tk.StringVar()
        ttk.Entry(page, textvariable=self.lip_audio).grid(
            row=1, column=1, columnspan=2, sticky="ew", padx=6, pady=(6, 0))
        ttk.Button(page, text="Browse", command=self._pick_lip_audio).grid(
            row=1, column=3, pady=(6, 0))
        ttk.Label(page, text="optional - a folder of .wav or .mp3 named after "
                            "each line's VO_ResRef",
                  foreground="#666").grid(row=2, column=1, columnspan=3,
                                          sticky="w", padx=6)

        opts = ttk.Frame(page)
        opts.grid(row=3, column=0, columnspan=4, sticky="w", pady=(8, 0))
        # On by default: every line of the broker's dialogue had an empty
        # VO_ResRef, so with this off the tool would have written nothing and
        # said so. A dialogue that already names its VOs is the exception.
        self.lip_assign = tk.BooleanVar(value=True)
        self.lip_replies = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Name the lines that have no VO_ResRef",
                        variable=self.lip_assign).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(opts, text="Include the player's replies",
                        variable=self.lip_replies).grid(row=0, column=1,
                                                        sticky="w", padx=(16, 0))

        force = ttk.Frame(page)
        force.grid(row=4, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self.lip_force_on = tk.BooleanVar(value=False)
        ttk.Checkbutton(force, text="Force every line to",
                        variable=self.lip_force_on).pack(side="left")
        self.lip_seconds = tk.DoubleVar(value=3.0)
        ttk.Spinbox(force, from_=0.5, to=60.0, increment=0.5, width=6,
                    textvariable=self.lip_seconds).pack(side="left", padx=4)
        ttk.Label(force, text="seconds - for when the timing is known but the "
                             "recordings are not here",
                  foreground="#666").pack(side="left")

        ttk.Button(page, text="Write the lips", command=self._lips_start).grid(
            row=5, column=0, sticky="w", pady=(10, 0))
        ttk.Label(
            page,
            text=("Your dialogue is never edited. Lines given a VO_ResRef get one "
                  "in a copy written beside the lips, and installing that copy is "
                  "your call - the game will not use the new names until you do."),
            foreground="#666", wraplength=620,
        ).grid(row=6, column=0, columnspan=4, sticky="w", pady=(4, 0))
        ttk.Label(
            page,
            text=("Shipped voice lines are MP3 behind a WAV header and cannot be "
                  "timed; those fall back to an estimate rather than a confident "
                  "wrong length. Run them through SithCodec first."),
            foreground="#a35", wraplength=620,
        ).grid(row=7, column=0, columnspan=4, sticky="w", pady=(4, 0))

    def _pick_dialogue(self):
        chosen = filedialog.askopenfilename(
            title="Choose a dialogue",
            filetypes=[("Dialogue", "*.dlg"), ("All files", "*.*")])
        if chosen:
            self.dlg_path.set(chosen)

    def _pick_lip_audio(self):
        chosen = filedialog.askdirectory(title="Choose the folder of recordings")
        if chosen:
            self.lip_audio.set(chosen)

    def _lips_start(self):
        if self.worker and self.worker.is_alive():
            return
        source = self.dlg_path.get().strip()
        if not source:
            self._say("choose a dialogue file first")
            return

        # Read on the main thread and handed over as plain values, the way
        # every other job here does - Tk variables are not thread-safe.
        cfg = dict(
            assign=self.lip_assign.get(),
            replies=self.lip_replies.get(),
            audio=self.lip_audio.get().strip() or None,
            seconds=(self.lip_seconds.get() if self.lip_force_on.get() else None),
        )
        # Its own folder per dialogue, because a build is a folder and two
        # conversations' lips landing in one would install as a single lump.
        out = str(Path(self.out_dir.get().strip() or ".")
                  / f"lips_{Path(source).stem}")
        self.build_btn.config(state="disabled")
        self._say(f"\n=== lips for {Path(source).name} ===")
        self.worker = threading.Thread(
            target=self._lips_work, args=(source, out, cfg), daemon=True)
        self.worker.start()

    def _lips_work(self, source, out, cfg):
        try:
            from . import dialogue as kdlg

            def progress(n, total, vo):
                # The dispatcher counts from zero, and this counts lines
                # written, so hand back the index rather than the tally.
                self.events.put(("progress", (n - 1, total, f"{vo}.lip")))

            job = kdlg.run(source, out, progress=progress, **cfg)
            lines = kdlg.summarise(job, audio=cfg["audio"])

            if job.written:
                from . import builds as kbuilds

                kbuilds.adopt(out, {
                    "kind": "lips",
                    "dialogue": Path(source).name,
                    "lines": job.written,
                    "named": job.assigned,
                    "timed": job.timed,
                })
                lines.append("Kept as a build, so it can be installed from the "
                             "Builds tab.")
                if job.dialogue_copy:
                    lines.append(
                        "Installing it copies the updated dialogue too - the "
                        "lips are named after VO_ResRefs that only exist in "
                        "that copy, so they are no use apart. If your Override "
                        "already holds that dialogue it is reported as foreign "
                        "and not replaced until you say so."
                    )
            self.events.put(("done_text", lines))
        except Exception as exc:  # noqa: BLE001
            self.events.put(("error", f"{type(exc).__name__}: {exc}"))

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

        # A requested minimum, not the size it runs at: the row has weight, so
        # the viewport takes all the spare height. Asking for less leaves room
        # for the framing and zoom controls below it in the default window.
        self.viewport = kviewport.Viewport(page, size=280)
        self.viewport.grid(row=3, column=0, columnspan=3, sticky="nsew", pady=(8, 0))

        frame_row = ttk.Frame(page)
        frame_row.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        ttk.Label(frame_row, text="Frame").pack(side="left", padx=(0, 6))
        # Defaults to the head, because that is what a head swap changed and
        # what a preview is being consulted about. The whole figure is one
        # click away when the question is proportion instead.
        self.preview_frame = tk.StringVar(value="head")
        for label, value in (("head", "head"), ("whole model", "whole")):
            ttk.Radiobutton(frame_row, text=label, value=value,
                            variable=self.preview_frame,
                            command=self._apply_framing).pack(side="left", padx=(0, 8))

        ttk.Label(frame_row, text="Zoom").pack(side="left", padx=(14, 4))
        self.preview_zoom = tk.DoubleVar(value=1.0)
        ttk.Scale(frame_row, from_=0.35, to=6.0, variable=self.preview_zoom,
                  orient="horizontal", length=150,
                  command=lambda _=None: self._apply_zoom()).pack(side="left")
        self.zoom_label = ttk.Label(frame_row, text="1.0x", width=6)
        self.zoom_label.pack(side="left", padx=(4, 0))
        ttk.Label(frame_row, text="the wheel zooms too; drag to turn, "
                                  "double-click to reset",
                  foreground="#666").pack(side="left", padx=(10, 0))

        views = ttk.Frame(page)
        views.grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))
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
        self.preview_status.grid(row=6, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(
            page,
            text=("Drag to turn, wheel to zoom, double-click to reset. No animation, "
                  "so this cannot tell you whether a face still moves. A preview is "
                  "not proof."),
            foreground="#a35", wraplength=600,
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(4, 0))

    def _on_kind_change(self):
        kind = self.character_kind.get()
        self.character_note.config(text={
            NOT_A_CHARACTER: "",
            "npc": "a blueprint only - no portrait, no conversation",
            "talker": "wired for conversation; the .dlg is yours to write",
            "companion": "adds a portrait row, henchman scripts and NoPermDeath; "
                         "the recruit script is yours",
        }.get(kind, ""))

    def _apply_framing(self):
        """Point the camera at the head, or at the whole figure."""
        want = getattr(self, "preview_frame", None)
        focus = getattr(self, "_focus_bounds", None)
        whole = getattr(self, "_whole_bounds", None)
        if want is None:
            return
        if want.get() == "head" and focus is not None:
            self.viewport.bounds = focus
        elif whole is not None:
            self.viewport.bounds = whole
        self.viewport.repaint()

    def _apply_zoom(self):
        self.viewport.zoom = float(self.preview_zoom.get())
        self.zoom_label.config(text=f"{self.viewport.zoom:.1f}x")
        self.viewport.repaint()

    def _repaint_viewport(self):
        self.viewport.cull = self.preview_cull.get()
        self.viewport.repaint()

    def _donor_install_for_preview(self) -> str:
        """The second game, if one is configured - a preview should not go grey
        just because the texture came from there."""
        return self.install2.get().strip()

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
                # the game will use once both are in Override. A cross-game build
                # names one that lives only in the other install, so that is
                # searched too rather than drawn grey.
                lookup = ktextures.lookup_across(
                    [install, self._donor_install_for_preview()],
                    extra=[out_dir, *sorted(p for p in Path(out_dir).glob("*")
                                            if p.is_dir())],
                )
                cache = lookup.caches[0]

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
        chosen = filedialog.askdirectory(title="Pick the KOTOR II folder")
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

    def _donor_kinds(self, path: str) -> dict[str, str]:
        """What each model in an install can donate, worked out once.

        A couple of seconds of reading, against scrolling three hundred names
        to find the ones that are heads. Cached per install path.
        """
        if not path:
            return {}
        cache = getattr(self, "_kind_cache", {})
        if path not in cache:
            from .library import ModelLibrary, character_models, classify

            try:
                lib = ModelLibrary(path)
                cache[path] = classify(lib, character_models(path, lib))
            except Exception as exc:  # noqa: BLE001
                self._say(f"could not read that install: {exc}")
                cache[path] = {}
            self._kind_cache = cache
        return cache[path]

    def _head_donors(self, path: str) -> list[str]:
        """Models a head can be taken from, best kind first."""
        from .library import DONOR_KINDS

        kinds = self._donor_kinds(path)
        return sorted(n for n, k in kinds.items() if k in DONOR_KINDS)

    def _donors_for_host(self, path: str, host: str,
                         named_node: bool = False) -> list[str]:
        """What can be taken *from*, given what is being built *onto*.

        A body host wants bodies. Offering it heads was not a filter working
        too hard - it was the whole list being about heads, which is what the
        tool did until now.
        """
        from .library import DONOR_KINDS

        kinds = self._donor_kinds(path)
        if named_node:
            # Naming both nodes is the escape hatch for models the automatic
            # rules cannot pair: a kath hound and a bantha share no node names
            # and neither has a head, so neither is a donor by any other test.
            # Anything that draws something can give a part.
            return sorted(n for n, k in kinds.items() if k != "empty" and n != host)
        if kinds.get(host) == "body":
            return sorted(n for n, k in kinds.items() if k == "body" and n != host)
        return sorted(n for n, k in kinds.items() if k in DONOR_KINDS)

    def donor_choices(self) -> list[str]:
        """The labels currently offered, in order.

        The widget showing them is an implementation detail - it has been a
        combobox and is now a list of faces - so callers ask for the choices
        rather than reaching into it.
        """
        return list(self.donor_labels)

    def _on_donor_pick(self, label=None):
        if label:
            self.donor.set(label)
            self._refresh_donor_nodes()

    def _refresh_donor_nodes(self):
        """Offer the chosen donor's own mesh nodes."""
        box = getattr(self, "donor_node_box", None)
        if box is None:
            return
        donor = self._selected_donor()
        nodes = self._mesh_nodes(self._donor_install(), donor) if donor else []
        box.config(values=[AUTO_NODE] + nodes)
        if self.donor_node.get() not in ([AUTO_NODE] + nodes):
            self.donor_node.set(AUTO_NODE)

    def _mesh_nodes(self, path: str, model: str) -> list[str]:
        """A model's visible mesh nodes, cached; one model is cheap to read."""
        cache = getattr(self, "_mesh_cache", {})
        key = (path, model)
        if key not in cache:
            from kmdlswap import layout as kl

            from . import parts as kparts
            from .library import ModelLibrary

            try:
                layout = kl.parse(*ModelLibrary(path).read(model))
                cache[key] = [n.name for n in kparts.mesh_nodes(layout)]
            except Exception:  # noqa: BLE001
                cache[key] = []
            self._mesh_cache = cache
        return cache[key]

    def _fill_donor_tree(self):
        """Put the current labels in the list, then fetch faces for them."""
        tree = getattr(self, "donor_tree", None)
        if tree is None:
            return
        tree.show(self.donor_labels)

        # Drop the images for entries that are gone. They are only kept because
        # Tk collects an image nothing references, and without this the dict
        # grows by a whole list every time the filter changes.
        for gone in set(self._donor_photos) - set(self.donor_labels):
            del self._donor_photos[gone]

        # Reselect what was already chosen, so refiltering does not silently
        # drop the user's pick.
        current = self.donor.get()
        if current in self.donor_labels:
            tree.select(current)

        self._start_thumbs()

    def _start_thumbs(self):
        """Draw the faces in the background, newest request wins.

        The list changes whenever the filter or the game does, so a run that is
        no longer about the visible list has to stop rather than paint faces
        onto the wrong rows.
        """
        self._thumb_job += 1
        job = self._thumb_job
        path = self._donor_install()
        wanted = dict(self.donor_labels)
        if not path or not wanted:
            return

        def work():
            from pathlib import Path as _Path

            from . import textures as ktextures
            from . import thumbs as kthumbs
            from .library import ModelLibrary

            try:
                lib = ModelLibrary(path)
                look = ktextures.lookup_across([_Path(path)])
                for label, model in wanted.items():
                    if job != self._thumb_job:
                        return
                    try:
                        mdl, mdx = lib.read(model)
                    except Exception:  # noqa: BLE001
                        continue
                    found = kthumbs.render(mdl, mdx, texture_lookup=look)
                    if found is not None:
                        self.events.put(("thumb", (job, label, str(found))))
            except Exception:  # noqa: BLE001
                return          # a missing face is not worth interrupting anyone

        threading.Thread(target=work, daemon=True).start()

    def _load_wardrobe(self, install: str):
        """Read what the install already dresses people in, off the Tk thread.

        Reading `appearance.2da` through Override is quick, but the model
        library it is filtered against is not, and neither belongs on the
        thread drawing the window.
        """
        if getattr(self, "_wardrobe_for", None) == install:
            return
        self._wardrobe_for = install

        def work():
            try:
                from . import twoda as k2da
                from .library import ModelLibrary

                rack = k2da.outfits(install, library=ModelLibrary(install))
                self.events.put(("wardrobe", rack))
            except Exception:  # noqa: BLE001
                return          # the box keeps its one safe entry

        threading.Thread(target=work, daemon=True).start()

    def _show_wardrobe(self, rack):
        # The resref leads, because that is what goes in the table and what
        # `cfg.outfit` is parsed back out of; the example is there to say what
        # it looks like without rendering 117 bodies.
        self.outfit_box.config(values=[SAME_AS_HOST] + [
            f"{o.model}  ({o.example})" if o.example else o.model for o in rack
        ])
        self._say(f"{len(rack)} outfits available to wear")

    def _show_thumb(self, job: int, label: str, path: str):
        if job != self._thumb_job or label not in self.donor_labels:
            return
        try:
            photo = tk.PhotoImage(file=path)
        except tk.TclError:
            return
        # Tk collects an image with no live reference, and the widget does not
        # count as one; dropping this dict blanks every face.
        self._donor_photos[label] = photo
        self.donor_tree.set_image(label, photo)

    def _import_glb(self):
        """Turn a .glb into a pack folder and select it, in one step.

        The pack lands beside the builds rather than beside the .glb, because
        the source is usually somewhere temporary - a download, an export - and
        the thing worth keeping is what this makes of it.
        """
        if self.worker and self.worker.is_alive():
            return
        chosen = filedialog.askopenfilename(
            title="Choose a .glb",
            filetypes=[("glTF binary", "*.glb"), ("All files", "*.*")])
        if not chosen:
            return

        out = str(Path(self.out_dir.get().strip() or ".") / "packs"
                  / Path(chosen).stem)
        self.build_btn.config(state="disabled")
        self._say(f"\n=== importing {Path(chosen).name} ===")
        self.worker = threading.Thread(
            target=self._import_work, args=(chosen, out), daemon=True)
        self.worker.start()

    def _import_work(self, source, out):
        try:
            from . import glbimport

            result = glbimport.run(source, out)
            lines = glbimport.summarise(result, source)
            if not result.has_uvs:
                lines.append("Without UVs the head builds but renders "
                             "untextured. Re-export with a UV map.")
            # Selecting it is the point: the next thing anyone does with a
            # pack is build it, and retyping the path is the step that gets
            # skipped and then blamed on the importer.
            self.events.put(("imported", (out, lines)))
        except Exception as exc:  # noqa: BLE001
            self.events.put(("error", f"{type(exc).__name__}: {exc}"))

    def _pick_pack(self):
        chosen = filedialog.askdirectory(title="Choose a head pack folder")
        if chosen:
            self.pack_dir.set(chosen)

    def _refresh_head_nodes(self):
        """Which node the mesh goes into, defaulting to the head."""
        host = self.head_host.get().strip()
        nodes = self._host_mesh_nodes(host) if host else []
        self.head_node_box.config(values=nodes)
        if self.head_node.get() not in nodes:
            head = next((n for n in nodes if n.lower() == "head"), None)
            self.head_node.set(head or (nodes[0] if nodes else ""))
        if not nodes:
            self.head_node_note.config(text="")
            return
        # Whether the target is skinned decides how much the pack has to get
        # right, so it is worth saying before anything is built.
        skinned = self._node_is_skinned(host, self.head_node.get())
        if skinned is None:
            self.head_node_note.config(text="")
        elif skinned:
            self.head_node_note.config(
                text=f"{host}:{self.head_node.get()} is skinned - weights are "
                     f"transferred from the host's surface onto the new mesh")
        else:
            self.head_node_note.config(
                text=f"{host}:{self.head_node.get()} is not skinned, so the pack's "
                     f"own topology and UVs are used as they are - the easy case")

    def _node_is_skinned(self, host: str, node: str):
        if not host or not node:
            return None
        from kmdlswap import layout as kl

        from .library import ModelLibrary

        try:
            layout = kl.parse(*ModelLibrary(self.install.get().strip()).read(host))
            return bool(layout.node_by_name(node).is_skin)
        except Exception:  # noqa: BLE001
            return None

    def _head_check(self):
        self._head_start(build=False)

    def _head_start(self, build: bool):
        if self.worker and self.worker.is_alive():
            return
        pack = self.pack_dir.get().strip()
        if not pack:
            self._say("choose a head pack folder first")
            return
        host = self.head_host.get().strip()
        if build and not host:
            self._say("choose a model to build the head onto")
            return

        # Read on the main thread and handed over as plain values.
        cfg = dict(
            install=self.install.get().strip() or None,
            host=host or None,
            node=self.head_node.get().strip() or None,
            crop=(self.head_crop.get() if self.head_crop_on.get() else None),
            decimate=(self.head_budget.get() if self.head_decimate.get() else None),
            repair=self.head_repair.get(),
            fit=self.head_fit.get(),
            reshape=self.head_reshape.get(),
            hide=([] if self.head_hide.get() else None),
            build=build,
        )
        self.build_btn.config(state="disabled")
        self._say(f"\n=== {'building' if build else 'checking'} head pack "
                  f"{Path(pack).name}"
                  + (f" onto {host}:{cfg['node']}" if host else "") + " ===")
        self.worker = threading.Thread(
            target=self._head_work,
            args=(pack, cfg, self.out_dir.get(), build),
            daemon=True,
        )
        self.worker.start()

    def _head_work(self, pack, cfg, out_dir, build):
        try:
            from . import builds as kbuilds
            from . import headbuild

            result = headbuild.run(pack, **cfg)
            lines = list(result.lines)
            lines.append(result.verdict)
            if result.error:
                lines.append(f"ERROR: {result.error}")
            elif build and result.built:
                name = kbuilds.unique_name(
                    out_dir, f"{cfg['host']}-{Path(pack).name}")
                folder = Path(out_dir) / name
                folder.mkdir(parents=True, exist_ok=True)
                headbuild.write(result, folder, cfg["host"])
                kbuilds.adopt(folder, {
                    "kind": "head pack",
                    "host": {"model": cfg["host"], "node": result.node_name},
                    "pack": {"folder": str(pack), "name": getattr(result.pack, "name", "")},
                })
                lines.append(f"build {name!r} kept in {folder}")
                lines.append("Install it from the Builds tab. A build is not proof.")
            self.events.put(("done_text", lines))
        except Exception as exc:  # noqa: BLE001
            self.events.put(("error", f"{type(exc).__name__}: {exc}\n"
                                      f"{traceback.format_exc(limit=3)}"))

    def _host_mesh_nodes(self, host: str) -> list[str]:
        """The host's visible mesh nodes, cached; one model is cheap to read."""
        cache = getattr(self, "_node_cache", {})
        key = (self.install.get().strip(), host)
        if key not in cache:
            from kmdlswap import layout as kl

            from . import parts as kparts
            from .library import ModelLibrary

            try:
                lib = ModelLibrary(key[0])
                layout = kl.parse(*lib.read(host))
                cache[key] = [n.name for n in kparts.mesh_nodes(layout)]
            except Exception:  # noqa: BLE001
                cache[key] = []
            self._node_cache = cache
        return cache[key]

    def _refresh_target_nodes(self):
        """Offer this host's nodes, and say when naming one is the only way in.

        A unified body - HK-47, T3-M4 - carries its head as one node among
        forty-odd droid-named meshes. Whole-model pairing needs half the names
        to agree and so finds nothing, which reads as "this host cannot take a
        head" when in fact its head node is the easiest kind of target there is:
        rigid, unskinned, its own topology used as it stands.
        """
        host = self._selected_host()
        nodes = self._host_mesh_nodes(host) if host else []
        self.target_box.config(values=[WHOLE_MODEL] + nodes)
        if self.target_node.get() not in ([WHOLE_MODEL] + nodes):
            self.target_node.set(WHOLE_MODEL)

        if not host or not nodes:
            self.target_note.config(text="")
            return
        if self.target_node.get() != WHOLE_MODEL:
            self.target_note.config(
                text=f"one node of {len(nodes)}; the rest of {host} is left alone")
            return
        # Nothing pairs whole-model? Then say what will work instead.
        pairs_nothing = (self.index is not None and host in self.index.nodes
                         and not self.index.donors_for(host, usable_only=True))
        head = next((n for n in nodes if n.lower() == "head"), None)
        if pairs_nothing and head:
            self.target_note.config(
                text=f"{host} pairs with nothing whole-model - choose '{head}' "
                     f"to put a head on it")
        else:
            self.target_note.config(text="")

    def _donor_looks(self, path: str) -> dict[str, str]:
        """Male, female or droid for every model in an install, worked out once.

        Costs about the same as the kind classification next to it, and for the
        same reason: the droid test is structural, so the models have to be
        read rather than guessed at from their names.
        """
        if not path:
            return {}
        cache = getattr(self, "_look_cache", {})
        if path not in cache:
            from . import who

            try:
                cache[path] = who.looks(path, self._head_donors(path))
            except Exception as exc:  # noqa: BLE001
                self._say(f"could not sort donors by who they are: {exc}")
                cache[path] = {}
            self._look_cache = cache
        return cache[path]

    def _look_note(self, path: str) -> str:
        """Say when a filter is hiding things, so a short list is not a puzzle."""
        wanted = self.donor_look.get()
        if wanted == ANYONE:
            return ""
        total = len(self._head_donors(path))
        return f"; showing {wanted} only, of {total}"

    def _by_look(self, path: str, models: list[str]) -> list[str]:
        wanted = self.donor_look.get()
        if wanted == ANYONE:
            return models
        from . import who

        looks = self._donor_looks(path)
        # `who.matches` rather than equality, so a head that is deliberately
        # both - Revan's - shows up under male and under female alike.
        return [m for m in models if who.matches(looks.get(m, "unknown"), wanted)]

    def _donor_install(self) -> str:
        """Where donors are coming from, which game depends on the radio."""
        if self.donor_game.get() == "K2":
            return self.install2.get().strip()
        return self.install.get().strip()

    def _rank_donors(self):
        """Sort the donor list by how well each one will actually sit.

        Alphabetical order says nothing about which donors are worth building,
        and building one to find out costs minutes. This measures how far each
        donor's shape sits from the host's after fitting, which is exactly the
        thing that decides whether it comes out looking right or smashed.
        """
        if self.worker and self.worker.is_alive():
            return
        host = self._selected_host()
        if not host:
            self._say("choose a host first")
            return
        path = self._donor_install()
        if not path:
            self._say("set the donor's game folder first")
            return

        # Worked out here rather than in the worker: it reads Tk vars and can
        # log, and Tk is not safe to touch off the main thread.
        donors = self._head_donors(path)
        if not donors:
            self._say("no donors to measure in that folder")
            self.rank_btn.config(state="normal")
            return

        self.rank_btn.config(state="disabled")
        self._say(f"\nmeasuring {len(donors)} donors against {host} ...")
        self.worker = threading.Thread(
            target=self._rank_work,
            args=(host, path, self.install.get().strip(), donors),
            daemon=True,
        )
        self.worker.start()

    def _rank_work(self, host: str, donor_path: str, host_path: str, donors):
        try:
            from . import compat
            from .library import ModelLibrary

            host_lib = ModelLibrary(host_path)
            donor_lib = (host_lib if donor_path == host_path
                         else ModelLibrary(donor_path))

            def progress(i, total, name):
                if not i % 10:
                    self.events.put(("progress", (i, total, f"measuring {name}")))

            fits = compat.rank(*host_lib.read(host), donor_lib, donors,
                               host_name=host, progress=progress)
            self.events.put(("ranked", (host, donor_path, fits)))
        except Exception as exc:  # noqa: BLE001
            self.events.put(("rank_failed", f"{type(exc).__name__}: {exc}"))

    def _finish_rank(self, host, donor_path, fits):
        cache = getattr(self, "_rank_cache", {})
        cache[(host, donor_path)] = fits
        self._rank_cache = cache
        from . import compat

        self.rank_btn.config(state="normal")
        self._say(f"{len(fits)} donors measured: {compat.summarise(fits)}")
        best = [f for f in fits if not f.blocked][:3]
        if best:
            self._say("best fits: " + ", ".join(f"{f.donor} ({f.far:.1%})"
                                                for f in best))
        self._refresh_donors()

    def _ranked_labels(self, host: str, path: str, models: list[str]):
        """Donor labels in measured order, or None if nothing was measured."""
        fits = getattr(self, "_rank_cache", {}).get((host, path))
        if not fits:
            return None
        offered = set(models)
        labels = {}
        for f in fits:
            if f.donor not in offered:
                continue
            if f.blocked:
                labels[f"{f.donor}   [cannot: {f.blocked.split(' carries ')[-1]}]"] = f.donor
            else:
                marks = " +parts" if f.extra_parts else ""
                weights = " own-weights" if f.own_weights else ""
                labels[f"{f.donor}   [{f.grade} {f.far:.0%}{weights}{marks}]"] = f.donor
        # Anything the ranking never saw still belongs in the list.
        for name in models:
            if name not in labels.values():
                labels[f"{name}   [not measured]"] = name
        return labels

    def _refresh_donors(self):
        """Offer only donors that can actually pair with the chosen host."""
        self._refresh_target_nodes()

        # Filling one named node is a different question from swapping two
        # whole models, so it gets a different test. Coverage is meaningless
        # here - the donor only has to have a head worth taking - and applying
        # it anyway is what left HK-47 with an empty donor list.
        if self.target_node.get() != WHOLE_MODEL:
            path = self._donor_install()
            host = self._selected_host()
            models = self._by_look(
                path, self._donors_for_host(path, host, named_node=True))
            ranked = self._ranked_labels(host, path, models)
            kinds = self._donor_kinds(path)
            self.donor_labels = ranked or {
                f"{n}   [{kinds.get(n, 'head')}]": n for n in models
            }
            self._fill_donor_tree()
            self.donor_game_note.config(
                text=f"{len(models)} models have a head to give"
                     + (", best fit first" if ranked else "")
                     + self._look_note(path))
            return

        if self.donor_game.get() == "K2":
            path = self.install2.get().strip()
            kinds = self._donor_kinds(path)
            models = self._by_look(path, self._head_donors(path))
            ranked = self._ranked_labels(self._selected_host(), path, models)
            self.donor_labels = ranked or {f"{n}   [{kinds[n]}]": n for n in models}
            self._fill_donor_tree()
            self.donor_game_note.config(
                text=(f"{len(models)} of {len(kinds)} KOTOR II models have a head "
                      f"to give, best fit first" if ranked else
                      f"{len(models)} of {len(kinds)} KOTOR II models have a head "
                      f"to give; only geometry crosses over"
                      if models else "set the KOTOR II folder above")
            )
            return

        self.donor_game_note.config(text="")
        if self.index is None:
            return
        host = self._selected_host()
        if not host or host not in self.index.nodes:
            self.donor_labels = {}
            self._fill_donor_tree()
            return

        ranked = self.index.donors_for(host, usable_only=not self.show_all.get())
        if not self.show_all.get():
            # Head swapping is the job, so a body has nothing to offer even when
            # its node names happen to line up.
            kinds = self._donor_kinds(self.install.get().strip())
            from .library import DONOR_KINDS

            allowed = ({"body"} if kinds.get(host) == "body"
                       else set(DONOR_KINDS))
            ranked = [(c, n) for c, n in ranked
                      if kinds.get(n, "head") in allowed]
            keep = set(self._by_look(self.install.get().strip(),
                                     [n for _c, n in ranked]))
            ranked = [(c, n) for c, n in ranked if n in keep]
        measured = self._ranked_labels(host, self.install.get().strip(),
                                       [n for _c, n in ranked])
        self.donor_labels = measured or {c.label(n): n for c, n in ranked}
        self._fill_donor_tree()

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

    def _selected_host(self) -> str:
        """The model name behind the host label.

        The list shows `p_carthh   [head]` so the kind is visible while
        choosing rather than discovered afterwards - a head model and a
        creature take a swap very differently, and the names do not say which
        is which. Everything downstream wants the bare name.
        """
        raw = self.host.get().strip()
        if raw in self.host_labels:
            return self.host_labels[raw]
        return raw.split()[0] if raw else ""

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
        # Read here, on the main thread, and handed over as a plain string.
        # Reading it inside the worker survived only while the main loop
        # happened to be spinning; the moment it was not, the scan died with
        # "main thread is not in main loop" and the donor list stayed empty.
        self.worker = threading.Thread(
            target=self._scan_work, args=(self.install.get().strip(),), daemon=True
        )
        self.worker.start()

    def _scan_work(self, install: str):
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

            inst = Installation(install)
            found: dict[str, dict] = {}
            for r in inst.chitin_resources():
                if r.restype() in (ResourceType.MDL, ResourceType.MDX):
                    found.setdefault(r.resname().lower(), {})[r.restype()] = r
            # Not a prefix test: the player-creation and commoner heads do
            # not follow one, and leaving them out hid forty-two ordinary human
            # faces from every list in the app.
            from .library import ModelLibrary, character_models

            names = [n for n in character_models(install, ModelLibrary(install))
                     if n in found and len(found[n]) == 2]

            from .library import kind_of

            index = kc.ModelIndex()
            kinds: dict[str, str] = {}
            for i, name in enumerate(names):
                if i % 20 == 0:
                    self.events.put(("progress", (i, len(names), f"reading {name}")))
                e = found[name]
                try:
                    lay = kl.parse(e[ResourceType.MDL].data(), e[ResourceType.MDX].data())
                    if kv.check(lay).ok:
                        index.add(kc.describe(lay, name))
                        # Free: the layout is already in hand, and classifying
                        # separately would read all 233 models a second time.
                        kinds[name] = kind_of(lay)
                except Exception:  # noqa: BLE001, S112
                    continue
            self.events.put(("index", (index, kinds, install)))
        except Exception as exc:  # noqa: BLE001
            self.events.put(("error", f"{type(exc).__name__}: {exc}"))

    def _preview_effect(self):
        """Show what an effect does to a whole character, before building it.

        A body model alone renders headless and a head model alone renders as a
        floating head, so neither shows what bighead actually did. The body's
        `headhook` says where the head model goes; putting them together is the
        only view that answers the question.
        """
        if self.worker and self.worker.is_alive():
            return
        if not self._check_install():
            return
        picked = [k for k, v in self.selected.items() if v.get()]
        if not picked:
            messagebox.showinfo("kmdlfun", "Pick a companion to preview.")
            return

        self.viewport.clear("reading ...")
        self.worker = threading.Thread(
            target=self._effect_preview_work,
            args=(self.install.get().strip(), self.effect.get(),
                  picked[0], self.intensity.get()),
            daemon=True,
        )
        self.worker.start()

    def _effect_preview_work(self, install, effect_key, companion_key, intensity):
        try:
            from kmdlswap import layout as kl

            from . import apply as kapply
            from . import effects as keff
            from . import render as krender
            from . import roster
            from . import textures as ktextures
            from .library import ModelLibrary

            effect = keff.resolve(effect_key)
            scales = effect.scaled(intensity)
            companion = next(c for c in roster.COMPANIONS if c.key == companion_key)
            lib = ModelLibrary(install)
            cache = ktextures.TextureCache(install)

            # The body actually worn, and the face actually seen.
            present = [m for m in companion.models if lib.has(m)]
            cache_head = {m: kapply.is_head_model(kl.parse(*lib.read(m)))
                          for m in present}
            body_name, head_name = roster.default_look(present, cache_head.__getitem__)
            if body_name is None:
                self.events.put(("error", f"no body model found for {companion.name}"))
                return

            def scene(apply_effect: bool):
                parts = []
                for name in (body_name, head_name):
                    if name is None:
                        parts.append(None)
                        continue
                    mdl, mdx = lib.read(name)
                    if apply_effect:
                        mdl, mdx, _ = kapply.apply_to_model(
                            mdl, mdx, scales, model_name=name
                        )
                    parts.append(kl.parse(mdl, mdx))
                return krender.character(parts[0], parts[1], texture_lookup=cache.get)

            before, after = scene(False), scene(True)
            models = body_name + (f" + {head_name}" if head_name else "")
            note = (f"{effect.label} at {intensity:.2f}x on {companion.name}  -  "
                    f"{models}  -  nothing written")
            self.events.put((
                "scenes",
                ([before, after], [f"{companion.name} now", effect.label], note),
            ))
            self.events.put(("done_text", [
                f"previewed {effect.label} at {intensity:.2f}x on {companion.name}",
                f"  {models}",
            ]))
        except Exception as exc:  # noqa: BLE001
            self.events.put(("error", f"{type(exc).__name__}: {exc}\n"
                                      f"{traceback.format_exc(limit=3)}"))

    def _start(self, preview: bool = False):
        if self.worker and self.worker.is_alive():
            return
        if not self._check_install():
            return

        tab = self.tabs.tab(self.tabs.select(), "text")
        self.build_btn.config(state="disabled")
        self.progress.config(value=0, maximum=100)

        if tab == "Custom head":
            self.build_btn.config(state="normal")   # _head_start disables it itself
            self._head_start(build=True)
            return

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
            host, donor = self._selected_host(), self._selected_donor()
            if not host or not donor:
                messagebox.showinfo("kmdlfun", "Pick a host and a donor.")
                self.build_btn.config(state="normal")
                return
            target = ("" if self.target_node.get() == WHOLE_MODEL
                      else self.target_node.get())
            # Whole-model compatibility has nothing to say about filling one
            # named node, so it is only consulted when that is the actual job.
            if not target and self.index is not None and host in self.index.nodes:
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
                # Hiding "parts the donor lacks" means every host mesh that did
                # not pair. Whole-model that is a handful of stray accessories;
                # filling one node of a unified body it is the entire body, so
                # HK-47 would come out as a floating head.
                hide=self.opt_hide.get() and not target,
                target_node=target,
                donor_node=("" if self.donor_node.get() == AUTO_NODE
                            else self.donor_node.get()),
                save_as=self.save_as.get().strip(),
                character_kind=("" if self.character_kind.get() == NOT_A_CHARACTER
                                else self.character_kind.get()),
                character_name=self.character_name.get().strip(),
                outfit=("" if self.outfit.get() == SAME_AS_HOST
                        else self.outfit.get()),
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
            if cfg.target_node:
                # One named node. Pair it with the donor node of the same name
                # if there is one, and otherwise with the donor's head - which
                # is the whole point on a host whose names are its own.
                from . import compat as kcompat

                if cfg.donor_node:
                    pairs = [(cfg.target_node, cfg.donor_node)]
                else:
                    same = [p for p in pairs if p[0] == cfg.target_node]
                    if same:
                        pairs = same
                    else:
                        donor_head = kcompat.head_node(donor_layout)
                        if donor_head is None:
                            self.events.put(("error",
                                             f"{donor} has no node named "
                                             f"{cfg.target_node!r} and no head. "
                                             f"Choose which of its nodes to use "
                                             f"in the 'from' list."))
                            return
                        pairs = [(cfg.target_node, donor_head.name)]
            if not pairs:
                self.events.put(("error",
                                 f"{host} and {donor} share no mesh node names, "
                                 f"so there is nothing to move between them"))
                return

            lines = [lines_prefix] if lines_prefix else []
            if cfg.target_node:
                lines.append(f"filling {host}:{pairs[0][0]} from {donor}:{pairs[0][1]}"
                             f" - the rest of {host} is untouched")
            else:
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
            left = ([] if cfg.target_node else
                    [n.name for n in kparts.mesh_nodes(host_layout)
                     if n.name not in taken])
            if left:
                lines.append(f"donor has no: {', '.join(left)}"
                             + ("  (will hide)" if cfg.hide else ""))

            # Several parts of one donor have to keep their positions
            # *relative to each other*. Re-centring each on its own host
            # counterpart destroys that: Bastila's arm sits 0.15 closer to her
            # spine than Carth's does, so moving it onto his arm's centre
            # shoves it off the shoulder of the torso it arrived with. One
            # offset, taken from the biggest shared part, is applied to all of
            # them - which is exactly what `model_alignment` was written for
            # and was until now only used for the parts folded in.
            shared_offset = None
            if len(pairs) > 1 and anchor:
                shared_offset = ktp.model_alignment(
                    donor_layout, donor_layout.node_by_name(anchor[1]),
                    host_layout, host_layout.node_by_name(anchor[0]),
                )
                lines.append(
                    f"{len(pairs) - 1} part(s) follow {anchor[0]} rather than "
                    f"being placed on their own"
                )

            reshape = cfg.reshape
            ok = 0
            for i, (host_node, donor_node) in enumerate(pairs):
                self.events.put(("progress", (i, len(pairs), f"{host_node} <- {donor_node}")))
                # The anchor is placed, exactly as before: that is what puts
                # a donor head onto the host at all, and it is the path with
                # in-game evidence behind it. Every *other* part rides on the
                # anchor's offset instead of being re-centred on its own
                # counterpart, which is what was pulling arms off shoulders.
                is_anchor = (host_node, donor_node) == anchor
                offset = None if is_anchor else shared_offset
                new_mdl, new_mdx, r = ktp.transplant_node(
                    mdl, mdx, donor_layout, donor, host_node, donor_node,
                    # Not fitting still means putting it where the part it
                    # replaces sits. A donor left exactly where it was authored
                    # lands about 1.5 units away - inside the chest - which is
                    # never what anyone wanted.
                    fit=cfg.fit and offset is None,
                    place=(not cfg.fit) and offset is None,
                    model_offset=offset, scale=cfg.scale,
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
                    self._post_scenes(cfg.install, host, donor, mdl, mdx, lib,
                                      donor_install=cfg.donor_install)
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
            written_as = host
            if cfg.save_as:
                from kmdlswap import rename as krename

                try:
                    krename.check_name(cfg.save_as)
                    mdl, mdx = krename.rename(mdl, mdx, cfg.save_as)
                except krename.RenameError as exc:
                    self.events.put(("error", str(exc)))
                    return
                written_as = cfg.save_as
                lines.append(f"saved as {written_as}, a new model rather than a "
                             f"replacement for {host}")

            out = root / kbuilds.unique_name(root, f"{written_as}-{donor}")
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{written_as}.mdl").write_bytes(mdl)
            (out / f"{written_as}.mdx").write_bytes(mdx)
            if cfg.donor_install and cfg.with_texture:
                from . import textures as ktextures

                lines.extend(ktextures.export_donor_textures(
                    mdl, mdx, cfg.donor_install, out,
                    host_install=cfg.install,
                ))
            if cfg.character_kind:
                from . import character as kchar

                if not cfg.save_as:
                    lines.append("a character needs Save as filled in, so it has "
                                 "a model of its own to wear - skipped")
                else:
                    try:
                        ch = kchar.create(
                            cfg.install, out, resref=cfg.save_as,
                            kind=cfg.character_kind,
                            name=cfg.character_name or cfg.save_as,
                            model=written_as, like=host,
                            outfit=cfg.outfit.split(" ")[0] or None,
                        )
                        lines.extend(ch.notes)
                        lines.extend(f"still yours: {x}" for x in ch.todo)
                    except Exception as exc:  # noqa: BLE001
                        lines.append(f"could not make it a character: {exc}")

            build = kbuilds.adopt(out, {
                "kind": "transplant",
                "host": {"model": host, "game": host_layout.game,
                         "install": cfg.install},
                "saved_as": written_as,
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

    def _post_scenes(self, install, host, donor, mdl, mdx, lib, donor_install=""):
        """Draw the host as it is beside the host as it would be.

        Framed by one shared ruler, because two renders at two scales make a
        part that changed size look unchanged.

        A head model is drawn **on its body**. Alone it is a head floating in
        space, and size and placement - the two things a head swap most often
        gets wrong - are close to unjudgeable without a neck and shoulders to
        judge against. `appearance.2da` says which body a head is worn with; a
        self-contained model like HK-47 has no separate body and needs none.
        """
        from kmdlswap import layout as kl

        from . import apply as kapply
        from . import render as krender
        from . import textures as ktextures
        from .library import body_for_head

        look = ktextures.lookup_across([install, donor_install])
        host_layout = kl.parse(*lib.read(host))
        built_layout = kl.parse(mdl, mdx)

        body_layout = None
        body_name = None
        if kapply.is_head_model(host_layout):
            body_name = body_for_head(install, host, lib)
            if body_name:
                try:
                    body_layout = kl.parse(*lib.read(body_name))
                except Exception:  # noqa: BLE001
                    body_layout = None

        def draw(layout):
            if body_layout is None:
                return krender.from_layout(layout, texture_lookup=look)
            return krender.character(body_layout, layout, texture_lookup=look)

        before, after = draw(host_layout), draw(built_layout)
        worn = f" on {body_name}" if body_layout is not None else ""
        note = (f"{before.triangles} vs {after.triangles} triangles   -   "
                f"nothing written; this is what Build would produce")

        # Framing on the swapped part as well as the whole figure. A head on a
        # standing body is a few dozen pixels, which is not enough to judge the
        # thing the swap actually changed.
        focus = None
        try:
            if body_layout is not None:
                heads = [krender.place_head(body_layout, lay, texture_lookup=look)
                         for lay in (host_layout, built_layout)]
            else:
                heads = [krender.from_layout(lay, texture_lookup=look)
                         for lay in (host_layout, built_layout)]
            heads = [h for h in heads if h is not None and len(h.faces)]
            if heads:
                focus = krender.shared_bounds(heads)
        except Exception:  # noqa: BLE001
            focus = None

        self.events.put((
            "scenes",
            ([before, after], [f"{host}{worn} (now)", f"{host} <- {donor}{worn}"],
             note, focus),
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
                    scenes, labels, note, *rest = payload
                    self.viewport.set_scenes(scenes, labels)
                    self._focus_bounds = rest[0] if rest else None
                    self._whole_bounds = self.viewport.bounds
                    self._apply_framing()
                    self.preview_status.config(text=note)
                    # The viewport lives on the Preview tab, so put it in front
                    # rather than drawing where nobody is looking.
                    for i in range(len(self.tabs.tabs())):
                        if self.tabs.tab(i, "text") == "Preview":
                            self.tabs.select(i)
                            break
                elif kind == "index":
                    payload, kinds, scanned = payload
                    self.index = payload
                    self.models = payload.names
                    self.host_labels = {
                        (f"{n}   [{kinds[n]}]" if n in kinds else n): n
                        for n in self.models
                    }
                    self.host_box.config(values=list(self.host_labels))
                    self.preview_box.config(values=self.models)
                    self.head_host_box.config(values=self.models)
                    # The scan classified everything on its way past, so the
                    # donor list does not have to read the install again.
                    cache = getattr(self, "_kind_cache", {})
                    cache.setdefault(scanned, kinds)
                    self._kind_cache = cache
                    self._say(f"indexed {len(self.models)} character models")
                    self._load_wardrobe(scanned)
                    self._load_catalogue(scanned)
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
                elif kind == "catalogue":
                    self._show_catalogue(payload)
                elif kind == "part_thumb":
                    self._show_part_thumb(*payload)
                elif kind == "character_drawn":
                    self._show_character(*payload)
                elif kind == "imported":
                    pack, lines = payload
                    self.pack_dir.set(pack)
                    for line in lines:
                        self._say(line)
                    self.build_btn.config(state="normal")
                elif kind == "wardrobe":
                    self._show_wardrobe(payload)
                elif kind == "thumb":
                    self._show_thumb(*payload)
                elif kind == "ranked":
                    self._finish_rank(*payload)
                elif kind == "rank_failed":
                    self.rank_btn.config(state="normal")
                    self._say("could not rank donors: " + payload)
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
    root.geometry(f"{WINDOW_W}x{WINDOW_H}")
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
