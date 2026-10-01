"""The goal continuation: a goal paused by a usage limit, set active again where the app does not
hold its conversation (P16), held beside while it carries a conversation on (P3), and set active
before the queued continuation only where M2b passed (P5).

Held against the shipped definition and the shipped statement, and against core's own engine,
store and simulated Codex home (tests/codexsim.py), with a goals database of the tests' own beside
it, laid out as Codex lays out goals_1.sqlite: off until armed; watched, it only journals; armed,
core carries out its route for a conversation the app does not hold - every gate a send passes, the
one claim paid for first, the pre-send look, the route once inside the launch guard - and the route
sets the existing goal active through a fake app server with the thread and the status alone, never
creating a goal and never touching its words; once the app opens the conversation the standard
continuation waits while the goal carries it on, and the goal's own turn supersedes the record; on a
conversation the app holds, the standard queue route stands unless M2b passed; the ceilings, the
tripwires and re-arming; M2's warning confirmed; MCP cannot arm it; and with the package gone the
standard edition sends only what it would.

No test opens a real Codex or reads the real Codex home: the capability is pointed at the harness's
home and its session speaks to a fake app server.

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from advancedcase import ENGINE  # noqa: E402
from codex_auto_resume import config  # noqa: E402
from codex_auto_resume.codex import transport  # noqa: E402
from codex_auto_resume.codex.errors import AdapterError  # noqa: E402
from codex_auto_resume.domain import ids  # noqa: E402
from codex_auto_resume.domain.plug import BACKEND, DEFER, Alternative, Point  # noqa: E402
from codex_auto_resume.engine import Engine  # noqa: E402
from codex_auto_resume.machine import WAITING  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402
from codex_auto_resume.win.kernel import NO_WINDOW  # noqa: E402
from codex_auto_resume_advanced import statement  # noqa: E402
from codex_auto_resume_advanced.codex import goals, inuse, protocol  # noqa: E402
from codex_auto_resume_advanced.engine import goal as goal_module  # noqa: E402
from codex_auto_resume_advanced.engine.goal import GoalContinuation, m2b_passed  # noqa: E402
from codex_auto_resume_advanced.registry import GOAL_CONTINUATION, MARKER_FREE, Registry  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (Actor, ArmingState, ArmingWarning,  # noqa: E402
                                                   GoalStatus, JournalCode, Measurement, OffReason,
                                                   Verdict)
from test_advanced_marker_free import FakeAppServer, FakeBackend  # noqa: E402
from test_engine import T1  # noqa: E402
from test_plug_points import PluggedCase  # noqa: E402

CAP = "goal_continuation"
GOAL_ID = "0a1b2c3d-0001-7000-8000-00000000900d"
# The goal's words, as a person wrote them: a fixture's, and never anything this product may read.
OBJECTIVE = "Finish the migration and keep every test green"
# The protocol's words for a goal's status, where the database's differ (ThreadGoalStatus).
PROTOCOL_STATUS = {"usage_limited": "usageLimited", "budget_limited": "budgetLimited"}

GOALS_TABLE = ("CREATE TABLE thread_goals (thread_id TEXT PRIMARY KEY NOT NULL, goal_id TEXT NOT NULL, "
               "objective TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('active', 'paused', "
               "'blocked', 'usage_limited', 'budget_limited', 'complete')), token_budget INTEGER, "
               "tokens_used INTEGER NOT NULL DEFAULT 0, time_used_seconds INTEGER NOT NULL DEFAULT 0, "
               "created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL)")


def goals_db(root, *, name="goals_1.sqlite", table=GOALS_TABLE) -> Path:
    path = Path(root) / name
    with contextlib.closing(sqlite3.connect(path)) as db:
        db.execute(table)
        db.commit()
    return path


def set_goal(root, thread_id, status, *, goal_id=GOAL_ID, objective=OBJECTIVE, at=1_000, name="goals_1.sqlite"):
    with contextlib.closing(sqlite3.connect(Path(root) / name)) as db:
        db.execute("INSERT OR REPLACE INTO thread_goals (thread_id, goal_id, objective, status, "
                   "created_at_ms, updated_at_ms) VALUES (?,?,?,?,?,?)",
                   (thread_id, goal_id, objective, status, at, at))
        db.commit()


def goal_row(root, thread_id, name="goals_1.sqlite"):
    with contextlib.closing(sqlite3.connect(Path(root) / name)) as db:
        return db.execute("SELECT goal_id, objective, status FROM thread_goals WHERE thread_id=?",
                          (thread_id,)).fetchone()


class GoalAppServer(FakeAppServer):
    """`codex app-server --stdio` as the goal continuation meets it: thread/goal/set updates the
    goal in the harness's goals database exactly as Codex's does - an existing goal only, refused
    where there is none - and answers with the goal, its words included, as Codex's does. `refuse`
    answers the set with Codex's error; `ignore` answers it as done and changes nothing; `on_set` is
    told of each set as it arrives, and `on_start` of each session as it starts - its initialize.
    thread/queue/add is the marker-free fake's."""

    def __init__(self, h, *, refuse=False, ignore=False, on_set=None, on_start=None, **options):
        super().__init__(h, **options)
        self.refuse_set, self.ignore_set, self.on_set, self.on_start = refuse, ignore, on_set, on_start

    def receive(self, message):
        if message.get("method") == "initialize" and self.on_start:
            self.on_start()
        if message.get("method") != "thread/goal/set" or message.get("id") is None:
            return super().receive(message)
        self.received.append(message)
        ident, params = message["id"], message.get("params") or {}
        if self.on_set:
            self.on_set(params)
        found = goal_row(self.h.home.root, params.get("threadId"))
        if self.refuse_set or found is None:
            self.send({"id": ident, "error": {"code": -32600, "message": "cannot update goal: no goal exists"}})
            return
        status = params.get("status")
        if not self.ignore_set:
            database = {"active": "active", "usageLimited": "usage_limited"}.get(status, status)
            with contextlib.closing(sqlite3.connect(self.h.home.root / "goals_1.sqlite")) as db:
                db.execute("UPDATE thread_goals SET status=?, updated_at_ms=updated_at_ms+1 WHERE thread_id=?",
                           (database, params["threadId"]))
                db.commit()
        goal_id, objective, stored = goal_row(self.h.home.root, params["threadId"])
        self.send({"id": ident, "result": {"goal": {"threadId": params["threadId"], "objective": objective,
                                                    "status": PROTOCOL_STATUS.get(stored, stored)}}})

    def sets(self):
        return [message["params"] for message in self.received if message.get("method") == "thread/goal/set"]

    def methods(self):
        return [message.get("method") for message in self.received if message.get("id") is not None
                and message.get("method") != "initialize"]


class GoalCase(PluggedCase):
    """The engine's own harness, with an advanced plug that ships only this capability, its shipped
    statement, and a view and measurements on which it arms with no warning: loaded_state_detection
    COMPATIBLE on ENGINE, M2 passed on ENGINE. The conversation T1 has a goal, paused by the usage
    limit that interrupted it."""

    registry = (GOAL_CONTINUATION,)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.where = Path(temporary.name)
        self.compat = ac.view(state="COMPATIBLE", capability="loaded_state_detection", version=ENGINE)
        self.measured = {Measurement.M2: (Verdict.PASS, ENGINE)}
        super().setUp()
        goals_db(self.h.home.root)
        set_goal(self.h.home.root, T1, "usage_limited")

    def advanced(self, h=None):
        h = h or self.h
        made = ac.advanced.AdvancedPlug(
            config.Paths(self.where / "home"), registry=Registry(self.registry), clock=lambda: h.now,
            policy=lambda: ac.policy.NONE, view=lambda: self.compat, measured=lambda: self.measured,
            catalogs=statement.CATALOGS)
        self.addCleanup(lambda: made._runtime and made._runtime.state.close())
        return made

    def code(self, plug, h=None) -> GoalContinuation:
        """The capability's code, pointed at the harness's Codex home, clock, view and measurements."""
        h = h or self.h
        made = plug.runtime._code_of(GOAL_CONTINUATION)
        made._home, made.clock = h.home.root, (lambda: h.now)
        made._view, made._measured = (lambda: self.compat), (lambda: self.measured)
        return made

    def arm(self, plug, capability=CAP, state="armed", **changes):
        runtime = plug.runtime
        request = dict(state=state, revision=runtime.registry.get(capability).revision,
                       generation=runtime.state.meta()["generation"], acknowledged_version=ENGINE,
                       actor=Actor.DASHBOARD)
        request.update(changes)
        result = runtime.arming.arm(capability, **request)
        self.assertTrue(result["done"], result)
        runtime.states(fresh=True)
        return result

    def server(self, h=None, **options):
        h = h or self.h
        server = GoalAppServer(h, **options)
        for target, name, value in (
                (protocol.S, "Popen", server.popen),
                (GoalContinuation, "_session",
                 lambda _self: protocol.Session(FakeBackend(h.home.root), capability=CAP))):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        return server

    def armed(self, h=None, state="armed", loaded=False, **server):
        """Armed (or watched), with a usage limit due in T1 - held by the app or not."""
        h = h or self.h
        self.ready_after_reset(h, loaded=loaded)
        plug = self.advanced(h)
        self.code(plug, h)
        self.arm(plug, state=state)
        fake = self.server(h, **server)
        self.plugged(plug, h)
        return plug, fake

    def spends(self, plug):
        with contextlib.closing(sqlite3.connect(plug.runtime.state.path)) as connection:
            return connection.execute("SELECT capability, thread_id, interruption_id FROM spend").fetchall()

    def journal(self, plug, capability=CAP):
        return [(line["code"], line["point"], line["answer"])
                for line in plug.runtime.state.journal(capability=capability)]

    def status(self, h=None):
        return goal_row((h or self.h).home.root, T1)[2]


class OffTests(GoalCase):
    def test_off_by_default_it_is_the_standard_edition(self):
        """Nothing armed: a conversation the app does not hold waits for it, one it holds gets the
        marker through `codex queue`, no app server is opened and the goal is left as it was."""
        self.ready_after_reset(loaded=False)
        plug = self.advanced()
        self.code(plug)
        fake = self.server()
        self.plugged(plug)
        self.h.tick()
        self.assertEqual((self.h.record()["state"], self.h.record()["last_error"]),
                         ("waiting_for_loaded_thread", "notLoaded"))
        self.h.backend.loaded_map[T1] = "loaded"
        self.h.tick(advance=61)
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertTrue(self.prompt().endswith(self.h.record()["marker"]))
        self.assertEqual((fake.started, fake.received), ([], []))
        self.assertEqual(self.status(), "usage_limited")
        self.assertIs(plug.unloaded({"interruption_id": ac.KEY, "thread_id": T1, "category": "usage_limit"}),
                      DEFER)


class UnloadedTests(GoalCase):
    def test_a_conversation_not_held_has_its_goal_set_active_and_nothing_is_sent(self):
        plug, fake = self.armed()
        key = self.h.record()["interruption_id"]
        self.h.tick()
        self.assert_no_send()
        self.assertEqual(fake.methods(), ["thread/goal/set"])
        (sent,) = fake.sets()
        # The thread and the status, and nothing else: never the goal's words, never a new goal.
        self.assertEqual(sent, {"threadId": T1, "status": "active"})
        self.assertEqual(goal_row(self.h.home.root, T1), (GOAL_ID, OBJECTIVE, "active"))
        self.assertEqual([options["creationflags"] for options in fake.started], [NO_WINDOW])
        self.assertEqual(self.h.home.queued(T1), [])
        row = self.h.record()
        self.assertEqual((row["state"], row["last_error"], row["submitted_at"], row["attempt_count"]),
                         ("waiting_retry", "notLoaded", None, 1))
        self.assertEqual(self.spends(plug), [(CAP, T1, key)])
        self.assertIn((JournalCode.ACTED, Point.UNLOADED, Point.UNLOADED), self.journal(plug))

    def test_once_the_app_opens_it_the_goal_carries_it_on_and_its_turn_supersedes_the_record(self):
        plug, fake = self.armed()
        self.h.tick()
        self.h.tick(advance=61)
        self.assertEqual(self.h.record()["last_error"], "notLoaded", "resumed once, then it waits")
        self.assertEqual(len(fake.sets()), 1)
        # The app opens the conversation: while the goal is active the standard continuation waits.
        self.h.backend.loaded_map[T1] = "loaded"
        self.h.tick(advance=61)
        row = self.h.record()
        self.assertEqual(json.loads(row["gate_eval"])["thread_available"], ["WAIT", "held"])
        self.assert_no_send()
        self.assertIn((JournalCode.ACTED, Point.GATES, Alternative.HOLD), self.journal(plug))
        # Codex carries the goal on, and that turn supersedes the record by core's own rule.
        self.h.home.add_turn(T1, status="inProgress")
        self.h.tick(advance=61)
        row = self.h.record()
        self.assertEqual((row["state"], row["last_error"]), ("superseded_by_user", "later_turn_exists"))
        for _ in range(6):
            self.h.tick(advance=900)
        self.assert_no_send()
        self.assertEqual(len(fake.sets()), 1)

    def test_a_goal_that_does_not_carry_it_on_is_waited_for_at_most_ten_minutes(self):
        plug, fake = self.armed()
        self.h.tick()
        claimed = self.h.record()["last_claim_at"]
        self.h.backend.loaded_map[T1] = "loaded"
        self.h.tick(advance=61)
        first_seen = self.h.now
        while not self.h.backend.send_calls and self.h.now < first_seen + 3600:
            self.h.tick(advance=61)
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertGreaterEqual(self.h.now, first_seen + goal_module.HOLD_SECONDS)
        self.assertGreaterEqual(self.h.now, claimed + 900, "and the claim's cooldown")
        self.assertTrue(self.prompt().endswith(self.h.record()["marker"]))

    def test_only_a_goal_paused_by_the_usage_limit_is_resumed_and_none_is_ever_made(self):
        for status in ("paused", "blocked", "budget_limited", "complete", "active", None):
            with self.subTest(status=status):
                h = self.fresh()
                goals_db(h.home.root)
                if status is not None:
                    set_goal(h.home.root, T1, status)
                plug, fake = self.armed(h)
                h.tick()
                self.assertEqual((fake.started, fake.received), ([], []))
                self.assertEqual((h.record()["state"], h.record()["last_error"]),
                                 ("waiting_for_loaded_thread", "notLoaded"))
                self.assertEqual(goal_row(h.home.root, T1)[2] if status else None, status)
                self.assertEqual(self.spends(plug), [])

    def test_a_goals_database_it_cannot_read_is_the_standard_editions_wait(self):
        def none(root):
            (root / "goals_1.sqlite").unlink()

        def moved_on(root):
            none(root)
            goals_db(root, table="CREATE TABLE thread_goals (thread_id TEXT, objective TEXT, state TEXT)")

        def unknown_status(root):
            none(root)
            goals_db(root, table="CREATE TABLE thread_goals (thread_id TEXT, goal_id TEXT, objective TEXT, "
                                 "status TEXT, updated_at_ms INTEGER)")
            with contextlib.closing(sqlite3.connect(root / "goals_1.sqlite")) as db:
                db.execute("INSERT INTO thread_goals VALUES (?,?,?,?,?)", (T1, GOAL_ID, OBJECTIVE, "resting", 1))
                db.commit()
        for name, spoil in {"none": none, "moved on": moved_on, "a status it does not know": unknown_status}.items():
            with self.subTest(name):
                h = self.fresh()
                goals_db(h.home.root)
                set_goal(h.home.root, T1, "usage_limited")
                spoil(h.home.root)
                plug, fake = self.armed(h)
                h.tick()
                self.assertEqual(fake.received, [])
                self.assertEqual(h.record()["last_error"], "notLoaded")

    def test_a_usage_limit_only(self):
        """A transient failure's conversation is not its business, goal or no goal."""
        self.h.home.fail_transient(T1)
        plug = self.advanced()
        self.code(plug)
        self.arm(plug)
        fake = self.server()
        self.plugged(plug)
        for _ in range(4):
            self.h.tick(advance=900)
        self.assertEqual(fake.received, [])
        self.assertEqual(self.status(), "usage_limited")


class RaceTests(GoalCase):
    """The app opens the conversation while the route's session is starting - after core last
    found it not held, before the set. M2 found a goal set while the app holds the conversation
    is not seen, so the set is not made: core's own look, asked again once the session is up,
    says the app holds it, the goal is left paused, the claim is given back, and the standard
    continuation follows as it would with the capability off, once the claim's cooldown is past.
    Nothing is left an uncertain submission, and the capability stays on."""

    def opened_while_starting(self, **server):
        def app_opens_it():
            self.h.backend.loaded_map[T1] = "loaded"
        plug, fake = self.armed(on_start=app_opens_it, **server)
        self.h.tick()
        self.assertEqual(fake.sets(), [], "no goal is set on a conversation the app holds")
        self.assertEqual(self.status(), "usage_limited")
        row = self.h.record()
        self.assertIn(row["state"], WAITING)
        self.assertEqual((row["last_error"], row["submitted_at"], row["chain_continuations"]),
                         ("released_before_send", None, 0))
        started = self.h.now
        while not self.h.backend.send_calls and self.h.now < started + 3600:
            self.h.tick(advance=61)
        self.assertLessEqual(self.h.now - started, 900 + 2 * 61, "the claim's cooldown, and no more")
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertTrue(self.prompt().endswith(self.h.record()["marker"]))
        self.assertEqual(plug.runtime.state.arming()[CAP]["state"], ArmingState.ARMED)
        self.assertEqual(fake.sets(), [])

    def test_the_app_opening_it_while_the_session_starts_leaves_the_goal_alone(self):
        self.opened_while_starting()

    def test_even_where_codex_would_have_answered_a_set_it_did_not_apply(self):
        """Where a set on a conversation the app holds would be answered and not applied, it was
        an uncertain submission - never continued, and the capability off. It is not made."""
        self.opened_while_starting(ignore=True)


class LoadedTests(GoalCase):
    """A conversation the app holds: the standard queue route, unless M2b passed for this Codex."""

    def test_without_m2b_the_standard_queue_route_stands_and_the_goal_is_left_alone(self):
        for measured in ({}, {Measurement.M2B: (Verdict.FAIL, ENGINE)},
                         {Measurement.M2B: (Verdict.PASS, "codex-cli 0.1.0")}):
            with self.subTest(measured=measured):
                h = self.fresh()
                goals_db(h.home.root)
                set_goal(h.home.root, T1, "usage_limited")
                self.measured = dict(measured, **{Measurement.M2: (Verdict.PASS, ENGINE)})
                plug, fake = self.armed(h, loaded=True)
                h.tick()
                self.assertEqual(len(h.backend.send_calls), 1)
                self.assertTrue(self.prompt(h).endswith(h.record()["marker"]))
                self.assertEqual(fake.received, [])
                self.assertEqual(goal_row(h.home.root, T1)[2], "usage_limited")

    def test_with_m2b_passed_the_goal_is_set_active_before_the_continuation_it_queues(self):
        self.measured[Measurement.M2B] = (Verdict.PASS, ENGINE)
        plug, fake = self.armed(loaded=True)
        key = self.h.record()["interruption_id"]
        self.h.tick()
        self.assert_no_send()
        self.assertEqual(fake.methods(), ["thread/goal/set", "thread/queue/add"])
        self.assertEqual(fake.sets(), [{"threadId": T1, "status": "active"}])
        (add,) = fake.adds()
        self.assertTrue(add["input"][0]["text"].endswith(self.h.record()["marker"]))
        self.assertNotIn("clientUserMessageId", add)
        self.assertEqual(self.status(), "active")
        self.follow()
        self.assertEqual(self.h.record()["state"], "recovered")
        self.assertEqual(self.spends(plug), [(CAP, T1, key)])

    def test_with_the_marker_free_continuation_on_too_it_goes_under_the_derived_id(self):
        """Its channel comes first at P5, and carries P15's client id: no marker, the id proves it."""
        self.registry = (GOAL_CONTINUATION, MARKER_FREE)
        self.compat = {"status": "ok", "engine": {"found": True, "version": ENGINE}, "capabilities": {
            "loaded_state_detection": {"state": "COMPATIBLE", "reason": "local_checks_passed"},
            "recovery_turn_tracking": {"state": "COMPATIBLE", "reason": "local_checks_passed"}}}
        self.measured.update({Measurement.M2B: (Verdict.PASS, ENGINE), Measurement.M7: (Verdict.PASS, ENGINE)})
        self.ready_after_reset(loaded=True)
        plug = self.advanced()
        self.code(plug)
        self.arm(plug)
        self.arm(plug, capability="marker_free_continuation")
        fake = self.server()
        self.plugged(plug)
        key = self.h.record()["interruption_id"]
        self.h.tick()
        self.assert_no_send()
        (add,) = fake.adds()
        self.assertEqual(add["clientUserMessageId"], ids.continuation_client_id(key))
        self.assertNotIn(ids.MARKER_PREFIX, add["input"][0]["text"])
        self.assertEqual(self.status(), "active")
        self.follow()
        self.assertEqual(self.h.record()["state"], "recovered")
        self.assertEqual(sorted(self.spends(plug)),
                         sorted([(CAP, T1, key), ("marker_free_continuation", T1, key)]))


class ShadowNeverActsTests(GoalCase):
    def test_watched_it_journals_what_it_would_have_done_and_the_goal_is_left_alone(self):
        """ShadowNeverActs: asked at P16 and P3, its answers written as what it would have done, none
        taken - the conversation waits for the app, no app server is opened, the goal stays paused
        and nothing is spent; once the app opens it, core sends as the standard edition does."""
        plug, fake = self.armed(state="shadow")
        self.h.tick()
        self.assertEqual((self.h.record()["state"], self.h.record()["last_error"]),
                         ("waiting_for_loaded_thread", "notLoaded"))
        self.assertEqual((fake.started, fake.received), ([], []))
        self.assertEqual(self.status(), "usage_limited")
        codes = {code for code, _point, _answer in self.journal(plug)}
        self.assertIn(JournalCode.WOULD_HAVE, codes)
        self.assertNotIn(JournalCode.ACTED, codes)
        self.assertEqual(self.spends(plug), [])
        set_goal(self.h.home.root, T1, "active")        # watched, a hold is not taken either
        self.h.backend.loaded_map[T1] = "loaded"
        self.h.tick(advance=61)
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertNotIn(JournalCode.ACTED, {code for code, _point, _answer in self.journal(plug)})


class SpendBeforeSendTests(GoalCase):
    def test_the_unit_is_spent_before_the_app_server_is_asked(self):
        seen = []
        plug, fake = self.armed(on_set=lambda params: seen.append(self.spends(plug)))
        key = self.h.record()["interruption_id"]
        self.h.tick()
        self.assertEqual(seen, [[(CAP, T1, key)]], "paid for, once, before the set arrived")

    def test_turned_off_between_its_answer_and_the_claim_nothing_is_asked_of_codex(self):
        """A disarm always wins: the ledger finds it off at the claim and holds it."""
        plug, fake = self.armed()
        ask = ac.advanced.AdvancedPlug.unloaded

        def unloaded(made, record):
            answer = ask(made, record)
            plug.runtime.arming.disarm(CAP, actor=Actor.DASHBOARD)
            return answer
        with patch.object(ac.advanced.AdvancedPlug, "unloaded", unloaded):
            self.h.tick()
        self.assertEqual(fake.received, [])
        self.assertEqual(self.spends(plug), [])
        self.assertEqual(self.status(), "usage_limited")
        self.assertEqual(self.h.record()["attempt_count"], 0)


class CeilingTests(GoalCase):
    def fill(self, plug, thread_of, count):
        with plug.runtime.state._transaction() as connection:
            for index in range(count):
                plug.runtime.state.record_spend(connection, "main", CAP, thread_of(index),
                                                "%064x" % index, self.h.now - 60)

    def test_past_its_conversation_ceiling_it_waits_as_the_standard_edition_does(self):
        plug, fake = self.armed()
        self.fill(plug, lambda index: T1, GOAL_CONTINUATION.ceilings.per_conversation)
        self.h.tick()
        self.assertEqual(fake.received, [])
        self.assertEqual(self.h.record()["last_error"], "notLoaded")
        self.assertIn(JournalCode.CEILING, {code for code, _point, _answer in self.journal(plug)})

    def test_past_its_daily_ceiling_too(self):
        plug, fake = self.armed()
        others = ["0a1b2c3d-0001-7000-8000-%012x" % (index + 16)
                  for index in range(GOAL_CONTINUATION.ceilings.per_day)]
        self.fill(plug, lambda index: others[index], GOAL_CONTINUATION.ceilings.per_day)
        self.h.now += 3601                               # past the global hour, inside the day
        self.h.tick()
        self.assertEqual(fake.received, [])
        self.assertEqual(self.status(), "usage_limited")


class TripwireTests(GoalCase):
    def test_a_resume_it_cannot_confirm_is_held_never_tried_again_and_turns_it_off(self):
        """Codex answered the set as done and the goal does not read back active: nothing proves
        what came of it, so the record is an uncertain submission - never tried again, by either
        route - and the tripwire for a paid send gone submission_unknown turns the capability off."""
        plug, fake = self.armed(ignore=True)
        self.h.tick()
        row = self.h.record()
        self.assertEqual((row["state"], row["last_error"]),
                         ("submission_unknown", "queue_result_unknown_do_not_resend"))
        stored = plug.runtime.state.arming()[CAP]
        self.assertEqual((stored["state"], stored["reason"]), (ArmingState.OFF, OffReason.SUBMISSION_UNKNOWN))
        self.h.backend.loaded_map[T1] = "loaded"
        for _ in range(12):
            self.h.tick(advance=900)
        self.assertEqual(len(fake.sets()), 1)
        self.assert_no_send()

    def test_a_set_codex_refuses_leaving_the_goal_paused_gives_the_claim_back(self):
        """Codex said no and the goal is still paused: nothing will carry the conversation on, so
        nothing was started - the claim is given back and the standard edition's way follows."""
        plug, fake = self.armed(refuse=True)
        self.h.tick()
        row = self.h.record()
        self.assertEqual((row["last_error"], row["submitted_at"]), ("released_before_send", None))
        self.assertEqual(plug.runtime.state.arming()[CAP]["state"], ArmingState.ARMED)
        self.h.backend.loaded_map[T1] = "loaded"
        self.h.tick(advance=901)
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertTrue(self.prompt().endswith(self.h.record()["marker"]))

    def test_a_hook_that_raises_trips_it_off_and_the_conversation_waits_as_standard(self):
        plug, fake = self.armed()
        with patch.object(GoalContinuation, "unloaded", side_effect=RuntimeError("boom")):
            self.h.tick()
        stored = plug.runtime.state.arming()[CAP]
        self.assertEqual((stored["state"], stored["reason"]), (ArmingState.OFF, OffReason.HOOK_EXCEPTION))
        self.assertEqual(self.h.record()["last_error"], "notLoaded")
        self.h.tick(advance=61)
        self.assertEqual(fake.received, [])
        self.assertEqual(self.status(), "usage_limited")

    def test_a_later_send_core_made_alone_going_unknown_leaves_it_on(self):
        """The goal was resumed and read back active: the unit it paid bought that, and it is done.
        The standard continuation of the same record, sent later by `codex queue` with nothing of
        this capability's in it, going unknown is core's uncertain submission - not a send this
        capability paid for, so it is not turned off for it."""
        plug, fake = self.armed()
        self.h.tick()
        self.assertEqual((self.h.record()["state"], self.status()), ("waiting_retry", "active"))
        self.h.backend.loaded_map[T1] = "loaded"
        self.h.backend.outcomes[T1] = "unknown"
        started = self.h.now
        while not self.h.backend.send_calls and self.h.now < started + 7200:
            self.h.tick(advance=61)
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertEqual(self.h.record()["state"], "submission_unknown")
        stored = plug.runtime.state.arming()[CAP]
        self.assertEqual((stored["state"], stored["reason"]), (ArmingState.ARMED, None))
        self.assertEqual(len(self.spends(plug)), 1, "it paid for the route alone")

    def test_re_arming_is_always_possible_after_a_trip(self):
        plug, fake = self.armed(ignore=True)
        self.h.tick()
        self.assertEqual(plug.runtime.state.arming()[CAP]["state"], ArmingState.OFF)
        self.arm(plug)
        self.assertEqual(plug.runtime.state.arming()[CAP]["state"], ArmingState.ARMED)


class WarningTests(GoalCase):
    def test_m2s_failure_is_a_warning_the_person_confirms_never_a_refusal(self):
        self.measured = {Measurement.M2: (Verdict.FAIL, ENGINE)}
        plug = self.advanced()
        shown = plug.runtime.arming.statement(GOAL_CONTINUATION, "en")
        self.assertEqual([item["warning"] for item in shown["warnings"]["items"]],
                         [ArmingWarning.MEASUREMENT_FAILED])
        self.assertEqual(shown["departs_from"], ["0.5", "A2", "A11", "B3", "B4"])
        self.assertTrue(all(field["text"] for field in shown["fields"]))
        self.assertTrue(self.arm(plug, warnings=[ArmingWarning.MEASUREMENT_FAILED])["done"])
        self.assertEqual(plug.runtime.states(fresh=True)[CAP], ArmingState.ARMED)

    def test_as_shipped_it_warns_of_m2_as_the_evidence_says(self):
        from codex_auto_resume_advanced.arming import warnings_for
        from codex_auto_resume_advanced.measured import MEASURED
        self.assertIn(ArmingWarning.MEASUREMENT_FAILED, warnings_for(GOAL_CONTINUATION, self.compat, MEASURED))


class McpTests(GoalCase):
    def test_mcp_cannot_arm_it_and_may_only_read_or_turn_it_off(self):
        """McpCannotArm: a model has list and disarm and nothing that turns a capability on."""
        from codex_auto_resume_advanced import surfaces
        from codex_auto_resume_advanced.vocabulary import McpTool
        plug = self.advanced()
        self.arm(plug)
        runtime = plug.runtime
        tools = {tool["name"] for tool in surfaces.mcp(runtime, {"request": "tools"})["tools"]}
        self.assertLessEqual(tools, set(McpTool))
        refused = runtime.arming.arm(CAP, state="armed", revision=GOAL_CONTINUATION.revision,
                                     generation=runtime.state.meta()["generation"],
                                     acknowledged_version=ENGINE, actor=Actor.MCP)
        self.assertFalse(refused["done"])
        reply = surfaces.mcp(runtime, {"request": "call", "tool": McpTool.DISARM_ADVANCED_CAPABILITY,
                                       "arguments": {"capability": CAP}})
        self.assertIn("data", reply)
        self.assertEqual(runtime.state.arming()[CAP]["state"], ArmingState.OFF)
        for arguments in ({"capability": CAP, "state": "armed"}, {"capability": CAP, "revision": 1}):
            with self.subTest(arguments=arguments):
                self.assertIn("refused", surfaces.mcp(runtime, {
                    "request": "call", "tool": McpTool.DISARM_ADVANCED_CAPABILITY, "arguments": arguments}))
        self.assertEqual(runtime.state.arming()[CAP]["state"], ArmingState.OFF)


class EditionRoundTripTests(GoalCase):
    def test_with_the_package_gone_the_standard_edition_sends_only_what_it_would(self):
        """EditionRoundTrip: armed, it resumed the goal of a conversation the app did not hold. Then
        the package is gone: the standard Store opens the state as it is, and a standard engine -
        NULL plug - on it waits for the app, sends nothing once the goal's own turn has superseded
        the record, and sends the next interruption as the standard edition does, with the marker,
        through `codex queue`."""
        plug, fake = self.armed()
        self.h.tick()
        self.assertEqual(self.status(), "active")
        standard_store = Store(self.h.root)
        self.addCleanup(self.h.store.close)          # the advanced run's, closed last
        (row,) = [record for record in standard_store.all_records() if record["thread_id"] == T1]
        self.assertEqual((row["state"], row["submitted_at"]), ("waiting_retry", None))
        self.h.store = standard_store
        self.h.engine = Engine(standard_store, self.h.source, self.h.backend, clock=lambda: self.h.now,
                               log=lambda *args: self.h.logs.append(args), options=self.h.options,
                               notify=lambda *args: self.h.notifications.append(args))
        self.h.tick(advance=61)
        self.assertEqual(self.h.record()["last_error"], "notLoaded")
        self.h.backend.loaded_map[T1] = "loaded"
        self.h.home.add_turn(T1, status="inProgress")
        self.h.tick(advance=61)
        self.assertEqual(self.h.record()["state"], "superseded_by_user")
        self.h.tick(advance=3600)
        self.assert_no_send()
        self.assertEqual(len(fake.sets()), 1)
        # The next interruption, on another conversation, goes as the standard edition sends one.
        other = "0a1b2c3d-0001-7000-8000-00000000abcd"
        set_goal(self.h.home.root, other, "usage_limited", goal_id="other-goal")
        self.h.home.fail_usage(other, "0a1b2c3d-0001-7000-8000-00000000abce",
                               completed=int(self.h.now) - 10, reset=int(self.h.now) - 5)
        self.h.backend.loaded_map[other] = "loaded"
        self.h.tick()
        self.h.tick(advance=120)
        sent = [call for call in self.h.backend.send_calls if call[0] == other]
        self.assertEqual(len(sent), 1)
        (record,) = [record for record in standard_store.all_records() if record["thread_id"] == other]
        self.assertTrue(sent[0][1].endswith(record["marker"]))
        self.assertEqual(len(fake.sets()), 1)
        self.assertEqual(goal_row(self.h.home.root, other)[2], "usage_limited")


class RouteTests(unittest.TestCase):
    """The route and the channel on their own: what each says of what it did, never raising."""

    class Session:
        def __init__(self, test, *, enter=None, fail=None, then=None):
            self.test, self.enter, self.fail, self.then, self.calls = test, enter, fail, then, []

        def __enter__(self):
            if self.enter:
                raise self.enter
            return self

        def call(self, method, params):
            self.calls.append((method, params))
            if self.then:
                self.then(method, params)
            if self.fail and method in self.fail:
                raise self.fail[method]
            return {"queuedSubmissionId": "0a1b2c3d-0001-7000-8000-0000000000ff"}

        def __exit__(self, *unused):
            return None

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        goals_db(self.root)
        set_goal(self.root, T1, "usage_limited")

    def made(self, session):
        return GoalContinuation(None, session=lambda: session, home=self.root,
                                view=lambda: ac.view(capability="loaded_state_detection"),
                                measured=lambda: {})

    def activate(self, method, params):
        if method == "thread/goal/set":
            set_goal(self.root, T1, "active")

    def test_it_answers_core_at_its_three_points(self):
        made = self.made(self.Session(self))
        record = {"interruption_id": ac.KEY, "thread_id": T1, "category": "usage_limit"}
        self.assertIs(made.unloaded(record), made)
        self.assertIs(made.unloaded(dict(record, category="server_overloaded")), DEFER)
        self.assertIs(made.sender(record, BACKEND), DEFER, "no M2b pass, no channel")
        self.assertIs(made.gate("thread_available", record, {}), DEFER)
        set_goal(self.root, T1, "active")
        self.assertIs(made.gate("thread_available", record, {}), Alternative.HOLD)
        self.assertIs(made.gate("usage", record, {}), DEFER)
        self.assertIs(made.unloaded(record), DEFER, "an active goal is not paused by the limit")

    def test_a_resume_that_reads_back_active_is_accepted(self):
        session = self.Session(self, then=self.activate)
        self.assertEqual(self.made(session).resume(T1), {"outcome": "accepted", "queue_id": None})
        self.assertEqual(session.calls, [("thread/goal/set", {"threadId": T1, "status": "active"})])

    def test_what_is_not_there_to_resume_is_not_started_and_nothing_is_opened(self):
        session = self.Session(self, enter=AssertionError("must not open"))
        for status in ("paused", "active", "complete"):
            with self.subTest(status=status):
                set_goal(self.root, T1, status)
                self.assertEqual(self.made(session).resume(T1)["outcome"], "not_started")
        self.assertEqual(self.made(session).resume("not-a-thread")["outcome"], "not_started")
        other = "0a1b2c3d-0001-7000-8000-000000000077"
        self.assertEqual(self.made(session).resume(other)["outcome"], "not_started", "no goal: none made")

    def test_a_consent_refused_at_the_guard_opens_nothing(self):
        @contextlib.contextmanager
        def refusing():
            yield False
        session = self.Session(self, enter=AssertionError("must not open"))
        self.assertEqual(self.made(session).resume(T1, launch_guard=refusing()),
                         {"outcome": "not_started", "error_code": "queue_consent_refused"})

    def test_no_app_server_is_not_started(self):
        session = self.Session(self, enter=AdapterError("codex_binary_unavailable"))
        self.assertEqual(self.made(session).resume(T1),
                         {"outcome": "not_started", "error_code": "queue_spawn_failed"})

    def test_a_refusal_is_not_started_only_while_the_goal_is_not_active(self):
        refused = protocol._refused_by_codex("thread/goal/set", -32600)
        self.assertEqual(self.made(self.Session(self, fail={"thread/goal/set": refused})).resume(T1)["outcome"],
                         "not_started")
        activating = self.Session(self, fail={"thread/goal/set": refused}, then=self.activate)
        self.assertEqual(self.made(activating).resume(T1)["outcome"], "unknown")

    def test_no_answer_or_an_answer_the_goal_does_not_bear_out_is_unknown(self):
        for session, code in ((self.Session(self, fail={"thread/goal/set": AdapterError("protocol_timeout")}),
                               "queue_timeout"),
                              (self.Session(self, fail={"thread/goal/set": AdapterError("protocol_unavailable")}),
                               "queue_result_unknown"),
                              (self.Session(self), "queue_result_unknown")):
            with self.subTest(code=code):
                set_goal(self.root, T1, "usage_limited")
                self.assertEqual(self.made(session).resume(T1), {"outcome": "unknown", "error_code": code})

    def test_the_set_is_made_only_while_cores_look_still_finds_it_not_held(self):
        """Core's look is asked once the session is up, at the last moment before the set. A yes
        sets the goal; a no, or a look that fails, leaves it as it was and nothing that changes
        Codex was asked - not started, so core gives its claim back."""
        order = []

        class Session(self.Session):
            def __enter__(inner):
                order.append("session")
                return super().__enter__()

        def look(answer):
            def asked():
                order.append("look")
                if isinstance(answer, Exception):
                    raise answer
                return answer
            return asked

        session = Session(self, then=self.activate)
        self.assertEqual(self.made(session).resume(T1, still_unloaded=look(True))["outcome"], "accepted")
        self.assertEqual(order, ["session", "look"])
        for answer in (False, None, "notLoaded", OSError("gone")):
            with self.subTest(answer=answer):
                set_goal(self.root, T1, "usage_limited")
                refused = Session(self, then=self.activate)
                self.assertEqual(self.made(refused).resume(T1, still_unloaded=look(answer)),
                                 {"outcome": "not_started", "error_code": "queue_preflight_failed"})
                self.assertEqual(refused.calls, [])
                self.assertEqual(goal_row(self.root, T1)[2], "usage_limited")

    def test_another_goal_in_its_place_is_not_the_one_resumed(self):
        def replaced(method, params):
            set_goal(self.root, T1, "active", goal_id="another-goal")
        self.assertEqual(self.made(self.Session(self, then=replaced)).resume(T1)["outcome"], "unknown")

    def test_the_channel_sets_the_goal_then_queues_and_a_set_that_fails_still_queues(self):
        cid = ids.continuation_client_id("a" * 64)
        session = self.Session(self)
        self.assertEqual(self.made(session).send(T1, "go", client_id=cid)["outcome"], "accepted")
        self.assertEqual([method for method, _params in session.calls], ["thread/goal/set", "thread/queue/add"])
        self.assertEqual(session.calls[1][1]["clientUserMessageId"], cid)
        failing = self.Session(self, fail={"thread/goal/set": AdapterError("protocol_timeout")})
        self.assertEqual(self.made(failing).send(T1, "go")["outcome"], "accepted")
        self.assertEqual([method for method, _params in failing.calls], ["thread/goal/set", "thread/queue/add"])
        refused = self.Session(self, fail={"thread/queue/add": protocol._refused_by_codex("thread/queue/add", -1)})
        self.assertEqual(self.made(refused).send(T1, "go")["outcome"], "unknown")
        set_goal(self.root, T1, "active")
        quiet = self.Session(self)
        self.made(quiet).send(T1, "go")
        self.assertEqual([method for method, _params in quiet.calls], ["thread/queue/add"],
                         "a goal not paused by the limit is not set")

    def test_its_session_may_call_its_two_methods_and_nothing_else(self):
        allowed = protocol.methods_for_capability(CAP)
        self.assertEqual(allowed, frozenset({"initialize", "initialized", "thread/goal/set",
                                             "thread/queue/add"}))
        self.assertTrue(allowed.isdisjoint(protocol.FORBIDDEN_METHODS))
        self.assertNotIn("thread/goal/get", allowed, "a goal is read from its database, never asked")

    def test_the_m2b_verdict_counts_only_as_a_pass_on_the_codex_in_force(self):
        view = ac.view(capability="loaded_state_detection")
        self.assertTrue(m2b_passed(view, {Measurement.M2B: (Verdict.PASS, ENGINE)}))
        for measured in ({}, {Measurement.M2B: (Verdict.FAIL, ENGINE)},
                         {Measurement.M2B: (Verdict.PASS, "0.1.0")}, {Measurement.M2: (Verdict.PASS, ENGINE)},
                         {Measurement.M2B: "pass"}):
            with self.subTest(measured=measured):
                self.assertFalse(m2b_passed(view, measured))
        self.assertFalse(m2b_passed({}, {Measurement.M2B: (Verdict.PASS, ENGINE)}))


class CodexInUseTests(GoalCase):
    """Its goals are read from the Codex home the watcher drives, and its session is with the
    codex.exe the watcher found - as the watcher told the plug (core's Plug.codex) - not a home
    or a Codex found anew: `--codex-home` and a pinned engine included. CODEX_HOME names a home of
    the test's own with no goals in it, never the real one."""

    def setUp(self):
        super().setUp()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.exe = Path(folder.name) / "bin" / "aaaa1111" / "codex.exe"
        self.exe.parent.mkdir(parents=True)
        self.exe.write_bytes(b"MZ")
        environment = patch.dict(os.environ, {"CODEX_HOME": folder.name})
        environment.start()
        self.addCleanup(environment.stop)

    def test_its_goals_and_its_session_are_of_the_codex_the_watcher_told_it_of(self):
        plug = self.advanced()
        self.addCleanup(inuse.forget, plug.paths)
        plug.codex(self.exe, self.h.home.root)
        made = plug.runtime._code_of(GOAL_CONTINUATION)
        record = {"interruption_id": ac.KEY, "thread_id": T1, "category": "usage_limit"}
        self.assertIs(made.unloaded(record), made, "the goal paused by the limit, read where Codex keeps it")
        with patch.object(transport.Backend, "_compatible", lambda backend: {}):
            session = made._session()
        self.assertEqual((session.backend.codex_exe, session.backend.codex_home),
                         (self.exe.resolve(), self.h.home.root.resolve()))
        self.assertEqual(session.allowed, protocol.methods_for_capability(CAP))


class GoalsReaderTests(unittest.TestCase):
    """Codex's goals database, read as the capability reads it: three columns, read-only."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_it_reads_which_goal_its_status_and_when_and_nothing_else(self):
        goals_db(self.root)
        set_goal(self.root, T1, "usage_limited", at=1234)
        self.assertEqual(goals.Goals(self.root).read(T1), (GOAL_ID, GoalStatus.USAGE_LIMITED, 1234))
        self.assertIsNone(goals.Goals(self.root).read("0a1b2c3d-0001-7000-8000-000000000077"))

    def test_the_goals_words_are_never_selected(self):
        """The one statement names its three columns; `objective` is in none of what it reads."""
        self.assertNotIn("objective", goals.SELECT)
        self.assertNotIn("*", goals.SELECT)
        self.assertNotIn("objective", goals.COLUMNS)
        source = (Path(goals.__file__)).read_text(encoding="utf-8")
        statements = [line for line in source.splitlines() if "SELECT" in line and '"' in line]
        self.assertEqual([line for line in statements if "objective" in line], [])

    def test_the_newest_generation_is_read_and_opened_read_only(self):
        goals_db(self.root)
        set_goal(self.root, T1, "paused")
        goals_db(self.root, name="goals_2.sqlite")
        set_goal(self.root, T1, "usage_limited", name="goals_2.sqlite")
        self.assertEqual(goals.Goals(self.root).read(T1).status, GoalStatus.USAGE_LIMITED)
        with patch.object(goals.Goals, "_connect", wraps=goals.Goals._connect) as connect:
            goals.Goals(self.root).read(T1)
        (path,), _ = connect.call_args
        self.assertEqual(path.name, "goals_2.sqlite")
        connection = goals.Goals._connect(self.root / "goals_2.sqlite")
        try:
            with self.assertRaises(sqlite3.Error):
                connection.execute("UPDATE thread_goals SET status='active'")
        finally:
            connection.close()

    def test_what_it_cannot_read_as_it_reads_it_is_unavailable(self):
        with self.assertRaises(goals.GoalsUnavailable):
            goals.Goals(self.root).read(T1)                     # no database at all
        goals_db(self.root, table="CREATE TABLE thread_goals (thread_id TEXT, objective TEXT, status TEXT)")
        with self.assertRaises(goals.GoalsUnavailable):
            goals.Goals(self.root).read(T1)                     # moved on: no goal_id
        (self.root / "goals_1.sqlite").unlink()
        goals_db(self.root, table="CREATE TABLE thread_goals (thread_id TEXT, goal_id TEXT, objective TEXT, "
                                  "status TEXT, updated_at_ms INTEGER)")
        for goal_id, status, at in (("g", "resting", 1), ("", "paused", 1), ("g", "paused", "soon"),
                                    ("g" * 200, "paused", 1)):
            with self.subTest(goal_id=goal_id[:8], status=status, at=at):
                with contextlib.closing(sqlite3.connect(self.root / "goals_1.sqlite")) as db:
                    db.execute("DELETE FROM thread_goals")
                    db.execute("INSERT INTO thread_goals VALUES (?,?,?,?,?)", (T1, goal_id, OBJECTIVE, status, at))
                    db.commit()
                with self.assertRaises(goals.GoalsUnavailable):
                    goals.Goals(self.root).read(T1)


if __name__ == "__main__":
    unittest.main()
