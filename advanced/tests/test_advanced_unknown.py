"""Retry failures it cannot name (v0.6.14): a failure nothing classified, on a budget of its own.

Held against the shipped definition and statement and against core's own engine, store and
simulated Codex home (takingcase.py): off, a failure nothing classified waits for the person, as in
the standard edition; armed, one with a code of Codex's is taken up at P17, waits ten minutes, goes as
the short standard continuation with its marker, and leaves one sample - Codex's code, the status, the
form, item counts and times, never a word; one try a task by default, up to three by choice; a rule
comes first; no code or a code naming a decision is never taken up, and a failure core left alone
leaves no sample; watched, it only journals; the unit is spent before the send; past its ceilings
nothing is taken up; a send it cannot prove turns it off; a policy reads it down; and MCP writes no
choice.

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from takingcase import TakingCase  # noqa: E402
from codex_auto_resume import continuation, ladder  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Alternative, Point  # noqa: E402
from codex_auto_resume_advanced import policy, surfaces  # noqa: E402
from codex_auto_resume_advanced.codex import inuse  # noqa: E402
from codex_auto_resume_advanced.engine.admitted import UnknownFailureBudget  # noqa: E402
from codex_auto_resume_advanced.registry import STRUCTURED_RULES, UNKNOWN_FAILURE_BUDGET  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (Actor, ArmingState, JournalCode, McpTool,  # noqa: E402
                                                   OffReason, OptionKey, Refusal)
from test_engine import T1  # noqa: E402

CAP = "unknown_failure_budget"
TAG = "brandNewVariant"
SECRET = "the secret words of the error"
UNNAMED = json.dumps({"codexErrorInfo": TAG, "message": SECRET})
FIRST = ladder.ADMITTED_WAITS[0]


class UnknownCase(TakingCase):
    DEFINITION = UNKNOWN_FAILURE_BUDGET

    def taken_up(self, error=UNNAMED, state="armed"):
        plug = self.armed(state=state)
        self.h.backend.after_accept = "queue"
        self.failing(error)
        self.h.tick()
        return plug

    def samples(self, plug):
        return plug.runtime.state.failure_samples(0)


class OffTests(UnknownCase):
    def test_off_a_failure_nothing_classified_waits_for_the_person(self):
        self.assertIsNone(self.standard(UNNAMED))
        plug = self.advanced()
        self.plugged(plug)
        self.failing(UNNAMED)
        self.h.tick()
        self.assertEqual(self.h.records(), [])
        self.assertFalse(plug.runtime.state.exists())


class ArmedTests(UnknownCase):
    def test_taken_up_it_goes_ten_minutes_on_as_the_short_continuation_and_leaves_one_sample(self):
        plug = self.taken_up()
        row = self.h.record()
        key = row["interruption_id"]
        self.assertEqual((row["category"], row["state"], row["next_retry_at"] - self.h.now),
                         ("unknown", "waiting_backoff", FIRST))
        self.assertEqual(self.samples(plug), [], "nothing kept before core goes on with it")
        self.h.tick(advance=FIRST - 1)
        self.assert_no_send()
        self.h.tick(advance=1)
        self.assertEqual(len(self.h.backend.send_calls), 1)
        expected = continuation.for_settings("unknown", self.h.engine.policy_values, row=self.h.record(),
                                             limits=self.h.engine.limits())
        self.assertEqual(self.prompt(), expected + "\n\n" + self.h.record()["marker"])
        (sample,) = self.samples(plug)
        self.assertEqual({name: sample[name] for name in ("tag", "status", "form", "has_words", "duration")},
                         {"tag": TAG, "status": None, "form": "tagged", "has_words": 1, "duration": 60.0})
        self.assertIsNone(sample["items_agent"], "no Codex home told: no counts")
        self.assertEqual(self.spends(plug), [(CAP, T1, key)])
        self.assertIn(("unk.sampled", None, None), self.journal(plug))
        plug.runtime.state.close()
        self.assertNotIn(SECRET.encode(), plug.runtime.state.path.read_bytes())
        self.follow()
        self.h.tick(advance=3600)
        self.assertEqual(len(self.samples(plug)), 1, "one sample an interruption")

    def test_told_the_codex_home_it_counts_the_items_the_failed_turn_left(self):
        plug = self.taken_up()
        plug.codex(self.where / "codex.exe", self.h.home.root)
        self.addCleanup(inuse.forget, plug.paths)
        self.h.tick(advance=FIRST)
        (sample,) = self.samples(plug)
        for column in ("items_agent", "items_command", "items_file", "items_tool", "items_user", "items_other"):
            self.assertIsInstance(sample[column], int, column)

    def test_one_try_a_task_by_default_and_more_by_choice(self):
        self.taken_up()
        again = self.again(self.h, UNNAMED, step=60)
        self.assertEqual(len(self.h.records()), 1, "the second failure of the task is left alone")
        self.assertIsNot(again, None)
        self.h = self.fresh()
        plug = self.taken_up()
        self.choose(plug, OptionKey.ATTEMPTS, 2)
        child = self.again(self.h, UNNAMED, step=60)
        self.assertEqual(len(self.h.records()), 2)
        self.assertEqual((child["category"], child["next_retry_at"] - self.h.now), ("unknown", ladder.ADMITTED_WAITS[1]))

    def test_no_code_or_a_code_that_names_a_decision_is_never_taken_up(self):
        for error in (None, json.dumps({"message": SECRET}), json.dumps({"codexErrorInfo": "policyRefused"}),
                      json.dumps({"codexErrorInfo": "approvalDenied"})):
            with self.subTest(error=error):
                self.h = self.fresh()
                plug = self.taken_up(error)
                self.assertEqual(self.h.records(), [])
                self.assertEqual(self.samples(plug), [])

    def test_a_failure_core_left_alone_leaves_no_sample(self):
        plug = self.armed()
        self.h.store.set_thread_enabled(T1, False, at=self.h.now)
        self.failing(UNNAMED)
        self.h.tick()
        self.h.tick(advance=FIRST)
        self.assertEqual((self.h.records(), self.samples(plug)), ([], []))


class RulesFirstTests(UnknownCase):
    BESIDE = (STRUCTURED_RULES,)

    def test_a_rule_that_names_the_code_comes_first(self):
        plug = self.armed()
        runtime = plug.runtime
        self.assertTrue(runtime.arming.add_rule(TAG, None, None, "timeout", generation=runtime.state.meta()
                                                ["generation"], actor=Actor.DASHBOARD)["done"])
        self.failing(UNNAMED)
        self.h.tick()
        admission = runtime.state.admission(self.h.record()["interruption_id"])
        self.assertEqual((admission["capability"], admission["answer"]), ("structured_rules", Alternative.AS_TIMEOUT))
        self.failing(json.dumps({"codexErrorInfo": "otherVariant"}), thread="0a1b2c3d-0001-7000-8000-00000000abcd",
                     turn="0a1b2c3d-0001-7000-8000-00000000abce")
        self.h.tick()
        (other,) = self.h.records("0a1b2c3d-0001-7000-8000-00000000abcd")
        self.assertEqual(runtime.state.admission(other["interruption_id"])["capability"], CAP)


class ShadowNeverActsTests(UnknownCase):
    def test_watched_it_journals_what_it_would_have_done_and_keeps_nothing(self):
        plug = self.taken_up(state="shadow")
        self.assertEqual(self.h.records(), [])
        self.assertIn((JournalCode.WOULD_HAVE, Point.ADMISSION, Alternative.ADMIT), self.journal(plug))
        self.assertEqual((self.samples(plug), self.spends(plug)), ([], []))


class SpendBeforeSendTests(UnknownCase):
    def test_the_unit_is_spent_before_the_continuation_goes(self):
        plug = self.taken_up()
        key = self.h.record()["interruption_id"]
        seen = []
        self.h.backend.on_send = lambda thread, prompt: seen.append(self.spends(plug))
        self.h.tick(advance=FIRST)
        self.assertEqual(seen, [[(CAP, T1, key)]])


class CeilingTests(UnknownCase):
    def test_past_its_ceiling_nothing_is_taken_up(self):
        plug = self.armed()
        self.fill(plug, UNKNOWN_FAILURE_BUDGET.ceilings.per_conversation, at=self.h.now - 3600)
        self.failing(UNNAMED)
        self.h.tick()
        self.assertEqual(self.h.records(), [])
        self.assertIn((JournalCode.CEILING, Point.ADMISSION, Alternative.ADMIT), self.journal(plug))

    def test_out_of_units_what_it_took_up_waits_and_never_ends_for_it(self):
        plug = self.taken_up()
        self.fill(plug, UNKNOWN_FAILURE_BUDGET.ceilings.per_conversation)
        self.h.tick(advance=FIRST)
        row = self.h.record()
        self.assertEqual((row["state"], json.loads(row["gate_eval"])["known_failure"]),
                         ("waiting_backoff", ["WAIT", "held"]))
        self.assert_no_send()
        self.h.now += ladder.ADMITTED_MAX_SECONDS
        self.h.tick()
        row = self.h.record()
        self.assertEqual((row["state"], row["last_error"]), ("terminal_failure", "admission_expired"))
        self.assert_no_send()


class TripwireTests(UnknownCase):
    def test_a_send_it_paid_for_gone_unknown_turns_it_off_and_is_never_sent_again(self):
        plug = self.taken_up()
        self.h.backend.default_outcome = "unknown"
        self.h.tick(advance=FIRST)
        self.assertEqual(self.h.record()["state"], "submission_unknown")
        stored = plug.runtime.state.arming()[CAP]
        self.assertEqual((stored["state"], stored["reason"]), (ArmingState.OFF, OffReason.SUBMISSION_UNKNOWN))
        for _ in range(8):
            self.h.tick(advance=900)
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_a_sample_that_raises_trips_it_and_what_it_took_up_ends_unsent(self):
        plug = self.taken_up()
        with patch.object(UnknownFailureBudget, "taken", side_effect=RuntimeError("boom")):
            self.h.tick(advance=FIRST)
        self.assertEqual(plug.runtime.state.arming()[CAP]["reason"], OffReason.HOOK_EXCEPTION)
        self.assertEqual((self.h.record()["state"], self.samples(plug)), ("terminal_failure", []))
        self.assert_no_send()


class PolicyTests(UnknownCase):
    def test_shadow_forced_it_only_watches_and_on_is_refused(self):
        plug = self.armed()
        self.policy = policy.Policy(force_shadow=True)
        plug.runtime.states(fresh=True)
        self.failing(UNNAMED)
        self.h.tick()
        self.assertEqual(self.h.records(), [])
        self.assertIn((JournalCode.WOULD_HAVE, Point.ADMISSION, Alternative.ADMIT), self.journal(plug))
        result = plug.runtime.arming.arm(CAP, state="armed", revision=1, generation=plug.runtime.state.meta()
                                         ["generation"], acknowledged_version=ac.ENGINE, actor=Actor.DASHBOARD)
        self.assertEqual(result["refusal"], Refusal.SHADOW_FORCED_BY_POLICY)


class McpTests(UnknownCase):
    def test_mcp_writes_no_choice_and_arms_nothing(self):
        plug = self.armed()
        runtime = plug.runtime
        refused = surfaces.mcp(runtime, {"request": "call", "tool": McpTool.DISARM_ALL_ADVANCED,
                                         "arguments": {"attempts": 3}})
        self.assertIn("refused", refused)
        self.assertEqual(runtime.arming.set_option(CAP, OptionKey.ATTEMPTS, 3, generation=runtime.state.meta()
                                                   ["generation"], actor=Actor.MCP)["refusal"],
                         Refusal.NOT_THE_DASHBOARD)
        self.assertEqual(runtime.state.options(CAP), {OptionKey.ATTEMPTS: 1})
        self.assertEqual(runtime.state.arming()[CAP]["state"], ArmingState.ARMED)


class CodeTests(unittest.TestCase):
    class Scoped:
        def __init__(self, attempts=1, row=None):
            self.attempts, self.row = attempts, row

        def options(self):
            return {OptionKey.ATTEMPTS: self.attempts}

        def admission(self, key):
            return self.row

    def code(self, **scoped):
        made = UnknownFailureBudget(None)
        made.bind(self.Scoped(**scoped))
        return made

    def test_its_tries_are_counted_on_the_task_it_continues(self):
        facts = {"category": "unknown", "chain": None}
        self.assertIs(self.code().admission(facts), Alternative.ADMIT)
        self.assertIs(self.code().admission(dict(facts, chain={"recovery_attempts": 1})), DEFER)
        self.assertIs(self.code(attempts=3).admission(dict(facts, chain={"recovery_attempts": 2})), Alternative.ADMIT)
        self.assertIs(self.code(attempts=3).admission(dict(facts, chain={"recovery_attempts": 3})), DEFER)
        self.assertIs(self.code().admission(dict(facts, category="terminal_auth")), DEFER)
        self.assertIs(self.code().gate("known_failure", {"category": "unknown"}, {}), Alternative.ADMIT)
        self.assertIs(self.code().gate("usage", {"category": "unknown"}, {}), DEFER)

    def test_its_sample_is_the_shape_its_admission_kept_and_the_turns_times(self):
        row = {"tag": TAG, "status": 302, "form": "tagged", "has_words": 0}
        kept = self.code(row=row).taken(Point.GATES, Alternative.ADMIT, "known_failure",
                                        {"interruption_id": ac.KEY, "started_at": 100.0, "completed_at": 160.5}, {})
        self.assertEqual(kept, {"code": "sampled", "sample": {"code": TAG, "status": 302, "form": "tagged",
                                                              "has_message": False, "items": None,
                                                              "duration": 60.5}})


if __name__ == "__main__":
    unittest.main()
