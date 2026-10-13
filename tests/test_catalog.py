import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lavaticleaner.core.executor import Executor
from lavaticleaner.core.paths import rules_dir
from lavaticleaner.core.quarantine import Quarantine
from lavaticleaner.core.rules import load_rules
from lavaticleaner.core.safety import MANAGED_LOCKED_RULES, SafetyGuard
from lavaticleaner.core.scanner import ScanContext, expand_paths, scan_rule


class CatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules, cls.errors = load_rules(rules_dir())

    def test_loads_cleanly(self):
        self.assertEqual(self.errors, [])
        self.assertGreaterEqual(len(self.rules), 70)

    def test_ids_unique_and_labels_unique_per_group(self):
        ids = [r.id for r in self.rules]
        self.assertEqual(len(ids), len(set(ids)))
        seen = {}
        for r in self.rules:
            key = (r.category, r.label)
            self.assertNotIn(key, seen, f"duplicate label {key}")
            seen[key] = r.id

    def test_both_tabs_and_expected_groups(self):
        tabs = {r.tab for r in self.rules}
        self.assertEqual(tabs, {"windows", "apps"})
        groups = {r.category for r in self.rules}
        for g in ("Edge Browser", "Chrome Browser", "Firefox Browser", "File Explorer Traces",
                  "Windows Housekeeping", "Deep Clean", "Developer Tools", "Office & Documents"):
            self.assertIn(g, groups)

    def test_every_browser_has_the_full_item_set(self):
        for pre in ("edge", "chrome", "brave", "vivaldi", "opera"):
            for item in ("cache", "cookies", "history", "session", "forms", "logins"):
                self.assertIn(f"{pre}_{item}", {r.id for r in self.rules})

    def test_privacy_items_are_never_safe_or_permanent(self):
        for r in self.rules:
            if r.id.endswith(("_cookies", "_history", "_session", "_forms", "_logins")):
                self.assertNotEqual(r.risk, "safe", r.id)
                self.assertTrue(r.use_quarantine, r.id)       # restorable
        for r in self.rules:
            if r.id.endswith(("_forms", "_logins")):
                self.assertEqual(r.risk, "advanced", r.id)

    def test_no_registry_and_no_bookmark_files(self):
        for r in self.rules:
            blob = " ".join(r.paths + r.include).lower()
            self.assertNotIn("hkey", blob)
            self.assertNotIn("places.sqlite", blob, f"{r.id} would delete Firefox bookmarks")
        self.assertNotIn("firefox_history", {r.id for r in self.rules})

    def test_workplace_and_security_software_not_targeted(self):
        for r in self.rules:
            blob = " ".join(r.paths).lower()
            for bad in ("teams", "outlook", "onedrive", "slack", "zoom", "defender", "crowdstrike", "intune"):
                self.assertNotIn(bad, blob, f"{r.id} touches {bad}")

    def test_managed_locked_ids_exist(self):
        self.assertTrue(MANAGED_LOCKED_RULES <= {r.id for r in self.rules})

    def test_no_rule_root_is_refused_by_the_guard(self):
        g = SafetyGuard()
        for r in self.rules:
            roots = expand_paths(r.paths)
            self.assertEqual(g.register(r.id, roots), [], f"{r.id}: {roots}")

    def test_no_rule_path_is_protected_software(self):
        g = SafetyGuard()
        for r in self.rules:
            for root in expand_paths(r.paths):
                self.assertEqual(g.protected_reason(os.path.normcase(os.path.abspath(root)) + os.sep), "", r.id)


class OneShotActionsTest(unittest.TestCase):
    def test_clipboard_and_dns_scan_and_dry_run(self):
        rules = {r.id: r for r in load_rules(rules_dir())[0]}
        ctx = ScanContext(admin=False, running=set())
        with tempfile.TemporaryDirectory() as tmp:
            ex = Executor(SafetyGuard(), Quarantine(os.path.join(tmp, "q")), rules)
            for rid in ("clipboard", "dns_cache"):
                res = scan_rule(rules[rid], ctx)
                self.assertEqual((res.count, res.status), (1, "ok"))
                rep = ex.run(res.items, dry_run=True)
                self.assertEqual(rep.skipped_count, 0)


if __name__ == "__main__":
    unittest.main()
