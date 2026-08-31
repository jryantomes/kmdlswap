"""A draggable 3D view, as a Tk widget.

Wraps `render` in a canvas you can turn with the mouse. The only interesting
thing here is the quality switch: dragging redraws without supersampling, and a
moment after you let go it redraws properly. Rendering is synchronous on the UI
thread, so motion events are coalesced into one repaint - without that, Tk
queues a frame per mouse move and the view lags further behind the longer you
drag.

The widget owns no model knowledge. It is handed finished `Scene` objects and
draws them; loading and parsing stay in the worker thread that owns those.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import render as krender

DRAFT_MAX = 320          # cap the draft resolution so dragging stays responsive
SETTLE_MS = 140          # quiet period before the full-quality redraw
LABEL_FILL = "#c8ccd4"


class Viewport(ttk.Frame):
    def __init__(self, master, *, size: int = 440, **kw):
        super().__init__(master, **kw)
        self.size = size
        self.canvas = tk.Canvas(
            self, width=size, height=size, highlightthickness=0,
            background=_hex(krender.BACKGROUND),
        )
        self.canvas.pack(fill="both", expand=True)

        self.scenes: list = []
        self.labels: list[str] = []
        self.bounds = None
        self.yaw = 0.0
        self.pitch = 0.0
        self.zoom = 1.0
        self.cull = False

        self._photo = None       # Tk drops an image that nothing references
        self._drag = None
        self._pending = None
        self._settle = None
        self._message = "Pick a model and press Show"

        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Double-Button-1>", lambda _e: self.reset())
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Configure>", lambda _e: self._request(draft=True))
        self._paint_message()

    # ---- content -----------------------------------------------------------

    def set_scenes(self, scenes, labels=None) -> None:
        self.scenes = list(scenes)
        self.labels = list(labels or [])
        self.bounds = krender.shared_bounds(self.scenes)
        self._message = "" if self.scenes else "nothing to draw"
        self._request(draft=False)

    def clear(self, message: str = "") -> None:
        self.scenes = []
        self.bounds = None
        self._message = message
        self._paint_message()

    def repaint(self) -> None:
        """Redraw at full quality without moving the camera."""
        self._request(draft=False)

    def reset(self) -> None:
        self.yaw = self.pitch = 0.0
        self.zoom = 1.0
        self._request(draft=False)

    def look(self, yaw_degrees: float, pitch_degrees: float = 0.0) -> None:
        import math

        self.yaw = math.radians(yaw_degrees)
        self.pitch = math.radians(pitch_degrees)
        self._request(draft=False)

    # ---- interaction -------------------------------------------------------

    def _press(self, event):
        self._drag = (event.x, event.y)

    def _motion(self, event):
        if self._drag is None:
            return
        dx = event.x - self._drag[0]
        dy = event.y - self._drag[1]
        self._drag = (event.x, event.y)
        self.yaw += dx * 0.012
        self.pitch = max(-1.45, min(1.45, self.pitch + dy * 0.012))
        self._request(draft=True)

    def _release(self, _event):
        self._drag = None
        self._request(draft=False)

    def _wheel(self, event):
        step = 1.1 if event.delta > 0 else 1 / 1.1
        self.zoom = max(0.35, min(6.0, self.zoom * step))
        self._request(draft=True)

    # ---- painting ----------------------------------------------------------

    def _request(self, *, draft: bool) -> None:
        """Coalesce repaints: many mouse moves, one frame."""
        if self._settle is not None:
            self.after_cancel(self._settle)
            self._settle = None
        if not draft:
            if self._pending is None:
                self._pending = self.after(1, lambda: self._paint(draft=False))
            return
        if self._pending is None:
            self._pending = self.after(1, lambda: self._paint(draft=True))
        self._settle = self.after(SETTLE_MS, lambda: self._paint(draft=False))

    def _paint(self, *, draft: bool) -> None:
        self._pending = None
        if not self.scenes:
            self._paint_message()
            return
        from PIL import Image, ImageTk

        box = max(120, min(self.canvas.winfo_width(), self.canvas.winfo_height()))
        if len(self.scenes) > 1:
            box = max(120, self.canvas.winfo_width() // len(self.scenes) - 8)
            box = min(box, self.canvas.winfo_height())
        size = min(box, DRAFT_MAX) if draft else box

        pixels = krender.strip(
            self.scenes, yaw=self.yaw, pitch=self.pitch, zoom=self.zoom,
            size=size, bounds=self.bounds, supersample=1 if draft else 2,
            cull=self.cull,
        )
        image = Image.fromarray(pixels, mode="RGB")
        if size != box:                      # draft was rendered small; scale up
            image = image.resize(
                (image.width * box // size, image.height * box // size),
                Image.NEAREST,
            )

        self._photo = ImageTk.PhotoImage(image)
        self.canvas.delete("all")
        cw = self.canvas.winfo_width() or image.width
        ch = self.canvas.winfo_height() or image.height
        self.canvas.create_image(cw // 2, ch // 2, image=self._photo)

        for i, label in enumerate(self.labels[: len(self.scenes)]):
            x = (cw - image.width) // 2 + (image.width // len(self.scenes)) * i
            x += image.width // (2 * len(self.scenes))
            self.canvas.create_text(
                x, (ch + image.height) // 2 - 14, text=label,
                fill=LABEL_FILL, font=("Segoe UI", 9),
            )

    def _paint_message(self) -> None:
        self.canvas.delete("all")
        self.canvas.create_text(
            (self.canvas.winfo_width() or self.size) // 2,
            (self.canvas.winfo_height() or self.size) // 2,
            text=self._message, fill="#7a808c", font=("Segoe UI", 10),
        )


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(int(c * 255 + 0.5) for c in rgb)
