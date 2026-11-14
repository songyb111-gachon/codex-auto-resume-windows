"""v0.6.23 second round M4: the ten-a-day switch ceiling fails closed when switch.times cannot be read.

Any ProfileError reading the times - a damaged or unsealable file, a folder that became a link - read as "never kept",
and the count fell back to the pre-v0.6.23 stamps, which are 0 on any newer installation: an unknown count was taken as
no switch made. Now it is the ceiling reached - no switch, journalled `ceiling`, one notice in the not-finished words -
and the file is written again as the ceiling reached then, so the switch frees a day later rather than never.

Every home is a temporary folder and every sign-in file a fixture of no one's (test_advanced_autoswitch.EngineCase).

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_advanced_autoswitch as engine_tests  # noqa: E402
from test_advanced_autoswitch_swap import ONE, TWO  # noqa: E402
from codex_auto_resume_advanced import profiles  # noqa: E402
from codex_auto_resume_advanced.engine import autoswitch  # noqa: E402


class AnUnreadableCountIsTheCeiling(engine_tests.EngineCase):
    def damage(self):
        self.store.note_attempts([])
        (self.store.directory / profiles.TIMES).write_bytes(b"not sealed")
        with self.assertRaises(profiles.ProfileError):
            self.store.attempts()

    def test_a_damaged_switch_times_file_switches_nothing(self):
        """Fails with the old read: the unknown count was zero and the switch went through."""
        self.damage()
        self.look()
        self.assertEqual(self.scoped.counted, ["ceiling"])
        self.assertEqual((self.codex / "auth.json").read_bytes(), ONE)
        self.assertEqual(self.code.notice(), {"key": "autoswitch:not_finished:ceiling", "why": "not_finished"})

    def test_it_frees_a_day_later_not_never(self):
        self.damage()
        self.look()
        self.assertEqual(self.store.attempts(), [int(self.scoped.clock)] * autoswitch.PER_DAY,
                         "written again as the ceiling reached now")
        self.scoped.clock += autoswitch.DAY
        self.look([engine_tests.waiting("b", detected=self.scoped.clock - autoswitch.SETTLE)])
        self.assertEqual(self.scoped.counted, ["ceiling", "switched"])
        self.assertEqual((self.codex / "auth.json").read_bytes(), TWO)

    def test_times_never_kept_still_read_as_none_made(self):
        """A guard, not a proof: a new installation's first switch is not held by a file it never wrote."""
        self.assertIsNone(self.store.attempts())
        self.look()
        self.assertEqual(self.scoped.counted, ["switched"])


if __name__ == "__main__":
    unittest.main()
