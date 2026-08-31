"""A grid of faces to pick a donor from.

The donor list was a combobox of names, then a list of names with a face beside
each. Both were the wrong shape for the job. A name does not say what a face
looks like, and a vertical list of 96-pixel rows shows four of them at a time
out of a hundred and forty-four - so choosing meant scrolling past almost
everything.

Faces belong in a grid. The same vertical space holds about twenty of them, and
picking a face is a thing the eye does at a glance rather than by reading.

The widget knows nothing about models or textures. It is handed labels in
order, hands back the one that was clicked, and accepts images whenever they
arrive - which matters because they are drawn on a worker and land one at a
time.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

CELL_PAD = 8
LABEL_H = 16
SELECT_FILL = "#2d5c8a"
SELECT_OUTLINE = "#7fb4e8"
TEXT_FILL = "#dddddd"


class Gallery(ttk.Frame):
    def __init__(self, master, *, cell: int = 96, on_pick=None, **kw):
        super().__init__(master, **kw)
        self.cell = cell
        self.on_pick = on_pick

        # Ask for one row. A Canvas with no size asks for Tk's default, which
        # is a couple of hundred pixels and quietly made this the tallest thing
        # in the window - the row's weight is what actually sizes it, so the
        # request only needs to be a floor.
        self.canvas = tk.Canvas(
            self, highlightthickness=0, background="#1e1e1e",
            width=(cell + CELL_PAD * 2) * 4,
            height=cell + CELL_PAD * 2 + LABEL_H,
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        bar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=bar.set)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.labels: list[str] = []
        self.selected: str | None = None
        self._images: dict[str, object] = {}
        self._columns = 0

        self.canvas.bind("<Configure>", lambda _e: self._relayout())
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<MouseWheel>", self._wheel)

    # ---- content -----------------------------------------------------------

    def show(self, labels) -> None:
        """Replace the contents. `labels` is an ordered iterable of strings."""
        self.labels = list(labels)
        if self.selected not in self.labels:
            self.selected = None
        # Images for rows that are gone would otherwise accumulate; Tk only
        # keeps an image alive while something references it, so this dict is
        # both the cache and the leak.
        self._images = {k: v for k, v in self._images.items() if k in self.labels}
        self._relayout()

    def set_image(self, label: str, photo) -> None:
        if label in self.labels:
            self._images[label] = photo
            self._relayout()

    def select(self, label: str) -> None:
        if label in self.labels:
            self.selected = label
            self._relayout()
            self._scroll_to(self.labels.index(label))

    # ---- geometry ----------------------------------------------------------

    def _step(self) -> int:
        return self.cell + CELL_PAD * 2

    def _click(self, event):
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        step = self._step()
        col = int(x // step)
        row = int(y // (step + LABEL_H))
        if col < 0 or col >= max(1, self._columns):
            return
        i = row * max(1, self._columns) + col
        if 0 <= i < len(self.labels):
            self.selected = self.labels[i]
            self._relayout()
            if self.on_pick is not None:
                self.on_pick(self.selected)

    def _wheel(self, event):
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def _scroll_to(self, index: int) -> None:
        if not self._columns:
            return
        step = self._step() + LABEL_H
        total = max(1, self.canvas.bbox("all")[3] if self.canvas.bbox("all") else 1)
        top = (index // self._columns) * step
        self.canvas.yview_moveto(max(0.0, min(1.0, top / total)))

    def _relayout(self) -> None:
        self.canvas.delete("all")
        if not self.labels:
            self.canvas.create_text(
                (self.canvas.winfo_width() or 200) // 2, 40,
                text="No donors to show", fill="#888", font=("Segoe UI", 9),
            )
            self.canvas.configure(scrollregion=(0, 0, 0, 0))
            return

        step = self._step()
        width = max(step, self.canvas.winfo_width() or step * 4)
        self._columns = max(1, width // step)
        row_h = step + LABEL_H

        for i, label in enumerate(self.labels):
            col, row = i % self._columns, i // self._columns
            x, y = col * step, row * row_h

            if label == self.selected:
                self.canvas.create_rectangle(
                    x + 2, y + 2, x + step - 2, y + row_h - 2,
                    fill=SELECT_FILL, outline=SELECT_OUTLINE,
                )

            photo = self._images.get(label)
            if photo is not None:
                self.canvas.create_image(x + step // 2, y + CELL_PAD + self.cell // 2,
                                         image=photo)
            else:
                self.canvas.create_rectangle(
                    x + CELL_PAD, y + CELL_PAD,
                    x + CELL_PAD + self.cell, y + CELL_PAD + self.cell,
                    outline="#333", fill="#252525",
                )

            # The model name is what identifies it; the grade and marks are in
            # the full label and would not fit under a 96-pixel cell.
            self.canvas.create_text(
                x + step // 2, y + step + LABEL_H // 2 - 2,
                text=label.split()[0][:16], fill=TEXT_FILL, font=("Segoe UI", 8),
            )

        rows = (len(self.labels) + self._columns - 1) // self._columns
        self.canvas.configure(scrollregion=(0, 0, self._columns * step, rows * row_h))
