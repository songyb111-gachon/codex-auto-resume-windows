"""Empty-response recovery answers only conversations core takes for a person's own (v0.6.18, the advanced audit's R4):
a subagent's, a review's or another kind Codex makes for itself ended with only reasoning is never continued - core
would hold its record WAITING for good (not_user_conversation), ahead of the capability's others at P2 - and one made
before is ended.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from codex_auto_resume_advanced.vocabulary import ContinuationKind, ContinuationReason  # noqa: E402
from test_advanced_empty_response import EmptyCase  # noqa: E402
from test_engine import T1  # noqa: E402


class OwnConversationTests(EmptyCase):
    def test_a_subagents_empty_turn_is_never_continued(self):
        """Fails with the source check reverted: a continuation was made that core never sends."""
        self.h.home.add_thread(T1, thread_source="subagent")
        plug = self.on()
        self.empty_turn()
        self.settle()
        self.h.tick(advance=61)
        self.assertEqual(self.continuations(plug), [])
        self.assertEqual(self.h.backend.send_calls, [])

    def test_a_person_s_own_is_still_continued(self):
        plug = self.on()
        self.empty_turn()
        self.settle()
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertEqual(len(self.continuations(plug)), 1)

    def test_one_made_before_for_a_conversation_not_its_own_is_ended(self):
        """Fails with the clean-up reverted: the row stayed waiting, first at P2 on every tick."""
        self.h.home.add_thread(T1, thread_source="subagent")
        plug = self.on()
        self.empty_turn()
        state = plug.runtime.state
        state.add_continuation("%064x" % 5, self.cap, ContinuationKind.EMPTY_RESPONSE, T1, "go on", ordinal=1)
        self.h.tick(advance=61)
        (row,) = state.continuations(pending=None)
        self.assertEqual(row["reason"], ContinuationReason.WITHDRAWN)
        self.assertIsNotNone(row["finished_at"])


if __name__ == "__main__":
    unittest.main()
