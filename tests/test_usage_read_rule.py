"""The click that promises a usage reading and the watcher that makes one stop for the same four reasons.

control/actions._not_checked and engine/freshness._not_served each wrote the rule out, and the click's copy did not ask
the administrator's DisableAutoResume: until the watcher had written that policy into the state, Retry now said it was
checking usage, and a moment later that it had not.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from codex_auto_resume.control.actions import ActionsMixin
from codex_auto_resume.domain import gates
from codex_auto_resume.engine.freshness import FreshnessMixin
from codex_auto_resume.managed import Managed

RECORD = {"thread_id": "t", "category": "usage_limit"}


class Store:
    def __init__(self, enabled=True, observe_only=False, conversation_on=True):
        self.values = {"enabled": enabled, "observe_only": observe_only}
        self.conversation_on = conversation_on

    def settings(self):
        return self.values

    def thread_enabled(self, _thread_id):
        return self.conversation_on


class Click:
    _not_checked = ActionsMixin._not_checked

    def __init__(self, held=Managed()):
        self.held = held

    def managed(self):
        return self.held

    @staticmethod
    def get_settings():
        return {}


class Watcher:
    _not_served = FreshnessMixin._not_served

    def __init__(self, store, held=Managed()):
        self.store, self.managed = store, held

    @staticmethod
    def observing(settings):
        return bool(settings["observe_only"])

    @staticmethod
    def offline():
        return False


class TheAdministratorsPause(unittest.TestCase):
    def test_the_click_says_paused_before_the_watcher_has_written_the_policy(self):
        self.assertEqual(Click(Managed(disable_auto_resume=True))._not_checked(Store(), RECORD, 100.0), "paused")

    def test_with_no_policy_the_click_stops_for_nothing(self):
        self.assertIsNone(Click()._not_checked(Store(), RECORD, 100.0))


class OneRule(unittest.TestCase):
    CASES = ((dict(enabled=False, conversation_on=False, observing=True, quiet=True), "paused"),
             (dict(enabled=True, conversation_on=False, observing=True, quiet=True), "conversation_off"),
             (dict(enabled=True, conversation_on=True, observing=True, quiet=True), "observe_only"),
             (dict(enabled=True, conversation_on=True, observing=False, quiet=True), "quiet_hours"),
             (dict(enabled=True, conversation_on=True, observing=False, quiet=False), None))

    def test_the_words_come_in_this_order(self):
        for facts, word in self.CASES:
            with self.subTest(word):
                self.assertEqual(gates.usage_read_stopped(**facts), word)

    def test_both_sides_answer_what_the_rule_answers(self):
        with patch.object(gates, "usage_read_stopped", return_value="the_rule"):
            self.assertEqual(Click()._not_checked(Store(), RECORD, 100.0), "the_rule")
            self.assertEqual(Watcher(Store())._not_served(RECORD, 100.0, None), "the_rule")


if __name__ == "__main__":
    unittest.main()
