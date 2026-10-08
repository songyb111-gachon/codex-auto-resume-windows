"""Notice a usage limit that lifts early (v0.6.13): EARLY at P7, and the usage gate's two yeses at P3.

Held against the shipped definition and statement and against core's own engine, store and
simulated Codex home (takingcase.py): off, a usage-limited conversation waits for its reset as in the
standard edition; armed, it is looked at early every five minutes, with one usage reading for every
waiting conversation, and goes on before its reset time only once two readings at least five minutes
apart both found usage - one yes never sends, and a look that found none starts the count again; a
conversation due in its own time goes as the standard edition sends it; watched, it only journals; the
unit is spent before the send; past its ceilings nothing is looked at early; a send it cannot prove
turns it off; a policy refuses it; and MCP arms nothing.

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
from codex_auto_resume import continuation, machine  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Alternative, Point  # noqa: E402
from codex_auto_resume_advanced import policy, surfaces  # noqa: E402
from codex_auto_resume_advanced.engine import earlyreset  # noqa: E402
from codex_auto_resume_advanced.engine.earlyreset import EarlyReset  # noqa: E402
from codex_auto_resume_advanced.registry import EARLY_RESET  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (Actor, ArmingState, JournalCode, McpTool,  # noqa: E402
                                                   OffReason, Refusal)
from test_engine import T1, T2, TURN_A, TURN_B  # noqa: E402

CAP = "early_reset"
NO_USAGE = {"available": False, "reset_at": None, "limit_type": "exposed_windows", "reason": "ok"}
USAGE = {"available": True, "reset_at": None, "limit_type": "exposed_windows", "reason": "ok"}
SPACING = earlyreset.SPACING
KEPT = ("state", "last_error", "next_retry_at", "reset_at", "attempt_count")


class EarlyCase(TakingCase):
    DEFINITION = EARLY_RESET

    def waiting(self, h=None, thread=T1, turn=TURN_A):
        """A conversation that waits for its usage limit to reset, an hour ahead."""
        h = h or self.h
        h.home.fail_usage(thread, turn)
        h.backend.loaded_map[thread] = "loaded"
        h.backend.after_accept = "queue"
        h.tick()
        row = h.record(thread)
        self.assertEqual(row["state"], "waiting_reset")
        return row

    def counts(self, plug):
        return plug.runtime.state.samples(self.cap)


class OffTests(EarlyCase):
    def test_off_a_usage_limited_conversation_waits_for_its_reset(self):
        plug = self.advanced()
        self.plugged(plug)
        row = self.waiting()
        while self.h.now + SPACING < row["reset_at"]:
            self.h.tick(advance=SPACING)
        self.assert_no_send()
        self.assertEqual({key: self.h.record()[key] for key in KEPT}, {key: row[key] for key in KEPT})
        self.assertFalse(plug.runtime.state.exists())


class ArmedTests(EarlyCase):
    def test_two_yeses_five_minutes_apart_continue_it_before_its_reset(self):
        row = self.waiting()
        plug = self.armed()
        key = row["interruption_id"]
        self.h.tick(advance=60)
        self.assert_no_send()
        after = self.h.record()
        self.assertEqual({name: after[name] for name in KEPT}, {name: row[name] for name in KEPT})
        gates = json.loads(after["gate_eval"])
        self.assertEqual((gates["schedule"], gates["usage"]), (["PASS", "plugged"], ["WAIT", "held"]))
        self.assertEqual(self.counts(plug), {"probed": 1})
        self.h.tick(advance=SPACING - 1)
        self.assert_no_send()
        self.h.tick(advance=1)
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertLess(self.h.now, row["reset_at"])
        sent = self.h.record()
        expected = continuation.for_settings("usage_limit", self.h.engine.policy_values, row=sent,
                                             limits=self.h.engine.limits())
        self.assertEqual(self.prompt(), expected + "\n\n" + sent["marker"])
        self.assertEqual(self.spends(plug), [(CAP, T1, key)])
        self.assertIn((JournalCode.ACTED, Point.SCHEDULE, Alternative.EARLY), self.journal(plug))
        self.assertIn(("erl.lifted", None, None), self.journal(plug))
        self.assertEqual(self.counts(plug), {"probed": 1, "lifted": 1})

    def test_one_yes_never_sends_and_a_look_that_found_no_usage_starts_the_count_again(self):
        row = self.waiting()
        plug = self.armed()
        self.h.tick(advance=60)                              # a first yes
        self.h.backend.usage_result = dict(NO_USAGE)
        self.h.tick(advance=SPACING)                         # no usage: the yes is forgotten
        self.assertEqual({name: self.h.record()[name] for name in KEPT}, {name: row[name] for name in KEPT})
        self.h.backend.usage_result = dict(USAGE)
        self.h.tick(advance=SPACING)                         # a first yes again
        self.assert_no_send()
        self.h.tick(advance=SPACING)                         # and the second
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertEqual(self.counts(plug), {"probed": 2, "lifted": 1})

    def test_one_question_a_look_serves_every_waiting_conversation(self):
        self.waiting(self.h, T1, TURN_A)
        self.waiting(self.h, T2, TURN_B)
        self.armed()
        reads, real = [], self.h.backend.usage
        self.h.backend.usage = lambda: (reads.append(self.h.now), real())[1]
        self.h.tick(advance=60)
        self.assertEqual((len(reads), len(self.h.backend.send_calls)), (1, 0))
        self.h.tick(advance=60)
        self.assertEqual(len(reads), 1, "nothing is asked between two looks")
        self.h.tick(advance=SPACING - 60)
        self.assertEqual(sorted(thread for thread, _prompt in self.h.backend.send_calls), sorted([T1, T2]))
        self.assertEqual(len(reads), 2, "one reading a look, for both")

    def test_a_conversation_due_in_its_own_time_goes_as_the_standard_edition_sends_it(self):
        expected = self.fresh()
        self.waiting(expected)
        due = expected.record()["reset_at"] + expected.engine.options["reset_grace_seconds"] + 1 - expected.now
        expected.tick(advance=due)
        self.assertEqual(len(expected.backend.send_calls), 1)
        self.waiting()
        plug = self.armed()
        self.h.tick(advance=due)
        self.assertEqual([thread for thread, _prompt in self.h.backend.send_calls],
                         [thread for thread, _prompt in expected.backend.send_calls])
        self.assertEqual(self.spends(plug), [], "a send in its own time is the standard edition's, and costs nothing")
        self.assertEqual(self.counts(plug), {})


class ShadowNeverActsTests(EarlyCase):
    def test_watched_it_journals_what_it_would_have_done_and_looks_at_nothing_early(self):
        self.waiting()
        plug = self.armed(state="shadow")
        for _ in range(4):
            self.h.tick(advance=SPACING)
        self.assert_no_send()
        self.assertIn((JournalCode.WOULD_HAVE, Point.SCHEDULE, Alternative.EARLY), self.journal(plug))
        self.assertEqual((self.spends(plug), self.counts(plug)), ([], {}))


class SpendBeforeSendTests(EarlyCase):
    def test_the_unit_is_spent_before_the_continuation_goes(self):
        key = self.waiting()["interruption_id"]
        plug = self.armed()
        seen = []
        self.h.backend.on_send = lambda thread, prompt: seen.append(self.spends(plug))
        self.h.tick(advance=60)
        self.h.tick(advance=SPACING)
        self.assertEqual(seen, [[(CAP, T1, key)]])


class CeilingTests(EarlyCase):
    def test_past_its_ceiling_nothing_is_looked_at_early(self):
        self.waiting()
        plug = self.armed()
        self.fill(plug, EARLY_RESET.ceilings.per_conversation, at=self.h.now - 3600)
        for _ in range(4):
            self.h.tick(advance=SPACING)
        self.assert_no_send()
        self.assertIn((JournalCode.CEILING, Point.SCHEDULE, Alternative.EARLY), self.journal(plug))
        self.assertEqual(self.counts(plug), {})


class TripwireTests(EarlyCase):
    def test_a_send_it_paid_for_gone_unknown_turns_it_off_and_is_never_sent_again(self):
        self.waiting()
        plug = self.armed()
        self.h.backend.default_outcome = "unknown"
        self.h.tick(advance=60)
        self.h.tick(advance=SPACING)
        self.assertEqual(self.h.record()["state"], "submission_unknown")
        stored = plug.runtime.state.arming()[CAP]
        self.assertEqual((stored["state"], stored["reason"]), (ArmingState.OFF, OffReason.SUBMISSION_UNKNOWN))
        for _ in range(8):
            self.h.tick(advance=900)
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_a_hook_that_raises_trips_it_and_looks_at_nothing_early(self):
        self.waiting()
        plug = self.armed()
        with patch.object(EarlyReset, "schedule", side_effect=RuntimeError("boom")):
            self.h.tick(advance=60)
        self.assertEqual(plug.runtime.state.arming()[CAP]["reason"], OffReason.HOOK_EXCEPTION)
        self.h.tick(advance=SPACING)
        self.assert_no_send()


class PolicyTests(EarlyCase):
    def test_not_allowed_it_reads_off_and_cannot_be_turned_on(self):
        self.waiting()
        plug = self.armed()
        self.policy = policy.Policy(allowed=frozenset({"capacity_retry"}))
        plug.runtime.states(fresh=True)
        self.h.tick(advance=60)
        self.h.tick(advance=SPACING)
        self.assert_no_send()
        result = plug.runtime.arming.arm(CAP, state="armed", revision=1, generation=plug.runtime.state.meta()
                                         ["generation"], acknowledged_version=ac.ENGINE, actor=Actor.DASHBOARD)
        self.assertEqual(result["refusal"], Refusal.NOT_ALLOWED_BY_POLICY)


class McpTests(EarlyCase):
    def test_mcp_arms_nothing_and_turns_it_off(self):
        plug = self.armed()
        runtime = plug.runtime
        tools = {tool["name"] for tool in surfaces.mcp(runtime, {"request": "tools"})["tools"]}
        self.assertLessEqual(tools, set(McpTool))
        self.assertFalse(runtime.arming.arm(CAP, state="armed", revision=1, generation=runtime.state.meta()
                                            ["generation"], acknowledged_version=ac.ENGINE, actor=Actor.MCP)["done"])
        reply = surfaces.mcp(runtime, {"request": "call", "tool": McpTool.DISARM_ADVANCED_CAPABILITY,
                                       "arguments": {"capability": CAP}})
        self.assertIn("data", reply)
        self.assertEqual(runtime.state.arming()[CAP]["state"], ArmingState.OFF)


class CodeTests(unittest.TestCase):
    LOOKED_EARLY = {"schedule": machine.gate(machine.PASS, machine.PLUGGED)}

    class Scoped:
        def __init__(self, now):
            self.at, self.counted = now, []

        def now(self):
            return self.at

        def count(self, code):
            self.counted.append(code)
            return True

    def code(self, now=1000.0):
        made = EarlyReset(None)
        self.scoped = self.Scoped(now)
        made.bind(self.scoped)
        return made

    def record(self, key="a", **changes):
        return dict({"interruption_id": key, "category": "usage_limit", "state": "waiting_reset"}, **changes)

    def test_early_only_for_a_record_that_waits_for_a_usage_reset_before_its_time(self):
        code = self.code()
        self.assertIs(code.schedule(self.record(), 5000.0), Alternative.EARLY)
        for record, due in ((self.record(category="server_5xx"), 5000.0), (self.record(state="waiting_backoff"), 5000.0),
                            (self.record(), 1000.0), (self.record(), None), ("not a record", 5000.0)):
            with self.subTest(record=record, due=due):
                self.assertIs(self.code().schedule(record, due), DEFER)
        self.assertIs(self.code().schedule(self.record(state="waiting_poll"), 5000.0), Alternative.EARLY)

    def test_a_postponed_record_opens_no_probe(self):
        """Core never looks at one early, and asks P7 of it only for a person's Send now (v0.6.13):
        no probe is opened for it, so the one core's early window opens is still the code's."""
        code = self.code()
        self.assertIs(code.schedule(self.record("a", not_before=3000.0), 5000.0), DEFER)
        self.assertIsNone(code.probe_at)
        self.assertIs(code.schedule(self.record("a", not_before=900.0), 5000.0), Alternative.EARLY)

    def test_one_look_every_five_minutes_with_every_record_in_its_first_seconds(self):
        code = self.code()
        self.assertIs(code.schedule(self.record("a"), 9000.0), Alternative.EARLY)
        self.scoped.at += earlyreset.WINDOW - 1
        self.assertIs(code.schedule(self.record("b"), 9000.0), Alternative.EARLY)
        self.scoped.at += 1
        self.assertIs(code.schedule(self.record("c"), 9000.0), DEFER)
        self.scoped.at = 1000.0 + SPACING
        self.assertIs(code.schedule(self.record("c"), 9000.0), Alternative.EARLY)
        self.assertEqual(code.released, {"c"}, "each look releases its own records")

    def test_hold_on_a_first_yes_and_go_on_a_second_five_minutes_later_counting_each_once(self):
        code = self.code()
        code.schedule(self.record("a"), 9000.0)
        code.schedule(self.record("b"), 9000.0)
        self.assertIs(code.gate("usage", self.record("a"), self.LOOKED_EARLY), Alternative.HOLD)
        self.assertIs(code.gate("usage", self.record("b"), self.LOOKED_EARLY), Alternative.HOLD)
        self.scoped.at += SPACING
        code.schedule(self.record("a"), 9000.0)
        code.schedule(self.record("b"), 9000.0)
        self.assertIs(code.gate("usage", self.record("a"), self.LOOKED_EARLY), DEFER)
        self.assertIs(code.gate("usage", self.record("b"), self.LOOKED_EARLY), DEFER)
        self.assertEqual(self.scoped.counted, ["probed", "lifted"])

    def test_a_record_in_its_own_time_another_gate_or_one_it_did_not_release_is_cores(self):
        code = self.code()
        code.schedule(self.record("a"), 9000.0)
        self.assertIs(code.gate("usage", self.record("a"), {"schedule": machine.gate(machine.PASS)}), DEFER)
        self.assertIs(code.gate("usage", self.record("b"), self.LOOKED_EARLY), DEFER)
        self.assertIs(code.gate("known_failure", self.record("a"), self.LOOKED_EARLY), DEFER)
        self.assertIsNone(code.first_available_at, "none of those was a yes")

    def test_a_look_that_never_reached_the_usage_gate_forgets_the_first_yes(self):
        code = self.code()
        code.schedule(self.record("a"), 9000.0)
        code.gate("usage", self.record("a"), self.LOOKED_EARLY)
        self.scoped.at += SPACING
        code.schedule(self.record("a"), 9000.0)          # no usage: the gate is never reached
        self.scoped.at += SPACING
        code.schedule(self.record("a"), 9000.0)
        self.assertIs(code.gate("usage", self.record("a"), self.LOOKED_EARLY), Alternative.HOLD)
        self.assertEqual(self.scoped.counted, ["probed", "probed"])


if __name__ == "__main__":
    unittest.main()
