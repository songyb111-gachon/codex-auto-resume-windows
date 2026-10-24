# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""Reviewer's proof for v0.6.19-beta.2 (issue #50): early_reset's line after the reading that lifted a limit.

Fails on cf2984b6a. control/earlycheck.py `view` reads `read` from the usage gate of the records that STILL wait
(`_waiting`); once two readings lift the limit and the recovery is sent, it waits no more, no row is left, and `read`
is "not_read" - so AdvancedEarly.cs EarlyText, which tests `read` before `lifted`, says "usage was not read, because
another check came first. Nothing was continued." of the very reading that continued it (the issue #50 reply: the line
says "whether anything was continued because of it").

    PYTHONPATH=src;advanced/src;tests python -m unittest discover -s advanced/tests -p test_advanced_early_check_review.py
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_advanced_early_check import CheckCase  # noqa: E402
from test_advanced_early_reset import NO_USAGE, SPACING, USAGE  # noqa: E402
from codex_auto_resume_advanced.control import earlycheck  # noqa: E402


class LiftedLineTests(CheckCase):
    def test_the_line_after_a_lift_says_usage_was_read_and_something_went_on(self):
        self.waiting()
        plug = self.armed()
        self.h.backend.usage_result = dict(NO_USAGE)
        self.h.tick(advance=60)
        self.h.backend.usage_result = dict(USAGE)
        self.h.tick(advance=60)
        self.assertEqual(self.check(plug)["check"], earlycheck.ASKED)
        self.h.tick(advance=1)                               # the first yes
        self.h.tick(advance=SPACING)                         # the second: lifted, sent
        self.assertEqual(self.sends(), 1)
        line = self.line(plug)
        self.assertTrue(line["lifted"])
        self.assertEqual(line["read"], "available",
                         "lifted and sent, yet the line reads 'not_read': EarlyText says nothing was read or continued")


if __name__ == "__main__":
    unittest.main()
