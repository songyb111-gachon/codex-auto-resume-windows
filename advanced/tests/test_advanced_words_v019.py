"""The v0.6.19 groundwork's closed words (plans/v0619-design/D-groundwork.md, section 2): every word the stage's
capabilities store, journal or answer with, added in one block before any of them is built - and the stage's bridge
commands, which the bridge passes over until the capability that answers one is built.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_advanced_surfaces import SurfaceCase  # noqa: E402
from codex_auto_resume_advanced import surfaces, vocabulary  # noqa: E402
from codex_auto_resume_advanced.vocabulary import BridgeCommand  # noqa: E402

# The words the design names, list by list - a writer appends to a list, never renames one of these.
NEW_LISTS = {
    "WhileRunning": ("queue", "wait"),
    "CourierChannel": ("ntfy", "webhook", "telegram", "email"),
    "CourierEvent": ("usage_limit_detected", "recovered", "failed", "needs_you", "stopped_unexpectedly", "restarted",
                     "update_offered", "test"),
    "OutboxState": ("waiting", "sent", "dropped"),
    "FeedWord": ("operational", "degraded", "outage", "unknown"),
    "OpenOutcome": ("opened", "loaded", "not_loaded", "refused"),
    "HookOutcome": ("blocked", "passed", "refused"),
    "PlanWord": ("free", "plus", "pro", "team", "business", "enterprise", "edu", "other"),
}
ADDED = {
    "OptionKey": ("analytics_days", "feed_minutes", "push_events", "ntfy", "webhook", "telegram", "email", "api_port",
                  "open_idle_minutes", "open_start_codex", "wake_lead_minutes", "restart_cap", "last_ingest",
                  "last_feed", "last_fleet_write"),
    "WordingKey": ("fleet_alias", "fleet_folder"),
    "PromptReason": ("turn_running",),
}
COMMANDS = ("advanced-analytics", "advanced-analytics-csv", "advanced-courier", "advanced-courier-save",
            "advanced-courier-forget", "advanced-courier-test", "advanced-feed-refresh", "advanced-api",
            "advanced-api-token-new", "advanced-remote-pair-start", "advanced-remote-pair-state", "advanced-fleet",
            "advanced-fleet-save", "advanced-prompt-edit", "advanced-prompts-clear-done", "advanced-account",
            "advanced-account-switch")
# The commands whose capability has been built since, each with what answers it now: no longer passed over.
BUILT = {"advanced-prompts-clear-done": "#50, Delete completed (control/prompts.clear_done)",
         "advanced-prompt-edit": "#50, the editor's Save and return on a waiting message (control/prompts.edit)",
         # v0.6.20, the courier (control/courier.py).
         "advanced-courier": "the courier's card read", "advanced-courier-save": "one channel saved, or Telegram paired",
         "advanced-courier-forget": "one channel forgotten", "advanced-courier-test": "a test notice",
         "advanced-feed-refresh": "the status feed read now",
         "advanced-analytics": "usage_analytics, its card (control/analytics.view)",
         "advanced-analytics-csv": "usage_analytics, its CSV (control/analytics.save_csv)",
         "advanced-account": "account_switch, the account card's read (control/account.view)",
         "advanced-account-switch": "account_switch, Codex's own sign-out and sign-in (control/account.switch)"}


class WordTests(unittest.TestCase):
    def test_each_new_list_holds_exactly_the_designs_words_in_its_order(self):
        """Fails with the block reverted: the lists are not there."""
        for name, words in NEW_LISTS.items():
            with self.subTest(name):
                self.assertEqual(tuple(str(word) for word in getattr(vocabulary, name)), words)

    def test_each_grown_list_holds_the_designs_words_together(self):
        # The design's words were added at the end of each list; words a capability built since adds (v0.6.20:
        # window_anchor's options) come after them, so the design's words stand together, in their order.
        for name, words in ADDED.items():
            with self.subTest(name):
                held = tuple(str(word) for word in getattr(vocabulary, name))
                self.assertIn(words[0], held)
                start = held.index(words[0])
                self.assertEqual(held[start:start + len(words)], words)

    def test_every_command_the_designs_name_is_a_word(self):
        self.assertEqual(tuple(str(command) for command in BridgeCommand)[-len(COMMANDS):], COMMANDS)


class UnansweredTests(SurfaceCase):
    def test_a_command_not_built_yet_is_passed_over_as_an_unknown_one_is(self):
        """Until its capability answers it, a new command is DEFER, so core says "unknown command" - exactly what an
        installation said for it before the word was added. Fails with the guard reverted: the request falls through
        to the last command `bridge` answers (the global ceiling) and is refused as that one."""
        waiting = [command for command in COMMANDS if command not in BUILT]
        self.assertEqual(surfaces.UNANSWERED, frozenset(BridgeCommand(command) for command in waiting))
        for command in waiting:
            with self.subTest(command):
                self.assertEqual(self.bridge(command, {}),
                                 {"ok": False, "error": "unknown command", "error_code": "request_failed"})
                self.assertIs(surfaces.bridge(self.advanced.runtime, command, {}), surfaces.DEFER)

    def test_nothing_is_written_for_one(self):
        before = self.advanced.runtime.state.exists()
        for command in COMMANDS:
            if command not in BUILT:
                self.bridge(command, {})
        self.assertEqual(self.advanced.runtime.state.exists(), before)


if __name__ == "__main__":
    unittest.main()
