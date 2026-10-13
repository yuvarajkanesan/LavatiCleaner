"""Quarantine: reversible deletion. Items are moved here with a manifest and expire after N days."""
from __future__ import annotations

import json
import os
import re
import shutil
import time

from .safety import _norm, _under, hard_block_paths, protected_prefixes

MANIFEST = "manifest.json"
_RUN_ID = re.compile(r"^[0-9A-Za-z\-]{1,40}$")
_ITEM_ID = re.compile(r"^\d{6}$")


def valid_run_id(run_id) -> bool:
    return isinstance(run_id, str) and bool(_RUN_ID.match(run_id))


def restore_target_problem(target) -> str:
    """Why `target` must not be restored to, or "" when it is fine. The manifest is data on disk, so it
    is never trusted: the target must be absolute, outside system/protected locations, and not reached
    through a link."""
    if not isinstance(target, str) or not os.path.isabs(target) or target.startswith("\\\\"):
        return "Original location is not a normal local path"
    n = _norm(target)
    if any(_under(n, b) for b in hard_block_paths()) or any(_under(n, p) for p in protected_prefixes()):
        return "Original location is a protected system folder"
    anc = os.path.dirname(n)
    while anc and not os.path.isdir(anc):
        up = os.path.dirname(anc)
        if up == anc:
            break
        anc = up
    if os.path.normcase(os.path.realpath(anc)) != os.path.normcase(os.path.abspath(anc)):
        return "A folder on the way to the original location is a link"
    return ""


class QuarantineRun:
    def __init__(self, base: str, run_id: str, label: str = ""):
        self.run_id = run_id
        self.dir = os.path.join(base, run_id)
        os.makedirs(self.dir, exist_ok=True)
        self.manifest = {"run_id": run_id, "created": time.time(), "label": label, "items": []}
        self._n = 0

    def store(self, path: str, size: int) -> None:
        self._n += 1
        stored = f"{self._n:06d}"
        shutil.move(path, os.path.join(self.dir, stored))
        self.manifest["items"].append({"id": stored, "original": os.path.abspath(path), "size": size})
        if self._n % 200 == 0:
            self.save()

    def save(self) -> None:
        tmp = os.path.join(self.dir, MANIFEST + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.manifest, fh)
        os.replace(tmp, os.path.join(self.dir, MANIFEST))

    @property
    def count(self) -> int:
        return len(self.manifest["items"])

    def discard_if_empty(self) -> None:
        if not self.count:
            shutil.rmtree(self.dir, ignore_errors=True)


class Quarantine:
    def __init__(self, base: str, keep_days: int = 7):
        self.base = base
        self.keep_days = keep_days
        os.makedirs(base, exist_ok=True)

    def begin(self, run_id: str, label: str = "") -> QuarantineRun:
        return QuarantineRun(self.base, run_id, label)

    def _load(self, run_dir: str):
        try:
            with open(os.path.join(run_dir, MANIFEST), encoding="utf-8") as fh:
                m = json.load(fh)
            items = m["items"]
            if not isinstance(items, list) or not isinstance(m["created"], (int, float)) \
                    or not valid_run_id(m["run_id"]):
                return None
            m["items"] = [i for i in items if isinstance(i, dict) and _ITEM_ID.match(str(i.get("id", "")))
                          and isinstance(i.get("original"), str) and isinstance(i.get("size"), int)]
            return m
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def list_runs(self) -> list[dict]:
        out = []
        for name in sorted(os.listdir(self.base), reverse=True):
            d = os.path.join(self.base, name)
            if not os.path.isdir(d):
                continue
            m = self._load(d)
            if not m:
                continue
            expires = m["created"] + self.keep_days * 86400
            out.append({
                "run_id": m["run_id"], "label": m.get("label", ""), "created": m["created"],
                "expires": expires, "count": len(m["items"]),
                "size": sum(i["size"] for i in m["items"]),
            })
        return out

    def get(self, run_id: str) -> dict | None:
        return next((r for r in self.list_runs() if r["run_id"] == run_id), None)

    def restore(self, run_id: str) -> tuple[int, list[tuple[str, str]]]:
        """Move items back. Never overwrites: an existing target gets a ' (restored)' suffix."""
        if not valid_run_id(run_id):
            return 0, [("", "Invalid run id")]
        d = os.path.join(self.base, run_id)
        m = self._load(d)
        if not m:
            return 0, [("", "Quarantine run not found")]
        restored, failed, remaining = 0, [], []
        for it in m["items"]:
            src = os.path.join(d, it["id"])
            if not os.path.lexists(src):
                continue
            target = it["original"]
            problem = restore_target_problem(target)
            if problem:
                failed.append((target, problem))
                remaining.append(it)
                continue
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                if os.path.lexists(target):
                    root, ext = os.path.splitext(target)
                    k, cand = 1, f"{root} (restored){ext}"
                    while os.path.lexists(cand):
                        k += 1
                        cand = f"{root} (restored {k}){ext}"
                    target = cand
                shutil.move(src, target)
                restored += 1
            except OSError as e:
                failed.append((it["original"], str(e)))
                remaining.append(it)
        if remaining:
            m["items"] = remaining
            with open(os.path.join(d, MANIFEST), "w", encoding="utf-8") as fh:
                json.dump(m, fh)
        else:
            shutil.rmtree(d, ignore_errors=True)
        return restored, failed

    def delete_run(self, run_id: str) -> None:
        if not valid_run_id(run_id):
            return
        shutil.rmtree(os.path.join(self.base, run_id), ignore_errors=True)

    def purge_expired(self) -> int:
        n = 0
        now = time.time()
        for r in self.list_runs():
            if now >= r["expires"]:
                self.delete_run(r["run_id"])
                n += 1
        return n

    def purge_all(self) -> int:
        runs = self.list_runs()
        for r in runs:
            self.delete_run(r["run_id"])
        return len(runs)
