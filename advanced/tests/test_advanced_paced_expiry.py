"""A message held only by the product's own pace never expires for it (v0.6.23, finding B2 of the second round's audit).

Since the waiting limits were raised (2026-11-10: twenty a conversation and fifty in all for the prompt queue, fifty
reset messages), more may wait than the pace lets go in a day - the prompt queue's five a day and fifteen minutes in one
conversation, reset messages' twenty a day - and the day after which an unsent message expires used to count from its
due time, so most of them expired unsent. That day now counts from when a message could first go: a hold by the claim's
pace moves it on (state/resets.paced_wait, the record's `waiting_since`), and so does the end of the prompt before it in
its conversation. Kept by anything else - here the conversation not open in the app - a message still expires a day after
it fell due.

Held against the shipped definitions and core's own engine, store and simulated Codex home (takingcase.py), on the
harness's clock.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_advanced_prompt_queue as queue_case  # noqa: E402
import test_advanced_reset_message as reset_case  # noqa: E402
from codex_auto_resume_advanced.state.prompts import PER_CONVERSATION  # noqa: E402
from codex_auto_resume_advanced.state.resets import MESSAGES_LIMIT  # noqa: E402
from codex_auto_resume_advanced.vocabulary import PromptReason, PromptState, RuleReason, RuleState  # noqa: E402
from test_engine import T1  # noqa: E402

DAY = 86400


def thread(n):
    return "%08x-%04x-7%03x-8%03x-%012x" % (n, n, n, n, n)


class QueuePaceTests(queue_case.QueueCase):
    def test_twenty_after_this_turn_messages_in_one_conversation_are_all_sent_once_in_order(self):
        """Fails with paced_wait and could_go reverted: from the sixth on, most expire a day after they were written."""
        plug = self.on()
        words = ["Queued message %02d, please." % n for n in range(1, PER_CONVERSATION + 1)]
        for text in words:
            self.assertTrue(self.add(plug, words=text)["done"])
        times = []
        for _ in range(4 * 96 + 8):                           # four days and two hours, a tick every fifteen minutes
            before = len(self.sends())
            self.h.tick(advance=900)
            times += [self.h.now] * (len(self.sends()) - before)
        sent = [text.split("\n\n")[0] for text in self.sends()]
        self.assertEqual(sent, words, "each once, in the order queued")
        rows = self.prompts(plug)
        self.assertEqual({(row["state"], row["reason"]) for row in rows}, {(PromptState.DONE, PromptReason.DELIVERED)})
        for first, second in zip(times, times[5:]):
            self.assertGreaterEqual(second - first, DAY, "five a day in one conversation")

    def test_one_kept_by_something_else_still_expires_a_day_after_it_fell_due(self):
        plug = self.on()
        self.h.backend.loaded_map[T1] = "notLoaded"           # the conversation is not open in the app
        self.assertTrue(self.add(plug)["done"])
        for _ in range(25):
            self.h.tick(advance=3600)
        row = self.prompts(plug)[0]
        self.assertEqual((row["state"], row["reason"]), (PromptState.DONE, PromptReason.EXPIRED))
        self.assertEqual(self.sends(), [])



class ResetPaceTests(reset_case.MessageCase):
    def test_fifty_reset_messages_for_one_reset_are_all_sent_within_the_ceilings(self):
        """Fails with paced_wait reverted: twenty go on the first day and the other thirty expire."""
        plug = self.armed()
        threads = [thread(n) for n in range(1, MESSAGES_LIMIT + 1)]
        rules = []
        for index, conversation in enumerate(threads):
            self.h.home.add_turn(conversation)
            self.h.backend.loaded_map[conversation] = "loaded"
            rules.append(self.message(plug, thread=conversation, words="reset message %d of mine" % index)[0])
        self.h.tick()
        self.h.now = reset_case.RESET + reset_case.CLOSE_AFTER
        per_day = plug.runtime.registry.get(self.cap).ceilings.per_day
        days = []
        for day in range(3):                                  # twenty, twenty and ten
            for _ in range(DAY // 600):
                self.h.tick(advance=600)
            days.append(len(self.h.backend.send_calls))
        self.assertEqual(sorted(conversation for conversation, _words in self.h.backend.send_calls), sorted(threads),
                         "every one sent, each once")
        self.assertLessEqual(days[0], per_day)
        self.assertLessEqual(days[1] - days[0], per_day)
        for rule in rules:
            found = self.found(plug, rule)
            self.assertEqual((found["state"], found["reason"]), (RuleState.DONE, RuleReason.DELIVERED))

    def test_one_kept_by_something_else_still_expires_a_day_after_it_fell_due(self):
        plug = self.armed()
        rule, _key = self.message(plug)
        self.h.backend.loaded_map[T1] = "notLoaded"
        self.h.tick()
        self.h.now = reset_case.RESET + reset_case.CLOSE_AFTER
        for _ in range(25):
            self.h.tick(advance=3600)
        found = self.found(plug, rule)
        self.assertEqual((found["state"], found["reason"]), (RuleState.DONE, RuleReason.EXPIRED))
        self.assertEqual(self.h.backend.send_calls, [])


if __name__ == "__main__":
    unittest.main()
