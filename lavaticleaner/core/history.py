"""SQLite storage for run history and settings."""
from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import time

from .models import RunReport
from .paths import data_dir

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, ts REAL, label TEXT, dry_run INTEGER,
    freed INTEGER, files INTEGER, quarantined INTEGER, quarantined_bytes INTEGER,
    would_free INTEGER, skipped INTEGER, seconds REAL, cancelled INTEGER
);
CREATE TABLE IF NOT EXISTS skipped (run_id TEXT, path TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""


class Store:
    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(data_dir(), "history.db")
        with self._conn() as c:
            c.executescript(_SCHEMA)

    @contextlib.contextmanager
    def _conn(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        try:
            with c:                      # commit / rollback
                yield c
        finally:
            c.close()                    # sqlite3's own `with` never closes (locks the file on Windows)

    # -- settings ------------------------------------------------------
    def get(self, key: str, default=None):
        with self._conn() as c:
            row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except ValueError:
            return default

    def set(self, key: str, value) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                      "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))

    # -- runs ----------------------------------------------------------
    def save_run(self, r: RunReport) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (r.run_id, time.time(), r.label, int(r.dry_run), r.freed, r.deleted_files,
                 r.quarantined, r.quarantined_bytes, r.would_free, r.skipped_count, r.seconds,
                 int(r.cancelled)))
            c.executemany("INSERT INTO skipped VALUES (?,?,?)",
                          [(r.run_id, s.path, s.reason) for s in r.skipped[:2000]])

    def runs(self, limit: int = 200) -> list[sqlite3.Row]:
        with self._conn() as c:
            return c.execute("SELECT * FROM runs ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()

    def skipped_for(self, run_id: str) -> list[sqlite3.Row]:
        with self._conn() as c:
            return c.execute("SELECT path, reason FROM skipped WHERE run_id=?", (run_id,)).fetchall()

    def total_freed(self) -> int:
        with self._conn() as c:
            row = c.execute("SELECT COALESCE(SUM(freed),0) AS t FROM runs WHERE dry_run=0").fetchone()
        return int(row["t"])
