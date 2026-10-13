"""Application pages. Each page talks to the App controller (queue, scan, clean flow, services)."""
from __future__ import annotations

import heapq
import os
import shutil
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..core import analyzers, winapi
from .. import APP_NAME, __version__
from ..core.paths import app_root, data_dir, user_folders
from . import theme
from .theme import F, M, label
from .widgets import Btn, Card, Check, CheckTree, Donut, Pill, ScrollFrame, Segmented, StackBar

RISK_ORDER = {"safe": 0, "review": 1, "advanced": 2}
LOG_RULES = {"crash_dumps", "wer", "old_logs"}

DESCRIPTIONS = {
    "safe": "Temporary files that Windows or your apps rebuild when they need them. Apps may start a little "
            "slower the first time afterwards.",
    "review": "Usually safe to remove, but look at the list first. Removed files can be restored from quarantine "
              "where that applies.",
    "advanced": "Only remove this if you know what it does.",
}


def group_of(rule):
    """Browser caches are shown as one expandable group; every other rule stands alone."""
    if rule.category == "Browsers":
        return "grp:browsers", "Browser cache"
    return rule.id, rule.label


def worst_risk(rules):
    return max((r.risk for r in rules), key=lambda k: RISK_ORDER[k])


def ago(ts):
    s = int(time.time() - ts)
    if s < 45:
        return "just now"
    if s < 3600:
        return f"{s // 60} min ago"
    return f"{s // 3600} h ago"


class Page(tk.Frame):
    title = ""

    def __init__(self, master, app):
        super().__init__(master, bg=theme.CONTENT)
        self.app = app

    def on_show(self):
        pass

    def header(self, title):
        h = tk.Frame(self, bg=theme.CONTENT)
        h.pack(fill="x", pady=(0, 18))
        label(h, title, 20, True).pack(side="left")
        self.meta = label(h, "", 10, fg=theme.MUTED)
        self.meta.pack(side="right")
        self.header_row = h
        return h


# --------------------------------------------------------------------- Dashboard
class DashboardPage(Page):
    title = "Dashboard"

    def __init__(self, master, app):
        super().__init__(master, app)
        h = self.header("Dashboard")
        self.admin_pill = Pill(h, "Administrator" if app.admin else "Standard user",
                               "safe" if app.admin else "muted", size=9)
        self.admin_pill.pack(side="right", padx=(0, 14))
        self.managed_pill = None

        hero = Card(self, pad=28, radius=16)
        hero.pack(fill="x")
        hb = hero.body
        left = tk.Frame(hb, bg=theme.CARD)
        left.pack(side="left", fill="x", expand=True)
        self.kicker = label(left, "READY TO SCAN", 9, fg=theme.MUTED)
        self.kicker.pack(anchor="w")
        num = tk.Frame(left, bg=theme.CARD)
        num.pack(anchor="w", pady=(2, 0))
        self.big = label(num, "—", 44, True, mono=True)
        self.big.pack(side="left")
        self.unit = label(num, "", 20, fg=theme.MUTED, mono=True)
        self.unit.pack(side="left", padx=(12, 0), anchor="s", pady=(0, 10))
        self.sub = label(left, "Press Scan to see what can be cleaned.", 10, fg=theme.MUTED)
        self.sub.pack(anchor="w", pady=(0, 18))
        btns = tk.Frame(left, bg=theme.CARD)
        btns.pack(anchor="w")
        self.review_btn = Btn(btns, "Review and clean", lambda: app.show("Cleaner"), "primary")
        self.scan_btn = Btn(btns, "Scan", app.start_scan, "ghost")
        self.review_btn.pack(side="left")
        self.scan_btn.pack(side="left", padx=(12, 0))
        right = tk.Frame(hb, bg=theme.CARD)
        right.pack(side="right")
        self.donut = Donut(right, 150, 14)
        self.donut.pack(side="left", padx=(0, 22))
        info = tk.Frame(right, bg=theme.CARD)
        info.pack(side="left")
        self.drive_t = label(info, "C: drive", 10, True)
        self.drive_t.pack(anchor="w")
        self.drive_a = label(info, "", 10, fg=theme.MUTED)
        self.drive_a.pack(anchor="w")
        self.drive_b = label(info, "", 10, fg=theme.MUTED)
        self.drive_b.pack(anchor="w")

        found = Card(self, pad=22, radius=16)
        found.pack(fill="x", pady=14)
        fb = found.body
        top = tk.Frame(fb, bg=theme.CARD)
        top.pack(fill="x", pady=(0, 14))
        label(top, "What was found", 12, True).pack(side="left")
        link = label(top, "See details", 10, fg=theme.AMBER)
        link.pack(side="right")
        link.configure(cursor="hand2")
        link.bind("<Button-1>", lambda _e: app.show("Cleaner"))
        self.stack = StackBar(fb, height=10)
        self.stack.pack(fill="x", pady=(0, 14))
        self.grid_f = tk.Frame(fb, bg=theme.CARD)
        self.grid_f.pack(fill="x")
        self.grid_f.columnconfigure((0, 1), weight=1, uniform="c")
        self.empty_note = label(fb, "", 10, fg=theme.MUTED)

        row = tk.Frame(self, bg=theme.CONTENT)
        row.pack(fill="x")
        row.columnconfigure((0, 1, 2), weight=1, uniform="t")
        self.tiles = []
        for i, (title, page) in enumerate((("Duplicates", "Duplicates"), ("Large files", "Large & empty"),
                                           ("Quarantine", "History"))):
            c = Card(row, pad=18, radius=14)
            c.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 8, 0 if i == 2 else 8))
            label(c.body, title, 11, True).pack(anchor="w")
            sub = label(c.body, "", 10, fg=theme.MUTED)
            sub.pack(anchor="w", pady=(2, 0))
            for w in (c, c.body, *c.body.winfo_children()):
                w.bind("<Button-1>", lambda _e, p=page: app.show(p))
                w.configure(cursor="hand2")
            self.tiles.append(sub)

    def on_show(self):
        a = self.app
        drive = os.environ.get("SystemDrive", "C:") + "\\"
        try:
            du = shutil.disk_usage(drive)
            gb = 1024 ** 3
            self.donut.set(du.used / du.total * 100)
            self.drive_t.configure(text=f"{drive[:2]} drive")
            self.drive_a.configure(text=f"{du.used / gb:.0f} of {du.total / gb:.0f} GB used")
            self.drive_b.configure(text=f"{du.free / gb:.0f} GB free")
        except OSError:
            pass
        self.meta.configure(text=f"Last scan finished {ago(a.last_scan)}" if a.last_scan else "")
        if self.managed_pill:
            self.managed_pill.destroy()
            self.managed_pill = None
        if a.managed_info.get("managed"):
            self.managed_pill = Pill(self.header_row, "Managed PC", "review", size=9)
            self.managed_pill.pack(side="right", padx=(0, 10), before=self.admin_pill)
        self.scan_btn.configure_text("Scan again" if a.results else "Scan")

        entries: dict[str, list] = {}
        for res in a.results.values():
            if res.status == "ok" and res.size > 0:
                key, lab = group_of(res.rule)
                e = entries.setdefault(key, [lab, 0, 0, []])
                e[1] += res.size
                e[2] += res.count
                e[3].append(res.rule)
        ranked = sorted(entries.values(), key=lambda e: -e[1])
        total = sum(e[1] for e in ranked)
        files = sum(e[2] for e in ranked)
        if a.results:
            num, unit = theme.size_parts(total)
            self.big.configure(text=num if ranked else "0")
            self.unit.configure(text=unit if ranked else "GB")
            self.kicker.configure(text="SCAN COMPLETE")
            self.sub.configure(text=f"{theme.fmt_count(files)} files in {len(ranked)} categories can be removed"
                               if ranked else "Nothing to clean right now.")
        self.review_btn.set_enabled(bool(ranked))
        if a.results:
            self.review_btn.pack(side="left", before=self.scan_btn)
        else:
            self.review_btn.pack_forget()

        for w in self.grid_f.winfo_children():
            w.destroy()
        shown = ranked[:8]
        self.stack.set([(theme.SEGMENTS[i % len(theme.SEGMENTS)], e[1]) for i, e in enumerate(shown)])
        for i, (lab, size, _n, rules) in enumerate(shown):
            col = tk.Frame(self.grid_f, bg=theme.CARD)
            col.grid(row=i // 2, column=i % 2, sticky="ew", padx=(0, 28) if i % 2 == 0 else (0, 0))
            inner = tk.Frame(col, bg=theme.CARD)
            inner.pack(fill="x", pady=7)
            tk.Frame(inner, bg=theme.SEGMENTS[i % len(theme.SEGMENTS)], width=11, height=11).pack(side="left")
            label(inner, lab, 10).pack(side="left", padx=(12, 0))
            label(inner, theme.fmt_size(size), 10, True, mono=True).pack(side="right")
            Pill(inner, theme.RISK_LABEL[worst_risk(rules)], worst_risk(rules)).pack(side="right", padx=14)
            tk.Frame(col, bg=theme.BORDER, height=1).pack(fill="x")

        d = a.dup_summary
        self.tiles[0].configure(text=f"{d[0]} groups, {theme.fmt_size(d[1])} reclaimable" if d else "Not scanned yet")
        lg = a.large_summary
        self.tiles[1].configure(text=lg if lg else "Not scanned yet")
        q = a.quarantine.list_runs()
        self.tiles[2].configure(text=(f"{sum(r['count'] for r in q)} files, {theme.fmt_size(sum(r['size'] for r in q))}"
                                      " restorable") if q else "Nothing waiting")


# --------------------------------------------------------------------- Cleaner
class CleanerPage(Page):
    title = "Cleaner"

    def __init__(self, master, app):
        super().__init__(master, app)
        self.header("Cleaner")
        self.checked: set[str] = set()
        self._scan_id = -1
        self.selected = None
        self.rows: dict[str, tuple] = {}
        self.groups: dict[str, tuple] = {}

        mid = tk.Frame(self, bg=theme.CONTENT)
        mid.pack(fill="both", expand=True)
        mid.columnconfigure(0, weight=1)
        mid.columnconfigure(1, minsize=350)
        mid.rowconfigure(0, weight=1)
        listcard = Card(mid, pad=10, stretch=True, radius=16)
        listcard.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        self.sf = ScrollFrame(listcard.body, bg=theme.CARD)
        self.sf.pack(fill="both", expand=True)
        self.detail_card = Card(mid, pad=22, radius=16)
        self.detail_card.grid(row=0, column=1, sticky="new")
        self.detail = self.detail_card.body

        bar = Card(self, pad=16, radius=16)
        bar.pack(fill="x", pady=(14, 0))
        bb = bar.body
        self.total_lbl = label(bb, "0 B", 20, True, mono=True)
        self.total_lbl.pack(side="left")
        self.files_lbl = label(bb, "", 10, fg=theme.MUTED)
        self.files_lbl.pack(side="left", padx=(12, 0), pady=(6, 0))
        self.clean_btn = Btn(bb, "Clean selected", lambda: self._clean(False), "primary")
        self.clean_btn.pack(side="right")
        self.preview_btn = Btn(bb, "Preview only", lambda: self._clean(True), "ghost")
        self.preview_btn.pack(side="right", padx=(0, 10))

    # -- building ------------------------------------------------------
    def on_show(self):
        if self._scan_id != self.app.scan_id:
            self._scan_id = self.app.scan_id
            self.checked = {rid for rid, r in self.app.results.items()
                            if r.status == "ok" and r.rule.risk == "safe" and not r.running and r.count}
            self.selected = None
        self.rebuild()

    def rebuild(self):
        sf = self.sf
        sf.clear()
        self.rows.clear()
        self.groups.clear()
        groups: dict[str, list] = {}
        for res in sorted(self.app.results.values(), key=lambda r: -r.size):
            if res.status == "empty":
                continue
            key, lab = group_of(res.rule)
            groups.setdefault(key, [lab, []])[1].append(res)
        if not groups:
            label(sf.inner, "Nothing to show yet. Run a scan from the Dashboard.", 10, fg=theme.MUTED, bg=theme.CARD
                  ).pack(pady=40)
        for key, (lab, lst) in sorted(groups.items(), key=lambda kv: -sum(r.size for r in kv[1][1])):
            if len(lst) == 1:
                self._rule_row(sf.inner, lst[0], 0)
            else:
                self._group(sf.inner, key, lab, lst)
        for key in self.groups:
            self._refresh_group(key)
        if self.selected not in self.rows:
            self.selected = next(iter(self.rows), None)
        self._select(self.selected)
        self._summary()

    def _rule_row(self, parent, res, indent):
        r = res.rule
        disabled = res.status in ("needs_admin", "managed")
        row = tk.Frame(parent, bg=theme.CARD, cursor="hand2")
        row.pack(fill="x")
        accent = tk.Frame(row, width=3, bg=theme.CARD)
        accent.pack(side="left", fill="y")
        inner = tk.Frame(row, bg=theme.CARD)
        inner.pack(side="left", fill="x", expand=True, padx=(14 + indent, 14), pady=10)
        chk = Check(inner, "on" if (r.id in self.checked and not disabled) else "off", disabled=disabled,
                    command=lambda v, rid=r.id: self._toggle(rid, v))
        chk.pack(side="left")
        name = label(inner, r.label, 10, fg=theme.TEXT if not disabled else theme.MUTED)
        name.pack(side="left", padx=12)
        label(inner, "—" if disabled else theme.fmt_size(res.size), 10, True, mono=True,
              fg=theme.TEXT if not disabled else theme.FAINT, width=10, anchor="e").pack(side="right")
        if res.running:
            Pill(inner, "Running", "running").pack(side="right", padx=10)
        elif disabled:
            Pill(inner, "Managed" if res.status == "managed" else "Admin", "muted").pack(side="right", padx=10)
        else:
            Pill(inner, theme.RISK_LABEL[r.risk], r.risk).pack(side="right", padx=10)
        for w in (row, inner, name):
            w.bind("<Button-1>", lambda _e, rid=r.id: self._select(rid))
        self.rows[r.id] = (accent, chk, disabled)

    def _group(self, parent, key, lab, lst):
        wrap = tk.Frame(parent, bg=theme.CARD)
        wrap.pack(fill="x")
        head = tk.Frame(wrap, bg=theme.CARD, cursor="hand2")
        head.pack(fill="x", padx=14, pady=(10, 4))
        arrow = label(head, "▾", 12, fg=theme.MUTED, width=2)
        arrow.pack(side="left")
        selectable = [r.rule.id for r in lst if r.status == "ok"]
        chk = Check(head, "off", command=lambda v, ids=selectable, k=key: self._toggle_group(k, ids, v))
        chk.pack(side="left")
        col = tk.Frame(head, bg=theme.CARD)
        col.pack(side="left", padx=12)
        label(col, lab, 10, True).pack(anchor="w")
        sub = label(col, "", 9, fg=theme.MUTED)
        sub.pack(anchor="w")
        label(head, theme.fmt_size(sum(r.size for r in lst)), 10, True, mono=True, width=10, anchor="e").pack(side="right")
        Pill(head, theme.RISK_LABEL[worst_risk([r.rule for r in lst])], worst_risk([r.rule for r in lst])
             ).pack(side="right", padx=10)
        kids = tk.Frame(wrap, bg=theme.CARD)
        kids.pack(fill="x")
        for res in lst:
            self._rule_row(kids, res, 28)

        def fold(_e=None):
            if kids.winfo_ismapped():
                kids.pack_forget()
                arrow.configure(text="▸")
            else:
                kids.pack(fill="x")
                arrow.configure(text="▾")
        for w in (head, arrow, col):
            w.bind("<Button-1>", fold)
        self.groups[key] = (chk, sub, selectable)

    def _refresh_group(self, key):
        chk, sub, ids = self.groups[key]
        n = sum(1 for i in ids if i in self.checked)
        chk.set("on" if ids and n == len(ids) else ("part" if n else "off"))
        sub.configure(text=f"{n} of {len(ids)} selected")

    def _toggle(self, rid, value):
        (self.checked.add if value else self.checked.discard)(rid)
        for key in self.groups:
            self._refresh_group(key)
        self._summary()

    def _toggle_group(self, key, ids, value):
        for rid in ids:
            (self.checked.add if value else self.checked.discard)(rid)
            self.rows[rid][1].set("on" if value else "off")
        self._refresh_group(key)
        self._summary()

    def _select(self, rid):
        self.selected = rid
        for k, (accent, _c, _d) in self.rows.items():
            accent.configure(bg=theme.AMBER if k == rid else theme.CARD)
        self._detail(rid)

    # -- right panel ---------------------------------------------------
    def _detail(self, rid):
        d = self.detail
        for w in d.winfo_children():
            w.destroy()
        res = self.app.results.get(rid)
        if not res:
            label(d, "Select an item to see details.", 10, fg=theme.MUTED).pack(anchor="w")
            return
        r = res.rule
        top = tk.Frame(d, bg=theme.CARD)
        top.pack(fill="x")
        label(top, r.label, 15, True).pack(side="left")
        Pill(top, theme.RISK_LABEL[r.risk], r.risk).pack(side="left", padx=10)
        if res.status == "needs_admin":
            label(d, "Needs administrator rights", 10, fg=theme.MUTED).pack(anchor="w", pady=(4, 10))
        elif res.status == "managed":
            label(d, "Managed by your organization", 10, fg=theme.MUTED).pack(anchor="w", pady=(4, 10))
        else:
            label(d, f"{theme.fmt_size(res.size)} in {theme.fmt_count(res.count)} files", 10, fg=theme.MUTED
                  ).pack(anchor="w", pady=(4, 10))
        label(d, r.note or DESCRIPTIONS[r.risk], 10, wraplength=300, justify="left", anchor="w").pack(anchor="w", fill="x")

        if res.running:
            exe = res.running[0]
            nice = exe.rsplit(".", 1)[0].capitalize()
            warn = Card(d, pad=14, fill=theme.WARN_BG, outline=theme.WARN_BORDER, radius=10)
            warn.pack(fill="x", pady=(14, 0))
            label(warn.body, f"⚠  {nice} is running. Close it to clean this cache, or leave it unchecked and "
                             "clean it later.", 10, fg=theme.AMBER, bg=theme.WARN_BG, wraplength=270, justify="left",
                  anchor="w").pack(anchor="w", fill="x")
            Btn(warn.body, f"Close {nice}", lambda e=exe: self.app.close_app(e), "ghost", padx=16, height=36
                ).pack(anchor="w", pady=(10, 0))
        elif res.status == "managed":
            warn = Card(d, pad=14, fill=theme.WARN_BG, outline=theme.WARN_BORDER, radius=10)
            warn.pack(fill="x", pady=(14, 0))
            label(warn.body, "⚠  This PC looks managed by an organization. Windows servicing, diagnostic and log "
                             "locations are left alone so IT tooling keeps working.", 10, fg=theme.AMBER,
                  bg=theme.WARN_BG, wraplength=270, justify="left", anchor="w").pack(anchor="w", fill="x")
        elif res.status == "needs_admin":
            warn = Card(d, pad=14, fill=theme.WARN_BG, outline=theme.WARN_BORDER, radius=10)
            warn.pack(fill="x", pady=(14, 0))
            label(warn.body, "⚠  Start LavatiCleaner with “Run as administrator” to include this location.", 10,
                  fg=theme.AMBER, bg=theme.WARN_BG, wraplength=270, justify="left", anchor="w").pack(anchor="w", fill="x")

        if res.protected:
            label(d, f"{theme.fmt_count(res.protected)} files were left out because they belong to security or "
                     "management software.", 9, fg=theme.MUTED, wraplength=300, justify="left", anchor="w"
                  ).pack(anchor="w", fill="x", pady=(10, 0))
        big = heapq.nlargest(3, [i for i in res.items if not i.path.startswith("::")], key=lambda i: i.size)
        if big:
            label(d, "LARGEST FILES", 8, True, fg=theme.MUTED).pack(anchor="w", pady=(18, 4))
            for it in big:
                row = tk.Frame(d, bg=theme.CARD)
                row.pack(fill="x", pady=5)
                nm = os.path.basename(it.path)
                label(row, nm if len(nm) < 24 else nm[:22] + "…", 9, mono=True).pack(side="left")
                label(row, theme.fmt_size(it.size), 9, fg=theme.MUTED, mono=True).pack(side="right")
                tk.Frame(d, bg=theme.BORDER, height=1).pack(fill="x")
        if r.paths:
            label(d, "LOCATION", 8, True, fg=theme.MUTED).pack(anchor="w", pady=(18, 4))
            label(d, "\n".join(r.paths[:3]), 9, mono=True, wraplength=300, justify="left", anchor="w"
                  ).pack(anchor="w", fill="x")

    # -- summary / actions ---------------------------------------------
    def _selected_results(self):
        return [self.app.results[i] for i in self.checked if i in self.app.results and self.app.results[i].count]

    def _summary(self):
        sel = self._selected_results()
        size, files = sum(r.size for r in sel), sum(r.count for r in sel)
        found = sum(r.size for r in self.app.results.values())
        self.total_lbl.configure(text=theme.fmt_size(size))
        self.files_lbl.configure(text=f"{theme.fmt_count(files)} files selected")
        self.meta.configure(text=f"{theme.fmt_size(size)} selected of {theme.fmt_size(found)} found" if found else "")
        self.clean_btn.set_enabled(bool(sel))
        self.preview_btn.set_enabled(bool(sel))

    def _clean(self, dry_only):
        items = [it for r in self._selected_results() for it in r.items]
        self.app.clean(items, "Cleaner", dry_only=dry_only)


# --------------------------------------------------------------------- shared scan bar
class ScanBar(Card):
    """Folders being scanned + page-specific controls + the Find / Stop buttons."""

    def __init__(self, master, page, find_text):
        super().__init__(master, pad=16, radius=14)
        self.page = page
        b = self.body
        top = tk.Frame(b, bg=theme.CARD)
        top.pack(fill="x")
        self.roots_lbl = label(top, "", 9, fg=theme.MUTED, wraplength=620, justify="left", anchor="w")
        self.roots_lbl.pack(side="left", fill="x", expand=True)
        Btn(top, "Reset", page.reset_roots, "ghost", padx=14, height=32).pack(side="right")
        Btn(top, "Add folder…", page.add_root, "ghost", padx=14, height=32).pack(side="right", padx=8)
        self.controls = tk.Frame(b, bg=theme.CARD)
        self.controls.pack(fill="x", pady=(12, 0))
        self.find = Btn(self.controls, find_text, page.find, "primary", padx=18, height=36)
        self.find.pack(side="right")
        self.stop = Btn(self.controls, "Stop", page.cancel_scan, "ghost", padx=16, height=36)
        self.status = label(self.controls, "", 9, fg=theme.MUTED)
        self.status.pack(side="right", padx=14)

    def set_roots(self, roots):
        self.roots_lbl.configure(text="Scanning: " + ";  ".join(roots) if roots else "No folders selected")

    def running(self, on):
        self.find.set_enabled(not on)
        if on:
            self.stop.pack(side="right", padx=(0, 8), before=self.status)
        else:
            self.stop.pack_forget()


class AnalyzerPage(Page):
    rule_key = ""

    def __init__(self, master, app):
        super().__init__(master, app)
        self.roots = self.default_roots()
        self.cancel = threading.Event()
        self.busy = False
        self._key = ""

    @staticmethod
    def default_roots():
        return [r for r in user_folders() if os.path.basename(r).lower() != "music"]

    def add_root(self):
        d = filedialog.askdirectory(parent=self, title="Choose a folder to scan")
        if d:
            d = os.path.normpath(d)
            if d not in self.roots:
                self.roots.append(d)
            self.bar.set_roots(self.roots)

    def reset_roots(self):
        self.roots = self.default_roots()
        self.bar.set_roots(self.roots)

    def cancel_scan(self):
        self.cancel.set()

    def find(self):
        if self.busy or not self.roots:
            return
        self.busy = True
        self._key = self.rule_key
        self.cancel.clear()
        self.bar.running(True)
        self.before_scan()

        def progress(text):
            self.app.post(lambda: self.bar.status.configure(text=text))
        self.app.run_bg(lambda: self.work(progress), self._done)

    def _done(self, result):
        self.busy = False
        self.bar.running(False)
        if isinstance(result, Exception):
            self.bar.status.configure(text="Scan failed: " + str(result))
            return
        self.bar.status.configure(text="Cancelled" if self.cancel.is_set() else "")
        self.app.guard.register(self._key, self.roots, strict=False)
        self.populate(result)

    def before_scan(self):
        pass


class DuplicatesPage(AnalyzerPage):
    title = "Duplicates"
    rule_key = analyzers.DUP_RULE
    MAX_GROUPS = 150
    FILTERS = {
        "All": None,
        "Pictures": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".tif", ".tiff", ".raw", ".cr2"},
        "Videos": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".m4v"},
        "Documents": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".odt", ".csv", ".rtf"},
    }
    AUTO = ["Keep newest copy", "Keep oldest copy", "Keep shortest path"]

    def __init__(self, master, app):
        super().__init__(master, app)
        self.header("Duplicates")
        self.groups: list[dict] = []
        self.sel: set[str] = set()
        self.filter = "All"
        self.min_var = tk.StringVar(value="1 MB")
        self.auto_var = tk.StringVar(value=self.AUTO[0])
        self.bar = ScanBar(self, self, "Find duplicates")
        self.bar.pack(fill="x", pady=(0, 12))
        self.bar.set_roots(self.roots)
        c = tk.Frame(self.bar.controls, bg=theme.CARD)
        c.pack(side="left")
        label(c, "Minimum size", 9, fg=theme.MUTED).pack(side="left", padx=(0, 8))
        ttk.Combobox(c, textvariable=self.min_var, values=["100 KB", "1 MB", "10 MB", "100 MB"], width=7,
                     state="readonly").pack(side="left")

        chips = tk.Frame(self, bg=theme.CONTENT)
        chips.pack(fill="x", pady=(0, 10))
        self.chip_btns = {}
        for name in ("All", "Pictures", "Videos", "Documents", "Other"):
            b = tk.Label(chips, text=name, font=F(10), padx=16, pady=6, cursor="hand2", bd=0)
            b.pack(side="left", padx=(0, 8))
            b.bind("<Button-1>", lambda _e, n=name: self._set_filter(n))
            self.chip_btns[name] = b
        auto = ttk.Combobox(chips, textvariable=self.auto_var, values=self.AUTO, width=20, state="readonly")
        auto.pack(side="right")
        auto.bind("<<ComboboxSelected>>", lambda _e: self._reselect())
        label(chips, "Auto-select", 10, fg=theme.MUTED).pack(side="right", padx=(0, 10))
        self._style_chips()

        listcard = Card(self, pad=10, stretch=True, radius=16)
        listcard.pack(fill="both", expand=True)
        self.sf = ScrollFrame(listcard.body, bg=theme.CARD)
        self.sf.pack(fill="both", expand=True)

        bar = Card(self, pad=16, radius=16)
        bar.pack(fill="x", pady=(12, 0))
        left = tk.Frame(bar.body, bg=theme.CARD)
        left.pack(side="left")
        row = tk.Frame(left, bg=theme.CARD)
        row.pack(anchor="w")
        self.total_lbl = label(row, "0 B", 20, True, mono=True)
        self.total_lbl.pack(side="left")
        self.count_lbl = label(row, "", 10, fg=theme.MUTED)
        self.count_lbl.pack(side="left", padx=(12, 0), pady=(6, 0))
        label(left, "One copy in every group is always kept.", 9, fg=theme.MUTED).pack(anchor="w")
        self.remove_btn = Btn(bar.body, "Move to quarantine", self._remove, "primary")
        self.remove_btn.pack(side="right")
        self.open_btn = Btn(bar.body, "Open folder", self._open, "ghost")
        self.open_btn.pack(side="right", padx=(0, 10))
        self._empty("Press “Find duplicates” to scan the folders above.")

    # -- scan ----------------------------------------------------------
    def _min_bytes(self):
        n, unit = self.min_var.get().split()
        return int(n) * (1024 if unit == "KB" else 1024 * 1024)

    def before_scan(self):
        self._empty("Scanning…")

    def work(self, progress):
        return analyzers.find_duplicates(self.roots, self._min_bytes(), self.cancel, progress)

    def populate(self, groups):
        self.groups = [{"items": g, "name": os.path.basename(g[0].path), "exts": os.path.splitext(g[0].path)[1].lower()}
                       for g in groups]
        waste = sum(g[0].size * (len(g) - 1) for g in groups)
        self.app.dup_summary = (len(groups), waste)
        self.meta.configure(text=f"{len(groups)} groups, {theme.fmt_size(waste)} reclaimable")
        self._reselect()

    # -- selection -----------------------------------------------------
    def _keep_of(self, items):
        mode = self.auto_var.get()
        if mode == "Keep oldest copy":
            return min(items, key=lambda i: i.mtime)
        if mode == "Keep shortest path":
            return min(items, key=lambda i: len(i.path))
        return max(items, key=lambda i: i.mtime)

    def _reselect(self):
        self.sel.clear()
        for g in self.groups:
            g["keep"] = self._keep_of(g["items"]).path
            for it in g["items"]:
                if it.path != g["keep"] and not self.app.guard.is_protected(it.path):
                    self.sel.add(it.path)
        self._render()

    def _set_filter(self, name):
        self.filter = name
        self._style_chips()
        self._render()

    def _style_chips(self):
        for n, b in self.chip_btns.items():
            on = n == self.filter
            b.configure(bg=theme.AMBER_DIM if on else theme.CONTENT, fg=theme.AMBER if on else theme.MUTED,
                        highlightthickness=1, highlightbackground=theme.AMBER if on else theme.BORDER)

    def _passes(self, g):
        if self.filter == "All":
            return True
        known = set().union(*[v for v in self.FILTERS.values() if v])
        if self.filter == "Other":
            return g["exts"] not in known
        return g["exts"] in self.FILTERS[self.filter]

    # -- rendering -----------------------------------------------------
    def _empty(self, text):
        self.sf.clear()
        label(self.sf.inner, text, 10, fg=theme.MUTED, bg=theme.CARD).pack(pady=40)
        self._summary()

    def _render(self):
        self.sf.clear()
        shown = [g for g in self.groups if self._passes(g)]
        if not shown:
            label(self.sf.inner, "No duplicates found." if not self.groups else "Nothing in this filter.", 10,
                  fg=theme.MUTED, bg=theme.CARD).pack(pady=40)
        for gi, g in enumerate(shown[:self.MAX_GROUPS]):
            self._group(g, expanded=gi < 2)
        if len(shown) > self.MAX_GROUPS:
            label(self.sf.inner, f"Showing the {self.MAX_GROUPS} largest of {len(shown)} groups.", 9,
                  fg=theme.MUTED, bg=theme.CARD).pack(pady=12)
        self._summary()

    def _group(self, g, expanded):
        items = g["items"]
        waste = items[0].size * (len(items) - 1)
        wrap = tk.Frame(self.sf.inner, bg=theme.CARD)
        wrap.pack(fill="x", pady=2)
        head = Card(wrap, pad=12, fill=theme.CARD_HI, outline=theme.CARD_HI, radius=10, bg=theme.CARD)
        head.pack(fill="x", padx=4)
        hb = head.body
        arrow = label(hb, "▾" if expanded else "▸", 12, fg=theme.MUTED, bg=theme.CARD_HI, width=2)
        arrow.pack(side="left")
        col = tk.Frame(hb, bg=theme.CARD_HI)
        col.pack(side="left", padx=8)
        label(col, g["name"], 10, True, bg=theme.CARD_HI).pack(anchor="w")
        label(col, f"{len(items)} copies, {theme.fmt_size(items[0].size)} each", 9, fg=theme.MUTED,
              bg=theme.CARD_HI).pack(anchor="w")
        label(hb, f"{theme.fmt_size(waste)} reclaimable", 10, True, mono=True, fg=theme.AMBER,
              bg=theme.CARD_HI).pack(side="right")
        kids = tk.Frame(wrap, bg=theme.CARD)

        def fill_kids():
            for it in items:
                self._file_row(kids, g, it)

        state = {"built": False}

        def fold(_e=None):
            if kids.winfo_ismapped():
                kids.pack_forget()
                arrow.configure(text="▸")
            else:
                if not state["built"]:
                    fill_kids()
                    state["built"] = True
                kids.pack(fill="x")
                arrow.configure(text="▾")
        for w in (head, hb, arrow, col, *col.winfo_children()):
            w.bind("<Button-1>", fold)
        if expanded:
            fill_kids()
            state["built"] = True
            kids.pack(fill="x")

    def _file_row(self, parent, g, it):
        row = tk.Frame(parent, bg=theme.CARD)
        row.pack(fill="x", padx=14, pady=8)
        chk = Check(row, "on" if it.path in self.sel else "off",
                    command=lambda v, p=it.path: self._toggle(p, v))
        chk.pack(side="left")
        shown = it.path if len(it.path) < 62 else it.path[:24] + "…" + it.path[-36:]
        label(row, shown, 9, mono=True).pack(side="left", padx=14)
        label(row, theme.fmt_date(it.mtime), 9, fg=theme.MUTED).pack(side="right")
        if it.path == g.get("keep"):
            Pill(row, "Keep", "keep").pack(side="right", padx=12)
        elif self.app.guard.is_protected(it.path):
            Pill(row, "Protected folder", "muted").pack(side="right", padx=12)

    def _toggle(self, path, value):
        (self.sel.add if value else self.sel.discard)(path)
        self._summary()

    def _selected_items(self):
        out = []
        for g in self.groups:
            out.extend(i for i in g["items"] if i.path in self.sel)
        return out

    def _summary(self):
        items = self._selected_items()
        self.total_lbl.configure(text=theme.fmt_size(sum(i.size for i in items)))
        self.count_lbl.configure(text=f"{len(items)} files selected")
        self.remove_btn.set_enabled(bool(items))
        self.open_btn.set_enabled(bool(items))

    def _open(self):
        items = self._selected_items()
        if items:
            winapi.show_in_explorer(items[0].path)

    def _remove(self):
        items = self._selected_items()
        paths = {i.path for i in items}
        for g in self.groups:
            if all(i.path in paths for i in g["items"]):
                messagebox.showwarning("Keep one copy", f"At least one copy of “{g['name']}” must stay.", parent=self)
                return
        self.app.clean(items, "Duplicates", on_done=lambda _r: self._after(paths))

    def _after(self, paths):
        gone = {p for p in paths if not os.path.lexists(p)}
        if not gone:
            return
        self.sel -= gone
        for g in self.groups:
            g["items"] = [i for i in g["items"] if i.path not in gone]
        self.groups = [g for g in self.groups if len(g["items"]) > 1]
        self._reselect()


class LargePage(AnalyzerPage):
    title = "Large & empty"

    def __init__(self, master, app):
        super().__init__(master, app)
        self.header("Large files & empty folders")
        self.kind = tk.StringVar(value="Large files")
        self.size_var = tk.StringVar(value="100 MB")
        self.bar = ScanBar(self, self, "Find")
        self.bar.pack(fill="x", pady=(0, 12))
        self.bar.set_roots(self.roots)
        c = tk.Frame(self.bar.controls, bg=theme.CARD)
        c.pack(side="left")
        ttk.Combobox(c, textvariable=self.kind, values=["Large files", "Empty folders"], width=14,
                     state="readonly").pack(side="left", padx=(0, 12))
        label(c, "Larger than", 9, fg=theme.MUTED).pack(side="left", padx=(0, 8))
        ttk.Combobox(c, textvariable=self.size_var, values=["50 MB", "100 MB", "500 MB", "1 GB"], width=7,
                     state="readonly").pack(side="left")

        card = Card(self, pad=8, stretch=True, radius=16)
        card.pack(fill="both", expand=True)
        self.tree = CheckTree(card.body, columns=("size", "extra"),
                              headings={"#0": "Path", "size": "Size", "extra": "Modified"},
                              widths={"#0": 560, "size": 100, "extra": 150})
        self.tree.pack(fill="both", expand=True)
        self.tree.on_change = self._summary
        self.tree.bind("<Button-3>", self._menu)
        self.items: dict[str, object] = {}

        bar = Card(self, pad=16, radius=16)
        bar.pack(fill="x", pady=(12, 0))
        left = tk.Frame(bar.body, bg=theme.CARD)
        left.pack(side="left")
        self.total_lbl = label(left, "0 B", 20, True, mono=True)
        self.total_lbl.pack(side="left")
        self.count_lbl = label(left, "", 10, fg=theme.MUTED)
        self.count_lbl.pack(side="left", padx=(12, 0), pady=(6, 0))
        self.remove_btn = Btn(bar.body, "Move to quarantine", self._remove, "primary")
        self.remove_btn.pack(side="right")
        self.remove_btn.set_enabled(False)

    @property
    def rule_key(self):
        return analyzers.EMPTY_RULE if self.kind.get() == "Empty folders" else analyzers.LARGE_RULE

    def before_scan(self):
        self.tree.clear()
        self.items.clear()
        self._summary()

    def work(self, progress):
        if self.kind.get() == "Empty folders":
            return analyzers.find_empty_folders(self.roots, self.cancel, progress)
        n, unit = self.size_var.get().split()
        return analyzers.find_large(self.roots, int(n) * (1024 ** (3 if unit == "GB" else 2)), self.cancel, progress)

    def populate(self, items):
        for k, it in enumerate(items):
            iid = f"i{k}"
            self.items[iid] = it
            self.tree.add(iid, it.path, (theme.fmt_size(it.size) if it.size else "", theme.fmt_time(it.mtime)
                                         if it.size else ""))
        total = sum(i.size for i in items)
        self.meta.configure(text=f"{len(items)} found" + (f", {theme.fmt_size(total)}" if total else ""))
        if self.kind.get() == "Large files":
            self.app.large_summary = f"{len(items)} files over {self.size_var.get()}"
        self._summary()

    def _selected(self):
        return [self.items[i] for i in self.tree.checked() if i in self.items]

    def _summary(self):
        sel = self._selected()
        self.total_lbl.configure(text=theme.fmt_size(sum(i.size for i in sel)))
        self.count_lbl.configure(text=f"{len(sel)} selected")
        self.remove_btn.set_enabled(bool(sel))

    def _remove(self):
        items = self._selected()
        self.app.clean(items, self.title, on_done=lambda _r: self._after(items))

    def _after(self, items):
        for iid, it in list(self.items.items()):
            if not os.path.lexists(it.path) and self.tree.exists(iid):
                self.tree.delete(iid)
                self.tree._state.pop(iid, None)
                self.items.pop(iid)
        self._summary()

    def _menu(self, e):
        iid = self.tree.identify_row(e.y)
        if iid in self.items:
            m = tk.Menu(self, tearoff=0, bg=theme.CARD, fg=theme.TEXT, activebackground=theme.AMBER_DIM,
                        activeforeground=theme.AMBER, bd=0)
            m.add_command(label="Show in Explorer", command=lambda: winapi.show_in_explorer(self.items[iid].path))
            m.tk_popup(e.x_root, e.y_root)


# --------------------------------------------------------------------- History
class HistoryPage(Page):
    title = "History"

    def __init__(self, master, app):
        super().__init__(master, app)
        self.header("History & undo")
        qc = Card(self, pad=18, radius=16)
        qc.pack(fill="x")
        label(qc.body, "Quarantine", 12, True).pack(anchor="w")
        label(qc.body, "Files moved here can be restored until they expire.", 9, fg=theme.MUTED).pack(anchor="w", pady=(0, 10))
        self.q = ttk.Treeview(qc.body, columns=("when", "files", "size", "expires"), height=4, selectmode="browse")
        for c, w, txt in (("#0", 190, "Run"), ("when", 140, "Cleaned"), ("files", 70, "Files"),
                          ("size", 100, "Size"), ("expires", 140, "Expires")):
            self.q.heading(c, text=txt, anchor="w")
            self.q.column(c, width=w, anchor="w", stretch=(c == "#0"))
        self.q.pack(fill="x")
        row = tk.Frame(qc.body, bg=theme.CARD)
        row.pack(fill="x", pady=(12, 0))
        Btn(row, "Restore selected", self._restore, "primary", padx=18, height=36).pack(side="left")
        Btn(row, "Delete permanently", self._delete, "ghost", padx=18, height=36).pack(side="left", padx=10)

        hc = Card(self, pad=18, radius=16, stretch=True)
        hc.pack(fill="both", expand=True, pady=(14, 0))
        label(hc.body, "Runs", 12, True).pack(anchor="w", pady=(0, 10))
        self.h = ttk.Treeview(hc.body, columns=("when", "kind", "freed", "files", "skipped", "label"), selectmode="browse")
        for c, w, txt in (("#0", 190, "Run"), ("when", 130, "When"), ("kind", 80, "Mode"), ("freed", 100, "Freed"),
                          ("files", 70, "Files"), ("skipped", 70, "Skipped"), ("label", 120, "From")):
            self.h.heading(c, text=txt, anchor="w")
            self.h.column(c, width=w, anchor="w", stretch=(c == "#0"))
        self.h.pack(fill="both", expand=True)

    def on_show(self):
        a = self.app
        self.q.delete(*self.q.get_children())
        for r in a.quarantine.list_runs():
            self.q.insert("", "end", iid=r["run_id"], text=r["run_id"],
                          values=(theme.fmt_time(r["created"]), r["count"], theme.fmt_size(r["size"]),
                                  theme.fmt_time(r["expires"])))
        self.h.delete(*self.h.get_children())
        for r in a.store.runs():
            kind = "Dry run" if r["dry_run"] else "Clean"
            freed = r["would_free"] if r["dry_run"] else r["freed"] + r["quarantined_bytes"]
            self.h.insert("", "end", iid=r["run_id"], text=r["run_id"],
                          values=(theme.fmt_time(r["ts"]), kind, theme.fmt_size(freed),
                                  r["files"] + r["quarantined"], r["skipped"], r["label"]))

    def _restore(self):
        sel = self.q.selection()
        if sel:
            self.app.restore(sel[0])
            self.on_show()

    def _delete(self):
        sel = self.q.selection()
        if sel and messagebox.askyesno("Delete permanently", "These files cannot be restored afterwards. Continue?",
                                       parent=self):
            self.app.quarantine.delete_run(sel[0])
            self.on_show()


# --------------------------------------------------------------------- Settings
class SettingsPage(Page):
    title = "Settings"

    def __init__(self, master, app):
        super().__init__(master, app)
        self.header("Settings")
        c = Card(self, pad=24, radius=16)
        c.pack(fill="x")
        b = c.body
        self.dry = bool(app.store.get("dry_run_always", False))
        row = tk.Frame(b, bg=theme.CARD)
        row.pack(fill="x")
        self.dry_chk = Check(row, "on" if self.dry else "off", command=self._set_dry)
        self.dry_chk.pack(side="left", anchor="n", padx=(0, 12), pady=2)
        col = tk.Frame(row, bg=theme.CARD)
        col.pack(side="left")
        label(col, "Always start with “dry run” ticked", 10).pack(anchor="w")
        label(col, "It is always ticked until your first real clean.", 9, fg=theme.MUTED).pack(anchor="w")

        row = tk.Frame(b, bg=theme.CARD)
        row.pack(anchor="w", pady=18)
        label(row, "Keep quarantined files for", 10).pack(side="left")
        self.days = tk.IntVar(value=app.quarantine.keep_days)
        ttk.Spinbox(row, from_=1, to=90, width=4, textvariable=self.days, command=self._save_days).pack(side="left", padx=10)
        label(row, "days", 10).pack(side="left")

        label(b, "Appearance", 10, True).pack(anchor="w", pady=(0, 8))
        Segmented(b, [("system", "System"), ("light", "Light"), ("dark", "Dark")], app.theme_mode,
                  app.set_theme).pack(anchor="w", pady=(0, 20))

        mi = app.managed_info
        label(b, "Managed-PC protection", 10, True).pack(anchor="w")
        if mi.get("managed"):
            why = [n for n, on in (("domain-joined", mi.get("domain")), ("device management (MDM)", mi.get("mdm")),
                                   ("cloud-joined", mi.get("aad")), ("company policy", mi.get("policy_lock"))) if on]
            if mi.get("agents"):
                why.append("security agents running")
            label(b, "This PC looks managed by an organization (" + ", ".join(why) + "). Windows servicing, "
                  "diagnostic and log locations are left alone.", 9, fg=theme.MUTED, wraplength=720,
                  justify="left", anchor="w").pack(anchor="w", pady=(2, 8))
            row = tk.Frame(b, bg=theme.CARD)
            row.pack(fill="x", pady=(0, 6))
            locked = bool(mi.get("policy_lock"))
            self.pm = Check(row, "on" if (app.store.get("protect_managed", True) or locked) else "off",
                            disabled=locked, command=self._set_pm)
            self.pm.pack(side="left", padx=(0, 12))
            label(row, "Leave Windows update, diagnostic, log and crash-dump locations alone"
                  + (" (set by your administrator)" if locked else ""), 10).pack(side="left")
        else:
            label(b, "No organization management detected, so all rules are available.", 9, fg=theme.MUTED
                  ).pack(anchor="w", pady=(2, 6))
        label(b, "Security tools, monitoring agents, Windows event logs (.evtx) and tracing logs (.etl) are "
              "always protected, on every PC. Add your own in protected.json.", 9, fg=theme.MUTED,
              wraplength=720, justify="left", anchor="w").pack(anchor="w", pady=(0, 18))

        label(b, ("Running as Administrator." if app.admin else
                  "Running as a standard user. Windows locations that need admin rights are listed but disabled. "
                  "LavatiCleaner never asks for elevation by itself: start it with “Run as administrator” to "
                  "include them."), 10, fg=theme.MUTED, wraplength=720, justify="left", anchor="w").pack(anchor="w")
        btns = tk.Frame(b, bg=theme.CARD)
        btns.pack(anchor="w", pady=(18, 0))
        Btn(btns, "Open quarantine folder", lambda: winapi.open_folder(app.quarantine.base), "ghost", height=36
            ).pack(side="left")
        Btn(btns, "Open data folder", lambda: winapi.open_folder(data_dir()), "ghost", height=36).pack(side="left", padx=10)
        Btn(btns, "Empty quarantine now", self._purge, "ghost", height=36).pack(side="left")
        self.rules_lbl = label(self, "", 9, fg=theme.MUTED, wraplength=760, justify="left", anchor="w")
        self.rules_lbl.pack(anchor="w", pady=(16, 0))

        about = Card(self, pad=20, radius=16)
        about.pack(fill="x", pady=(16, 0))
        label(about.body, f"{APP_NAME} {__version__}", 11, True).pack(anchor="w")
        label(about.body, "Copyright (C) Lavati Softwares. No data leaves your PC.", 9, fg=theme.MUTED).pack(anchor="w", pady=(2, 10))
        ab = tk.Frame(about.body, bg=theme.CARD)
        ab.pack(anchor="w")
        for text, fname in (("License agreement", "LICENSE.txt"), ("Privacy", "PRIVACY.md"),
                            ("Security model", "SECURITY.md"), ("Third-party notices", "THIRD_PARTY_NOTICES.txt")):
            Btn(ab, text, lambda f=fname: winapi.open_file(os.path.join(app_root(), f)), "ghost", height=34, padx=16
                ).pack(side="left", padx=(0, 8))

    def on_show(self):
        a = self.app
        txt = f"{len(a.rules)} cleaning rules loaded (JSON files in the rules folder; add your own in {a.user_rules})."
        if a.rule_errors:
            txt += "\nIgnored rules:\n" + "\n".join("  • " + e for e in a.rule_errors[:6])
        self.rules_lbl.configure(text=txt)

    def _set_pm(self, v):
        self.app.store.set("protect_managed", bool(v))

    def _set_dry(self, v):
        self.app.store.set("dry_run_always", bool(v))

    def _save_days(self):
        try:
            d = max(1, int(self.days.get()))
        except (tk.TclError, ValueError):
            return
        self.app.quarantine.keep_days = d
        self.app.store.set("keep_days", d)

    def _purge(self):
        if messagebox.askyesno("Empty quarantine", "Permanently delete everything in quarantine?", parent=self):
            n = self.app.quarantine.purge_all()
            messagebox.showinfo("Quarantine", f"Removed {n} runs.", parent=self)
