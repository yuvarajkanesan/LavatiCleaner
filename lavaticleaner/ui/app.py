"""Main window and controller: background work queue, scan flow, clean flow."""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox

from .. import APP_NAME, __version__
from ..core import winapi
from ..core.executor import Executor
from ..core.history import Store
from ..core.paths import app_root, data_dir, quarantine_dir, rules_dir, user_rules_dir
from ..core.quarantine import Quarantine
from ..core.rules import load_rules
from ..core.safety import MANAGED_LOCKED_RULES, SafetyGuard
from ..core.models import RuleResult
from ..core.scanner import RECYCLE_PSEUDO_PATH, ScanContext, scan_all
from . import theme
from .dialogs import ConfirmDialog, ProgressDialog, ResultDialog
from .pages import (LOG_RULES, CleanerPage, DashboardPage, DuplicatesPage, HistoryPage, LargePage,
                    OptimizePage, SettingsPage)
from .theme import F, label

log = logging.getLogger("lavati")

# (name, class, Segoe MDL2 glyph)
PAGES = [("Dashboard", DashboardPage, ""), ("Cleaner", CleanerPage, ""),
         ("Duplicates", DuplicatesPage, ""), ("Large & empty", LargePage, ""),
         ("Optimize", OptimizePage, ""),
         ("History", HistoryPage, ""), ("Settings", SettingsPage, "")]

ANALYZER_LABELS = {"analyzer:duplicates": "Duplicate files", "analyzer:large": "Large files",
                   "analyzer:empty": "Empty folders"}


class App(tk.Tk):
    def __init__(self):
        theme.load_fonts()
        super().__init__()
        theme.init_fonts(self)
        self.title(APP_NAME)
        self.geometry("1180x780")
        self.minsize(980, 660)
        self.store = Store()
        self.theme_mode = self.store.get("theme", "system")
        theme.apply(self.theme_mode)
        theme.setup_style(self)
        self._set_icon()

        self.admin = winapi.is_admin()
        self.managed_info = winapi.managed_info()
        self.managed_active = False
        self.quarantine = Quarantine(quarantine_dir(), keep_days=int(self.store.get("keep_days", 7)))
        self.user_rules = user_rules_dir()
        self.rules, self.rule_errors = load_rules(rules_dir(), self.user_rules)
        self.rule_labels = {r.id: r.label for r in self.rules} | ANALYZER_LABELS
        self.guard = SafetyGuard([os.path.join(data_dir(), "protected.json"),
                                  os.path.join(os.environ.get("ProgramData", ""), APP_NAME, "protected.json")])
        self.executor = Executor(self.guard, self.quarantine, {r.id: r for r in self.rules})
        self.results: dict = {}
        self.scan_id = 0
        self.last_scan = 0.0
        self.dup_summary = None
        self.large_summary = None
        self.busy = False
        self._q: queue.Queue = queue.Queue()
        self.after(50, self._poll)

        try:
            n = self.quarantine.purge_expired()
            if n:
                log.info("purged %d expired quarantine runs", n)
        except OSError:
            log.exception("quarantine purge failed")

        self._build()
        self.show("Dashboard")
        self.after(50, lambda: theme.dark_titlebar(self))

    def _set_icon(self):
        try:
            self.iconbitmap(os.path.join(app_root(), "assets", "lavati.ico"))
        except tk.TclError:
            pass

    # ---------------------------------------------------------- layout
    def _build(self):
        side = tk.Frame(self, bg=theme.SIDEBAR, width=232)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Frame(self, bg=theme.BORDER, width=1).pack(side="left", fill="y")
        brand = tk.Frame(side, bg=theme.SIDEBAR)
        brand.pack(fill="x", padx=18, pady=(20, 22))
        try:
            self._logo = tk.PhotoImage(file=os.path.join(app_root(), "assets", "logo30.png"))
            tk.Label(brand, image=self._logo, bg=theme.SIDEBAR, bd=0).pack(side="left")
        except tk.TclError:
            pass
        label(brand, APP_NAME, 11, True, bg=theme.SIDEBAR).pack(side="left", padx=10)

        host = tk.Frame(self, bg=theme.CONTENT)
        host.pack(side="left", fill="both", expand=True)
        self._nav: dict[str, tuple] = {}
        self._pages: dict[str, tk.Frame] = {}
        for name, cls, glyph in PAGES:
            self._pages[name] = cls(host, self)
            if name == "Settings":
                tk.Frame(side, bg=theme.SIDEBAR).pack(fill="both", expand=True)
            self._nav_item(side, name, glyph)
        tk.Frame(side, bg=theme.SIDEBAR, height=14).pack()
        label(side, f"v{__version__}", 8, fg=theme.FAINT, bg=theme.SIDEBAR).pack(anchor="w", padx=22, pady=(0, 12))
        self.current = None

    def _nav_item(self, side, name, glyph):
        row = tk.Frame(side, bg=theme.SIDEBAR, cursor="hand2")
        row.pack(fill="x", padx=12, pady=2)
        ic = tk.Label(row, text=glyph, font=theme.icon(13), fg=theme.MUTED, bg=theme.SIDEBAR, bd=0, width=2)
        ic.pack(side="left", padx=(12, 6), pady=11)
        tx = label(row, name, 10, fg=theme.MUTED, bg=theme.SIDEBAR)
        tx.pack(side="left")
        for w in (row, ic, tx):
            w.bind("<Button-1>", lambda _e, n=name: self.show(n))
            w.bind("<Enter>", lambda _e, n=name: self._nav_hover(n, True))
            w.bind("<Leave>", lambda _e, n=name: self._nav_hover(n, False))
        self._nav[name] = (row, ic, tx)

    def _paint_nav(self, name, bg, icon_fg, text_fg, bold):
        row, ic, tx = self._nav[name]
        for w in (row, ic, tx):
            w.configure(bg=bg)
        ic.configure(fg=icon_fg)
        tx.configure(fg=text_fg, font=F(10, bold))

    def _nav_hover(self, name, on):
        if name != self.current:
            self._paint_nav(name, theme.CARD if on else theme.SIDEBAR, theme.MUTED, theme.TEXT if on else theme.MUTED, False)

    def show(self, name):
        if self.current:
            self._pages[self.current].pack_forget()
            self._paint_nav(self.current, theme.SIDEBAR, theme.MUTED, theme.MUTED, False)
        self.current = name
        self._paint_nav(name, theme.CARD, theme.AMBER, theme.TEXT, True)
        page = self._pages[name]
        page.pack(fill="both", expand=True, padx=34, pady=(26, 24))
        page.on_show()

    def set_status(self, text):
        log.info(text)

    # ---------------------------------------------------------- background work
    def post(self, fn):
        self._q.put(fn)

    def _poll(self):
        try:
            while True:
                self._q.get_nowait()()
        except queue.Empty:
            pass
        except Exception:
            log.exception("UI callback failed")
        self.after(50, self._poll)

    def run_bg(self, work, done):
        def target():
            try:
                res = work()
            except Exception as e:  # reported on the UI thread
                log.exception("background task failed")
                res = e
            self.post(lambda: done(res))
        threading.Thread(target=target, daemon=True).start()

    # ---------------------------------------------------------- scan
    def start_scan(self):
        if self.busy:
            return
        self.busy = True
        cancel = threading.Event()
        dlg = ProgressDialog(self, "Scanning your PC", cancel)
        total = len(self.rules)
        done_n = [0]

        def on_result(res):
            done_n[0] += 1
            n = done_n[0]
            self.post(lambda: dlg.update_progress(n, total, res.rule.label))

        def work():
            hours = max(0, int(self.store.get("temp_min_age_hours", 24)))
            for r in self.rules:
                if r.id in ("user_temp", "windows_temp"):
                    r.min_age_days = hours / 24
            running = winapi.running_processes()
            info = winapi.managed_info(running)
            lock = info["managed"] and (bool(self.store.get("protect_managed", True)) or info["policy_lock"])
            to_scan = [r for r in self.rules if not (lock and r.id in MANAGED_LOCKED_RULES)]
            ctx = ScanContext(admin=self.admin, running=running)
            res = scan_all(to_scan, cancel, on_result, ctx)
            for r in self.rules:
                if r.id not in res:
                    res[r.id] = RuleResult(rule=r, status="managed")
            # the plan the user sees must be the plan that runs: drop anything the guard would refuse
            for rid, rr in res.items():
                if rr.status != "ok":
                    continue
                refused = self.guard.register(rid, rr.roots)
                if refused:
                    log.warning("rule %s: refused roots %s", rid, refused)
                rr.items, rr.protected = self.guard.filter_items(rid, rr.items)
                rr.count = len(rr.items)
                rr.size = sum(i.size for i in rr.items)
                if not rr.count:
                    rr.status = "empty"
            return res, info, lock

        def done(out):
            self.busy = False
            dlg.close()
            if isinstance(out, Exception):
                messagebox.showerror(APP_NAME, f"Scan failed:\n{out}", parent=self)
                return
            self.results, self.managed_info, self.managed_active = out
            self.scan_id += 1
            self.last_scan = time.time()
            self._pages[self.current].on_show()

        self.run_bg(work, done)

    def close_app(self, exe):
        """Politely ask a program to close (no /F: it can still show its own save prompt)."""
        if not messagebox.askyesno(APP_NAME, f"Ask {exe} to close?\nIt may prompt you to save your work.", parent=self):
            return

        def work():
            winapi.close_process(exe)
            time.sleep(2)
        self.run_bg(work, lambda _r: self.start_scan())

    # ---------------------------------------------------------- clean
    def clean(self, items, label_text, on_done=None, dry_only=False, force_real=False):
        if self.busy:
            return
        if not items:
            messagebox.showinfo(APP_NAME, "Nothing selected.", parent=self)
            return
        size = sum(i.size for i in items)
        files = sum(i.n for i in items)
        by_rule: dict[str, list] = {}
        for it in items:
            e = by_rule.setdefault(it.rule_id, [0, 0])
            e[0] += it.n
            e[1] += it.size
        rows = sorted(((self.rule_labels.get(k, k), v[0], v[1]) for k, v in by_rule.items()), key=lambda r: -r[2])
        rule_by_id = {r.id: r for r in self.rules}
        review = [rule_by_id[k].label for k in by_rule if k in rule_by_id and rule_by_id[k].risk != "safe"]
        recycle = sum(i.n for i in items if i.path == RECYCLE_PSEUDO_PATH)
        keep_ids = {k for k in by_rule if k in LOG_RULES}

        if dry_only:
            dry, keep = True, False
        else:
            first = not (self.store.get("real_run_done", False) or self.store.get("dry_run_done", False))
            dry_default = not force_real and (bool(self.store.get("dry_run_always", False)) or first)
            dlg = ConfirmDialog(self, rows, files, size, review, dry_default, bool(keep_ids), recycle,
                                self.quarantine.keep_days)
            self.wait_window(dlg)
            if not dlg.result:
                return
            dry, keep = dlg.result["dry_run"], dlg.result["keep"]
        self.executor.force_quarantine = keep_ids if keep else set()

        self.busy = True
        cancel = threading.Event()
        prog = ProgressDialog(self, "Dry run" if dry else "Cleaning", cancel)

        def progress(d, t, p):
            self.post(lambda: prog.update_progress(d, t, p))

        def work():
            return self.executor.run(items, dry_run=dry, cancel=cancel, progress=progress, label=label_text)

        def done(rep):
            self.busy = False
            prog.close()
            if isinstance(rep, Exception):
                messagebox.showerror(APP_NAME, f"Clean failed:\n{rep}", parent=self)
                return
            try:
                self.store.save_run(rep)
                self.store.set("real_run_done" if not dry else "dry_run_done", True)
            except Exception:
                log.exception("saving history failed")
            res = ResultDialog(self, rep, self.rule_labels, self.quarantine.keep_days)
            self.wait_window(res)
            if res.result == "undo":
                self.restore(rep.run_id)
            if res.result == "clean":
                self.clean(items, label_text, on_done, force_real=True)
                return
            if not dry and self.results:
                self.start_scan()
            elif self.current:
                self._pages[self.current].on_show()
            if on_done:
                on_done(rep)

        self.run_bg(work, done)

    def restore(self, run_id):
        n, failed = self.quarantine.restore(run_id)
        msg = f"Restored {n} files."
        if failed:
            msg += f"\n{len(failed)} could not be restored:\n" + "\n".join(f"• {p}: {e}" for p, e in failed[:5])
        messagebox.showinfo(APP_NAME, msg, parent=self)
        if self.results and not self.busy:
            self.start_scan()

    def set_theme(self, mode):
        """Switch light/dark/system and rebuild the window (scan results are kept)."""
        self.theme_mode = mode
        self.store.set("theme", mode)
        theme.apply(mode)
        theme.setup_style(self)
        cur = self.current or "Dashboard"
        for w in self.winfo_children():
            w.destroy()
        self._build()
        self.show(cur)
        theme.dark_titlebar(self)
