"""Taking failures up (v0.6.13, stage 3b): what the runtime takes at P17 and at known_failure, what it
remembers of it, and what it keeps the first time core goes on.

Held against a capability of the tests' own (advancedcase.py) and, end to end, against core's own
engine, store and simulated Codex home (tests/codexsim.py):

* at P17 an answer is taken only if core offered it (`takes`), only for a failure from after the
  capability was turned on or watched, only while it has a unit left - and taken, it is remembered,
  once an interruption, with its word, the rule it rests on and, for one that samples, the shape;
* at P3 a word that relaxes is taken only at known_failure, from the capability that took the record
  up, with that very word;
* a record core never recovers alone waits where the state cannot be read or its capability has no
  unit left, and ends only where reads that worked found nothing holding it; a capacity error falls
  back to the standard edition's handling instead;
* `taken` is asked the first time core goes on with such a record, never at P17 and never watched, and
  what it keeps is written with the mark, once.

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from advancedcase import ENGINE  # noqa: E402
from codex_auto_resume import config, ladder  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, TAKE_UP, Alternative, FailureForm, Point  # noqa: E402
from codex_auto_resume_advanced import statement  # noqa: E402
from codex_auto_resume_advanced.registry import Ceilings, Registry  # noqa: E402
from codex_auto_resume_advanced.state import StateError  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (Actor, ArmingState, JournalCode,  # noqa: E402
                                                   OffReason)
from test_engine import T1, TURN_A  # noqa: E402
from test_plug_points import PluggedCase, failed  # noqa: E402

CAP = "test_wake"
POINTS = frozenset({Point.ADMISSION, Point.GATES})


class Taking(ac.Code):
    """The tests' capability's code, with the two optional hooks a capability that takes failures up
    may have: the rule its answer rests on, and what it keeps the first time core goes on."""

    def rule_for(self, facts, answer):
        return self._answer("rule_for", facts, answer)

    def taken(self, point, answer, *arguments):
        return self._answer("taken", point, answer, *arguments)

    def bind(self, scoped):
        self.scoped = scoped


def taking(**changes):
    made = {}

    def make(paths):
        made.setdefault("code", Taking(paths))
        return made["code"]
    fields = dict(points=POINTS, make=make, codes=("sampled", "matched"), samples=True)
    fields.update(changes)
    return ac.definition(**fields)


class RuntimeCase(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        self.rt = self.runtime(taking())
        self.code = ac.code_of(self.rt)

    def armed(self, state="armed"):
        self.assertTrue(self.arm(self.rt, state=state)["done"])
        self.rt.states(fresh=True)

    def facts(self, **changes):
        made = {"interruption_id": ac.KEY, "thread_id": ac.THREAD, "turn_id": ac.THREAD, "category": "unknown",
                "code": "brandNewVariant", "status": None, "form": FailureForm.TAGGED, "has_message": True,
                "started_at": self.now - 60, "completed_at": self.now, "ordinal": 3, "takes": TAKE_UP,
                "chain": None}
        made.update(changes)
        return made

    def record(self, **changes):
        made = {"interruption_id": ac.KEY, "thread_id": ac.THREAD, "category": "unknown"}
        made.update(changes)
        return made

    def lines(self):
        return [(line["code"], line["point"], line["answer"]) for line in self.rt.state.journal(capability=CAP)]

    def fill(self, count):
        with self.rt.state._transaction() as connection:
            for index in range(count):
                self.rt.state.record_spend(connection, "main", CAP, ac.THREAD, "%064x" % index, self.now - 60)


class AdmissionPointTests(RuntimeCase):
    def test_an_armed_answer_core_offered_is_taken_and_remembered_with_its_word_rule_and_shape(self):
        self.armed()
        self.code.answers.update(admission=Alternative.ADMIT, rule_for=4)
        self.assertIs(self.rt.ask(Point.ADMISSION, self.facts()), Alternative.ADMIT)
        row = self.rt.state.admission(ac.KEY)
        self.assertEqual((row["capability"], row["answer"], row["rule_id"], row["tag"], row["form"],
                          row["has_words"], row["sampled"]),
                         (CAP, Alternative.ADMIT, 4, "brandNewVariant", "tagged", 1, False))
        self.assertIn((JournalCode.ACTED, Point.ADMISSION, Alternative.ADMIT), self.lines())
        self.assertNotIn("taken", self.code.asked, "never told at P17")

    def test_an_answer_core_did_not_offer_is_neither_taken_nor_journalled(self):
        self.armed()
        self.code.answers["admission"] = Alternative.ADMIT
        for takes in (frozenset({Alternative.AS_TIMEOUT}), frozenset(), None):
            with self.subTest(takes=takes):
                facts = self.facts(takes=takes) if takes is not None else {
                    key: value for key, value in self.facts().items() if key != "takes"}
                self.assertIs(self.rt.ask(Point.ADMISSION, facts), DEFER)
        self.assertIsNone(self.rt.state.admission(ac.KEY))
        self.assertFalse([line for line in self.lines() if line[1] == Point.ADMISSION])

    def test_turning_it_on_or_watching_it_never_reaches_back_to_an_earlier_failure(self):
        self.code.answers["admission"] = Alternative.ADMIT
        for state in ("shadow", "armed"):
            with self.subTest(state):
                self.armed(state)
                self.now += 30
                self.assertIs(self.rt.ask(Point.ADMISSION, self.facts(completed_at=self.now - 31)), DEFER)
                self.assertFalse([line for line in self.lines() if line[1] == Point.ADMISSION])
        self.assertIs(self.rt.ask(Point.ADMISSION, self.facts(completed_at=self.now - 30)), Alternative.ADMIT)

    def test_watched_it_journals_what_it_would_have_done_and_remembers_nothing(self):
        self.armed("shadow")
        self.code.answers["admission"] = Alternative.ADMIT
        self.assertIs(self.rt.ask(Point.ADMISSION, self.facts()), DEFER)
        self.assertEqual(self.lines()[-1], (JournalCode.WOULD_HAVE, Point.ADMISSION, Alternative.ADMIT))
        self.assertIsNone(self.rt.state.admission(ac.KEY))

    def test_with_no_unit_left_nothing_is_taken_up(self):
        self.armed()
        self.code.answers["admission"] = Alternative.ADMIT
        self.fill(2)                                  # the tests' capability: two a conversation a day
        self.assertIs(self.rt.ask(Point.ADMISSION, self.facts()), DEFER)
        self.assertEqual(self.lines()[-1], (JournalCode.CEILING, Point.ADMISSION, Alternative.ADMIT))
        self.assertIsNone(self.rt.state.admission(ac.KEY))

    def test_a_memory_that_cannot_be_written_takes_nothing_up(self):
        self.armed()
        self.code.answers["admission"] = Alternative.ADMIT
        with patch.object(self.rt.state, "admit", side_effect=StateError("locked")):
            self.assertIs(self.rt.ask(Point.ADMISSION, self.facts()), DEFER)
        self.assertNotIn((JournalCode.ACTED, Point.ADMISSION, Alternative.ADMIT), self.lines())

    def test_a_rule_hook_that_raises_trips_it_and_takes_nothing_up(self):
        self.armed()
        self.code.answers.update(admission=Alternative.ADMIT, rule_for=RuntimeError("boom"))
        self.assertIs(self.rt.ask(Point.ADMISSION, self.facts()), DEFER)
        self.assertEqual(self.rt.state.arming()[CAP]["reason"], OffReason.HOOK_EXCEPTION)
        self.assertIsNone(self.rt.state.admission(ac.KEY))

    def test_its_code_is_given_its_own_view_of_the_state(self):
        self.armed()
        self.rt.ask(Point.ADMISSION, self.facts())
        self.assertEqual(self.code.scoped.capability, CAP)
        self.assertEqual(self.code.scoped.now(), self.now)


class KnownFailureTests(RuntimeCase):
    def taken_up(self, answer=Alternative.ADMIT, capability=CAP):
        self.armed()
        self.assertTrue(self.rt.state.admit(ac.KEY, capability, answer, shape={
            "code": "brandNewVariant", "status": 502, "form": FailureForm.TAGGED, "has_message": False}))

    def gate(self, name="known_failure", **record):
        return self.rt.ask(Point.GATES, name, self.record(**record), {})

    def test_a_word_that_relaxes_is_taken_only_at_known_failure_and_only_as_it_was_taken_up(self):
        self.taken_up()
        self.code.answers["gate"] = Alternative.ADMIT
        self.assertIs(self.gate(), Alternative.ADMIT)
        self.assertIs(self.gate("usage"), DEFER, "at another gate it relaxes nothing")
        self.code.answers["gate"] = Alternative.AS_TIMEOUT
        self.assertIs(self.gate(), DEFER, "not the word it was taken up with")
        self.code.answers["gate"] = Alternative.HOLD
        self.assertIs(self.gate("usage"), Alternative.HOLD, "a restriction, anywhere, as always")

    def test_a_capability_never_relaxes_a_record_another_took_up(self):
        other = taking(id="test_other", journal_prefix="to")
        self.catalogs = ac.catalogs(tempfile.mkdtemp(dir=self.home.parent), taking(), other)
        self.rt = self.runtime(taking(), other)
        self.arm(self.rt, "test_other")
        self.taken_up()
        ac.code_of(self.rt, "test_other").answers["gate"] = Alternative.ADMIT
        self.assertTrue(self.rt.state.admit(ac.KEY, CAP, Alternative.ADMIT))
        self.rt.states(fresh=True)
        self.assertIs(self.gate(), DEFER)
        ac.code_of(self.rt).answers["gate"] = Alternative.ADMIT
        self.assertIs(self.gate(), Alternative.ADMIT)

    def test_a_state_that_cannot_be_read_holds_a_record_it_may_have_taken_up_and_never_ends_it(self):
        self.taken_up()
        self.code.answers["gate"] = Alternative.ADMIT
        with patch.object(self.rt.state, "arming", side_effect=StateError("locked")):
            self.rt.states(fresh=True)
            for category in ("unknown", "terminal_auth", "terminal_failure"):
                with self.subTest(category):
                    self.assertIs(self.gate(category=category), Alternative.HOLD)
            self.assertIs(self.gate(category="server_5xx"), DEFER, "the standard edition's own")
        self.rt.states(fresh=True)
        with patch.object(self.rt.state, "admission", side_effect=StateError("locked")):
            self.assertIs(self.gate(), Alternative.HOLD)
        self.assertFalse([line for line in self.lines() if line[1] == Point.GATES and line[0] != JournalCode.ACTED])

    def test_reads_that_worked_and_found_nothing_holding_it_end_it(self):
        self.taken_up()
        self.code.answers["gate"] = Alternative.ADMIT
        self.rt.arming.disarm(CAP, actor=Actor.DASHBOARD)
        self.rt.states(fresh=True)
        self.assertIs(self.gate(), DEFER)

    def test_with_no_unit_left_one_it_took_up_waits_and_a_capacity_retry_falls_back(self):
        self.taken_up()
        self.fill(2)
        self.code.answers["gate"] = Alternative.ADMIT
        self.assertIs(self.gate(), Alternative.HOLD)
        self.assertEqual(self.lines()[-1], (JournalCode.CEILING, Point.GATES, Alternative.ADMIT))
        self.rt.state.admit(ac.KEY, CAP, Alternative.CAPACITY)
        self.code.answers["gate"] = Alternative.CAPACITY
        self.assertIs(self.gate(category="server_5xx"), DEFER)

    def test_taken_is_asked_the_first_time_core_goes_on_and_what_it_keeps_is_written_once(self):
        self.taken_up()
        seen = []
        self.code.answers.update(gate=Alternative.ADMIT, taken=lambda *arguments: (
            seen.append(arguments), {"code": "sampled", "sample": dict(self.rt.state.admission(ac.KEY),
                                                                      code="brandNewVariant",
                                                                      items={"agentMessage": 1})})[1])
        self.assertIs(self.gate(), Alternative.ADMIT)
        self.assertIs(self.gate(), Alternative.ADMIT)
        ((point, answer, name, record, _facts),) = seen
        self.assertEqual((point, answer, name, record["interruption_id"]),
                         (Point.GATES, Alternative.ADMIT, "known_failure", ac.KEY))
        (sample,) = self.rt.state.failure_samples(0)
        self.assertEqual((sample["tag"], sample["status"], sample["items_agent"]), ("brandNewVariant", 502, 1))
        self.assertTrue(self.rt.state.admission(ac.KEY)["sampled"])

    def test_watched_it_is_never_told_and_keeps_nothing(self):
        self.taken_up()
        self.armed("shadow")
        self.code.answers.update(gate=Alternative.ADMIT, taken={"code": "sampled"})
        self.assertIs(self.gate(), DEFER)
        self.assertNotIn("taken", self.code.asked)
        self.assertFalse(self.rt.state.admission(ac.KEY)["sampled"])

    def test_a_taken_that_raises_trips_it_and_costs_its_answer(self):
        self.taken_up()
        self.code.answers.update(gate=Alternative.ADMIT, taken=RuntimeError("boom"))
        self.assertIs(self.gate(), DEFER)
        self.assertEqual(self.rt.state.arming()[CAP]["reason"], OffReason.HOOK_EXCEPTION)
        self.assertFalse(self.rt.state.admission(ac.KEY)["sampled"])


class EngineCase(PluggedCase):
    """Core's own engine and store with an advanced plug that ships only the tests' capability: it
    takes every failure up with ADMIT, and again at known_failure."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.where = Path(temporary.name)
        self.definition = taking(ceilings=Ceilings(per_day=3, per_conversation=2))
        super().setUp()

    def advanced(self):
        h = self.h
        made = ac.advanced.AdvancedPlug(
            config.Paths(self.where / "home"), registry=Registry((self.definition,)), clock=lambda: h.now,
            policy=lambda: ac.policy.NONE, view=lambda: ac.view(), measured=lambda: {},
            catalogs=ac.catalogs(self.where, self.definition))
        self.addCleanup(lambda: made._runtime and made._runtime.state.close())
        runtime = made.runtime
        result = runtime.arming.arm(CAP, state="armed", revision=1, generation=runtime.state.meta()["generation"],
                                    acknowledged_version=ENGINE, actor=Actor.DASHBOARD)
        self.assertTrue(result["done"], result)
        runtime.states(fresh=True)
        code = ac.code_of(runtime)
        code.answers.update(admission=Alternative.ADMIT,
                            gate=lambda name, record, facts: Alternative.ADMIT if name == "known_failure" else DEFER)
        return made, code

    def taken_up(self):
        plug, code = self.advanced()
        self.h.now += 1
        failed(self.h, completed=self.h.now)
        self.plugged(plug)
        return plug, code

    def test_one_taken_up_before_a_restart_is_taken_up_again_once_and_sampled_once(self):
        plug, code = self.taken_up()
        self.h.tick()
        key = self.h.record()["interruption_id"]
        # The same failure put to it again - a restart between its answer and register, say - is the
        # one row, and still unsampled.
        plug.runtime.state.admit(key, CAP, Alternative.ADMIT)
        self.assertFalse(plug.runtime.state.admission(key)["sampled"])
        code.answers["taken"] = {"code": "sampled", "sample": {"code": "brandNewVariant", "status": None,
                                                               "form": FailureForm.TAGGED, "has_message": False}}
        held = []
        code.answers["gate"] = lambda name, record, facts: (
            Alternative.ADMIT if name == "known_failure"
            else Alternative.HOLD if name == "thread_available" and not held and not held.append(name)
            else DEFER)
        self.h.tick(advance=ladder.ADMITTED_WAITS[0])
        self.assert_no_send()
        self.h.tick(advance=ladder.ADMITTED_WAITS[0])
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertEqual(code.asked.count("taken"), 1)
        self.assertEqual(len(plug.runtime.state.failure_samples(0)), 1)
        self.assertTrue(plug.runtime.state.admission(key)["sampled"])

    def test_a_state_that_cannot_be_read_at_known_failure_holds_it_and_it_goes_once_it_can(self):
        plug, code = self.taken_up()
        self.h.tick()
        with patch.object(plug.runtime.state, "arming", side_effect=StateError("locked")):
            plug.runtime.states(fresh=True)
            self.h.tick(advance=ladder.ADMITTED_WAITS[0])
            row = self.h.record()
            self.assertEqual(row["state"], "waiting_backoff")
            self.assertEqual(json.loads(row["gate_eval"])["known_failure"], ["WAIT", "held"])
            self.assert_no_send()
        self.h.tick(advance=ladder.ADMITTED_WAITS[0])
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_turned_off_it_ends_what_it_took_up_unsent(self):
        plug, code = self.taken_up()
        self.h.tick()
        plug.runtime.arming.disarm(CAP, actor=Actor.DASHBOARD)
        self.h.tick(advance=ladder.ADMITTED_WAITS[0])
        row = self.h.record()
        self.assertEqual((row["state"], row["last_error"]), ("terminal_failure", "not_recoverable"))
        self.assert_no_send()

    def test_the_turn_it_took_up_is_of_the_conversation_and_turn_core_registered(self):
        plug, code = self.taken_up()
        self.h.tick()
        row = self.h.record()
        self.assertEqual((row["thread_id"], row["turn_id"], row["category"]), (T1, TURN_A, "unknown"))
        self.assertEqual(plug.runtime.state.admission(row["interruption_id"])["capability"], CAP)


if __name__ == "__main__":
    unittest.main()
