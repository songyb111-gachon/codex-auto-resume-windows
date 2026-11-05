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
from codex_auto_resume.store.schema import _TABLES_V4  # noqa: E402
from codex_auto_resume_advanced import arming  # noqa: E402
from codex_auto_resume_advanced import ledger as ledger_module  # noqa: E402
from codex_auto_resume_advanced.registry import Ceilings  # noqa: E402
from codex_auto_resume_advanced.state import ATTACHED, StateError  # noqa: E402
from codex_auto_resume_advanced.state.spend import SAME_CLAIM  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Actor, ArmingState, RecordState  # noqa: E402
from test_engine import T1, TURN_A  # noqa: E402
from test_plug_points import POLL, PluggedCase  # noqa: E402

DAY = 86400


class LedgerCase(PluggedCase):
    """The engine's own harness, with an advanced plug whose home is apart from it. The home is
    made first, so it is cleaned up last: core's connection holds the advanced file attached
    until the harness closes it."""

    #: Capabilities beside the tests' own that this case's registry and catalogs hold.
    EXTRA = ()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.where = Path(temporary.name)
        self.paths = config.Paths(self.where / "home")
        self.catalogs = ac.catalogs(self.where, ac.definition(), *self.EXTRA)
        super().setUp()

    def advanced(self, h=None, *, home="home", **changes):
        """An advanced plug for harness `h`, on the harness's clock, with the tests' capability
        (and this case's `EXTRA` ones), in the advanced home named `home`."""
        h = h or self.h
        made = ac.advanced.AdvancedPlug(
            config.Paths(self.where / home), registry=ac.Registry((ac.definition(**changes), *self.EXTRA)),
            clock=lambda: h.now,
            policy=lambda: ac.policy.NONE, view=lambda: ac.view(), catalogs=self.catalogs)
        self.addCleanup(lambda: made._runtime and made._runtime.state.close())
        return made

    def arm(self, plug, state="armed", capability="test_wake"):
        runtime = plug.runtime
        result = runtime.arming.arm(capability, state=state, revision=1,
                                    generation=runtime.state.meta()["generation"],
                                    acknowledged_version=ac.ENGINE, actor=Actor.DASHBOARD)
        self.assertTrue(result["done"], result)
        runtime.states(fresh=True)
        return ac.code_of(runtime, capability)

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
            self.assertEqual(Store._tables(reopened._connection), _TABLES_V4)


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
            return guard(plug).claim_ledger(connection, row, self.h.now, frozenset())

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
            self.assertEqual(guard(plug).claim_ledger(connection, record, self.h.now, {Point.TEXT}),
                             Alternative.HOLD)

    def test_a_capability_turned_off_after_it_answered_is_not_paid_for_and_holds_the_claim(self):
        self.due()
        plug = self.advanced()
        runtime = plug.runtime
        self.arm(plug).answers["text"] = "Please go on."
        record = self.h.record()
        self.assertEqual(runtime.ask(Point.TEXT, record, "core"), "Please go on.")
        runtime.arming.disarm("test_wake", actor=Actor.MCP)
        with self.h.store._transaction() as connection:
            self.assertEqual(guard(plug).claim_ledger(connection, record, self.h.now, {Point.TEXT}),
                             Alternative.HOLD)
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
                self.assertEqual(guard(plug).claim_ledger(connection, record, self.h.now, {Point.TEXT}),
                                 Alternative.HOLD)
            guarded = guard(plug)
            with self.h.store._transaction() as connection:
                self.assertIs(guarded.claim_ledger(connection, record, self.h.now, frozenset()), DEFER)
            self.assertEqual(guarded.failures, 1, "core's own claim: the failure costs only its answer")

    def test_words_core_drops_are_neither_paid_for_nor_a_reason_to_hold(self):
        """Words that pass the validator and fill in to nothing for the record - {reset_time}
        on a failure with no reset - are dropped by core, which sends the person's own style.
        The runtime paid by its own list of what it had answered, so a unit was spent on words
        never sent, and a ledger that broke held a claim that carried only core's own words.
        It pays for what core says the send carries, and nothing else."""
        for broken in (False, True):
            with self.subTest(broken=broken):
                standard, h = self.fresh(), self.fresh()
                plug = self.advanced(h, home="broken" if broken else "whole")
                self.arm(plug).answers["text"] = "{reset_time}"
                for harness in (standard, h):
                    harness.home.fail_transient(T1, TURN_A)
                    harness.backend.loaded_map[T1] = "loaded"
                    harness.tick()
                self.plugged(plug, h)
                standard.tick(advance=300)
                failing = (patch.object(ledger_module, "held_by_records",
                                        side_effect=sqlite3.OperationalError("advanced.sqlite is locked"))
                           if broken else contextlib.nullcontext())
                with failing:
                    h.tick(advance=300)
                self.assertEqual(len(standard.backend.send_calls), 1)
                self.assertEqual(len(h.backend.send_calls), 1, "core's own words go, as with no plug")
                words = [calls[0][1].rsplit("\n\n", 1)[0]
                         for calls in (h.backend.send_calls, standard.backend.send_calls)]
                self.assertEqual(words[0], words[1])
                self.assertEqual(self.spends(plug), [])

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


class GlobalHourTests(LedgerCase):
    """The global hourly ceiling counts sends, not the capabilities that rode them (v0.6.17, P-9).

    A person is told it in sends - "Sends an hour, all advanced features together", 24 by default -
    so with two capabilities answering for one send it used to leave 12, and the second capability of
    the 13th send was passed over at the ceiling: its answer dropped, core going its own way."""

    CEILINGS = Ceilings(per_day=40, per_conversation=5)

    def setUp(self):
        self.second = ac.definition(id="test_nap", journal_prefix="tn", ceilings=self.CEILINGS)
        self.EXTRA = (self.second,)
        super().setUp()

    def two_on(self):
        """A plug with both capabilities armed, neither near a day or a conversation ceiling."""
        plug = self.advanced(ceilings=self.CEILINGS)
        for capability in ("test_wake", "test_nap"):
            self.arm(plug, capability=capability)
        return plug

    def send(self, plug, number, at, *acted, thread=None):
        """One claim of core's for a standard record, carrying the answers of `acted` - both capabilities
        where none is named - as core makes it: everything the ledger wrote is taken back where it holds
        (store/ledger.py). Each send is its own conversation unless `thread` says otherwise, so only the
        hourly ceiling binds."""
        acted = acted or ("test_wake", "test_nap")
        self.h.now = at
        record = {"interruption_id": self.key(number), "thread_id": thread or self.thread(number)}
        with self.h.store._transaction() as connection:
            connection.execute("SAVEPOINT one_claim")
            answer = plug.runtime.ledger.claim(connection, record, at, dict.fromkeys(acted, frozenset()))
            connection.execute("ROLLBACK TO one_claim" if answer is Alternative.HOLD else "RELEASE one_claim")
        return answer

    @staticmethod
    def key(number) -> str:
        return "%064x" % number

    @staticmethod
    def thread(number) -> str:
        return "0a1b2c3d-0001-7000-8000-%012d" % (number + 100)

    def test_one_send_two_capabilities_ride_is_one_of_the_sends_an_hour_a_person_is_told_of(self):
        plug = self.two_on()
        state = plug.runtime.state
        self.assertEqual(state.meta()["global_hourly"], 24, "what the page says: sends an hour, all together")
        base = self.h.now
        for number in range(24):
            self.assertIs(self.send(plug, number, base + number), DEFER, "send %d" % number)
        self.assertIs(self.send(plug, 24, base + 24), Alternative.HOLD, "the 25th send")
        self.assertEqual(len(self.spends(plug)), 48, "two capabilities paid for each of the 24 sends")
        self.assertEqual(state.spent("test_wake", ac.THREAD)["global_hour"], 24)

    def test_each_capability_still_counts_its_own_units_by_day_and_by_conversation(self):
        plug = self.two_on()
        state = plug.runtime.state
        base = self.h.now
        for number in range(3):
            self.assertIs(self.send(plug, number, base + number, thread=ac.THREAD), DEFER)
        for capability in ("test_wake", "test_nap"):
            counts = state.spent(capability, ac.THREAD)
            self.assertEqual((counts["capability_day"], counts["conversation_day"]), (3, 3), capability)
            self.assertEqual(counts["global_hour"], 3, "three sends, six units")
        self.assertEqual(state.spent("test_wake", ac.OTHER_THREAD)["conversation_day"], 0)

    def test_a_second_send_of_one_record_is_a_second_send_against_the_hour(self):
        """What a resend costs is what it cost before: the one record claimed again, later, is another
        send - only the capabilities inside one claim are one."""
        plug = self.two_on()
        state = plug.runtime.state
        base = self.h.now
        self.assertIs(self.send(plug, 1, base, thread=ac.THREAD), DEFER)
        self.assertEqual(state.spent("test_wake", ac.THREAD)["global_hour"], 1)
        self.assertIs(self.send(plug, 1, base + 30, thread=ac.THREAD), DEFER)
        self.assertEqual(state.spent("test_wake", ac.THREAD)["global_hour"], 2)
        self.assertEqual(len(self.spends(plug)), 4)

    def test_a_send_one_capability_rides_counts_as_it_did(self):
        # A guard for behaviour this change leaves alone, not a proof of it: it passes with the fix reverted.
        plug = self.two_on()
        base = self.h.now
        for number in range(24):
            self.assertIs(self.send(plug, number, base + number, "test_wake"), DEFER)
        self.assertIs(self.send(plug, 24, base + 24, "test_wake"), Alternative.HOLD)
        self.assertEqual(len(self.spends(plug)), 24)

    def test_one_record_claimed_twice_at_one_reading_of_the_clock_is_two_sends(self):
        """Two claims of the one record at the identical time are two sends, though their units bear the
        one record and the one time: what a claim leaves out of its hour is the units it wrote itself."""
        plug = self.two_on()
        base = self.h.now
        for number in range(23):
            self.assertIs(self.send(plug, number, base + number), DEFER)
        self.assertIs(self.send(plug, 99, base + 23), DEFER, "the 24th send")
        self.assertIs(self.send(plug, 99, base + 23), Alternative.HOLD, "the 25th, at the same time")

    def test_two_claims_of_one_record_at_one_reading_both_granted_are_two_sends_in_the_hour(self):
        """Two claims of the one record at a bit-identical time, both below the ceiling, used to write their units
        under the one (record, time) and so count one send in the hour: the 24th claim after them saw 23 and
        one more send went than a person allowed. The second claim writes its units at the next float above the
        first's (state/spend.claim_time), so each counts and the ceiling holds."""
        plug = self.two_on()
        state = plug.runtime.state
        base = self.h.now
        self.assertIs(self.send(plug, 99, base), DEFER, "the first claim")
        self.assertIs(self.send(plug, 99, base), DEFER, "the second claim, at the same reading of the clock")
        self.assertEqual(state.spent("test_wake", ac.THREAD)["global_hour"], 2, "two sends, though one time")
        with contextlib.closing(sqlite3.connect(state.path)) as connection:
            times = [row[0] for row in connection.execute("SELECT at FROM spend ORDER BY spend_id")]
        self.assertEqual(len(times), 4, "two capabilities paid for each claim")
        self.assertEqual(times[0], times[1], "the units of one claim stand at its one time")
        self.assertEqual(times[2], times[3])
        self.assertGreater(times[2], times[0], "the second claim's time is apart from the first's")
        self.assertLessEqual(times[2] - times[0], SAME_CLAIM, "and still names the claim it paid for")
        for number in range(22):
            self.assertIs(self.send(plug, number, base + 1 + number), DEFER, "send %d" % (number + 3))
        self.assertIs(self.send(plug, 50, base + 30), Alternative.HOLD, "the 25th send")
        self.assertEqual(state.spent("test_wake", ac.THREAD)["global_hour"], 24)

    def test_a_spend_table_v0616_wrote_counts_as_it_did(self):
        # A guard for rows this change never writes, not a proof of it: it passes with the fix reverted. v0.6.16
        # wrote every claim's units at its own time, so two claims of one record at one reading share a group.
        plug = self.two_on()
        state = plug.runtime.state
        now = self.h.now
        first, second = self.key(1), self.key(2)
        with state._transaction() as connection:
            for capability, key, at in (("test_wake", first, now), ("test_nap", first, now),
                                        ("test_wake", first, now), ("test_wake", second, now + 1),
                                        ("test_wake", None, now + 2), ("test_wake", None, now + 2)):
                connection.execute("INSERT INTO spend (at, capability, thread_id, interruption_id) VALUES (?,?,?,?)",
                                   (at, capability, ac.THREAD, key))
        counts = state.spent("test_wake", ac.THREAD, now + 3)
        self.assertEqual(counts["global_hour"], 4, "one for the first record's time, one for the second's, and one "
                                                   "for each unit of this edition's own records")
        self.assertEqual(counts["capability_day"], 5)

    def test_the_units_of_this_editions_own_records_at_one_reading_are_the_sends_they_are(self):
        """A record of this edition's own bears no standard record and is paid for by its one capability,
        so each of its units is a send of its own, however many fall at one reading of the clock."""
        plug = self.two_on()
        state = plug.runtime.state
        with state._transaction() as connection:
            for _ in range(3):
                state.record_spend(connection, "main", "test_wake", ac.THREAD, None, self.h.now)
        self.assertEqual(state.spent("test_wake", ac.THREAD)["global_hour"], 3)

    def test_the_25th_send_goes_once_the_first_is_an_hour_old(self):
        # A guard for the hour's edge, which this change leaves alone: it passes with the fix reverted.
        plug = self.two_on()
        base = self.h.now
        for number in range(24):
            self.assertIs(self.send(plug, number, base + number), DEFER)
        self.assertIs(self.send(plug, 24, base + 24), Alternative.HOLD)
        self.assertIs(self.send(plug, 24, base + 3600), DEFER, "the first send is an hour old")


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

    def paid_send_with_an_unknown_result(self, prepare=None):
        self.due()
        plug = self.advanced()
        self.arm(plug).answers["text"] = "Please go on."
        self.plugged(plug)
        if prepare is not None:
            prepare(plug)
        h = self.h
        h.backend.after_accept = "queue"
        h.backend.default_outcome = "unknown"
        # The queue process timed out, but Codex did enqueue the capability's message.
        h.backend.on_send = lambda thread_id, prompt: h.home.enqueue(thread_id, prompt)
        h.tick()
        self.assertEqual(h.record()["state"], "submission_unknown")
        self.assertEqual(len(self.spends(plug)), 1, "the capability paid for this send")
        return plug

    def assert_tripped(self, plug):
        row = plug.runtime.state.arming()["test_wake"]
        self.assertEqual((row["state"], row["reason"]), (ArmingState.OFF, "submission_unknown"))

    def test_it_trips_while_core_still_holds_the_record_unknown(self):
        plug = self.paid_send_with_an_unknown_result()
        self.h.tick(advance=1)
        self.assert_tripped(plug)

    def test_it_trips_though_core_resolves_the_record_before_the_sweep_looks(self):
        """The watch pass runs before P8 in the same tick, and core's own late-delivery case
        moves the record on before the sweep sees it. Core told the plug of the move into
        submission_unknown as it wrote it (P14), so the send that was unknown is still found -
        and nothing is read back from core's journal."""
        plug = self.paid_send_with_an_unknown_result()
        self.h.home.dispatch(self.h.record()["thread_id"])      # Codex runs the queued item
        self.h.tick(advance=1)
        self.assertNotEqual(self.h.record()["state"], "submission_unknown")
        self.assert_tripped(plug)

    def test_a_trip_whose_write_failed_is_written_though_core_resolved_the_record(self):
        """Core tells the plug of the move once. Where the trip cannot be written then - the
        advanced state locked past its busy timeout, say - it is not lost: the next tick writes
        it, though the watch has settled the record by then and its state says nothing."""
        failed = []

        def failing_once(plug):
            state = plug.runtime.state
            real = state.move

            def move(capability, target, **kwargs):
                if kwargs.get("reason") == "submission_unknown" and not failed:
                    failed.append(capability)
                    raise StateError("the advanced state is locked")
                return real(capability, target, **kwargs)
            state.move = move
        plug = self.paid_send_with_an_unknown_result(failing_once)
        self.assertEqual(failed, ["test_wake"])
        self.assertEqual(plug.runtime.state.arming()["test_wake"]["state"], ArmingState.ARMED)
        self.h.home.dispatch(self.h.record()["thread_id"])      # Codex runs the queued item
        self.h.tick(advance=1)
        self.assertNotEqual(self.h.record()["state"], "submission_unknown")
        self.assert_tripped(plug)

    def test_it_trips_on_the_move_though_unknown_and_resolved_with_no_sweep_between(self):
        """Unknown and resolved inside one stretch the sweep never looks at: the watch that runs
        every second while something may be queued finds the item, and settles it once Codex
        runs it, all before the next tick's P8. With the sweep doing nothing at all, the
        capability is off all the same - by the move core told the plug of as it wrote it."""
        with patch.object(arming.Arming, "sweep", lambda self, view: None):
            plug = self.paid_send_with_an_unknown_result()
            self.assert_tripped(plug)
            self.h.watch(advance=1)                             # the item is found in the queue
            self.h.home.dispatch(self.h.record()["thread_id"])  # Codex runs it
            self.h.watch(advance=1)
            self.assertEqual(self.h.record()["state"], "turn_started")
            self.h.tick(advance=1)
        self.assert_tripped(plug)


if __name__ == "__main__":
    unittest.main()
