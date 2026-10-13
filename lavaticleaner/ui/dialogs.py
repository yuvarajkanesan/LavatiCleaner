"""Modal dialogs: confirm, progress (with cancel), result (with undo)."""
from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import ttk

from . import theme
from .theme import F, M, label
from .widgets import Btn, Card, Check, rrect


class Modal(tk.Toplevel):
    def __init__(self, app, title, width=520):
        super().__init__(app)
        self.app = app
        self.title(title)
        self.configure(bg=theme.CARD)
        self.transient(app)
        self.resizable(False, False)
        self.body = tk.Frame(self, bg=theme.CARD)
        self.body.pack(fill="both", expand=True, padx=28, pady=26)
        self._width = width

    def present(self):
        self.update_idletasks()
        theme.dark_titlebar(self)
        h = self.winfo_reqheight()
        x = self.app.winfo_rootx() + (self.app.winfo_width() - self._width) // 2
        y = self.app.winfo_rooty() + max((self.app.winfo_height() - h) // 3, 20)
        self.geometry(f"{self._width}x{h}+{max(x, 0)}+{max(y, 0)}")
        self.grab_set()
        self.focus_set()


def _toggle_row(parent, text, sub, var_value, command=None, bg=None):
    bg = bg or theme.CARD
    row = tk.Frame(parent, bg=bg)
    chk = Check(row, "on" if var_value else "off", command=command)
    chk.pack(side="left", anchor="n", padx=(0, 12), pady=2)
    col = tk.Frame(row, bg=bg)
    col.pack(side="left", fill="x", expand=True)
    label(col, text, 10, fg=theme.TEXT, bg=bg, justify="left", wraplength=420, anchor="w").pack(anchor="w")
    if sub:
        label(col, sub, 9, fg=theme.MUTED, bg=bg, justify="left", wraplength=420, anchor="w").pack(anchor="w")
    return row, chk


def _notice(parent, text, kind="warn"):
    fg, bg = (theme.AMBER, theme.WARN_BG) if kind == "warn" else (theme.RED, theme.RED_BG)
    c = Card(parent, pad=12, fill=bg, outline=theme.WARN_BORDER if kind == "warn" else theme.RED_BORDER, radius=10, bg=theme.CARD)
    label(c.body, "⚠", 12, fg=fg, bg=bg).pack(side="left", anchor="n", padx=(0, 10))
    label(c.body, text, 10, fg=fg, bg=bg, wraplength=420, justify="left", anchor="w").pack(side="left", fill="x")
    return c


class ConfirmDialog(Modal):
    """result: None (cancelled) or {"dry_run": bool, "keep": bool}"""

    def __init__(self, app, rows, files, size, review_labels, dry_run_default, keep_option, recycle_files, keep_days):
        super().__init__(app, "Confirm clean", width=560)
        self.result = None
        b = self.body
        label(b, f"Clean {theme.fmt_size(size)}?", 17, True).pack(anchor="w")
        label(b, f"{theme.fmt_count(files)} files across {len(rows)} items will be removed.", 10,
              fg=theme.MUTED).pack(anchor="w", pady=(2, 14))
        for lab, n, sz in rows[:9]:
            r = tk.Frame(b, bg=theme.CARD)
            r.pack(fill="x", pady=5)
            label(r, lab, 10).pack(side="left")
            label(r, theme.fmt_size(sz), 10, True, mono=True).pack(side="right")
            label(r, f"{theme.fmt_count(n)} files", 9, fg=theme.MUTED, mono=True).pack(side="right", padx=(0, 22))
            tk.Frame(b, bg=theme.BORDER, height=1).pack(fill="x")
        if len(rows) > 9:
            label(b, f"…and {len(rows) - 9} more items", 9, fg=theme.MUTED).pack(anchor="w", pady=4)

        self.keep = keep_option
        if keep_option:
            row, chk = _toggle_row(b, f"Keep a restorable copy of logs and crash dumps for {keep_days} days",
                                   "Caches and temp files are rebuilt by Windows, so they are not kept.",
                                   True, command=lambda v: setattr(self, "keep", v))
            row.pack(fill="x", pady=(16, 0))
        if recycle_files:
            _notice(b, f"The Recycle Bin will be emptied. Its {theme.fmt_count(recycle_files)} files cannot be "
                       "restored afterward.").pack(fill="x", pady=(14, 0))

        self.ack = not review_labels
        if review_labels:
            names = ", ".join(review_labels[:4]) + (f" and {len(review_labels) - 4} more" if len(review_labels) > 4 else "")
            row, chk = _toggle_row(b, "I understand these items need a closer look: " + names,
                                   "Windows and your apps can rebuild most of them, but check the list first.",
                                   False, command=lambda v: (setattr(self, "ack", v), self._sync()))
            row.pack(fill="x", pady=(14, 0))

        self.dry = dry_run_default
        row, chk = _toggle_row(b, "Dry run: show what would be removed and delete nothing",
                               ("Preview only: nothing is deleted while this is ticked. Untick it to really clean."
                                if dry_run_default else "Tick this to preview first; nothing is deleted."),
                               dry_run_default, command=lambda v: (setattr(self, "dry", v), self._sync()))
        row.pack(fill="x", pady=(14, 0))

        bar = tk.Frame(b, bg=theme.CARD)
        bar.pack(fill="x", pady=(22, 0))
        self.go = Btn(bar, "Clean", self._ok, "primary")
        self.go.pack(side="right")
        Btn(bar, "Cancel", self.destroy, "ghost").pack(side="right", padx=(0, 10))
        self._size = theme.fmt_size(size)
        self._sync()
        self.bind("<Escape>", lambda _e: self.destroy())
        self.present()

    def _sync(self):
        self.go.configure_text("Run dry run" if self.dry else f"Clean {self._size}")
        self.go.set_enabled(self.ack or self.dry)

    def _ok(self):
        self.result = {"dry_run": self.dry, "keep": self.keep}
        self.destroy()


class ProgressDialog(Modal):
    def __init__(self, app, title, cancel_event: threading.Event):
        super().__init__(app, title, width=500)
        self.cancel_event = cancel_event
        self._closed = False
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        label(self.body, title, 15, True).pack(anchor="w")
        self.bar = ttk.Progressbar(self.body, mode="determinate", length=440)
        self.bar.pack(fill="x", pady=(16, 8))
        self.status = label(self.body, "Starting…", 9, fg=theme.MUTED, wraplength=440, justify="left", anchor="w")
        self.status.pack(anchor="w", fill="x")
        row = tk.Frame(self.body, bg=theme.CARD)
        row.pack(fill="x", pady=(18, 0))
        self.btn = Btn(row, "Cancel", self.cancel, "ghost")
        self.btn.pack(side="right")
        self.present()

    def update_progress(self, done, total, text):
        if self._closed:
            return          # a late update queued before the dialog closed
        if total:
            self.bar.configure(mode="determinate", maximum=total, value=done)
        shown = text if len(text) < 64 else "…" + text[-62:]
        self.status.configure(text=f"{theme.fmt_count(done)} / {theme.fmt_count(total)}   {shown}")

    def cancel(self):
        self.cancel_event.set()
        self.btn.configure_text("Cancelling…")
        self.btn.set_enabled(False)

    def close(self):
        self._closed = True
        try:
            self.bar.stop()
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


class ResultDialog(Modal):
    """result: "undo" when the user asked to restore quarantined files."""

    def __init__(self, app, report, rule_labels, keep_days):
        super().__init__(app, "Clean result", width=580)
        self.result = None
        r = report
        b = self.body
        ok = tk.Canvas(b, width=64, height=64, bg=theme.CARD, highlightthickness=0, bd=0)
        ok.pack()
        ok.create_oval(0, 0, 63, 63, fill=theme.OK_BG if not r.cancelled else theme.AMBER_DIM, outline="")
        if r.cancelled:
            ok.create_text(32, 32, text="!", font=F(22, True), fill=theme.AMBER)
        else:
            ok.create_line(20, 33, 28, 41, 44, 24, fill=theme.GREEN, width=4, capstyle="round", joinstyle="round")

        if r.dry_run:
            amount, tail = r.would_free, "would be freed"
            sub = "Dry run: nothing was removed. Press “Clean for real” to remove these files."
        else:
            amount, tail = r.freed + r.quarantined_bytes, "freed"
            files = r.deleted_files + r.quarantined
            sub = f"{theme.fmt_count(files)} files removed in {r.seconds:.1f} seconds"
            if r.cancelled:
                sub += " (cancelled before finishing)"
        label(b, f"{theme.fmt_size(amount)} {tail}", 22, True, mono=True).pack(pady=(10, 0))
        label(b, sub, 10, fg=theme.MUTED).pack(pady=(2, 16))

        stats = tk.Frame(b, bg=theme.CARD)
        stats.pack(fill="x")
        until = None
        if r.quarantined and not r.dry_run:
            until = time.strftime("%d %b", time.localtime(time.time() + keep_days * 86400)).lstrip("0")
        first = ("Would remove", theme.fmt_size(r.would_free)) if r.dry_run else \
                ("Removed", theme.fmt_count(r.deleted_files + r.quarantined))
        cells = [first,
                 ("Skipped", theme.fmt_count(r.skipped_count)),
                 (f"Restore by {until}" if until else "Restorable", theme.fmt_size(r.quarantined_bytes))]
        for i, (cap, val) in enumerate(cells):
            c = Card(stats, pad=14, fill=theme.CONTENT, outline=theme.BORDER, radius=12, bg=theme.CARD)
            c.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 8, 0))
            stats.columnconfigure(i, weight=1, uniform="s")
            label(c.body, cap, 9, fg=theme.MUTED, bg=theme.CONTENT).pack(anchor="w")
            label(c.body, val, 15, True, mono=True, bg=theme.CONTENT).pack(anchor="w")

        if r.skipped:
            label(b, "SKIPPED BECAUSE THEY WERE PROTECTED OR IN USE", 8, True, fg=theme.MUTED).pack(anchor="w", pady=(18, 4))
            groups: dict[tuple[str, str], int] = {}
            for s in r.skipped:
                k = (rule_labels.get(s.rule_id, s.rule_id or "Other"), s.reason)
                groups[k] = groups.get(k, 0) + 1
            for (lab, reason), n in sorted(groups.items(), key=lambda kv: -kv[1])[:6]:
                row = tk.Frame(b, bg=theme.CARD)
                row.pack(fill="x", pady=4)
                label(row, lab, 10).pack(side="left")
                label(row, f"  {reason}", 9, fg=theme.MUTED).pack(side="left")
                label(row, f"{theme.fmt_count(n)} files", 9, fg=theme.MUTED, mono=True).pack(side="right")
                tk.Frame(b, bg=theme.BORDER, height=1).pack(fill="x")

        bar = tk.Frame(b, bg=theme.CARD)
        bar.pack(fill="x", pady=(20, 0))
        if r.dry_run:
            Btn(bar, "Clean for real", self._clean, "primary").pack(side="right")
            Btn(bar, "Close", self.destroy, "ghost").pack(side="right", padx=(0, 10))
        else:
            Btn(bar, "Done", self.destroy, "primary").pack(side="right")
        if r.quarantined and not r.dry_run:
            Btn(bar, "Undo", self._undo, "ghost").pack(side="right", padx=(0, 10))
        self.bind("<Escape>", lambda _e: self.destroy())
        self.present()

    def _undo(self):
        self.result = "undo"
        self.destroy()

    def _clean(self):
        self.result = "clean"
        self.destroy()
