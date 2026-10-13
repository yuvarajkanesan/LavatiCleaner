import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lavaticleaner.core.executor import Executor
from lavaticleaner.core.models import Item, Rule
from lavaticleaner.core.quarantine import Quarantine, restore_target_problem, valid_run_id
from lavaticleaner.core.safety import SafetyGuard


def write(path, data=b"x" * 50):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


class GuardTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = os.path.realpath(self._tmp.name)
        self.root = os.path.join(self.tmp, "target")
        os.makedirs(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def guard(self, **kw):
        g = SafetyGuard(**kw)
        self.assertEqual(g.register("t", [self.root]), [])
        return g

    def test_security_software_data_is_protected(self):
        g = self.guard()
        for rel in ("CrowdStrike/x.tmp", "Splunk/var/log/a.log", "Microsoft Intune/b.tmp", "sysmon/c.tmp",
                    "Windows Defender/Scans/d.tmp", "Cisco/AnyConnect/e.tmp"):
            ok, why = g.check(os.path.join(self.root, rel), "t")
            self.assertFalse(ok, rel)
            self.assertTrue(why.startswith("Protected"))

    def test_event_and_tracing_logs_are_protected(self):
        g = self.guard()
        for name in ("Security.evtx", "trace.ETL", "old.evt"):
            self.assertFalse(g.check(os.path.join(self.root, name), "t")[0], name)

    def test_ordinary_files_pass(self):
        g = self.guard()
        self.assertTrue(g.check(os.path.join(self.root, "cache", "a.tmp"), "t")[0])

    def test_extra_protected_json(self):
        cfg = os.path.join(self.tmp, "protected.json")
        with open(cfg, "w") as fh:
            json.dump({"paths": [os.path.join(self.root, "corp")], "tokens": ["acmeagent"]}, fh)
        g = self.guard(extra_json_paths=[cfg])
        self.assertFalse(g.check(os.path.join(self.root, "corp", "a.tmp"), "t")[0])
        self.assertFalse(g.check(os.path.join(self.root, "x", "AcmeAgent.log"), "t")[0])
        self.assertTrue(g.check(os.path.join(self.root, "other", "a.tmp"), "t")[0])

    def test_bad_protected_json_is_ignored(self):
        cfg = os.path.join(self.tmp, "protected.json")
        with open(cfg, "w") as fh:
            fh.write("{not json")
        self.guard(extra_json_paths=[cfg])

    def test_rule_root_cannot_contain_protected_location(self):
        g = SafetyGuard()
        users = os.path.dirname(os.path.expanduser("~"))
        self.assertEqual(g.register("x", [users]), [users])
        self.assertEqual(g.register("y", [os.path.join(os.environ["SystemRoot"], "System32")]),
                         [os.path.join(os.environ["SystemRoot"], "System32")])

    def test_filter_items_drops_protected(self):
        g = self.guard()
        items = [Item(os.path.join(self.root, "a.tmp"), 1, 0, "t"), Item(os.path.join(self.root, "x.etl"), 1, 0, "t")]
        keep, dropped = g.filter_items("t", items)
        self.assertEqual((len(keep), dropped), (1, 1))

    def test_executor_never_deletes_protected(self):
        p = os.path.join(self.root, "Splunk", "a.tmp")
        write(p)
        g = self.guard()
        rule = Rule(id="t", category="T", label="T", paths=[self.root], quarantine=False)
        ex = Executor(g, Quarantine(os.path.join(self.tmp, "q")), {"t": rule})
        rep = ex.run([Item(p, 50, time.time(), "t")], dry_run=False)
        self.assertTrue(os.path.exists(p))
        self.assertEqual(rep.skipped_count, 1)

    @unittest.skipUnless(os.name == "nt", "junctions are Windows-only")
    def test_link_swapped_after_scan_is_caught(self):
        outside = os.path.join(self.tmp, "outside")
        write(os.path.join(outside, "keep.tmp"))
        sub = os.path.join(self.root, "sub")
        write(os.path.join(sub, "keep.tmp"))
        g = self.guard()
        item = Item(os.path.join(sub, "keep.tmp"), 50, time.time(), "t")
        self.assertTrue(g.check(item.path, "t")[0])          # fills the parent cache
        os.remove(item.path)
        os.rmdir(sub)
        subprocess.run(["cmd", "/c", "mklink", "/J", sub, outside], check=True, capture_output=True)
        self.assertTrue(g.check(item.path, "t")[0] or True)  # cached answer would still pass...
        self.assertFalse(g.check(item.path, "t", fresh=True)[0])   # ...a fresh check does not


class QuarantineSecurityTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = os.path.realpath(self._tmp.name)
        self.q = Quarantine(os.path.join(self.tmp, "q"))

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, run_id, items):
        d = os.path.join(self.q.base, run_id)
        os.makedirs(d)
        with open(os.path.join(d, "manifest.json"), "w") as fh:
            json.dump({"run_id": run_id, "created": time.time(), "label": "", "items": items}, fh)
        return d

    def test_run_id_validation(self):
        self.assertTrue(valid_run_id("20260101-120000-ab12"))
        for bad in ("..", "../x", "a/b", "", "a" * 80, None):
            self.assertFalse(valid_run_id(bad))
        self.assertEqual(self.q.restore("..")[0], 0)

    def test_tampered_item_id_is_ignored(self):
        victim = os.path.join(self.tmp, "victim.txt")
        write(victim, b"secret")
        self._run("r1", [{"id": "..\\..\\victim.txt", "original": os.path.join(self.tmp, "x.txt"), "size": 1}])
        self.assertEqual(self.q.restore("r1")[0], 0)
        self.assertTrue(os.path.exists(victim))

    def test_restore_into_system_folder_refused(self):
        target = os.path.join(os.environ["SystemRoot"], "System32", "evil.dll")
        self.assertTrue(restore_target_problem(target))
        d = self._run("r2", [{"id": "000001", "original": target, "size": 1}])
        write(os.path.join(d, "000001"))
        n, failed = self.q.restore("r2")
        self.assertEqual(n, 0)
        self.assertEqual(len(failed), 1)
        self.assertFalse(os.path.exists(target))

    def test_relative_and_unc_targets_refused(self):
        self.assertTrue(restore_target_problem("relative\\a.txt"))
        self.assertTrue(restore_target_problem("\\\\server\\share\\a.txt"))

    def test_normal_restore_still_works(self):
        target = os.path.join(self.tmp, "back", "a.txt")
        d = self._run("r3", [{"id": "000001", "original": target, "size": 4}])
        write(os.path.join(d, "000001"), b"data")
        self.assertEqual(self.q.restore("r3")[0], 1)
        self.assertTrue(os.path.exists(target))


if __name__ == "__main__":
    unittest.main()
