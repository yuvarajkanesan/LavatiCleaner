import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lavaticleaner.core import disks

REPORT = """
Invoking analysis on OS (C:)...

The operation completed successfully.

Post Defragmentation Report:

        Volume Information:
                Volume size                 = 465.12 GB
                Free space                  = 120.30 GB
                Total fragmented space      = 7%
                Largest free space extent   = 80.00 GB
"""


class ParseTest(unittest.TestCase):
    def test_fragmentation_percent(self):
        self.assertEqual(disks.parse_fragmentation(REPORT), 7)
        self.assertEqual(disks.parse_fragmentation("Volume is 12% fragmented"), 12)
        self.assertIsNone(disks.parse_fragmentation("Der Vorgang wurde erfolgreich abgeschlossen."))

    def test_error_detection(self):
        txt = "The storage optimizer cannot start because you have insufficient privileges (0x89000024)"
        self.assertIn("Administrator", disks.find_error(txt))
        self.assertIn("0x89000099", disks.find_error("failed (0x89000099)"))
        self.assertEqual(disks.find_error(REPORT), "")


class DriveTest(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows only")
    def test_lists_system_drive_with_kind(self):
        drives = disks.list_drives()
        letters = {d.letter for d in drives}
        self.assertIn(os.environ.get("SystemDrive", "C:")[0].upper(), letters)
        for d in drives:
            self.assertIn(d.kind, ("ssd", "hdd", "unknown"))
            self.assertGreater(d.total, 0)
            self.assertEqual(d.can_defrag, d.kind == "hdd")     # SSDs are never offered a defrag


@unittest.skipUnless(os.name == "nt", "uses cmd.exe as a stand-in program")
class RunTest(unittest.TestCase):
    CMD = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "cmd.exe")

    def test_streams_lines_and_succeeds(self):
        got = []
        ok, err, text = disks.run_defrag("C", "analyze", got.append, exe=self.CMD,
                                         extra_args=["/c", "echo one& echo two"])
        self.assertTrue(ok, err)
        self.assertEqual([g.strip() for g in got], ["one", "two"])

    def test_error_text_fails_even_with_exit_code_zero(self):
        ok, err, _ = disks.run_defrag("C", "optimize", exe=self.CMD,
                                      extra_args=["/c", "echo cannot start (0x89000024)"])
        self.assertFalse(ok)
        self.assertIn("Administrator", err)

    def test_cancel_stops_a_long_operation(self):
        cancel = threading.Event()
        threading.Timer(0.5, cancel.set).start()
        t0 = time.time()
        ok, err, _ = disks.run_defrag("C", "optimize", cancel=cancel, exe=self.CMD,
                                      extra_args=["/c", "ping -n 30 127.0.0.1 >nul"])
        self.assertFalse(ok)
        self.assertEqual(err, "Cancelled.")
        self.assertLess(time.time() - t0, 10)

    def test_rejects_bad_letter(self):
        self.assertFalse(disks.run_defrag("C:\\x", "analyze")[0])


if __name__ == "__main__":
    unittest.main()
