"""Reviewer's proof for v0.6.19-beta.2 (issue #50): the Pending note's order in ShowPendingNote (gui/DashboardData.cs).

Fails on cf2984b6a. Once a row has any usage_check in the last day (control/records.py usage_checks_shown), the note
under Pending shows that old reading INSTEAD of whatever a person's action on that row just said: Retry now's "The
watcher is not running, so usage was not checked" (the issue #50 reply promises "if the watcher is not running, it says
so"), "Postponed until ...", "It may continue now", Cancel all's and Rescan's counts (BulkNote) and once-words' note -
for 24 hours. A second Retry now's "Checking usage now" is hidden behind the first click's reading too.
"""
from __future__ import annotations

import re
import unittest

import guiscan  # noqa: E402


class NoteOrderTests(unittest.TestCase):
    def test_an_action_just_taken_on_the_row_is_said_before_an_older_usage_reading(self):
        body = guiscan.member_body("SettingsForm", "ShowPendingNote")
        # The note handed to SetNote: an older reading must not stand in front of the note for this row (`mine`).
        self.assertIsNone(re.search(r"checkedText\s*\?\?\s*\(\s*mine\s*\?\s*pendingNoteText", body),
                          "a usage reading up to a day old hides every note a person's action on the row just made")


if __name__ == "__main__":
    unittest.main()
