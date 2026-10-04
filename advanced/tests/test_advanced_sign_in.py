"""Retry a sign-in failure after proof (v0.6.13): Codex's unauthorized, or a 401, taken up once a task.

Held against the shipped definition and statement and against core's own engine, store and
simulated Codex home (takingcase.py): off, a sign-in failure waits for the person, as in the
standard edition; armed, it is taken up at P17 and goes ten minutes on as the short standard
continuation with its marker - only once the usage read every continuation needs works, and never
while it does not, a day on the clock ending it unsent; a second sign-in failure of the task ends it
there, and a permission refusal (403) is never taken up; watched, it only journals; the unit is
spent before the send; past its ceilings nothing is taken up; a send it cannot prove turns it off; a
policy refuses it; MCP arms nothing; and its code names no sign-in of Codex's.

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import inspect
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
from codex_auto_resume_advanced.codex import protocol  # noqa: E402
from codex_auto_resume_advanced.engine import admitted  # noqa: E402
from codex_auto_resume_advanced.engine.admitted import SignInRetry  # noqa: E402
from codex_auto_resume_advanced.registry import SIGN_IN_RETRY  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (Actor, ArmingState, JournalCode, McpTool,  # noqa: E402
                                                   OffReason, Refusal)
from test_engine import T1  # noqa: E402

CAP = "sign_in_retry"
SIGNED_OUT = json.dumps({"codexErrorInfo": "unauthorized"})
SIGNED_OUT_401 = json.dumps({"codexErrorInfo": {"type": "unauthorized", "httpStatusCode": 401}})
EXPIRED_401 = json.dumps({"codexErrorInfo": {"type": "sessionExpired", "httpStatusCode": 401}})
REFUSED_403 = json.dumps({"codexErrorInfo": {"type": "unauthorized", "httpStatusCode": 403}})
EXPIRED_403 = json.dumps({"codexErrorInfo": {"type": "sessionExpired", "httpStatusCode": 403}})
DROPPED = json.dumps({"codexErrorInfo": "httpConnectionFailed"})
UNKNOWN_USAGE = {"available": None, "reset_at": None, "limit_type": "unknown", "reason": "probe_failed"}
READ_USAGE = {"available": True, "reset_at": None, "limit_type": "exposed_windows", "reason": "ok"}
FIRST = ladder.ADMITTED_WAITS[0]


class SignInCase(TakingCase):
    DEFINITION = SIGN_IN_RETRY

    def taken_up(self, error=SIGNED_OUT, state="armed"):
        plug = self.armed(state=state)
        self.h.backend.after_accept = "queue"
        self.failing(error)
        self.h.tick()
        return plug


class OffTests(SignInCase):
    def test_off_a_sign_in_failure_waits_for_the_person(self):
        self.assertIsNone(self.standard(SIGNED_OUT))
        plug = self.advanced()
        self.plugged(plug)
        self.failing(SIGNED_OUT)
        self.h.tick()
        self.assertEqual(self.h.records(), [])
        self.assertFalse(plug.runtime.state.exists())


class ArmedTests(SignInCase):
    def test_taken_up_it_goes_ten_minutes_on_as_the_short_continuation(self):
        for error in (SIGNED_OUT, SIGNED_OUT_401, EXPIRED_401):
            with self.subTest(error=error):
                self.h = self.fresh()
                plug = self.taken_up(error)
                row = self.h.record()
                key = row["interruption_id"]
                self.assertEqual((row["category"], row["state"], row["next_retry_at"] - self.h.now),
                                 ("terminal_auth", "waiting_backoff", FIRST))
                self.h.tick(advance=FIRST - 1)
                self.assert_no_send()
                self.h.tick(advance=1)
                self.assertEqual(len(self.h.backend.send_calls), 1)
                expected = continuation.for_settings("terminal_auth", self.h.engine.policy_values,
                                                     row=self.h.record(), limits=self.h.engine.limits())
                self.assertEqual(self.prompt(), expected + "\n\n" + self.h.record()["marker"])
                self.assertEqual(self.spends(plug), [(CAP, T1, key)])
                self.assertIn((JournalCode.ACTED, Point.GATES, Alternative.ADMIT), self.journal(plug))

    def test_it_goes_only_once_a_usage_read_works_and_a_day_on_the_clock_ends_it_unsent(self):
        poll = self.h.engine.options["conservative_poll_seconds"]
        for restored in (True, False):
            with self.subTest(restored=restored):
                self.h = self.fresh()
                plug = self.taken_up()
                self.h.backend.usage_result = dict(UNKNOWN_USAGE)
                self.h.tick(advance=FIRST)
                row = self.h.record()
                self.assertEqual((row["state"], row["last_error"]), ("waiting_for_usage", "usage_unknown"))
                for _ in range(4):
                    self.h.tick(advance=poll)
                self.assert_no_send()
                self.assertEqual(self.spends(plug), [], "nothing is paid for while the proof is missing")
                if restored:
                    self.h.backend.usage_result = dict(READ_USAGE)
                    self.h.tick(advance=poll)
                    self.assertEqual(len(self.h.backend.send_calls), 1)
                    continue
                self.h.now = row["detected_at"] + ladder.ADMITTED_MAX_SECONDS
                self.h.tick()
                row = self.h.record()
                self.assertEqual((row["state"], row["last_error"]), ("terminal_failure", "admission_expired"))
                self.assert_no_send()

    def test_a_second_sign_in_failure_of_the_task_ends_it_there(self):
        self.taken_up()
        self.again(self.h, SIGNED_OUT, step=60)
        self.assertEqual(len(self.h.records()), 1, "the second sign-in failure is left for the person")
        for _ in range(4):
            self.h.tick(advance=FIRST)
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_a_sign_in_failure_of_another_kinds_continuation_is_taken_up(self):
        self.armed()
        self.h.backend.after_accept = "queue"
        self.failing(DROPPED)
        self.h.tick()
        self.assertEqual(self.h.record()["category"], "network_transient")
        child = self.again(self.h, SIGNED_OUT, step=60)
        self.assertEqual(len(self.h.records()), 2)
        self.assertEqual((child["category"], child["state"]), ("terminal_auth", "waiting_backoff"))

    def test_a_permission_refusal_is_never_taken_up(self):
        for error in (REFUSED_403, EXPIRED_403):
            with self.subTest(error=error):
                self.h = self.fresh()
                plug = self.taken_up(error)
                self.assertEqual(self.h.records(), [])
                self.assertNotIn((JournalCode.ACTED, Point.ADMISSION, Alternative.ADMIT), self.journal(plug))


class ShadowNeverActsTests(SignInCase):
    def test_watched_it_journals_what_it_would_have_done_and_takes_nothing_up(self):
        plug = self.taken_up(state="shadow")
        self.assertEqual(self.h.records(), [])
        self.assertIn((JournalCode.WOULD_HAVE, Point.ADMISSION, Alternative.ADMIT), self.journal(plug))
        self.assertEqual(self.spends(plug), [])


class SpendBeforeSendTests(SignInCase):
    def test_the_unit_is_spent_before_the_continuation_goes(self):
        plug = self.taken_up()
        key = self.h.record()["interruption_id"]
        seen = []
        self.h.backend.on_send = lambda thread, prompt: seen.append(self.spends(plug))
        self.h.tick(advance=FIRST)
        self.assertEqual(seen, [[(CAP, T1, key)]])


class CeilingTests(SignInCase):
    def test_past_its_ceiling_nothing_is_taken_up(self):
        plug = self.armed()
        self.fill(plug, SIGN_IN_RETRY.ceilings.per_day, lambda index: "0a1b2c3d-0002-7000-8000-%012x" % index,
                  at=self.h.now - 3600)
        self.failing(SIGNED_OUT)
        self.h.tick()
        self.assertEqual(self.h.records(), [])
        self.assertIn((JournalCode.CEILING, Point.ADMISSION, Alternative.ADMIT), self.journal(plug))


class TripwireTests(SignInCase):
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
        self.failing(SIGNED_OUT)
        with patch.object(SignInRetry, "admission", side_effect=RuntimeError("boom")):
            self.h.tick()
        self.assertEqual(plug.runtime.state.arming()[CAP]["reason"], OffReason.HOOK_EXCEPTION)
        self.assertEqual(self.h.records(), [])


class PolicyTests(SignInCase):
    def test_not_allowed_it_reads_off_and_cannot_be_turned_on(self):
        plug = self.armed()
        self.policy = policy.Policy(allowed=frozenset({"capacity_retry"}))
        plug.runtime.states(fresh=True)
        self.failing(SIGNED_OUT)
        self.h.tick()
        self.assertEqual(self.h.records(), [])
        result = plug.runtime.arming.arm(CAP, state="armed", revision=1, generation=plug.runtime.state.meta()
                                         ["generation"], acknowledged_version=ac.ENGINE, actor=Actor.DASHBOARD)
        self.assertEqual(result["refusal"], Refusal.NOT_ALLOWED_BY_POLICY)


class McpTests(SignInCase):
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
    def test_once_a_task_and_only_a_sign_in_failure(self):
        code = SignInRetry(None)
        facts = {"category": "terminal_auth", "chain": None}
        self.assertIs(code.admission(facts), Alternative.ADMIT)
        self.assertIs(code.admission(dict(facts, chain={"category": "network_transient"})), Alternative.ADMIT)
        self.assertIs(code.admission(dict(facts, chain={"category": "terminal_auth"})), DEFER)
        self.assertIs(code.admission(dict(facts, chain="not a chain")), DEFER)
        self.assertIs(code.admission(dict(facts, category="terminal_failure")), DEFER)
        self.assertIs(code.gate("known_failure", {"category": "terminal_auth"}, {}), Alternative.ADMIT)
        self.assertIs(code.gate("known_failure", {"category": "unknown"}, {}), DEFER)
        self.assertIs(code.gate("usage", {"category": "terminal_auth"}, {}), DEFER)

    def test_it_names_no_sign_in_file_route_or_token_of_codexs(self):
        """It never reads or changes Codex's sign-in: its code names no auth file, no login or logout
        route and no token refresh, opens nothing and calls no app-server method of its own."""
        source = inspect.getsource(SignInRetry).lower()
        for word in ("auth.json", "login", "logout", "authtokens", "account/", "open(", "codex_home",
                     "subprocess", "protocol"):
            self.assertNotIn(word, source)
        self.assertNotIn(CAP, protocol.CAPABILITY_METHODS)
        self.assertNotIn("protocol", vars(admitted))


if __name__ == "__main__":
    unittest.main()
