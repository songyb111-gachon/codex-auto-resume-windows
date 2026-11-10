"""The limits the owner decided on 2026-11-10 (v0.6.23, the limits review): each number held, and what goes with it.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests -p test_advanced_limits_v0623.py
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from test_advanced_state import StateCase  # noqa: E402
from codex_auto_resume_advanced.state import Refused  # noqa: E402
from codex_auto_resume_advanced.state import prompts as prompts_module, resets as resets_module  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Refusal  # noqa: E402

CATALOG = Path(prompts_module.__file__).resolve().parent.parent / "locales" / "en.json"


def thread(n):
    return "0a1b2c3d-0005-7000-8000-%012d" % n


def key(n):
    return "%064x" % (5000 + n)


class WaitingCounts(StateCase):
    """L1.7, L1.7b and L1.9: the waiting rows are local and cost nothing; what is sent stays under the ceilings."""

    def test_the_numbers(self):
        self.assertEqual((prompts_module.PROMPTS_LIMIT, prompts_module.PER_CONVERSATION), (50, 20))
        self.assertEqual((resets_module.MESSAGES_LIMIT, resets_module.CREDIT_RULES_LIMIT), (50, 4))

    def test_twenty_wait_in_one_conversation_and_the_twenty_first_is_refused(self):
        state = self.state()
        for n in range(20):
            state.add_prompt(ac.THREAD, "mine %d" % n, "after_turn")
        with self.assertRaises(Refused) as refused:
            state.add_prompt(ac.THREAD, "one more", "after_turn")
        self.assertEqual(refused.exception.refusal, Refusal.QUEUE_FULL)

    def test_fifty_wait_in_all_and_the_fifty_first_is_refused(self):
        state = self.state()
        for n in range(50):
            state.add_prompt(thread(n // 20), "mine %d" % n, "after_turn")
        with self.assertRaises(Refused) as refused:
            state.add_prompt(thread(40), "one more", "after_turn")
        self.assertEqual(refused.exception.refusal, Refusal.QUEUE_FULL)

    def test_fifty_reset_messages_wait_each_for_a_conversation_of_its_own(self):
        """The ordinal is which reset a message waits for, so it does not stop the fifty: every one here says the first."""
        state = self.state()
        for n in range(50):
            state.add_reset_rule("reset_message", "codex", 300, 1, thread_id=thread(n), words="go on", record_id=key(n))
        with self.assertRaises(Refused) as refused:
            state.add_reset_rule("reset_message", "codex", 300, 1, thread_id=thread(50), words="go on", record_id=key(50))
        self.assertEqual(refused.exception.refusal, Refusal.RESETS_FULL)

    def test_a_person_reads_the_same_numbers(self):
        english = CATALOG.read_text(encoding="utf-8")
        self.assertIn("twenty for a conversation, fifty in all", english)
        self.assertIn("one message to a conversation and fifty in all", english)


if __name__ == "__main__":
    unittest.main()
