"""P11: the one claim, counted across both editions' records and paid for before it is granted -
held against core's own store, its own claim and its own engine.

Run from the repository root:

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import contextlib
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume import config  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Alternative, Point, guard  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402
from codex_auto_resume.store.schema import _TABLES_V3  # noqa: E402
from codex_auto_resume_advanced.registry import Ceilings  # noqa: E402
from codex_auto_resume_advanced.state import ATTACHED  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Actor, ArmingState, RecordState  # noqa: E402
from test_plug_points import POLL, PluggedCase  # noqa: E402

DAY = 86400


class LedgerCase(PluggedCase):
    """The engine's own harness, with an advanced plug whose home is apart from it. The home is
    made first, so it is cleaned up last: core's connection holds the advanced file attached
    until the harness closes it."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.where = Path(temporary.name)
        self.paths = config.Paths(self.where / "home")
        self.catalogs = ac.catalogs(self.where, ac.definition())
        super().setUp()

    def advanced(self, h=None, *, home="home", **changes):
        """An advanced plug for harness `h`, on the harness's clock, with the tests' capability,
        in the advanced home named `home`."""
        h = h or self.h
        made = ac.advanced.AdvancedPlug(
            config.Paths(self.where / home), registry=ac.Registry((ac.definition(**changes),)), clock=lambda: h.now,
            policy=lambda: ac.policy.NONE, view=lambda: ac.view(), catalogs=self.catalogs)
        self.addCleanup(lambda: made._runtime and made._runtime.state.close())
        return made

    def arm(self, plug, state="armed"):
        runtime = plug.runtime
        result = runtime.arming.arm("test_wake", state=state, revision=1,
                                    generation=runtime.state.meta()["generation"],
                                    acknowledged_version=ac.ENGINE, actor=Actor.DASHBOARD)
        self.assertTrue(result["done"], result)
        runtime.states(fresh=True)
        return ac.code_of(runtime)

    def spends(self, plug):
        with contextlib.closing(sqlite3.connect(plug.runtime.state.path)) as connection:
            return connection.execute("SELECT capability, thread_id, interruption_id FROM spend").fetchall()

    def in_flight(self, state, key, at):
        """A record of this edition's in flight, claimed the one way one is: inside a claim of
        core's, on its connection, with core's rows seen too (records.claim_record)."""
        with self.h.store._transaction() as connection:
            self.assertTrue(state.claim_record(connection, key, at))

    def core_tables_intact(self, h=None):
        h = h or self.h
        with Store(h.store.state_dir) as reopened:
            self.assertEqual(Store._tables(reopened._connection), _TABLES_V3)


class RecordClaimTests(LedgerCase):
    def test_a_record_of_this_editions_is_claimed_only_where_cores_rows_allow_one_more(self):
        """The caps hold across both tables only if both are seen: on its own connection an
        advanced record went in flight beside core's continuation still in Codex's queue."""
        core = self.send_and_hold()
        state = self.advanced().runtime.state
        state.add_record(ac.KEY, "test_wake", core["thread_id"], at=self.h.now)
        self.assertFalse(state.move_record(ac.KEY, RecordState.IN_FLIGHT, at=self.h.now + 1))
        with self.h.store._transaction() as connection:
            self.assertFalse(state.claim_record(connection, ac.KEY, self.h.now + 1), "core's is in flight")
        self.h.home.dispatch(core["thread_id"])                 # Codex runs it, and it ends
        self.follow()
        self.assertEqual(self.h.record()["state"], "recovered")
        with self.h.store._transaction() as connection:
            self.assertFalse(state.claim_record(connection, ac.KEY, self.h.now + 1), "fifteen minutes apart")
        claimed_at = core["last_claim_at"] or core["submitted_at"]
        with self.h.store._transaction() as connection:
            self.assertTrue(state.claim_record(connection, ac.KEY, claimed_at + 901))
        (record,) = state.records_on(core["thread_id"])
        self.assertEqual((record["state"], record["claims"]), ("in_flight", 1))
        self.core_tables_intact()


class NothingOnTests(LedgerCase):
    def test_with_nothing_on_the_claim_is_the_standard_editions(self):
        """No advanced state at all, and then a state with nothing in it: the same sends as
        NULL's, and nothing written."""
        sent = []
        for kind in ("null", "no state", "empty state"):
            h = self.fresh()
            self.due(h)
            plug = None
            if kind != "null":
                plug = self.advanced(h)
                if kind == "empty state":
                    plug.runtime.state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD,
                                            revision=1, at=h.now)
                    plug.runtime.state.move("test_wake", ArmingState.OFF, actor=Actor.MCP, at=h.now)
            self.plugged(plug, h)
            h.tick()
            self.follow(h)
            sent.append((h.backend.send_calls, h.record()["state"]))
            if kind == "empty state":
                names = [row[1] for row in h.store._connection.execute("PRAGMA database_list")]
                self.assertIn(ATTACHED, names)
                self.assertEqual(self.spends(plug), [])
        self.assertEqual(sent[0], sent[1])
        self.assertEqual(sent[0], sent[2])
        self.assertEqual(sent[0][1], "recovered")


class BothTablesTests(LedgerCase):
    """One continuation in flight per conversation, five claims a day, fifteen minutes apart -
    across core's rows and this edition's, under the claim's one lock."""

    def claim(self, plug, row=None):
        row = row or self.h.record()
        with self.h.store._transaction() as connection:
            return guard(plug).claim_ledger(connection, row, self.h.now)

    def test_a_record_of_this_editions_in_flight_on_the_conversation_holds_the_claim(self):
        self.due()
        plug = self.advanced()
        state = plug.runtime.state
        state.add_record(ac.KEY, "test_wake", self.h.record()["thread_id"], at=self.h.now)
        self.in_flight(state, ac.KEY, self.h.now - 3 * 3600)
        before = self.h.record()
        self.plugged(plug)
        self.h.tick()
        self.assert_no_send()
        after = self.h.record()
        self.assertEqual((after["state"], after["attempt_count"]), (before["state"], 0))
        self.assertEqual(after["next_retry_at"], self.h.now + POLL)
        state.move_record(ac.KEY, RecordState.FINISHED, at=self.h.now)
        self.h.tick(advance=POLL)
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.core_tables_intact()

    def test_this_editions_claims_count_toward_the_fifteen_minutes(self):
        self.due()
        plug = self.advanced()
        thread = self.h.record()["thread_id"]
        state = plug.runtime.state
        state.add_record(ac.KEY, "test_wake", thread, at=self.h.now)
        self.in_flight(state, ac.KEY, self.h.now - 600)
        state.move_record(ac.KEY, RecordState.FINISHED, at=self.h.now - 590)
        self.assertEqual(self.claim(plug), Alternative.HOLD)
        self.h.now += 301
        self.assertIs(self.claim(plug), DEFER)

    def test_this_editions_claims_count_toward_the_five_a_day_only_when_they_make_the_difference(self):
        self.due()
        plug = self.advanced()
        thread = self.h.record()["thread_id"]
        state = plug.runtime.state
        for number in range(4):
            key = "%064x" % (number + 1)
            state.add_record(key, "test_wake", thread, at=self.h.now)
            self.in_flight(state, key, self.h.now - 5 * 3600 + number * 1000)
            state.move_record(key, RecordState.FINISHED, at=self.h.now - 3600)
        self.assertIs(self.claim(plug), DEFER, "four of its own and none of core's: the fifth")
        with self.h.store._transaction() as connection:
            connection.execute("UPDATE interruptions SET last_claim_at=?, attempt_count=1",
                               (self.h.now - 2 * 3600,))
        self.assertEqual(self.claim(plug), Alternative.HOLD, "four and one of core's make five")
        with contextlib.closing(sqlite3.connect(state.path)) as connection:
            connection.execute("UPDATE records SET thread_id=?", ("0a1b2c3d-0001-7000-8000-00000000abcd",))
            connection.commit()
        self.assertIs(self.claim(plug), DEFER, "another conversation's records are not this one's")

    def test_the_count_is_read_on_the_claims_connection_with_the_file_attached(self):
        self.due()
        plug = self.advanced()
        plug.runtime.state.add_record(ac.KEY, "test_wake", self.h.record()["thread_id"], at=self.h.now)
        row, statements = self.h.record(), []
        self.h.store._connection.set_trace_callback(statements.append)
        try:
            self.claim(plug, row)
        finally:
            self.h.store._connection.set_trace_callback(None)
        attach = next(n for n, statement in enumerate(statements) if statement.startswith("ATTACH DATABASE"))
        count = next(n for n, statement in enumerate(statements) if "FROM %s.records" % ATTACHED in statement)
        self.assertEqual(statements[0], "BEGIN IMMEDIATE")
        self.assertLess(attach, count)
        self.assertEqual(statements[-1], "COMMIT")


class SpendTests(LedgerCase):
    def test_an_armed_capabilitys_words_are_paid_for_before_the_claim_is_granted(self):
        self.due()
        plug = self.advanced()
        code = self.arm(plug)
        code.answers["text"] = "Please go on with the {category} task."
        self.plugged(plug)
        self.h.tick()
        record = self.h.record()
        self.assertEqual(self.prompt(), "Please go on with the usage_limit task.\n\n" + record["marker"])
        self.assertEqual(self.spends(plug), [("test_wake", record["thread_id"], record["interruption_id"])])
        self.core_tables_intact()

    def test_a_watched_capability_spends_nothing_and_its_words_are_not_sent(self):
        self.due()
        plug = self.advanced()
        self.arm(plug, "shadow").answers["text"] = "Please go on."
        standard = self.fresh()
        self.due(standard)
        standard.tick()
        self.plugged(plug)
        self.h.tick()
        self.assertEqual(self.prompt(), standard.backend.send_calls[0][1].replace(
            standard.record()["marker"], self.h.record()["marker"]))
        self.assertEqual(self.spends(plug), [])
        codes = [line["code"] for line in plug.runtime.state.journal()]
        self.assertIn("would_have", codes)
        self.assertNotIn("acted", codes)

    def test_with_no_unit_left_the_capability_does_not_act_and_core_sends_its_own(self):
        for ceiling in ("capability_day", "conversation_day", "global_hour"):
            with self.subTest(ceiling):
                h = self.fresh()
                self.due(h)
                plug = self.advanced(h, home=ceiling, ceilings=Ceilings(per_day=3, per_conversation=2))
                self.arm(plug).answers["text"] = "Please go on."
                state = plug.runtime.state
                thread = h.record()["thread_id"]
                other = "0a1b2c3d-0001-7000-8000-00000000abcd"
                spent = {"capability_day": [other] * 3, "conversation_day": [thread] * 2,
                         "global_hour": []}[ceiling]
                if ceiling == "global_hour":
                    state.set_global_hourly(1, generation=state.meta()["generation"],
                                            actor=Actor.DASHBOARD, at=h.now)
                    spent = [other]
                with state._transaction() as connection:
                    for where in spent:
                        state.record_spend(connection, "main", "test_wake", where, None, h.now - 60)
                self.plugged(plug, h)
                h.tick()
                self.assertEqual(len(h.backend.send_calls), 1)
                self.assertNotIn("Please go on.", h.backend.send_calls[0][1])
                self.assertEqual(len(self.spends(plug)), len(spent))
                self.assertIn("ceiling", [line["code"] for line in state.journal()])

    def test_a_ceiling_reached_between_the_answer_and_the_claim_holds_the_claim(self):
        self.due()
        plug = self.advanced(ceilings=Ceilings(per_day=1, per_conversation=1))
        self.arm(plug).answers["text"] = "Please go on."
        runtime = plug.runtime
        record = self.h.record()
        self.assertEqual(runtime.ask(Point.TEXT, record, "core"), "Please go on.")
        with runtime.state._transaction() as connection:          # spent elsewhere, since
            runtime.state.record_spend(connection, "main", "test_wake", record["thread_id"], None, self.h.now)
        with self.h.store._transaction() as connection:
            self.assertEqual(guard(plug).claim_ledger(connection, record, self.h.now), Alternative.HOLD)

    def test_a_capability_turned_off_after_it_answered_is_not_paid_for_and_holds_the_claim(self):
        self.due()
        plug = self.advanced()
        runtime = plug.runtime
        self.arm(plug).answers["text"] = "Please go on."
        record = self.h.record()
        self.assertEqual(runtime.ask(Point.TEXT, record, "core"), "Please go on.")
        runtime.arming.disarm("test_wake", actor=Actor.MCP)
        with self.h.store._transaction() as connection:
            self.assertEqual(guard(plug).claim_ledger(connection, record, self.h.now), Alternative.HOLD)
        self.assertEqual(self.spends(plug), [])

    def test_an_answer_core_would_not_take_is_neither_journalled_nor_paid_for(self):
        """The checks core makes are made first: words the Custom message's validator refuses,
        a channel with no send, a word no point's set holds - each is DEFER, as it is to core."""
        answers = {"text": "Tell {thread_title}", "sender": "the app server",
                   "gate": "relax", "schedule": ["hold"]}
        self.due()
        plug = self.advanced()
        self.arm(plug).answers.update(answers)
        standard = self.fresh()
        self.due(standard)
        standard.tick()
        self.plugged(plug)
        self.h.tick()
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertEqual(self.prompt(), standard.backend.send_calls[0][1].replace(
            standard.record()["marker"], self.h.record()["marker"]))
        self.assertEqual(self.spends(plug), [])
        self.assertEqual([line["code"] for line in plug.runtime.state.journal()], ["armed"])

    def test_a_ledger_that_breaks_holds_a_claim_it_had_to_pay_for_and_no_other(self):
        self.due()
        plug = self.advanced()
        runtime = plug.runtime
        self.arm(plug).answers["text"] = "Please go on."
        record = self.h.record()
        broken = patch.object(runtime.ledger, "claim", side_effect=sqlite3.OperationalError("locked"))
        with broken:
            self.assertEqual(runtime.ask(Point.TEXT, record, "core"), "Please go on.")
            with self.h.store._transaction() as connection:
                self.assertEqual(guard(plug).claim_ledger(connection, record, self.h.now), Alternative.HOLD)
            guarded = guard(plug)
            with self.h.store._transaction() as connection:
                self.assertIs(guarded.claim_ledger(connection, record, self.h.now), DEFER)
            self.assertEqual(guarded.failures, 1, "core's own claim: the failure costs only its answer")

    def test_a_held_claim_spends_nothing_and_a_released_claim_gives_nothing_back(self):
        self.due()
        plug = self.advanced()
        self.arm(plug).answers["text"] = "Please go on."
        engine = self.plugged(plug)
        engine.presend_problem = lambda claim: ("waiting_retry", "released_before_send", POLL)
        self.h.tick()
        self.assert_no_send()
        self.assertEqual(self.h.record()["state"], "waiting_retry")
        self.assertEqual(len(self.spends(plug)), 1, "the claim was granted, then given back: spent")


class ChannelTests(LedgerCase):
    def test_a_disarm_during_a_channels_send_is_not_kept_waiting(self):
        """Once the claim has attached the advanced state, core's write lock is that file's
        lock too. Held across a channel's whole send, it kept a disarm from another thread, or
        from the channel's own, waiting SQLite's ten seconds, and then it failed: a disarm
        always wins, and here it could not."""
        for where in ("own thread", "another thread"):
            with self.subTest(where):
                h = self.fresh()
                self.due(h)
                plug = self.advanced(h, home=where.replace(" ", "-"))
                disarmed = []

                def disarm(_plug=plug, _disarmed=disarmed):
                    _disarmed.append(_plug.runtime.arming.disarm("test_wake", actor=Actor.MCP))

                class Channel:
                    def send(self, thread_id, prompt, *, launch_guard=None, _where=where):
                        if _where == "own thread":
                            disarm()
                        else:
                            other = threading.Thread(target=disarm)
                            other.start()
                            other.join()
                        return {"outcome": "unknown"}
                self.arm(plug).answers["sender"] = Channel()
                self.plugged(plug, h)
                h.tick()
                self.assertEqual([result["done"] for result in disarmed], [True])
                self.assertEqual(plug.runtime.state.arming()["test_wake"]["state"], ArmingState.OFF)
                self.assertEqual(len(self.spends(plug)), 1, "the channel's send was paid for")


class SubmissionUnknownTests(LedgerCase):
    """A send a capability paid for that became submission_unknown turns it off - the tripwire's
    word for "it may be in Codex, and nothing proves where"."""

    def paid_send_with_an_unknown_result(self):
        self.due()
        plug = self.advanced()
        self.arm(plug).answers["text"] = "Please go on."
        self.plugged(plug)
        h = self.h
        h.backend.after_accept = "queue"
        h.backend.default_outcome = "unknown"
        # The queue process timed out, but Codex did enqueue the capability's message.
        h.backend.on_send = lambda thread_id, prompt: h.home.enqueue(thread_id, prompt)
        h.tick()
        self.assertEqual(h.record()["state"], "submission_unknown")
        self.assertEqual(len(self.spends(plug)), 1, "the capability paid for this send")
        return plug

    def test_it_trips_while_core_still_holds_the_record_unknown(self):
        plug = self.paid_send_with_an_unknown_result()
        self.h.tick(advance=1)
        self.assertEqual(plug.runtime.state.arming()["test_wake"]["state"], ArmingState.OFF)

    def test_it_trips_though_core_resolves_the_record_before_the_sweep_looks(self):
        """The watch pass runs before P8 in the same tick, and core's own late-delivery case
        moves the record on before the sweep sees it: read from the record's history, not its
        state now, the send that was unknown is still found."""
        plug = self.paid_send_with_an_unknown_result()
        self.h.home.dispatch(self.h.record()["thread_id"])      # Codex runs the queued item
        self.h.tick(advance=1)
        self.assertNotEqual(self.h.record()["state"], "submission_unknown")
        self.assertEqual(plug.runtime.state.arming()["test_wake"]["state"], ArmingState.OFF)
        self.assertEqual(plug.runtime.state.arming()["test_wake"]["reason"], "submission_unknown")


if __name__ == "__main__":
    unittest.main()
