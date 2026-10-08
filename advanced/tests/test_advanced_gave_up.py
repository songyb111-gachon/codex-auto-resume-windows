"""Retry when Codex gave up (v0.6.14): responseTooManyFailedAttempts on a server error or none.

Held against the shipped definition and statement and against core's own engine, store and
simulated Codex home (takingcase.py): off, Codex giving up waits for the person, as in the standard
edition; armed, it is taken up at P17, goes ten minutes on as the short standard continuation with its
marker, again 15 minutes after a second such failure of the task and never a third time; on a 429 the
standard edition retries it as a rate limit, and no other failure Codex could not get past is taken
up; watched, it only journals; the unit is spent before the send; past its ceilings nothing is taken
up; a send it cannot prove turns it off; a policy refuses it; and MCP arms nothing.

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
from codex_auto_resume_advanced.engine.admitted import CodexGaveUp  # noqa: E402
from codex_auto_resume_advanced.registry import CODEX_GAVE_UP  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (Actor, ArmingState, JournalCode, McpTool,  # noqa: E402
                                                   OffReason, Refusal)
from test_engine import T1  # noqa: E402

CAP = "codex_gave_up"
GAVE_UP = json.dumps({"codexErrorInfo": "responseTooManyFailedAttempts"})
GAVE_UP_503 = json.dumps({"codexErrorInfo": {"type": "responseTooManyFailedAttempts", "httpStatusCode": 503}})
GAVE_UP_429 = json.dumps({"codexErrorInfo": {"type": "responseTooManyFailedAttempts", "httpStatusCode": 429}})
SANDBOX = json.dumps({"codexErrorInfo": "sandboxError"})
FIRST = ladder.ADMITTED_WAITS[0]


class GaveUpCase(TakingCase):
    DEFINITION = CODEX_GAVE_UP

    def taken_up(self, error=GAVE_UP, state="armed"):
        plug = self.armed(state=state)
        self.h.backend.after_accept = "queue"
        self.failing(error)
        self.h.tick()
        return plug


class OffTests(GaveUpCase):
    def test_off_codex_giving_up_waits_for_the_person(self):
        self.assertIsNone(self.standard(GAVE_UP))
        plug = self.advanced()
        self.plugged(plug)
        self.failing(GAVE_UP)
        self.h.tick()
        self.assertEqual(self.h.records(), [])
        self.assertFalse(plug.runtime.state.exists())


class ArmedTests(GaveUpCase):
    def test_taken_up_it_goes_ten_minutes_on_as_the_short_continuation(self):
        for error in (GAVE_UP, GAVE_UP_503):
            with self.subTest(error=error):
                self.h = self.fresh()
                plug = self.taken_up(error)
                row = self.h.record()
                key = row["interruption_id"]
                self.assertEqual((row["category"], row["state"], row["next_retry_at"] - self.h.now),
                                 ("terminal_failure", "waiting_backoff", FIRST))
                self.h.tick(advance=FIRST - 1)
                self.assert_no_send()
                self.h.tick(advance=1)
                self.assertEqual(len(self.h.backend.send_calls), 1)
                expected = continuation.for_settings("terminal_failure", self.h.engine.policy_values,
                                                     row=self.h.record(), limits=self.h.engine.limits())
                self.assertEqual(self.prompt(), expected + "\n\n" + self.h.record()["marker"])
                self.assertEqual(self.spends(plug), [(CAP, T1, key)])
                self.assertIn((JournalCode.ACTED, Point.GATES, Alternative.ADMIT), self.journal(plug))

    def test_twice_a_task_at_most_the_second_fifteen_minutes_on(self):
        self.taken_up()
        child = self.again(self.h, GAVE_UP, step=60)
        self.assertEqual(len(self.h.records()), 2)
        self.assertEqual((child["category"], child["next_retry_at"] - self.h.now),
                         ("terminal_failure", ladder.ADMITTED_WAITS[1]))
        self.again(self.h, GAVE_UP, step=60)
        self.assertEqual(len(self.h.records()), 2, "a third failure of the task is left for the person")
        self.assertEqual(len(self.h.backend.send_calls), 2)

    def test_on_a_429_the_standard_edition_retries_it_and_nothing_else_is_taken_up(self):
        expected = self.standard(GAVE_UP_429)
        plug = self.armed()
        self.failing(GAVE_UP_429)
        self.h.tick()
        row = self.h.record()
        self.assertEqual((row["category"], row["state"], row["next_retry_at"] - self.h.now, row["last_error"]),
                         expected)
        self.assertIsNone(plug.runtime.state.admission(row["interruption_id"]))
        self.h = self.fresh()
        self.taken_up(SANDBOX)
        self.assertEqual(self.h.records(), [], "a sandbox failure is never Codex giving up")


class ShadowNeverActsTests(GaveUpCase):
    def test_watched_it_journals_what_it_would_have_done_and_takes_nothing_up(self):
        plug = self.taken_up(state="shadow")
        self.assertEqual(self.h.records(), [])
        self.assertIn((JournalCode.WOULD_HAVE, Point.ADMISSION, Alternative.ADMIT), self.journal(plug))
        self.assertEqual(self.spends(plug), [])


class SpendBeforeSendTests(GaveUpCase):
    def test_the_unit_is_spent_before_the_continuation_goes(self):
        plug = self.taken_up()
        key = self.h.record()["interruption_id"]
        seen = []
        self.h.backend.on_send = lambda thread, prompt: seen.append(self.spends(plug))
        self.h.tick(advance=FIRST)
        self.assertEqual(seen, [[(CAP, T1, key)]])


class CeilingTests(GaveUpCase):
    def test_past_its_ceiling_nothing_is_taken_up(self):
        plug = self.armed()
        self.fill(plug, CODEX_GAVE_UP.ceilings.per_conversation, at=self.h.now - 3600)
        self.failing(GAVE_UP)
        self.h.tick()
        self.assertEqual(self.h.records(), [])
        self.assertIn((JournalCode.CEILING, Point.ADMISSION, Alternative.ADMIT), self.journal(plug))


class TripwireTests(GaveUpCase):
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

    def test_a_hook_that_raises_trips_it_and_takes_nothing_up(self):
        plug = self.armed()
        self.failing(GAVE_UP)
        with patch.object(CodexGaveUp, "admission", side_effect=RuntimeError("boom")):
            self.h.tick()
        self.assertEqual(plug.runtime.state.arming()[CAP]["reason"], OffReason.HOOK_EXCEPTION)
        self.assertEqual(self.h.records(), [])


class PolicyTests(GaveUpCase):
    def test_not_allowed_it_reads_off_and_cannot_be_turned_on(self):
        plug = self.armed()
        self.policy = policy.Policy(allowed=frozenset({"capacity_retry"}))
        plug.runtime.states(fresh=True)
        self.failing(GAVE_UP)
        self.h.tick()
        self.assertEqual(self.h.records(), [])
        result = plug.runtime.arming.arm(CAP, state="armed", revision=1, generation=plug.runtime.state.meta()
                                         ["generation"], acknowledged_version=ac.ENGINE, actor=Actor.DASHBOARD)
        self.assertEqual(result["refusal"], Refusal.NOT_ALLOWED_BY_POLICY)


class McpTests(GaveUpCase):
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
    def test_twice_a_task_and_only_codex_giving_up(self):
        code = CodexGaveUp(None)
        facts = {"category": "terminal_failure", "chain": None}
        self.assertIs(code.admission(facts), Alternative.ADMIT)
        self.assertIs(code.admission(dict(facts, chain={"recovery_attempts": 1})), Alternative.ADMIT)
        self.assertIs(code.admission(dict(facts, chain={"recovery_attempts": 2})), DEFER)
        self.assertIs(code.admission(dict(facts, chain={})), DEFER)
        self.assertIs(code.admission(dict(facts, category="unknown")), DEFER)
        self.assertIs(code.gate("known_failure", {"category": "terminal_failure"}, {}), Alternative.ADMIT)
        self.assertIs(code.gate("known_failure", {"category": "terminal_auth"}, {}), DEFER)
        self.assertIs(code.gate("usage", {"category": "terminal_failure"}, {}), DEFER)


if __name__ == "__main__":
    unittest.main()
