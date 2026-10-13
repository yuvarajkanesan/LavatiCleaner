"""Scanner: walks rule paths with os.scandir and yields Items. Never deletes anything."""
from __future__ import annotations

import fnmatch
import glob
import os
import stat
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from . import winapi
from .models import Item, Rule, RuleResult

REPARSE = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT (junctions, symlinks, OneDrive placeholders)
RECYCLE_PSEUDO_PATH = "::recycle_bin::"
CLIPBOARD_PSEUDO_PATH = "::clipboard::"
DNS_PSEUDO_PATH = "::dns::"


def is_reparse(st: os.stat_result) -> bool:
    return bool(getattr(st, "st_file_attributes", 0) & REPARSE) or stat.S_ISLNK(st.st_mode)


def expand_paths(patterns) -> list[str]:
    """Expand env vars and * / ? wildcards. Unresolved %VARS% and missing paths are dropped."""
    out, seen = [], set()
    for p in patterns:
        e = os.path.expandvars(p)
        if "%" in e:
            continue
        matches = glob.glob(e) if ("*" in e or "?" in e) else ([e] if os.path.exists(e) else [])
        for m in matches:
            key = os.path.normcase(os.path.abspath(m))
            if key not in seen:
                seen.add(key)
                out.append(os.path.abspath(m))
    return out


@dataclass
class ScanContext:
    admin: bool = field(default_factory=winapi.is_admin)
    running: set = field(default_factory=set)
    now: float = field(default_factory=time.time)


def _name_ok(name: str, include, exclude) -> bool:
    if not any(fnmatch.fnmatch(name, pat) for pat in include):
        return False
    return not any(fnmatch.fnmatch(name, pat) for pat in exclude)


def iter_files(root, *, include=("*",), exclude=(), cutoff=None, recursive=True,
               skip_dirs=(), cancel=None, errors=None, follow_dirs_named=None):
    """Yield (path, size, mtime). Reparse points are yielded as zero-size entries and never entered."""
    skip = {s.lower() for s in skip_dirs}
    stack = [root]
    while stack:
        if cancel is not None and cancel.is_set():
            return
        d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError:
            if errors is not None:
                errors[0] += 1
            continue
        with it:
            for e in it:
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    if errors is not None:
                        errors[0] += 1
                    continue
                if is_reparse(st):
                    if _name_ok(e.name, include, exclude) and (cutoff is None or st.st_mtime <= cutoff):
                        yield e.path, 0, st.st_mtime
                    continue
                if stat.S_ISDIR(st.st_mode):
                    if recursive and e.name.lower() not in skip:
                        stack.append(e.path)
                    continue
                if not _name_ok(e.name, include, exclude):
                    continue
                if cutoff is not None and st.st_mtime > cutoff:
                    continue
                yield e.path, st.st_size, st.st_mtime


def _find_named_dirs(root, name, skip_dirs, cancel):
    """Directories called `name` under root (not descending into matches)."""
    skip = {s.lower() for s in skip_dirs}
    target = name.lower()
    stack = [root]
    while stack:
        if cancel is not None and cancel.is_set():
            return
        d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    if not e.is_dir(follow_symlinks=False):
                        continue
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if is_reparse(st):
                    continue
                low = e.name.lower()
                if low == target:
                    yield e.path
                elif low not in skip:
                    stack.append(e.path)


def scan_rule(rule: Rule, ctx: ScanContext, cancel=None) -> RuleResult:
    res = RuleResult(rule=rule)
    res.running = [p for p in rule.requires_closed if p.lower() in ctx.running]
    if rule.requires_admin and not ctx.admin:
        res.status = "needs_admin"
        return res

    if rule.action in ("clipboard", "flush_dns"):      # one-shot actions: nothing to size
        path = CLIPBOARD_PSEUDO_PATH if rule.action == "clipboard" else DNS_PSEUDO_PATH
        res.items.append(Item(path, 0, ctx.now, rule.id, 1))
        res.count = 1
        return res

    if rule.action == "recycle_bin":
        size, n = winapi.recycle_bin_info()
        if n:
            res.items.append(Item(RECYCLE_PSEUDO_PATH, size, ctx.now, rule.id, n))
            res.size, res.count = size, n
        else:
            res.status = "empty"
        return res

    cutoff = ctx.now - rule.min_age_days * 86400 if rule.min_age_days else None
    errors = [0]
    roots = expand_paths(rule.paths)
    res.roots = roots
    for root in roots:
        if cancel is not None and cancel.is_set():
            break
        try:
            st = os.lstat(root)
        except OSError:
            continue
        if not stat.S_ISDIR(st.st_mode) or is_reparse(st):
            if not is_reparse(st) and _name_ok(os.path.basename(root), rule.include, rule.exclude) \
                    and (cutoff is None or st.st_mtime <= cutoff):
                res.items.append(Item(root, st.st_size, st.st_mtime, rule.id))
            continue
        if rule.dir_name:
            walkers = (
                (p for found in _find_named_dirs(root, rule.dir_name, rule.skip_dirs, cancel)
                 for p in iter_files(found, include=rule.include, exclude=rule.exclude,
                                     cutoff=cutoff, recursive=True, cancel=cancel, errors=errors))
            )
        else:
            walkers = iter_files(root, include=rule.include, exclude=rule.exclude, cutoff=cutoff,
                                 recursive=rule.recursive, skip_dirs=(), cancel=cancel, errors=errors)
        for path, size, mtime in walkers:
            res.items.append(Item(path, size, mtime, rule.id))
            res.size += size
    res.count = len(res.items)
    res.errors = errors[0]
    if not res.count:
        res.status = "empty"
    return res


def scan_all(rules, cancel=None, on_result=None, ctx: ScanContext | None = None, workers=4) -> dict:
    ctx = ctx or ScanContext(running=winapi.running_processes())
    results: dict[str, RuleResult] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(scan_rule, r, ctx, cancel): r for r in rules}
        for fut in as_completed(futures):
            rule = futures[fut]
            try:
                res = fut.result()
            except Exception:  # a broken rule must not abort the whole scan
                res = RuleResult(rule=rule, status="empty", errors=1)
            results[rule.id] = res
            if on_result:
                on_result(res)
    return results
