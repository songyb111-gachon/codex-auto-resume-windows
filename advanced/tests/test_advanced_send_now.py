"""Send now (v0.6.14, stage 3b): a person's request, in the Dashboard, that one waiting recovery go at
the watcher's next look - SEND_NOW at P7, and the claim that uses it.

Held against the shipped definition and statement and against core's own engine, store and
simulated Codex home (takingcase.py): the request is refused off, watched, under each policy key and
for an id of the wrong shape; armed, a waiting recovery it names goes at the next look, paid with one
unit, and the request is used; one not used lapses after fifteen minutes, and one made before the
capability last moved - turned off and on again, or read down by ForceShadow - passes nothing; the
claim uses it once; and its paid send gone unknown turns it off. No MCP tool reaches it.

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from takingcase import TakingCase  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Alternative, Point  # noqa: E402
from codex_auto_resume_advanced import policy, surfaces  # noqa: E402
from codex_auto_resume_advanced.control import sendnow  # noqa: E402
from codex_auto_resume_advanced.control.sendnow import LIFETIME, SendNow  # noqa: E402
from codex_auto_resume_advanced.registry import SEND_NOW  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (Actor, ArmingState, JournalCode, McpTool,  # noqa: E402
                                                   OffReason, OverrideKind, Refusal)
from test_engine import T1  # noqa: E402
from test_plug_points import OVERLOADED  # noqa: E402

CAP = "send_now"


class SendNowCase(TakingCase):
    DEFINITION = SEND_NOW

    def setUp(self):
        super().setUp()
        woken = patch.object(sendnow, "wake", side_effect=lambda paths: self.woken.append(paths) or True)
        self.woken = []
        woken.start()
        self.addCleanup(woken.stop)

    def waiting(self, h=None):
        """A temporary failure, registered and waiting for its retry."""
        h = h or self.h
        self.failing(OVERLOADED, h)
        h.tick()
        row = h.record()
        self.assertEqual(row["state"], "waiting_backoff")
        self.assertGreater(row["next_retry_at"], h.now + 1)
        return row

    def ask(self, plug, key):
        return surfaces.answer(plug.runtime, "bridge", {"command": "advanced-send-now",
                                                        "argument": {"interruption_id": key}})

    def requests(self, plug):
        with plug.runtime.state._read() as connection:
            return [tuple(row) for row in connection.execute(
                "SELECT interruption_id, kind, used_at IS NULL FROM overrides WHERE capability=?", (CAP,))]


class RequestTests(SendNowCase):
    def test_refused_off_watched_under_each_policy_key_and_for_a_bad_id(self):
        plug = self.advanced()
        self.assertEqual(self.ask(plug, ac.KEY)["refusal"], Refusal.NOT_ON, "off")
        self.arm(plug, state="shadow")
        self.assertEqual(self.ask(plug, ac.KEY)["refusal"], Refusal.NOT_ON, "watched")
        self.arm(plug)
        for given in (policy.Policy(forbid=True), policy.Policy(allowed=frozenset({"capacity_retry"})),
                      policy.Policy(force_shadow=True)):
            with self.subTest(given):
                self.policy = given
                self.assertEqual(self.ask(plug, ac.KEY)["refusal"], Refusal.NOT_ON)
        self.policy = policy.NONE
        for key in ("A" * 64, "a" * 63, None, 7, "../" + "a" * 61):
            with self.subTest(key=key):
                self.assertEqual(self.ask(plug, key)["refusal"], Refusal.INVALID_REQUEST)
        self.assertEqual(surfaces.answer(plug.runtime, "bridge", {"command": "advanced-send-now", "argument": {
            "interruption_id": ac.KEY, "now": True}})["refusal"], Refusal.INVALID_REQUEST)
        self.assertEqual(self.requests(plug), [])
        self.assertEqual(self.woken, [])

    def test_on_it_is_one_request_that_lapses_after_fifteen_minutes_and_wakes_the_watcher(self):
        plug = self.advanced()
        self.arm(plug)
        found = self.ask(plug, ac.KEY)
        self.assertEqual(found, {"done": True, "refusal": None, "expires_at": self.h.now + LIFETIME})
        self.assertTrue(self.ask(plug, ac.KEY)["done"], "a second click renews it")
        self.assertEqual(self.requests(plug), [(ac.KEY, OverrideKind.FORCE_ONCE, 1)])
        self.assertEqual(len(self.woken), 2)
        self.assertIn(("sendnow.requested", None, None), self.journal(plug))
        code = ac.code_of(plug.runtime, CAP)
        record = {"interruption_id": ac.KEY, "state": "waiting_backoff"}
        self.h.now += LIFETIME - 1
        self.assertIs(code.schedule(record, self.h.now), Alternative.SEND_NOW)
        self.h.now += 1
        self.assertIs(code.schedule(record, self.h.now), DEFER, "lapsed")

    def test_only_for_a_waiting_record_with_a_request_made_since_it_last_moved(self):
        plug = self.advanced()
        self.arm(plug)
        self.ask(plug, ac.KEY)
        code = ac.code_of(plug.runtime, CAP)
        for state, answer in (("waiting_backoff", Alternative.SEND_NOW), ("waiting_reset", Alternative.SEND_NOW),
                              ("submission_unknown", DEFER), ("queued", DEFER), ("recovered", DEFER)):
            with self.subTest(state):
                self.assertIs(code.schedule({"interruption_id": ac.KEY, "state": state}, self.h.now), answer)
        self.assertIs(code.schedule({"interruption_id": "b" * 64, "state": "waiting_backoff"}, self.h.now), DEFER)
        # Turned off and on again within the fifteen minutes: the request is from before.
        self.h.now += 10
        plug.runtime.arming.disarm(CAP, actor=Actor.TRAY)
        self.h.now += 10
        self.arm(plug)
        self.assertIs(code.schedule({"interruption_id": ac.KEY, "state": "waiting_backoff"}, self.h.now), DEFER)

    def test_read_down_by_force_shadow_the_sweep_voids_it_and_lifting_the_policy_passes_nothing(self):
        plug = self.advanced()
        self.arm(plug)
        self.ask(plug, ac.KEY)
        self.policy = policy.Policy(force_shadow=True)
        plug.runtime.tick(self.h.engine.store)
        self.assertEqual(self.requests(plug), [(ac.KEY, OverrideKind.FORCE_ONCE, 0)], "closed by the sweep")
        self.policy = policy.NONE
        plug.runtime.states(fresh=True)
        code = ac.code_of(plug.runtime, CAP)
        self.assertIs(code.schedule({"interruption_id": ac.KEY, "state": "waiting_backoff"}, self.h.now), DEFER)

    def test_no_mcp_tool_reaches_it(self):
        plug = self.armed()
        tools = {tool["name"] for tool in surfaces.mcp(plug.runtime, {"request": "tools"})["tools"]}
        self.assertEqual(tools, set(McpTool))
        for tool in tools:
            self.assertNotIn("send", tool)
        self.assertIs(surfaces.mcp(plug.runtime, {"request": "call", "tool": "advanced-send-now",
                                                  "arguments": {"interruption_id": ac.KEY}}), DEFER)


class ArmedTests(SendNowCase):
    def test_a_waiting_recovery_it_names_goes_at_the_next_look_and_pays_one_unit(self):
        plug = self.armed()
        row = self.waiting()
        key = row["interruption_id"]
        self.h.tick(advance=1)
        self.assert_no_send()
        self.assertTrue(self.ask(plug, key)["done"])
        self.h.tick(advance=1)
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertLess(self.h.now, row["next_retry_at"], "before its retry's wait was over")
        self.assertEqual(self.spends(plug), [(CAP, T1, key)])
        self.assertEqual(self.requests(plug), [(key, OverrideKind.FORCE_ONCE, 0)], "used by the claim")
        self.assertIn((JournalCode.ACTED, Point.SCHEDULE, Alternative.SEND_NOW), self.journal(plug))
        self.follow()
        self.assertEqual(self.h.record()["state"], "recovered")

    def test_off_or_never_asked_it_waits_for_its_schedule(self):
        for armed in (False, True):
            with self.subTest(armed=armed):
                h = self.fresh()
                plug = self.armed(h) if armed else self.advanced(h)
                if not armed:
                    self.plugged(plug, h)
                self.waiting(h)
                h.tick(advance=1)
                self.assertEqual(h.backend.send_calls, [])

    def test_the_claim_uses_a_request_once_and_holds_a_second(self):
        plug = self.armed()
        row = dict(self.waiting())
        runtime = plug.runtime
        self.assertTrue(self.ask(plug, row["interruption_id"])["done"])
        with self.h.store._transaction() as connection:
            self.assertIs(runtime.ledger.claim(connection, row, self.h.now, {CAP: {Alternative.SEND_NOW}}), DEFER)
        with self.h.store._transaction() as connection:
            self.assertIs(runtime.ledger.claim(connection, row, self.h.now + 1, {CAP: {Alternative.SEND_NOW}}),
                          Alternative.HOLD, "used")
        self.h.now += LIFETIME
        self.assertTrue(self.ask(plug, row["interruption_id"])["done"])
        self.h.now += LIFETIME
        with self.h.store._transaction() as connection:
            self.assertIs(runtime.ledger.claim(connection, row, self.h.now, {CAP: {Alternative.SEND_NOW}}),
                          Alternative.HOLD, "lapsed")

    def test_its_paid_send_gone_unknown_turns_it_off(self):
        plug = self.armed()
        key = self.waiting()["interruption_id"]
        self.ask(plug, key)
        self.h.backend.default_outcome = "unknown"
        self.h.tick(advance=1)
        self.assertEqual(self.h.record()["state"], "submission_unknown")
        stored = plug.runtime.state.arming()[CAP]
        self.assertEqual((stored["state"], stored["reason"]), (ArmingState.OFF, OffReason.SUBMISSION_UNKNOWN))


class CodeTests(unittest.TestCase):
    class Scoped:
        def __init__(self, request, since, now):
            self._request, self._since, self.at = request, since, now

        def now(self):
            return self.at

        def request(self, key):
            if isinstance(self._request, Exception):
                raise self._request
            return self._request

        def since(self):
            return self._since

    def code(self, request, since=100.0, now=500.0):
        made = SendNow(None)
        made.bind(self.Scoped(request, since, now))
        return made

    def test_fail_closed(self):
        record = {"interruption_id": ac.KEY, "state": "waiting_backoff"}
        good = {"kind": OverrideKind.FORCE_ONCE, "created_at": 200.0, "used_at": None}
        self.assertIs(self.code(good).schedule(record, 0), Alternative.SEND_NOW)
        for request, since in ((None, 100.0), (dict(good, used_at=300.0), 100.0), (dict(good, kind="early_reset"), 100.0),
                               (good, 250.0), (good, None), (RuntimeError("locked"), 100.0),
                               (dict(good, created_at=500.0 - LIFETIME), 100.0)):
            with self.subTest(request=request, since=since):
                self.assertIs(self.code(request, since).schedule(record, 0), DEFER)
        self.assertIs(SendNow(None).schedule(record, 0), DEFER, "unbound")


if __name__ == "__main__":
    unittest.main()
