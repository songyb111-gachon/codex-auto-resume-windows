r"""A purge says it removed the settings and the recovery history only when it did.

-Purge removed config\ and logs\ without asking whether that worked, and always ended "Removed, including settings
and recovery history" - over a log file something still held (the v0.6.18 installer audit, M3). The uninstall tail is
lifted verbatim and run against scratch folders (tests/test_installer_uninstall_sweep.py's harness). Nothing real is
asked or changed.
"""
from __future__ import annotations

import sys
import unittest

from test_installer_uninstall_sweep import UninstallFixture, tail


@unittest.skipUnless(sys.platform == "win32", "the installer is Windows PowerShell")
class PurgeSaysWhatItDidTests(UninstallFixture):
    def test_a_purge_that_removed_everything_says_so(self):
        done = tail(self.home, self.folder, purge=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("Removed, including settings and recovery history.", done.stdout)
        self.assertFalse((self.home / "logs").exists())

    def test_a_held_log_is_said_and_the_purge_does_not_claim_it(self):
        with (self.home / "logs" / "auto-resume.log").open("rb"):
            done = tail(self.home, self.folder, purge=True)
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertNotIn("Removed, including settings and recovery history.", done.stdout)
        self.assertIn("could not be removed", done.stdout)
        self.assertIn(str(self.home / "logs"), done.stdout)


del UninstallFixture

if __name__ == "__main__":
    unittest.main()
