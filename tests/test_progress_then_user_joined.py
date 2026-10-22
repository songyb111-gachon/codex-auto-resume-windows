"""A recovery turn that worked before a person's message entered it is a recovery, and its next failure is recovered.

The owner's cases (2026-10-22, plans/notif-check.md rank 1). 04:24: a message he had queued in the Codex app entered the
recovery turn our continuation had started 52 minutes before ("4시58분에 복구 정상적으로 됐었어"). 16:38, live: Codex
asked him a question inside our recovery turn, he answered, and the turn hit the usage limit at once ("코덱스가 나한테
질문을 하고 내가 그걸 답변하자마자 사용량 초과가 떳거든? ... 복구 대상으로 안 잡히고 있네"). Both times engine/outcome.py
handed the record over (`handed_over / user_joined`) as soon as it saw the message, and the usage limit's record was then
born `superseded (parent_handed_over)`: never recovered, although the limit had stopped the person too. Now a turn with
progress before its first user message that is not ours ends `recovered (progress_then_user_joined)`, through
turn_completed as every outcome goes, and is not handed over, so its next failure is an ordinary chain child. A person
who joins before the turn did anything is handed over exactly as before (standard A23 keeps that child stopped).

Driven through test_outcomes' World: the real Engine, Store and LocalSource over a simulated Codex home.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from codexsim import USAGE_ERROR  # noqa: E402
from test_outcomes import SERVER_5XX, World  # noqa: E402

from codex_auto_resume import machine, notifier  # noqa: E402

JOINED_AFTER_PROGRESS = ("recovered", "progress_then_user_joined")
HANDED_OVER = ("handed_over", "user_joined")


class ProgressThenUserJoinedTests(unittest.TestCase):
    def world(self) -> World:
        w = World(self)
        w.enable()
        return w

    def worked_then_joined(self, w, client_id=None):
        """Our continuation's turn: our message, work, then a person's message - still running."""
        thread, key = w.queued()
        turn = w.home.dispatch(thread, status="inProgress", progress=True)
        w.home.add_item(thread, turn, "userMessage", "queued in the Codex app", client_id)
        return thread, key, turn

    def test_a_turn_that_worked_before_the_person_joined_is_a_recovery(self):
        for client_id in (None, "0a1b2c3d-0016-7000-8000-000000000002"):
            with self.subTest(client_id=client_id):
                w = self.world()
                thread, key, turn = self.worked_then_joined(w, client_id)
                w.tick(1)
                self.assertEqual(w.get(key)["state"], "turn_completed")
                w.tick(1)
                row = w.get(key)
                self.assertEqual((row["state"], row["last_error"]), JOINED_AFTER_PROGRESS)
                self.assertFalse(row["user_joined"], "not handed over")
                self.assertEqual(row["recovery_turn_id"], turn)
                self.assertEqual(machine.public_code(row), "recovered")
                self.assertEqual(machine.public_reason(row), "progress_then_user_joined")
                self.assertEqual(w.home.turns(thread)[-1]["status"], "inProgress", "decided while it runs")
                self.assertEqual(w.store.statistics()["outcomes"]["recovered"], 1)
                self.assertEqual([event for event, _ in w.notes_for(key) if event == "stopped"], [])

    def test_the_live_sequence_a_question_answered_then_the_usage_limit_is_recovered(self):
        """16:21:55 a transient failure; 16:22:43 our continuation; 16:22:53 its turn starts; Codex asks a question in
        it and the person answers; the same turn fails on the usage limit - all seen in one look (16:38:48-49)."""
        w = self.world()
        thread, key = w.queued()                                       # the transient failure, recorded and sent
        turn = w.home.dispatch(thread, status="inProgress", progress=False)
        w.tick(1)
        self.assertEqual(w.get(key)["state"], "turn_started")
        w.home.add_item(thread, turn, "agentMessage", "Which of the two should I keep?")      # Codex's question
        w.home.add_item(thread, turn, "userMessage", "the first one")                         # the person's answer
        w.home.add_item(thread, turn, "commandExecution")                                    # work on the answer
        w.finish(thread, turn, "failed", USAGE_ERROR)                                        # the usage limit
        w.tick(1)
        w.tick(1)
        parent = w.get(key)
        self.assertEqual((parent["state"], parent["last_error"]), JOINED_AFTER_PROGRESS)
        rows = w.records(thread)
        self.assertEqual(len(rows), 2, [(row["state"], row["last_error"]) for row in rows])
        child = rows[-1]
        self.assertEqual(child["parent_interruption_id"], key)
        self.assertEqual(child["category"], "usage_limit")
        self.assertNotIn(child["state"], machine.TERMINAL, (child["state"], child["last_error"]))
        self.assertNotEqual(child["last_error"], "parent_handed_over")
        self.assertEqual([event for event, _ in w.notes_for(child["interruption_id"])], ["interruption"])
        self.assertTrue(w.tick_until_sent(thread, step=600, limit=40), "the usage limit's record is recovered")
        self.assertEqual(w.sends(thread), 2)

    def test_a_transient_failure_of_that_turn_is_recovered_too(self):
        w = self.world()
        thread, key, turn = self.worked_then_joined(w)
        w.tick(1)
        w.tick(1)
        w.finish(thread, turn, "failed", SERVER_5XX)
        w.tick(1)
        child = w.records(thread)[-1]
        self.assertEqual(child["parent_interruption_id"], key)
        self.assertNotIn(child["state"], machine.TERMINAL, (child["state"], child["last_error"]))
        self.assertTrue(w.tick_until_sent(thread, step=120, limit=60), (child["state"], child["next_retry_at"] - w.now))
        self.assertEqual(w.sends(thread), 2)

    def test_after_a_person_joined_with_no_progress_the_child_stays_stopped_with_true_words(self):
        """Standard A23: a child of a handed-over record is created stopped - kept, and said as a hand-over."""
        w = self.world()
        thread, key = w.queued()
        turn = w.home.dispatch(thread, status="inProgress", progress=False)
        w.home.add_item(thread, turn, "userMessage", "typed before anything happened")
        w.tick(1)
        w.finish(thread, turn, "failed", SERVER_5XX)
        w.tick(1)
        child = w.records(thread)[-1]
        self.assertEqual((child["state"], child["last_error"]), ("superseded", "parent_handed_over"))
        said = [detail for event, detail in w.notes
                if event == "stopped" and detail.get("interruption_id") == child["interruption_id"]]
        self.assertEqual(len(said), 1)
        notice = notifier.build("stopped", said[0], {"name": "ExampleUser's task"})
        self.assertEqual(notice.line, notifier.notify.not_resumed_message("parent_handed_over"))
        self.assertEqual(w.sends(thread), 1)

    def test_a_person_who_joins_before_any_progress_is_handed_over_as_before(self):
        w = self.world()
        thread, key = w.queued()
        turn = w.home.dispatch(thread, status="inProgress", progress=False)
        w.home.add_item(thread, turn, "userMessage", "typed before anything happened")
        w.home.add_item(thread, turn, "agentMessage")                 # work, after the person's message
        w.tick(1)
        row = w.get(key)
        self.assertEqual((row["state"], row["last_error"]), HANDED_OVER)
        self.assertTrue(row["user_joined"])

    def test_a_turn_with_no_progress_at_all_is_handed_over_as_before(self):
        w = self.world()
        thread, key = w.queued()
        turn = w.home.dispatch(thread, status="inProgress", progress=False)
        w.home.add_item(thread, turn, "userMessage", "typed while it ran")
        w.tick(1)
        self.assertEqual((w.get(key)["state"], w.get(key)["last_error"]), HANDED_OVER)

    def test_what_the_source_reports(self):
        w = self.world()
        thread, key = w.queued()
        turn = w.home.dispatch(thread, status="inProgress", progress=True)
        proof = w.engine.proof(w.get(key))
        seen = w.source.turn_observation(thread, turn, proof)
        self.assertEqual((seen["foreign_user_messages"], seen["progress_before_foreign"]), (0, False))
        w.home.add_item(thread, turn, "userMessage", "queued in the Codex app")
        seen = w.source.turn_observation(thread, turn, proof)
        self.assertEqual((seen["foreign_user_messages"], seen["progress_before_foreign"]), (1, True))
        other, other_key = w.queued()
        late = w.home.dispatch(other, status="inProgress", progress=False)
        w.home.add_item(other, late, "userMessage", "first")
        w.home.add_item(other, late, "commandExecution")
        seen = w.source.turn_observation(other, late, w.engine.proof(w.get(other_key)))
        self.assertEqual((seen["foreign_user_messages"], seen["progress"], seen["progress_before_foreign"]),
                         (1, True, False))

    def test_a_source_that_does_not_say_hands_over_as_before(self):
        """An observation without progress_before_foreign (an older reader, a stand-in) keeps today's hand-over."""
        w = self.world()
        thread, key, turn = self.worked_then_joined(w)
        real = w.source.turn_observation

        def older(*args):
            seen = dict(real(*args))
            seen.pop("progress_before_foreign", None)
            return seen

        w.source.turn_observation = older
        w.tick(1)
        self.assertEqual((w.get(key)["state"], w.get(key)["last_error"]), HANDED_OVER)

    def test_the_reason_is_a_known_one(self):
        self.assertIn("progress_then_user_joined", machine.REASONS)
        self.assertEqual(machine.public_reason({"state": "recovered", "last_error": "progress_then_user_joined"}),
                         "progress_then_user_joined")


if __name__ == "__main__":
    unittest.main()
