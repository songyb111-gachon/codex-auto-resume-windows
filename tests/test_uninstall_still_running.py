"""An uninstall that is taking long says so in a sentence of its own (v0.6.23): the installer's names the Dashboard to look at
again, and by then an uninstall may have removed it.

    PYTHONPATH="src;tests" python -m unittest test_uninstall_still_running
"""
from __future__ import annotations

import json
import unittest

import guiscan
from codex_auto_resume import l10n

KEY = "installer.done.still_removing"


class SentenceTests(unittest.TestCase):
    def test_the_uninstall_has_its_own_sentence_before_the_installer_s(self):
        """Fails with the uninstall's branch taken out: it would say to look at a Dashboard that may be gone."""
        body = guiscan.member_body("InstallerWords", "Outcome")
        self.assertLess(body.index("code == InstallerFlow.StillRunning && mode == InstallerFlow.Uninstall"),
                        body.index('Say("installer.done.still_running"'))
        self.assertIn('Say("%s"' % KEY, body)

    def test_every_language_has_it_and_it_is_not_the_installer_s(self):
        english = l10n.catalog("en")[KEY]
        self.assertNotIn("Dashboard", english)
        for locale in l10n.LOCALES:
            own = json.loads((l10n.DIRECTORY / ("%s.json" % locale)).read_text(encoding="utf-8"))
            with self.subTest(locale=locale):
                self.assertTrue(own[KEY].strip())
                self.assertNotEqual(own[KEY], own["installer.done.still_running"])
                if locale != "en":
                    self.assertNotEqual(own[KEY], english)


if __name__ == "__main__":
    unittest.main()
