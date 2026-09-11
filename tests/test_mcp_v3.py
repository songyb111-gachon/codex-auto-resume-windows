"""Which tools Codex must ask about, pinned as one exact set (design T26).

A tool that can add automation - turn recovery back on, re-arm a stopped recovery,
start a watcher, change what is recovered - or that cannot be undone is marked
destructive, so Codex asks the user before running it in Auto approval mode. Content
in a conversation must not be able to do any of that on the user's behalf unseen.
"""
from __future__ import annotations

import unittest

from codex_auto_resume import mcpserver

ASKS_FIRST = {
    "update_settings", "restore_default_settings", "resume_auto_recovery", "cancel_recovery",
    "reset_recovery_budget", "start_watcher", "enable_conversation_recovery",
    "clear_recovery_history",
}
READ_ONLY = {"open_settings", "get_status", "list_pending", "get_recovery_statistics",
             "get_recovery_timeline"}


class ApprovalHintTests(unittest.TestCase):
    def test_exactly_these_tools_ask_first(self):
        marked = {tool["name"] for tool in mcpserver.TOOLS if tool["annotations"]["destructiveHint"]}
        self.assertEqual(marked, ASKS_FIRST)

    def test_reads_are_marked_read_only(self):
        for tool in mcpserver.TOOLS:
            with self.subTest(tool=tool["name"]):
                self.assertEqual(tool["annotations"]["readOnlyHint"], tool["name"] in READ_ONLY)

    def test_the_directions_that_reduce_automation_do_not_ask(self):
        # Pausing and switching a conversation off only ever take automation away, so
        # asking would train people to click through the prompts that matter.
        by_name = {tool["name"]: tool for tool in mcpserver.TOOLS}
        for name in ("pause_auto_recovery", "disable_conversation_recovery"):
            self.assertFalse(by_name[name]["annotations"]["destructiveHint"], name)


if __name__ == "__main__":
    unittest.main()
