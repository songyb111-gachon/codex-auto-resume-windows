# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""Start right after a reset is on unless a person turned it off (v0.6.20-beta.4, window_anchor).

Turning window_anchor on leaves Start right after a reset on: nothing stored for it reads as on - in the watcher's own
reading (engine/anchor.after_reset_on, which does not depend on its caller having filled the default in) and in what the
store hands the status - and only an explicit off is off. The page's side (its switch, and the card's line that it
starts nothing) is test_advanced_page_anchor_hint.

    PYTHONPATH=src;advanced/src;tests python -m unittest advanced/tests/test_advanced_anchor_default.py
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume_advanced import statement  # noqa: E402
from codex_auto_resume_advanced.engine import anchor  # noqa: E402
from codex_auto_resume_advanced.registry import WINDOW_ANCHOR  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Actor, OptionKey  # noqa: E402

CAP = "window_anchor"
KEY = OptionKey.ANCHOR_AFTER_RESET
ON, OFF = 1, 2


class ReadingTests(unittest.TestCase):
    def test_a_missing_value_is_on_and_only_an_explicit_off_is_off(self):
        """Fails with after_reset_on's default removed: a missing value reads as off."""
        for options in (None, {}, {OptionKey.ANCHOR_AT_1: anchor.TIME_OFF}, {KEY: ON}):
            with self.subTest(options=options):
                self.assertTrue(anchor.after_reset_on(options))
        self.assertFalse(anchor.after_reset_on({KEY: OFF}))

    def test_a_reset_seen_is_due_with_nothing_stored_and_not_with_an_explicit_off(self):
        """Fails with after_reset_on's default removed: the reset is never acted on."""
        seen = 1_000_000
        self.assertEqual(anchor.reset_due({}, seen + anchor.AFTER_RESET, seen, None), seen)
        self.assertIsNone(anchor.reset_due({KEY: OFF}, seen + anchor.AFTER_RESET, seen, None))


class StoredTests(ac.AdvancedCase):
    def test_turned_on_it_reads_on_until_a_person_turns_it_off_and_on_again_after_it_is_turned_on(self):
        rt = self.runtime(WINDOW_ANCHOR)
        rt.arming.catalogs = statement.CATALOGS
        self.assertEqual(WINDOW_ANCHOR.option(KEY).default, ON)
        done = rt.arming.arm(CAP, state="armed", revision=WINDOW_ANCHOR.revision,
                             generation=rt.state.meta()["generation"], acknowledged_version=ac.ENGINE,
                             warnings=[str(w) for w in rt.arming.warnings(WINDOW_ANCHOR)], actor=Actor.DASHBOARD)
        self.assertTrue(done["done"], done)
        self.assertEqual(rt.state.options(CAP)[KEY], ON)
        self.assertTrue(anchor.after_reset_on(rt.state.options(CAP)))
        for value in (OFF, ON):
            rt.state.set_option(CAP, KEY, value, generation=rt.state.meta()["generation"], actor=Actor.DASHBOARD)
            with self.subTest(value=value):
                self.assertEqual(rt.state.options(CAP)[KEY], value)
                self.assertEqual(anchor.after_reset_on(rt.state.options(CAP)), value == ON)


if __name__ == "__main__":
    unittest.main()
