"""Executor: deletes or quarantines Items that pass the Safety Guard. Never force-kills anything."""
from __future__ import annotations

import errno
import os
import secrets
import stat
import time

from . import winapi
from .models import Item, RunReport, Skipped
from .quarantine import Quarantine
from .safety import ANALYZER_PREFIX, SafetyGuard
from .scanner import CLIPBOARD_PSEUDO_PATH, DNS_PSEUDO_PATH, RECYCLE_PSEUDO_PATH, is_reparse


def new_run_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)


def _reason(e: OSError) -> str:
    we = getattr(e, "winerror", None)
    if we in (32, 33):
        return "File in use by another program"
    if we == 5 or isinstance(e, PermissionError) or e.errno in (errno.EACCES, errno.EPERM):
        return "Access denied"
    if isinstance(e, FileNotFoundError):
        return "Already gone"
    return e.strerror or str(e)


def _remove(path: str) -> None:
    """Remove one filesystem entry. Links are unlinked, never followed."""
    st = os.lstat(path)
    if is_reparse(st):
        try:
            os.unlink(path)
        except OSError:
            os.rmdir(path)           # directory junctions
        return
    if stat.S_ISDIR(st.st_mode):
        os.rmdir(path)               # only succeeds when empty
        return
    try:
        os.remove(path)
    except PermissionError:
        os.chmod(path, stat.S_IWRITE)  # read-only attribute: clear it and retry once
        os.remove(path)


class Executor:
    def __init__(self, guard: SafetyGuard, quarantine: Quarantine, rules_by_id: dict):
        self.guard = guard
        self.quarantine = quarantine
        self.rules = rules_by_id
        self.force_quarantine: set = set()   # rule ids the user asked to keep a restorable copy of

    def _wants_quarantine(self, item: Item) -> bool:
        if item.rule_id in self.force_quarantine:
            return True
        rule = self.rules.get(item.rule_id)
        return True if rule is None else rule.use_quarantine

    def run(self, items, *, dry_run: bool, cancel=None, progress=None, label: str = "") -> RunReport:
        t0 = time.time()
        report = RunReport(run_id=new_run_id(), dry_run=dry_run, label=label)
        total = len(items)
        qrun = None
        pruned_dirs: set[str] = set()
        last_tick = 0.0
        try:
            for i, item in enumerate(items):
                if cancel is not None and cancel.is_set():
                    report.cancelled = True
                    break
                now = time.time()
                if progress and (now - last_tick > 0.05 or i == total - 1):
                    last_tick = now
                    progress(i, total, item.path)

                if item.path == RECYCLE_PSEUDO_PATH:
                    if dry_run:
                        report.would_free += item.size
                    else:
                        ok, why = winapi.empty_recycle_bin()
                        if ok:
                            report.freed += item.size
                            report.deleted_files += item.n
                        else:
                            report.skipped.append(Skipped("Recycle Bin", why, item.size, item.rule_id))
                    report.by_rule[item.rule_id] = report.by_rule.get(item.rule_id, 0) + item.size
                    continue

                if item.path in (CLIPBOARD_PSEUDO_PATH, DNS_PSEUDO_PATH):
                    if not dry_run:
                        ok, why = (winapi.clear_clipboard() if item.path == CLIPBOARD_PSEUDO_PATH
                                   else winapi.flush_dns())
                        if not ok:
                            report.skipped.append(Skipped(item.path, why, 0, item.rule_id))
                            continue
                    report.by_rule[item.rule_id] = report.by_rule.get(item.rule_id, 0)
                    continue

                ok, why = self.guard.check(item.path, item.rule_id, fresh=not dry_run)
                if not ok:
                    report.skipped.append(Skipped(item.path, why, item.size, item.rule_id))
                    continue

                if dry_run:
                    report.would_free += item.size
                    report.by_rule[item.rule_id] = report.by_rule.get(item.rule_id, 0) + item.size
                    continue

                try:
                    lst = os.lstat(item.path)
                except FileNotFoundError:
                    continue
                except OSError as e:
                    report.skipped.append(Skipped(item.path, _reason(e), item.size, item.rule_id))
                    continue

                try:
                    plain_file = not is_reparse(lst) and not stat.S_ISDIR(lst.st_mode)
                    if self._wants_quarantine(item) and plain_file:
                        if qrun is None:
                            qrun = self.quarantine.begin(report.run_id, label)
                        qrun.store(item.path, item.size)
                        report.quarantined += 1
                        report.quarantined_bytes += item.size
                    else:
                        _remove(item.path)
                        report.deleted_files += 1
                        report.freed += item.size
                        self._prune_empty_parents(item, pruned_dirs)
                    report.by_rule[item.rule_id] = report.by_rule.get(item.rule_id, 0) + item.size
                except OSError as e:
                    report.skipped.append(Skipped(item.path, _reason(e), item.size, item.rule_id))
        finally:
            if qrun is not None:
                qrun.save()
                qrun.discard_if_empty()
            report.seconds = time.time() - t0
        if progress:
            progress(total, total, "")
        return report

    def _prune_empty_parents(self, item: Item, tried: set) -> None:
        """After a delete, remove now-empty parent folders, but never the rule root itself."""
        if item.rule_id.startswith(ANALYZER_PREFIX):
            return
        roots = self.guard._roots.get(item.rule_id, [])
        parent = os.path.dirname(os.path.abspath(item.path))
        while parent and parent not in tried:
            n = os.path.normcase(parent)
            if any(n == lex for lex, _ in roots) or not any(n.startswith(lex + os.sep) for lex, _ in roots):
                break
            tried.add(parent)
            try:
                os.rmdir(parent)
            except OSError:
                break
            parent = os.path.dirname(parent)
