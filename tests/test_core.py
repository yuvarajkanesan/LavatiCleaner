import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lavaticleaner.core import analyzers
from lavaticleaner.core.executor import Executor
from lavaticleaner.core.history import Store
from lavaticleaner.core.models import Rule
from lavaticleaner.core.paths import rules_dir
from lavaticleaner.core.quarantine import Quarantine
from lavaticleaner.core.rules import load_rules
from lavaticleaner.core.safety import SafetyGuard
from lavaticleaner.core.scanner import ScanContext, scan_rule


def write(path, data=b"x" * 100):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = os.path.realpath(self._tmp.name)
        self.root = os.path.join(self.tmp, "target")
        os.makedirs(self.root)
        self.ctx = ScanContext(admin=True, running=set())

    def tearDown(self):
        self._tmp.cleanup()

    def rule(self, **kw):
        base = dict(id="t", category="Test", label="Test", paths=[self.root])
        base.update(kw)
        return Rule(**base)

    def make_exec(self, rule):
        g = SafetyGuard()
        self.assertEqual(g.register(rule.id, [self.root]), [])
        q = Quarantine(os.path.join(self.tmp, "q"))
        return Executor(g, q, {rule.id: rule}), q


class RulesTest(unittest.TestCase):
    def test_shipped_rules_load(self):
        rules, errors = load_rules(rules_dir())
        self.assertEqual(errors, [])
        ids = [r.id for r in rules]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("user_temp", ids)


class ScanTest(Base):
    def test_scan_counts_and_age_filter(self):
        write(os.path.join(self.root, "a.tmp"))
        write(os.path.join(self.root, "sub", "b.tmp"))
        old = os.path.join(self.root, "old.log")
        write(old)
        os.utime(old, (time.time() - 40 * 86400,) * 2)
        res = scan_rule(self.rule(), self.ctx)
        self.assertEqual(res.count, 3)
        res = scan_rule(self.rule(min_age_days=30), self.ctx)
        self.assertEqual([os.path.basename(i.path) for i in res.items], ["old.log"])

    def test_needs_admin(self):
        res = scan_rule(self.rule(requires_admin=True), ScanContext(admin=False, running=set()))
        self.assertEqual(res.status, "needs_admin")

    @unittest.skipUnless(os.name == "nt", "junctions are Windows-only")
    def test_junction_not_followed(self):
        outside = os.path.join(self.tmp, "outside")
        write(os.path.join(outside, "precious.txt"))
        link = os.path.join(self.root, "link")
        import subprocess
        subprocess.run(["cmd", "/c", "mklink", "/J", link, outside], check=True, capture_output=True)
        res = scan_rule(self.rule(), self.ctx)
        self.assertFalse(any("precious" in i.path for i in res.items))
        rule = self.rule()
        ex, _ = self.make_exec(rule)
        ex.run(res.items, dry_run=False)
        self.assertTrue(os.path.exists(os.path.join(outside, "precious.txt")))

    def test_dir_name_mode(self):
        write(os.path.join(self.root, "proj", "__pycache__", "m.pyc"))
        write(os.path.join(self.root, "proj", "keep.py"))
        res = scan_rule(self.rule(dir_name="__pycache__", include=["*.pyc"]), self.ctx)
        self.assertEqual(res.count, 1)


class ExecTest(Base):
    def test_dry_run_deletes_nothing(self):
        p = os.path.join(self.root, "a.tmp")
        write(p)
        rule = self.rule()
        res = scan_rule(rule, self.ctx)
        ex, _ = self.make_exec(rule)
        rep = ex.run(res.items, dry_run=True)
        self.assertTrue(os.path.exists(p))
        self.assertEqual(rep.would_free, 100)

    def test_delete_and_prune_empty_dirs(self):
        p = os.path.join(self.root, "sub", "a.tmp")
        write(p)
        rule = self.rule(quarantine=False)
        res = scan_rule(rule, self.ctx)
        ex, _ = self.make_exec(rule)
        rep = ex.run(res.items, dry_run=False)
        self.assertEqual(rep.freed, 100)
        self.assertFalse(os.path.exists(os.path.dirname(p)))
        self.assertTrue(os.path.isdir(self.root))

    def test_quarantine_and_restore(self):
        p = os.path.join(self.root, "inst.exe")
        write(p, b"data")
        rule = self.rule(risk="review", quarantine=True)
        res = scan_rule(rule, self.ctx)
        ex, q = self.make_exec(rule)
        rep = ex.run(res.items, dry_run=False)
        self.assertFalse(os.path.exists(p))
        self.assertEqual(rep.quarantined, 1)
        self.assertEqual(rep.freed, 0)
        n, failed = q.restore(rep.run_id)
        self.assertEqual((n, failed), (1, []))
        with open(p, "rb") as fh:
            self.assertEqual(fh.read(), b"data")

    def test_guard_rejects_outside_item(self):
        from lavaticleaner.core.models import Item
        outside = os.path.join(self.tmp, "other.txt")
        write(outside)
        rule = self.rule()
        ex, _ = self.make_exec(rule)
        rep = ex.run([Item(outside, 100, time.time(), rule.id)], dry_run=False)
        self.assertTrue(os.path.exists(outside))
        self.assertEqual(rep.skipped_count, 1)

    def test_guard_refuses_broad_root(self):
        g = SafetyGuard()
        self.assertEqual(g.register("x", [os.path.expanduser("~")]), [os.path.expanduser("~")])

    def test_locked_file_skipped(self):
        p = os.path.join(self.root, "locked.tmp")
        write(p)
        rule = self.rule(quarantine=False)
        res = scan_rule(rule, self.ctx)
        ex, _ = self.make_exec(rule)
        with open(p, "rb"):
            rep = ex.run(res.items, dry_run=False)
        if os.name == "nt":
            self.assertEqual(rep.skipped_count, 1)
            self.assertIn("in use", rep.skipped[0].reason)

    def test_cancel(self):
        for i in range(5):
            write(os.path.join(self.root, f"{i}.tmp"))
        rule = self.rule(quarantine=False)
        res = scan_rule(rule, self.ctx)
        ex, _ = self.make_exec(rule)
        ev = threading.Event()
        ev.set()
        rep = ex.run(res.items, dry_run=False, cancel=ev)
        self.assertTrue(rep.cancelled)
        self.assertEqual(len(os.listdir(self.root)), 5)


class TempCleanTest(Base):
    def _old(self, path, days=3):
        t = time.time() - days * 86400
        os.utime(path, (t, t))

    def _age_dirs(self):
        for r, ds, _fs in os.walk(self.root, topdown=False):
            for d in ds:
                self._old(os.path.join(r, d))

    def test_empty_folders_are_removed_but_root_stays(self):
        write(os.path.join(self.root, "a", "b", "c", "old.tmp"))
        os.makedirs(os.path.join(self.root, "x", "y", "z"))              # already empty
        os.makedirs(os.path.join(self.root, "m", "n"))
        write(os.path.join(self.root, "m", "n", "old2.tmp"))
        for r, _d, fs in os.walk(self.root):
            for f in fs:
                self._old(os.path.join(r, f))
        self._age_dirs()
        rule = self.rule(min_age_days=1, prune_empty=True, quarantine=False)
        res = scan_rule(rule, self.ctx)
        ex, _ = self.make_exec(rule)
        rep = ex.run(res.items, dry_run=False)
        self.assertEqual(rep.skipped_count, 0)
        self.assertEqual(os.listdir(self.root), [])                      # everything gone, root kept
        self.assertTrue(os.path.isdir(self.root))

    def test_recent_files_and_their_folders_are_kept_and_counted(self):
        write(os.path.join(self.root, "keep", "fresh.tmp"))              # new: must survive
        write(os.path.join(self.root, "gone", "old.tmp"))
        self._old(os.path.join(self.root, "gone", "old.tmp"))
        self._age_dirs()
        rule = self.rule(min_age_days=1, prune_empty=True, quarantine=False)
        res = scan_rule(rule, self.ctx)
        self.assertEqual(res.young, 1)
        ex, _ = self.make_exec(rule)
        ex.run(res.items, dry_run=False)
        self.assertTrue(os.path.exists(os.path.join(self.root, "keep", "fresh.tmp")))
        self.assertFalse(os.path.exists(os.path.join(self.root, "gone")))

    @unittest.skipUnless(os.name == "nt", "file locking semantics are Windows-specific")
    def test_folder_with_a_locked_file_is_left_quietly(self):
        locked = os.path.join(self.root, "busy", "lock.tmp")
        write(locked)
        write(os.path.join(self.root, "busy", "free.tmp"))
        for f in (locked, os.path.join(self.root, "busy", "free.tmp")):
            self._old(f)
        self._age_dirs()
        rule = self.rule(min_age_days=1, prune_empty=True, quarantine=False)
        res = scan_rule(rule, self.ctx)
        ex, _ = self.make_exec(rule)
        with open(locked, "rb"):
            rep = ex.run(res.items, dry_run=False)
        self.assertTrue(os.path.exists(locked))
        reasons = [s.reason for s in rep.skipped]
        self.assertEqual(reasons, ["File in use by another program"])    # no extra "directory not empty" noise

    def test_prune_is_off_by_default(self):
        os.makedirs(os.path.join(self.root, "empty"))
        res = scan_rule(self.rule(), self.ctx)
        self.assertEqual(res.count, 0)


class AnalyzerTest(Base):
    def test_staged_duplicates(self):
        big = b"a" * 5000
        write(os.path.join(self.root, "one.bin"), big)
        write(os.path.join(self.root, "two.bin"), big)
        # same size and same first 64KB prefix is impossible at this size; differ at the end
        write(os.path.join(self.root, "three.bin"), b"a" * 4999 + b"b")
        groups = analyzers.find_duplicates([self.root], min_bytes=1000)
        self.assertEqual(len(groups), 1)
        self.assertEqual(sorted(os.path.basename(i.path) for i in groups[0]), ["one.bin", "two.bin"])

    def test_large_files(self):
        write(os.path.join(self.root, "big.bin"), b"z" * 3000)
        write(os.path.join(self.root, "small.bin"), b"z" * 10)
        items = analyzers.find_large([self.root], 1000)
        self.assertEqual([os.path.basename(i.path) for i in items], ["big.bin"])

    def test_empty_folders(self):
        os.makedirs(os.path.join(self.root, "a", "b"))
        write(os.path.join(self.root, "c", "f.txt"))
        items = analyzers.find_empty_folders([self.root])
        paths = [os.path.relpath(i.path, self.root) for i in items]
        self.assertIn("a", paths)
        self.assertNotIn("c", paths)


class StoreTest(Base):
    def test_settings_and_runs(self):
        from lavaticleaner.core.models import RunReport
        s = Store(os.path.join(self.tmp, "h.db"))
        self.assertEqual(s.get("k", 5), 5)
        s.set("k", {"a": 1})
        self.assertEqual(s.get("k"), {"a": 1})
        s.save_run(RunReport(run_id="r1", dry_run=False, label="x", freed=42))
        self.assertEqual(s.total_freed(), 42)


if __name__ == "__main__":
    unittest.main()
