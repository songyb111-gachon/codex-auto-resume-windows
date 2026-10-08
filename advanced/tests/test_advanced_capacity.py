"""Short retries when Codex is at capacity (v0.6.14): CAPACITY at P17 and at known_failure.

Held against the shipped definition and statement and against core's own engine, store and
simulated Codex home (takingcase.py): off, it is the standard edition; armed, Codex's own
serverOverloaded retries a minute on, then two, four and five, through Codex's queue with the marker,
past the standard edition's budgets, for the hours the person chose on the clock - two by default -
and then the standard edition's handling again; watched, it only journals; the unit is spent before
the send; past its ceilings the standard edition handles the error; a send it cannot prove turns it
off; a policy refuses or reads it down; and MCP neither arms it nor writes its choice.

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
from codex_auto_resume import ladder, managed, settings  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Alternative, Point  # noqa: E402
from codex_auto_resume.machine import TERMINAL  # noqa: E402
from codex_auto_resume_advanced import policy, surfaces  # noqa: E402
from codex_auto_resume_advanced.engine.capacity import CapacityRetry  # noqa: E402
from codex_auto_resume_advanced.registry import CAPACITY_RETRY  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (Actor, ArmingState, JournalCode, McpTool,  # noqa: E402
                                                   OffReason, OptionKey, Refusal)
from test_engine import T1, fail_turn  # noqa: E402
from test_plug_points import Fixed  # noqa: E402

CAP = "capacity_retry"
OVERLOADED = json.dumps({"codexErrorInfo": "serverOverloaded"})
INTERNAL = json.dumps({"codexErrorInfo": "internalServerError"})
OTHER = "0a1b2c3d-0001-7000-8000-%012x"


class CapacityCase(TakingCase):
    DEFINITION = CAPACITY_RETRY

    def vouched(self, h=None, state="armed"):
        """Armed (or watched), a capacity failure, and the tick that takes it up; jitter drawn at 0."""
        h = h or self.h
        plug = self.armed(h, state=state)
        h.engine._random = Fixed(0.0)
        h.backend.after_accept = "queue"
        self.failing(OVERLOADED, h)
        h.tick()
        return plug


class OffTests(CapacityCase):
    def test_off_it_is_the_standard_edition_and_reads_and_writes_nothing(self):
        expected = self.standard(OVERLOADED)
        plug = self.advanced()
        self.plugged(plug)
        self.failing(OVERLOADED)
        self.h.tick()
        row = self.h.record()
        self.assertEqual((row["category"], row["state"], row["next_retry_at"] - self.h.now, row["last_error"]),
                         expected)
        self.assertFalse(plug.runtime.state.exists(), "nothing was ever on: no advanced state at all")


class ArmedTests(CapacityCase):
    def test_a_capacity_error_goes_again_a_minute_on_through_codexs_queue_with_its_marker(self):
        plug = self.vouched()
        row = self.h.record()
        key = row["interruption_id"]
        self.assertEqual((row["category"], row["state"], row["next_retry_at"] - self.h.now),
                         ("server_5xx", "waiting_backoff", 60))
        self.assertEqual(plug.runtime.state.admission(key)["answer"], Alternative.CAPACITY)
        self.h.tick(advance=59)
        self.assert_no_send()
        self.h.tick(advance=1)
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertTrue(self.prompt().endswith(self.h.record()["marker"]))
        self.assertEqual(json.loads(self.h.record()["gate_eval"])["known_failure"], ["PASS", "plugged"])
        self.assertEqual(self.spends(plug), [(CAP, T1, key)])
        for point in (Point.ADMISSION, Point.GATES):
            self.assertIn((JournalCode.ACTED, point, Alternative.CAPACITY), self.journal(plug))

    def test_it_goes_on_past_the_standard_editions_floor_and_budgets(self):
        plug = self.vouched()
        times = []
        self.h.backend.on_send = lambda thread, prompt: times.append(self.h.now)
        waits = [self.again(self.h, OVERLOADED)["next_retry_at"] - self.h.now for _ in range(6)]
        self.assertEqual(waits, [120, 240, 300, 300, 300, 300])
        gaps = [later - earlier for earlier, later in zip(times, times[1:])]
        self.assertTrue(all(ladder.CAPACITY_SPACING <= gap < ladder.SPACING for gap in gaps), gaps)
        self.assertEqual(len(self.h.backend.send_calls), 6, "more than the standard edition's four attempts")
        self.assertNotIn(self.h.records()[-1]["state"], TERMINAL)
        self.assertEqual(len(self.spends(plug)), 6)

    def test_two_hours_by_default_counted_on_the_clock_then_the_standard_edition_ends_the_task(self):
        self.vouched()
        for _ in range(5):
            self.again(self.h, OVERLOADED)            # five attempts: past the standard edition's four
        origin, sent = self.h.records()[0], len(self.h.backend.send_calls)
        self.h.now = origin["detected_at"] + 2 * 3600 - 1
        self.h.tick()
        self.assertEqual(len(self.h.backend.send_calls), sent + 1, "inside two hours it still goes")
        turn = self.h.home.dispatch(T1, status="inProgress", progress=False)
        fail_turn(self.h.home, T1, turn, error_json=OVERLOADED)
        self.h.tick(advance=1)
        self.h.tick(advance=900)
        last = self.h.records()[-1]
        self.assertIn(last["state"], TERMINAL)
        self.assertEqual(len(self.h.backend.send_calls), sent + 1)

    def test_a_person_may_choose_one_hour(self):
        plug = self.vouched()
        self.choose(plug, OptionKey.CEILING_HOURS, 1)
        for _ in range(5):
            self.again(self.h, OVERLOADED)
        origin, sent = self.h.records()[0], len(self.h.backend.send_calls)
        self.h.now = origin["detected_at"] + 3600
        self.h.tick()
        self.assertIn(self.h.records()[-1]["state"], TERMINAL)
        self.assertEqual(len(self.h.backend.send_calls), sent)

    def test_another_server_error_is_never_taken_up(self):
        expected = self.standard(INTERNAL)
        plug = self.armed()
        self.failing(INTERNAL)
        self.h.tick()
        row = self.h.record()
        self.assertEqual((row["category"], row["state"], row["next_retry_at"] - self.h.now, row["last_error"]),
                         expected)
        self.assertIsNone(plug.runtime.state.admission(row["interruption_id"]))
        self.assertEqual(self.journal(plug)[1:], [])


class ShadowNeverActsTests(CapacityCase):
    def test_watched_it_journals_what_it_would_have_done_and_the_standard_edition_waits(self):
        expected = self.standard(OVERLOADED)
        plug = self.vouched(state="shadow")
        row = self.h.record()
        self.assertEqual((row["category"], row["state"], row["next_retry_at"] - self.h.now, row["last_error"]),
                         expected)
        self.assertIn((JournalCode.WOULD_HAVE, Point.ADMISSION, Alternative.CAPACITY), self.journal(plug))
        self.assertNotIn(JournalCode.ACTED, {code for code, _point, _answer in self.journal(plug)})
        self.assertIsNone(plug.runtime.state.admission(row["interruption_id"]))
        self.assertEqual(self.spends(plug), [])


class SpendBeforeSendTests(CapacityCase):
    def test_the_unit_is_spent_before_the_continuation_goes(self):
        plug = self.vouched()
        seen = []
        self.h.backend.on_send = lambda thread, prompt: seen.append(self.spends(plug))
        key = self.h.record()["interruption_id"]
        self.h.tick(advance=60)
        self.assertEqual(seen, [[(CAP, T1, key)]])

    def test_turned_off_between_its_answer_and_the_claim_nothing_is_sent(self):
        plug = self.vouched()
        ask = ac.advanced.AdvancedPlug.gate

        def gate(made, name, record, facts):
            answer = ask(made, name, record, facts)
            if name == "known_failure":
                plug.runtime.arming.disarm(CAP, actor=Actor.DASHBOARD)
            return answer
        with patch.object(ac.advanced.AdvancedPlug, "gate", gate):
            self.h.tick(advance=60)
        self.assert_no_send()
        self.assertEqual(self.spends(plug), [])


class CeilingTests(CapacityCase):
    def test_past_its_ceiling_in_a_conversation_the_standard_edition_handles_it(self):
        expected = self.standard(OVERLOADED)
        plug = self.armed()
        self.fill(plug, CAPACITY_RETRY.ceilings.per_conversation, at=self.h.now - 3600)
        self.failing(OVERLOADED)
        self.h.tick()
        row = self.h.record()
        self.assertEqual((row["category"], row["state"], row["next_retry_at"] - self.h.now, row["last_error"]),
                         expected)
        self.assertIn((JournalCode.CEILING, Point.ADMISSION, Alternative.CAPACITY), self.journal(plug))
        self.assertIsNone(plug.runtime.state.admission(row["interruption_id"]))

    def test_past_the_global_hour_too_and_a_record_it_took_up_is_not_parked(self):
        plug = self.vouched()
        self.fill(plug, 12, lambda index: OTHER % (index + 16))
        self.h.tick(advance=60)
        self.assertIn((JournalCode.CEILING, Point.GATES, Alternative.CAPACITY), self.journal(plug))
        self.assertNotEqual(json.loads(self.h.record()["gate_eval"])["known_failure"], ["WAIT", "held"])

    def test_an_administrators_max_recovery_attempts_holds_it_as_it_holds_the_standard_edition(self):
        """The capability passes the person's budgets, never the administrator's: MaxRecoveryAttempts at
        1 lets one continuation go, as in the standard edition, and then the task ends."""
        plug = self.armed()
        self.h.engine.apply_policy(settings.defaults(), managed.Managed(max_recovery_attempts=1))
        self.h.engine._random = Fixed(0.0)
        self.h.backend.after_accept = "queue"
        self.failing(OVERLOADED)
        self.h.tick()
        self.again(self.h, OVERLOADED)
        for _ in range(30):
            self.h.tick(advance=60)
        last = self.h.records()[-1]
        self.assertEqual((last["state"], last["last_error"]), ("retry_budget_exhausted", "recovery_budget"))
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertEqual(len(self.spends(plug)), 1)


class TripwireTests(CapacityCase):
    def test_a_send_it_paid_for_gone_unknown_turns_it_off_and_is_never_sent_again(self):
        plug = self.vouched()
        self.h.backend.default_outcome = "unknown"
        self.h.tick(advance=60)
        row = self.h.record()
        self.assertEqual(row["state"], "submission_unknown")
        stored = plug.runtime.state.arming()[CAP]
        self.assertEqual((stored["state"], stored["reason"]), (ArmingState.OFF, OffReason.SUBMISSION_UNKNOWN))
        for _ in range(12):
            self.h.tick(advance=900)
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_a_hook_that_raises_trips_it_and_the_standard_edition_goes_on(self):
        expected = self.standard(OVERLOADED)
        plug = self.armed()
        self.failing(OVERLOADED)
        with patch.object(CapacityRetry, "admission", side_effect=RuntimeError("boom")):
            self.h.tick()
        stored = plug.runtime.state.arming()[CAP]
        self.assertEqual((stored["state"], stored["reason"]), (ArmingState.OFF, OffReason.HOOK_EXCEPTION))
        row = self.h.record()
        self.assertEqual((row["category"], row["state"], row["next_retry_at"] - self.h.now, row["last_error"]),
                         expected)

    def test_re_arming_is_always_possible_after_a_trip(self):
        plug = self.vouched()
        self.h.backend.default_outcome = "unknown"
        self.h.tick(advance=60)
        self.assertEqual(plug.runtime.state.arming()[CAP]["state"], ArmingState.OFF)
        self.arm(plug)
        self.assertEqual(plug.runtime.state.arming()[CAP]["state"], ArmingState.ARMED)


class PolicyTests(CapacityCase):
    def test_forbidden_or_not_allowed_it_reads_off_and_cannot_be_turned_on(self):
        for found, refusal in ((policy.Policy(forbid=True), Refusal.FORBIDDEN_BY_POLICY),
                               (policy.Policy(allowed=frozenset({"goal_continuation"})),
                                Refusal.NOT_ALLOWED_BY_POLICY)):
            with self.subTest(refusal):
                h = self.fresh()
                expected = self.standard(OVERLOADED)
                plug = self.armed(h)
                self.policy = found
                plug.runtime.states(fresh=True)
                self.failing(OVERLOADED, h)
                h.tick()
                row = h.record()
                self.assertEqual((row["category"], row["state"], row["next_retry_at"] - h.now, row["last_error"]),
                                 expected)
                result = plug.runtime.arming.arm(CAP, state="armed", revision=1, generation=plug.runtime.state.meta()
                                                 ["generation"], acknowledged_version=ac.ENGINE, actor=Actor.DASHBOARD)
                self.assertEqual(result["refusal"], refusal)
                self.policy = policy.NONE

    def test_shadow_forced_it_only_watches(self):
        plug = self.armed()
        self.policy = policy.Policy(force_shadow=True)
        plug.runtime.states(fresh=True)
        self.failing(OVERLOADED)
        self.h.tick()
        self.assertIn((JournalCode.WOULD_HAVE, Point.ADMISSION, Alternative.CAPACITY), self.journal(plug))
        self.assertEqual(self.spends(plug), [])
        result = plug.runtime.arming.arm(CAP, state="armed", revision=1, generation=plug.runtime.state.meta()
                                         ["generation"], acknowledged_version=ac.ENGINE, actor=Actor.DASHBOARD)
        self.assertEqual(result["refusal"], Refusal.SHADOW_FORCED_BY_POLICY)


class McpTests(CapacityCase):
    def test_mcp_neither_arms_it_nor_writes_its_choice(self):
        plug = self.armed()
        runtime = plug.runtime
        tools = {tool["name"] for tool in surfaces.mcp(runtime, {"request": "tools"})["tools"]}
        self.assertLessEqual(tools, set(McpTool))
        refused = surfaces.mcp(runtime, {"request": "call", "tool": McpTool.DISARM_ADVANCED_CAPABILITY,
                                         "arguments": {"capability": CAP, "ceiling_hours": 12}})
        self.assertIn("refused", refused)
        self.assertEqual(runtime.arming.set_option(CAP, OptionKey.CEILING_HOURS, 12, generation=runtime.state
                                                   .meta()["generation"], actor=Actor.MCP)["refusal"],
                         Refusal.NOT_THE_DASHBOARD)
        self.assertEqual(runtime.state.options(CAP), {OptionKey.CEILING_HOURS: 2})
        self.assertEqual(runtime.state.arming()[CAP]["state"], ArmingState.ARMED)
        reply = surfaces.mcp(runtime, {"request": "call", "tool": McpTool.DISARM_ADVANCED_CAPABILITY,
                                       "arguments": {"capability": CAP}})
        self.assertIn("data", reply)
        self.assertEqual(runtime.state.arming()[CAP]["state"], ArmingState.OFF)


class CodeTests(unittest.TestCase):
    """The capability's code on its own: what it answers, and for how long."""

    class Scoped:
        def __init__(self, now, hours=2):
            self.at, self.hours = now, hours

        def now(self):
            return self.at

        def options(self):
            return {OptionKey.CEILING_HOURS: self.hours}

    def code(self, now=10_000.0, hours=2):
        made = CapacityRetry(None)
        made.bind(self.Scoped(now, hours))
        return made

    def test_only_codex_at_capacity_and_only_inside_the_hours_chosen(self):
        code = self.code()
        facts = {"category": "server_5xx", "code": "serverOverloaded", "chain": None}
        self.assertIs(code.admission(facts), Alternative.CAPACITY)
        self.assertIs(code.admission(dict(facts, code="internalServerError")), DEFER)
        self.assertIs(code.admission(dict(facts, category="unknown")), DEFER)
        self.assertIs(code.admission(dict(facts, chain={"chain_started_at": 10_000.0 - 7199})), Alternative.CAPACITY)
        self.assertIs(code.admission(dict(facts, chain={"chain_started_at": 10_000.0 - 7200})), DEFER)
        self.assertIs(code.admission(dict(facts, chain={"chain_started_at": None})), DEFER)
        record = {"category": "server_5xx", "chain_started_at": 10_000.0 - 3599}
        self.assertIs(code.gate("known_failure", record, {}), Alternative.CAPACITY)
        self.assertIs(code.gate("usage", record, {}), DEFER)
        self.assertIs(self.code(hours=1).gate("known_failure", dict(record, chain_started_at=10_000.0 - 3600), {}),
                      DEFER)
        self.assertIs(code.gate("known_failure", {"category": "server_5xx"}, {}), DEFER)


if __name__ == "__main__":
    unittest.main()
