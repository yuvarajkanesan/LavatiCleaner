"""Canvas-drawn primitives: Card, Btn, Pill, Check, Donut, StackBar, ScrollFrame, CheckTree."""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from . import theme


def rrect(cv, x1, y1, x2, y2, r, **kw):
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
           x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


def _mix(c1: str, c2: str, t: float) -> str:
    """Blend two #rrggbb colours (t=0 -> c1, t=1 -> c2). Tk has no alpha, so glows are faked this way."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


class Card(tk.Frame):
    """Rounded panel hosting `.body`. The frame sizes itself from its content (or fills what it is given)."""

    def __init__(self, master, pad=20, fill=None, outline=None, radius=14, stretch=False, bg=None, **kw):
        self.fill = fill or theme.CARD
        self._outline = outline or theme.BORDER
        self.radius = radius
        super().__init__(master, bg=bg or master.cget("bg"), bd=0, highlightthickness=0, **kw)
        self._bgc = tk.Canvas(self, bg=self.cget("bg"), highlightthickness=0, bd=0)
        self._bgc.place(x=0, y=0, relwidth=1, relheight=1)
        self.body = tk.Frame(self, bg=self.fill)
        self.body.pack(fill="both", expand=True, padx=pad, pady=pad)
        self._bgc.bind("<Configure>", self._draw)

    def _draw(self, e):
        c = self._bgc
        c.delete("all")
        rrect(c, 1, 1, e.width - 1, e.height - 1, self.radius, fill=self.fill, outline=self._outline)

    def set_fill(self, fill, outline=None):
        self.fill = fill
        self.body.configure(bg=fill)
        if outline:
            self._outline = outline
        self._bgc.itemconfigure("all", fill=fill, outline=self._outline)


class Btn(tk.Canvas):
    """Rounded button. kind: primary (amber) | ghost (outlined)."""

    def __init__(self, master, text, command=None, kind="ghost", padx=22, height=40, **kw):
        super().__init__(master, bg=master.cget("bg"), highlightthickness=0, bd=0, height=height, cursor="hand2", **kw)
        self.kind, self.command, self.enabled, self._hover = kind, command, True, False
        self.font = theme.F(10, True)
        self._padx, self._h = padx, height
        self._text = text
        self._pulse, self._phase = False, 0.0
        self._fit()
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", self._click)
        self.bind("<Configure>", lambda _e: self._draw())

    def _fit(self):
        w = tkfont.Font(font=self.font).measure(self._text) + 2 * self._padx
        self.configure(width=w)

    def configure_text(self, text):
        self._text = text
        self._fit()
        self._draw()

    def set_kind(self, kind: str):
        self.kind = kind
        self._draw()

    def start_pulse(self):
        """Breathing amber glow around the button: draws the eye to the one thing to press."""
        if not self._pulse:
            self._pulse = True
            self._tick()

    def stop_pulse(self):
        self._pulse = False
        self._draw()

    def _tick(self):
        if not self._pulse or not self.winfo_exists():
            return
        self._phase += 0.16
        self._draw()
        self.after(40, self._tick)

    def set_enabled(self, on: bool):
        self.enabled = on
        self.configure(cursor="hand2" if on else "arrow")
        self._draw()

    def _set_hover(self, v):
        self._hover = v
        self._draw()

    def _click(self, e):
        if self.enabled and self.command and 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height():
            self.command()

    def _draw(self):
        self.delete("all")
        w, h = max(self.winfo_width(), int(self.cget("width"))), self._h
        if self.kind == "primary":
            fill = theme.AMBER_HI if self._hover and self.enabled else theme.AMBER
            fill = fill if self.enabled else theme.AMBER_OFF
            fg, out = (theme.INK if self.enabled else theme.AMBER_OFF_FG), fill
        else:
            fill = theme.CARD_HI if self._hover and self.enabled else self.master.cget("bg")
            fg, out = (theme.TEXT if self.enabled else theme.FAINT), theme.BORDER
        inset = 0
        if self._pulse and self.enabled:
            import math
            t = (1 + math.sin(self._phase)) / 2
            glow = _mix(self.master.cget("bg"), theme.AMBER, 0.2 + 0.8 * t)
            rrect(self, 1, 1, w - 1, h - 1, 13, fill="", outline=glow, width=2)
            inset = 5
        rrect(self, 1 + inset, 1 + inset, w - 1 - inset, h - 1 - inset, 10, fill=fill, outline=out)
        self.create_text(w / 2, h / 2, text=self._text, font=self.font, fill=fg)


class Pill(tk.Canvas):
    def __init__(self, master, text, kind="safe", size=8, bg=None):
        fg = {"safe": theme.GREEN, "review": theme.AMBER, "advanced": theme.RED, "danger": theme.RED,
              "running": theme.RED, "muted": theme.MUTED, "keep": theme.GREEN}.get(kind, theme.MUTED)
        fill = {"safe": theme.GREEN_BG, "review": theme.AMBER_DIM, "advanced": theme.RED_BG, "danger": theme.RED_BG,
                "running": theme.RED_BG, "muted": theme.TRACK, "keep": theme.GREEN_BG}.get(kind, theme.TRACK)
        f = theme.F(size, True)
        w = tkfont.Font(font=f).measure(text) + 18
        h = tkfont.Font(font=f).metrics("linespace") + 8
        super().__init__(master, width=w, height=h, bg=bg or master.cget("bg"), highlightthickness=0, bd=0)
        rrect(self, 0, 0, w, h, h / 2, fill=fill, outline=fill)
        self.create_text(w / 2, h / 2, text=text, font=f, fill=fg)


class Check(tk.Canvas):
    """Amber checkbox. state: 'on' | 'off' | 'part'."""

    def __init__(self, master, state="off", command=None, disabled=False, size=20):
        super().__init__(master, width=size, height=size, bg=master.cget("bg"), highlightthickness=0, bd=0,
                         cursor="arrow" if disabled else "hand2")
        self.size, self.state, self.command, self.disabled = size, state, command, disabled
        self.bind("<ButtonRelease-1>", self._click)
        self._draw()

    def set(self, state):
        self.state = state
        self._draw()

    def _click(self, _e):
        if self.disabled:
            return
        self.set("off" if self.state == "on" else "on")
        if self.command:
            self.command(self.state == "on")

    def _draw(self):
        self.delete("all")
        s = self.size
        if self.state == "off":
            rrect(self, 1, 1, s - 1, s - 1, 5, fill=self.master.cget("bg"),
                  outline=theme.FAINT if not self.disabled else theme.BORDER, width=2)
            return
        rrect(self, 0, 0, s, s, 5, fill=theme.AMBER if not self.disabled else theme.AMBER_OFF, outline="")
        if self.state == "on":
            self.create_line(s * .27, s * .52, s * .43, s * .68, s * .74, s * .33, fill=theme.INK, width=2.4,
                             capstyle="round", joinstyle="round")
        else:
            self.create_line(s * .3, s * .5, s * .7, s * .5, fill=theme.INK, width=2.6, capstyle="round")


class Donut(tk.Canvas):
    def __init__(self, master, size=150, thickness=14, color=None):
        super().__init__(master, width=size, height=size, bg=master.cget("bg"), highlightthickness=0, bd=0)
        self.size, self.t, self.color = size, thickness, color or theme.BLUE
        self.set(0)

    def set(self, pct: float, sub="used"):
        self.delete("all")
        s, t = self.size, self.t
        box = (t / 2 + 1, t / 2 + 1, s - t / 2 - 1, s - t / 2 - 1)
        self.create_arc(*box, start=0, extent=359.9, style="arc", outline=theme.TRACK, width=t)
        if pct > 0:
            self.create_arc(*box, start=90, extent=-3.6 * pct, style="arc", outline=self.color, width=t)
        self.create_text(s / 2, s / 2 - 8, text=f"{pct:.0f}%", font=theme.F(18, True), fill=theme.TEXT)
        self.create_text(s / 2, s / 2 + 16, text=sub, font=theme.F(9), fill=theme.MUTED)


class StackBar(tk.Canvas):
    def __init__(self, master, height=10):
        super().__init__(master, height=height, bg=master.cget("bg"), highlightthickness=0, bd=0)
        self.segs: list[tuple[str, float]] = []
        self.bind("<Configure>", lambda _e: self._draw())

    def set(self, segs):
        self.segs = [(c, v) for c, v in segs if v > 0]
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), int(self.cget("height"))
        total = sum(v for _, v in self.segs)
        if not total or w < 10:
            rrect(self, 0, 0, w, h, h / 2, fill=theme.TRACK, outline="")
            return
        gap = 3
        avail = w - gap * (len(self.segs) - 1)
        x = 0.0
        for c, v in self.segs:
            nx = x + max(avail * v / total, 4)
            rrect(self, x, 0, nx, h, 3, fill=c, outline="")
            x = nx + gap


class ScrollFrame(tk.Frame):
    """Vertically scrolling frame (mouse wheel; thin scrollbar)."""

    def __init__(self, master, bg=None):
        bg = bg or master.cget("bg")
        super().__init__(master, bg=bg)
        self.cv = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.sb = ttk.Scrollbar(self, orient="vertical", command=self.cv.yview)
        self.cv.configure(yscrollcommand=self._set)
        self.sb.pack(side="right", fill="y")
        self.cv.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.cv, bg=bg)
        self._win = self.cv.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda _e: self.cv.configure(scrollregion=self.cv.bbox("all")))
        self.cv.bind("<Configure>", lambda e: self.cv.itemconfigure(self._win, width=e.width))
        self.bind("<Enter>", lambda _e: self.bind_all("<MouseWheel>", self._wheel))
        self.bind("<Leave>", lambda _e: self.unbind_all("<MouseWheel>"))

    def _set(self, a, b):
        self.sb.set(a, b)
        if float(a) <= 0 and float(b) >= 1:
            self.sb.pack_forget()
        elif not self.sb.winfo_ismapped():
            self.sb.pack(side="right", fill="y", before=self.cv)

    def _wheel(self, e):
        if self.inner.winfo_reqheight() > self.cv.winfo_height():
            self.cv.yview_scroll(int(-e.delta / 120) * 2, "units")

    def clear(self):
        for w in self.inner.winfo_children():
            w.destroy()
        self.cv.yview_moveto(0)


class CheckTree(ttk.Treeview):
    """Dark Treeview with ☑/☐ rows (used for long lists where widget rows would be too heavy)."""

    ON, OFF = "☑", "☐"

    def __init__(self, master, columns=(), headings=None, widths=None, **kw):
        super().__init__(master, columns=columns, selectmode="browse", **kw)
        self._state: dict[str, bool] = {}
        self._label: dict[str, str] = {}
        self.on_change = None
        headings, widths = headings or {}, widths or {}
        self.heading("#0", text=headings.get("#0", ""), anchor="w")
        self.column("#0", width=widths.get("#0", 360), stretch=True)
        for c in columns:
            self.heading(c, text=headings.get(c, c), anchor="w")
            self.column(c, width=widths.get(c, 100), anchor="e" if c == "size" else "w", stretch=False)
        self.bind("<Button-1>", self._click, add="+")
        self.bind("<space>", lambda _e: self._toggle_sel())

    def add(self, iid, label, values=(), checked=False):
        self._state[iid] = checked
        self._label[iid] = label
        self.insert("", "end", iid=iid, text=self._text(iid), values=values)

    def clear(self):
        self.delete(*self.get_children())
        self._state.clear()
        self._label.clear()

    def _text(self, iid):
        return f"{self.ON if self._state[iid] else self.OFF}  {self._label[iid]}"

    def checked(self):
        return [i for i, v in self._state.items() if v]

    def toggle(self, iid):
        self._state[iid] = not self._state[iid]
        self.item(iid, text=self._text(iid))
        if self.on_change:
            self.on_change()

    def _toggle_sel(self):
        sel = self.selection()
        if sel:
            self.toggle(sel[0])
        return "break"

    def _click(self, e):
        if self.identify_region(e.x, e.y) == "tree":
            iid = self.identify_row(e.y)
            if iid:
                self.selection_set(iid)
                self.toggle(iid)
                return "break"


class Segmented(tk.Frame):
    """Pill-style option picker: Segmented(parent, [("light", "Light"), ...], value, on_change)."""

    def __init__(self, master, options, value, on_change):
        super().__init__(master, bg=master.cget("bg"))
        self.value, self.on_change, self.labels = value, on_change, {}
        for key, text in options:
            b = tk.Label(self, text=text, font=theme.F(10), padx=16, pady=7, cursor="hand2", bd=0)
            b.pack(side="left", padx=(0, 8))
            b.bind("<Button-1>", lambda _e, k=key: self._pick(k))
            self.labels[key] = b
        self._paint()

    def _paint(self):
        for k, b in self.labels.items():
            on = k == self.value
            b.configure(bg=theme.AMBER_DIM if on else self.master.cget("bg"), fg=theme.AMBER if on else theme.MUTED,
                        highlightthickness=1, highlightbackground=theme.AMBER if on else theme.BORDER)

    def _pick(self, key):
        if key != self.value:
            self.value = key
            self._paint()
            self.on_change(key)
