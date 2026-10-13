"""Analyzers: duplicates, large files, empty folders. They only *suggest*; the Safety Guard and the
user decide what happens."""
from __future__ import annotations

import hashlib
import os
import stat
import time
from collections import defaultdict

from .models import Item
from .scanner import is_reparse, iter_files

DUP_RULE = "analyzer:duplicates"
LARGE_RULE = "analyzer:large"
EMPTY_RULE = "analyzer:empty"

SKIP_DIRS = {"appdata", "$recycle.bin", ".git", "node_modules", "windows", "program files",
             "program files (x86)", "system volume information", "__pycache__"}
PARTIAL_BYTES = 64 * 1024
CHUNK = 1024 * 1024


def _hash(path: str, limit: int | None = None, cancel=None) -> str | None:
    h = hashlib.blake2b(digest_size=20)
    try:
        with open(path, "rb") as fh:
            if limit is not None:
                h.update(fh.read(limit))
            else:
                while True:
                    if cancel is not None and cancel.is_set():
                        return None
                    buf = fh.read(CHUNK)
                    if not buf:
                        break
                    h.update(buf)
    except OSError:
        return None
    return h.hexdigest()


def _walk_roots(roots, cancel, rule_id, min_size, progress=None):
    seen = 0
    done_roots = set()
    for root in roots:
        n = os.path.normcase(os.path.abspath(root))
        if n in done_roots or not os.path.isdir(root):
            continue
        done_roots.add(n)
        for path, size, mtime in iter_files(root, skip_dirs=SKIP_DIRS, cancel=cancel):
            if size >= min_size and size > 0:
                seen += 1
                if progress and seen % 500 == 0:
                    progress(f"Scanning… {seen:,} files checked")
                yield Item(path, size, mtime, rule_id)


def find_large(roots, min_bytes: int, cancel=None, progress=None, limit: int = 2000) -> list[Item]:
    items = list(_walk_roots(roots, cancel, LARGE_RULE, min_bytes, progress))
    items.sort(key=lambda i: i.size, reverse=True)
    return items[:limit]


def find_duplicates(roots, min_bytes: int = 1024 * 1024, cancel=None, progress=None) -> list[list[Item]]:
    """Staged: group by size -> hash first 64 KB -> full BLAKE2 hash. Groups sorted by wasted space."""
    by_size: dict[int, list[Item]] = defaultdict(list)
    seen_paths = set()
    for it in _walk_roots(roots, cancel, DUP_RULE, min_bytes, progress):
        key = os.path.normcase(it.path)
        if key not in seen_paths:
            seen_paths.add(key)
            by_size[it.size].append(it)

    groups: list[list[Item]] = []
    candidates = [g for g in by_size.values() if len(g) > 1]
    for gi, group in enumerate(candidates):
        if cancel is not None and cancel.is_set():
            return []
        if progress:
            progress(f"Comparing candidates… {gi + 1}/{len(candidates)}")
        partial: dict[str, list[Item]] = defaultdict(list)
        for it in group:
            h = _hash(it.path, PARTIAL_BYTES)
            if h:
                partial[h].append(it)
        for sub in partial.values():
            if len(sub) < 2:
                continue
            full: dict[str, list[Item]] = defaultdict(list)
            for it in sub:
                h = _hash(it.path, None, cancel)
                if h:
                    full[h].append(it)
            groups.extend(g for g in full.values() if len(g) > 1)
    groups.sort(key=lambda g: g[0].size * (len(g) - 1), reverse=True)
    return groups


def find_empty_folders(roots, cancel=None, progress=None) -> list[Item]:
    out: list[Item] = []

    def visit(d: str) -> bool:
        """True when `d` contains nothing (or only empty folders)."""
        if cancel is not None and cancel.is_set():
            return False
        try:
            entries = list(os.scandir(d))
        except OSError:
            return False
        empty = True
        for e in entries:
            try:
                st = e.stat(follow_symlinks=False)
            except OSError:
                empty = False
                continue
            if is_reparse(st) or not stat.S_ISDIR(st.st_mode):
                empty = False
            elif e.name.lower() in SKIP_DIRS or not visit(e.path):
                empty = False
        if empty:
            out.append(Item(d, 0, time.time(), EMPTY_RULE))
        return empty

    for root in roots:
        if os.path.isdir(root):
            try:
                for e in os.scandir(root):          # never list the scan root itself
                    if e.is_dir(follow_symlinks=False) and e.name.lower() not in SKIP_DIRS \
                            and not is_reparse(e.stat(follow_symlinks=False)):
                        visit(e.path)
            except OSError:
                continue
    # delete deepest first so parents become empty
    out.sort(key=lambda i: i.path.count(os.sep), reverse=True)
    return out
