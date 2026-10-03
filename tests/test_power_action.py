"""v0.6.12: the power action after usage-limit recoveries - when it may act, decided without a side effect.

poweraction.py is pure: the arming, the records and the times go in, a decision comes out. These tests
hold its batch (what is a member, what is open, what is still followed), its classes (each record by
its own state and reason, nothing inherited), the three policies, the order of its ten checks - a stop
first of all, because pressing the stop button is itself input - and the strict reading of its file.
Nothing here touches a file, Windows or Codex.
"""
from __future__ import annotations

import ast
import math
from pathlib import Path
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import machine, poweraction as pa  # noqa: E402
from codex_auto_resume.domain import ids, states  # noqa: E402
from codex_auto_resume.domain.power_vocabulary import (PowerAction, PowerAfter, PowerClass, PowerEnd,  # noqa: E402
                                                       PowerWait)

SRC = Path(_HERE).parent / "src" / "codex_auto_resume"
NOW = 1_790_000_000.0
HOUR, DAY = 3600.0, 86400.0
NONCE = "fedcba9876543210"
OTHER_NONCE = "a" * 16


def key(n) -> str:
    return "%064x" % n


def row(n, state="recovered", *, category="usage_limit", detected=NOW - 600, outcome=None, reason=None,
        queue_id=None, submitted=None):
    """A record as the store hands one out, with only what the power action reads."""
    return {"interruption_id": key(n), "state": state, "category": category, "detected_at": detected,
            "outcome_at": NOW - 300 if outcome is None and state in states.TERMINAL else outcome,
            "last_error": reason, "queue_id": queue_id, "submitted_at": submitted}


def armed(**changes) -> dict:
    value = {"nonce": NONCE, "action": "sleep", "after": "all_recovered", "repeat": "once",
             "grace_seconds": 300, "armed_at": NOW - HOUR, "since": NOW - HOUR, "carried": [], "stop_at": None}
    value.update(changes)
    return value


def document(armed_value=None, **parts) -> dict:
    value = {"format": pa.FORMAT, "armed": armed() if armed_value is None else armed_value,
             "shown": None, "last": None}
    value.update(parts)
    return value


def facts(rows=(), *, arming=None, **changes) -> pa.Facts:
    values = {"now": NOW, "read": pa.READ_OK, "document": document(arming), "rows": tuple(rows)}
    values.update(changes)
    return pa.Facts(**values)


# --------------------------------------------------------------------------------- the words
class VocabularyTests(unittest.TestCase):
    def test_each_list_is_its_enum_in_order(self):
        self.assertEqual(pa.ACTIONS, ("sleep", "hibernate", "shut_down"))
        self.assertEqual(pa.AFTERS, ("all_recovered", "handed_over_too", "any_end"))
        self.assertEqual(pa.REPEATS, ("once", "always"))
        self.assertEqual(pa.ENDS, ("done", "failed", "skipped", "not_met", "stale", "lapsed", "unavailable"))
        self.assertEqual(pa.UNAVAILABLE, ("no_privilege", "no_sleep_state", "hibernate_off"))
        self.assertIn("history_behind", pa.WAITS)
        self.assertEqual(pa.GRACE_SECONDS, (120, 300, 600, 900, 1800))

    def test_the_defaults_are_a_choice_the_dashboard_may_make(self):
        self.assertIsNone(pa.choice_problem(dict(pa.DEFAULT_CHOICE)))
        self.assertEqual(pa.DEFAULT_CHOICE, {"action": "sleep", "after": "all_recovered", "repeat": "once",
                                             "grace_minutes": 5})

    def test_a_choice_is_exactly_its_four_keys_and_its_words(self):
        good = dict(pa.DEFAULT_CHOICE)
        for bad in ({}, dict(good, extra=1), {k: v for k, v in good.items() if k != "repeat"},
                    dict(good, action="restart"), dict(good, after="all"), dict(good, repeat="twice"),
                    dict(good, grace_minutes=7), dict(good, grace_minutes=True), dict(good, grace_minutes=5.0),
                    dict(good, grace_minutes="5"), dict(good, action=["sleep"]), None, "sleep"):
            with self.subTest(bad=bad):
                self.assertIsNotNone(pa.choice_problem(bad))
        for minutes in pa.GRACE_MINUTES:
            self.assertIsNone(pa.choice_problem(dict(good, grace_minutes=minutes)))

    def test_vocabulary_py_is_at_its_budget_and_the_power_words_live_beside_it(self):
        lines = (SRC / "domain" / "vocabulary.py").read_text(encoding="utf-8").splitlines()
        self.assertLessEqual(len(lines), 700)
        from codex_auto_resume.domain.vocabulary import ErrorCode
        self.assertEqual(ErrorCode.POWER_UNAVAILABLE, "power_unavailable")
        self.assertFalse(any("Power" in line for line in lines if line.startswith("class ")))


# --------------------------------------------------------------------------------- the file
class DocumentTests(unittest.TestCase):
    def test_a_good_file_reads_as_written(self):
        value = document(armed(carried=[key(1), key(2)], stop_at=NOW),
                         shown={"nonce": NONCE, "phase": "grace", "waiting_for": None, "grace_until": NOW + 300},
                         last={"action": "hibernate", "result": "skipped", "at": NOW - DAY})
        self.assertEqual(pa.read_document(value, NOW), value)
        self.assertEqual(pa.read_document(pa.blank(), NOW), pa.blank())
        waiting = document(shown={"nonce": NONCE, "phase": "waiting", "waiting_for": "person_active",
                                  "grace_until": None})
        self.assertEqual(pa.read_document(waiting, NOW), waiting)

    def test_anything_else_is_refused(self):
        bad_armed = [
            armed(nonce="ABCDEF0123456789"), armed(nonce="abc"), armed(nonce=12),
            armed(action="restart"), armed(after=None), armed(repeat="ONCE"),
            armed(grace_seconds=301), armed(grace_seconds=True), armed(grace_seconds=300.0),
            armed(armed_at=True), armed(armed_at=float("nan")), armed(armed_at=float("inf")),
            armed(since=NOW - 2 * HOUR), armed(since=NOW + 301, armed_at=NOW), armed(armed_at="now"),
            armed(stop_at=False), armed(stop_at=-1), armed(stop_at=1e13),
            armed(carried=[key(1), key(1)]), armed(carried=["ab" * 10]), armed(carried=[key(0xabc).upper()]),
            armed(carried=[key(n) for n in range(257)]), armed(carried=(key(1),)), armed(carried=None),
            dict(armed(), extra=1), {k: v for k, v in armed().items() if k != "stop_at"}]
        for value in bad_armed:
            with self.subTest(armed=value):
                self.assertIsNone(pa.read_document(document(value), NOW))
        shown = {"nonce": NONCE, "phase": "waiting", "waiting_for": None, "grace_until": None}
        for value in (document(shown=dict(shown, nonce=OTHER_NONCE)),
                      {"format": pa.FORMAT, "armed": None, "shown": shown, "last": None},
                      document(shown=dict(shown, phase="counting")),
                      document(shown=dict(shown, waiting_for="nothing")),
                      document(shown=dict(shown, phase="grace")),
                      document(shown=dict(shown, grace_until=NOW)),
                      document(shown=dict(shown, extra=1)),
                      document(last={"action": "sleep", "result": "maybe", "at": NOW}),
                      document(last={"action": "sleep", "result": "done", "at": True}),
                      document(last={"action": "sleep", "result": "done"}),
                      dict(document(), format="codex-auto-resume/power-action/2"),
                      dict(document(), extra=None),
                      {k: v for k, v in document().items() if k != "last"},
                      [], "text", None, 3):
            with self.subTest(value=value):
                self.assertIsNone(pa.read_document(value, NOW))

    def test_a_since_a_little_ahead_is_a_clock_set_right_and_more_is_refused(self):
        self.assertIsNotNone(pa.read_document(document(armed(armed_at=NOW + 299, since=NOW + 299)), NOW))
        self.assertIsNone(pa.read_document(document(armed(armed_at=NOW + 301, since=NOW + 301)), NOW))

    def test_the_view_never_carries_the_nonce(self):
        value = document(armed(carried=[key(1)]),
                         shown={"nonce": NONCE, "phase": "grace", "waiting_for": None, "grace_until": NOW + 60})
        shown = pa.view(value)
        self.assertNotIn(NONCE, repr(shown))
        self.assertNotIn(key(1), repr(shown))
        self.assertEqual(shown["armed"], {"action": "sleep", "after": "all_recovered", "repeat": "once",
                                          "grace_seconds": 300, "armed_at": NOW - HOUR, "since": NOW - HOUR})
        self.assertEqual(shown["shown"], {"phase": "grace", "waiting_for": None, "grace_until": NOW + 60})
        self.assertEqual(pa.view(None), {"armed": None, "shown": None, "last": None})


# --------------------------------------------------------------------------------- the batch
class BatchTests(unittest.TestCase):
    def test_members_are_the_carried_and_every_usage_limit_detected_since(self):
        arming = armed(carried=[key(1)], since=NOW - HOUR)
        rows = [row(1, "waiting_reset", detected=NOW - DAY),              # carried, from before
                row(2, detected=NOW - HOUR),                              # detected at the very start
                row(3, detected=NOW - HOUR - 1),                          # just before: not a member
                row(4, category="network_transient", detected=NOW - 60),   # a temporary error never is
                row(5, detected=NOW - 60, state="no_progress_exhausted")]  # a child of a later limit
        self.assertEqual([r["interruption_id"] for r in pa.members(rows, arming)], [key(1), key(2), key(5)])

    def test_open_is_every_state_that_is_not_a_stop_and_one_this_does_not_know(self):
        for state in machine.STATES:
            with self.subTest(state=state):
                self.assertEqual(pa.is_open({"state": state}), state not in machine.TERMINAL)
        self.assertTrue(pa.is_open({"state": "a_state_from_a_newer_version"}))

    def test_an_uncertain_submission_is_followed_while_it_owns_a_queue_row_or_for_a_day(self):
        window = pa.FOLLOW_SECONDS
        unknown = row(1, "submission_unknown", detected=NOW - 2 * DAY)
        self.assertFalse(states.still_followed(unknown, NOW, window))
        self.assertTrue(states.still_followed(dict(unknown, queue_id="q"), NOW, window))
        self.assertTrue(states.still_followed(dict(unknown, submitted_at=NOW - DAY), NOW, window))
        self.assertFalse(states.still_followed(dict(unknown, submitted_at=NOW - DAY - 1), NOW, window))
        self.assertTrue(states.still_followed(dict(unknown, detected_at=NOW - DAY + 1), NOW, window))
        self.assertTrue(states.still_followed(dict(unknown, detected_at=None), NOW, window))
        for state in machine.STATES - {"submission_unknown"}:
            with self.subTest(state=state):
                self.assertFalse(states.still_followed(dict(unknown, state=state, queue_id="q"), NOW, window))

    def test_the_engine_s_watch_skips_by_the_same_rule(self):
        """One rule: the watch's skip of an uncertain submission nobody follows is still_followed."""
        text = (SRC / "engine" / "reconcile.py").read_text(encoding="utf-8")
        self.assertIn("machine.still_followed(row, now, self.options[\"unknown_reconcile_window_seconds\"])", text)
        self.assertIs(machine.still_followed, states.still_followed)


class ClassTests(unittest.TestCase):
    def test_every_stop_has_a_class_and_nothing_unfinished_has_one(self):
        expected = {"recovered": PowerClass.SUCCESS, "handed_over": PowerClass.PERSON,
                    "superseded_by_user": PowerClass.PERSON, "stopped_by_user": PowerClass.PERSON,
                    "cancelled": PowerClass.PERSON}
        for state in machine.STATES:
            with self.subTest(state=state):
                found = pa.classify({"state": state, "last_error": None})
                if state not in machine.TERMINAL:
                    self.assertIsNone(found)
                else:
                    self.assertEqual(found, expected.get(state, PowerClass.OTHER))

    def test_superseded_is_a_person_s_only_after_newer_work_or_a_parent_they_took_over(self):
        for reason, expected in (("latest_turn_changed", PowerClass.PERSON),
                                 ("parent_handed_over", PowerClass.PERSON),
                                 ("duplicate_owner", PowerClass.OTHER), (None, PowerClass.OTHER),
                                 ("superseded", PowerClass.OTHER)):
            with self.subTest(reason=reason):
                self.assertEqual(pa.classify({"state": "superseded", "last_error": reason}), expected)

    def test_each_policy(self):
        S, P, O = PowerClass.SUCCESS, PowerClass.PERSON, PowerClass.OTHER
        cases = {(S,): (True, True, True), (S, S): (True, True, True), (S, P): (False, True, True),
                 (P,): (False, False, True), (P, P): (False, False, True), (S, O): (False, False, True),
                 (O,): (False, False, True), (): (False, False, False), (S, None): (False, False, False)}
        for classes, (all_recovered, handed_over_too, any_end) in cases.items():
            with self.subTest(classes=classes):
                self.assertEqual(pa.met("all_recovered", classes), all_recovered)
                self.assertEqual(pa.met("handed_over_too", classes), handed_over_too)
                self.assertEqual(pa.met("any_end", classes), any_end)
        self.assertFalse(pa.met("unknown_policy", (S,)))

    def test_a_child_born_stopped_is_classed_by_its_own_state_never_its_parent_s(self):
        """store/records.py makes a child already stopped: parent_cancelled, parent_handed_over, or
        exhausted at birth. Its parent is often recovered; the task's last usage limit was not."""
        parent = row(1, "recovered", detected=NOW - 900)
        born = {"no_progress_budget": "no_progress_exhausted", "chain_cap": "retry_budget_exhausted",
                "chain_time_cap": "retry_budget_exhausted", "recovery_budget": "retry_budget_exhausted"}
        for reason, state in born.items():
            with self.subTest(reason=reason):
                child = row(2, state, reason=reason, detected=NOW - 600)
                self.assertEqual(pa.classify(child), PowerClass.OTHER)
                for after, expected in (("all_recovered", PowerEnd.NOT_MET), ("handed_over_too", PowerEnd.NOT_MET),
                                        ("any_end", None)):
                    decision = pa.decide(facts([parent, child], arming=armed(after=after)))
                    if expected is None:
                        self.assertEqual(decision.verdict, pa.GO)
                    else:
                        self.assertEqual((decision.verdict, decision.word), (pa.END, expected))
        joined = row(2, "superseded", reason="parent_handed_over", detected=NOW - 600)
        self.assertEqual(pa.classify(joined), PowerClass.PERSON, "the person joined in: not a success")
        self.assertEqual(pa.decide(facts([parent, joined])).word, PowerEnd.NOT_MET)
        self.assertEqual(pa.decide(facts([parent, joined], arming=armed(after="handed_over_too"))).verdict, pa.GO)
        cancelled = row(2, "cancelled", reason="parent_cancelled", detected=NOW - 600)
        self.assertEqual(pa.classify(cancelled), PowerClass.PERSON)


# --------------------------------------------------------------------------------- the order
class DecideTests(unittest.TestCase):
    def test_no_file_or_nothing_armed_is_off(self):
        self.assertEqual(pa.decide(pa.Facts(now=NOW)), pa.Decision(pa.OFF))
        self.assertEqual(pa.decide(facts(document=pa.blank())), pa.Decision(pa.OFF))
        self.assertEqual(pa.decide(facts(read=pa.READ_MISSING, document=None)), pa.Decision(pa.OFF))

    def test_an_invalid_file_is_off_and_an_unreadable_one_waits(self):
        self.assertEqual(pa.decide(facts(read=pa.READ_INVALID, document=None)),
                         pa.Decision(pa.OFF, pa.OFF_INVALID))
        self.assertEqual(pa.decide(facts([row(1)], read=pa.READ_UNREADABLE, document=None, saw_open=True)),
                         pa.Decision(pa.WAIT, None, True))

    def test_an_administrator_s_key_is_off_before_anything_else_of_the_arming(self):
        self.assertEqual(pa.decide(facts([row(1)], managed=True, arming=armed(stop_at=NOW))),
                         pa.Decision(pa.OFF, pa.OFF_MANAGED))

    def test_a_stop_ends_the_batch_skipped_in_every_phase(self):
        """Step 3, before every check below it: the press is input, so a check of input first would end
        only the countdown, and the next countdown would follow the stop."""
        stop = armed(stop_at=NOW - 1)
        phases = {"no batch": [], "recovery open": [row(1, "waiting_reset")],
                  "delivery unknown": [row(1, "submission_unknown", queue_id="q")],
                  "ready": [row(1)], "not met": [row(1, "failed")], "stale": [row(1, outcome=NOW - DAY)]}
        for phase, rows in phases.items():
            for changes in ({}, {"ok": False}, {"paused": True}, {"saw_open": True}):
                with self.subTest(phase=phase, **changes):
                    self.assertEqual(pa.decide(facts(rows, arming=stop, **changes)),
                                     pa.Decision(pa.END, PowerEnd.SKIPPED))
        self.assertEqual(pa.decide(facts([], arming=armed(stop_at=NOW, repeat="always", armed_at=NOW - 2 * DAY,
                                                          since=NOW - 2 * DAY))).word, PowerEnd.SKIPPED)

    def test_a_failed_tick_and_a_pause_wait(self):
        self.assertEqual(pa.decide(facts([row(1)], ok=False)), pa.Decision(pa.WAIT, None))
        self.assertEqual(pa.decide(facts([row(1)], ok=False, paused=True)), pa.Decision(pa.WAIT, None))
        self.assertEqual(pa.decide(facts([row(1)], paused=True, saw_open=True)),
                         pa.Decision(pa.WAIT, PowerWait.PAUSED, True))

    def test_a_once_with_no_usage_limit_lapses_after_a_day(self):
        early = armed(armed_at=NOW - DAY + 1, since=NOW - DAY + 1)
        self.assertEqual(pa.decide(facts([], arming=early)), pa.Decision(pa.WAIT, PowerWait.NO_BATCH))
        late = armed(armed_at=NOW - DAY - 1, since=NOW - DAY - 1)
        self.assertEqual(pa.decide(facts([], arming=late)), pa.Decision(pa.END, PowerEnd.LAPSED))
        always = armed(armed_at=NOW - 30 * DAY, since=NOW - 30 * DAY, repeat="always")
        self.assertEqual(pa.decide(facts([], arming=always)), pa.Decision(pa.WAIT, PowerWait.NO_BATCH))
        transient = [row(1, "waiting_backoff", category="network_transient", detected=NOW - 60)]
        self.assertEqual(pa.decide(facts(transient, arming=late)).word, PowerEnd.LAPSED,
                         "a temporary error never makes a batch")

    def test_anything_open_waits_and_a_member_seen_open_is_remembered(self):
        member, transient = row(1, "waiting_reset"), row(2, "waiting_backoff", category="timeout")
        self.assertEqual(pa.decide(facts([member])), pa.Decision(pa.WAIT, PowerWait.RECOVERY_OPEN, True))
        self.assertEqual(pa.decide(facts([row(1), transient])), pa.Decision(pa.WAIT, PowerWait.RECOVERY_OPEN))
        old = row(3, "queued", detected=NOW - 2 * DAY)          # open, not a member: still holds it
        self.assertEqual(pa.decide(facts([row(1), old])).word, PowerWait.RECOVERY_OPEN)

    def test_an_uncertain_submission_still_followed_waits(self):
        followed = row(2, "submission_unknown", submitted=NOW - HOUR)
        self.assertEqual(pa.decide(facts([row(1), followed])), pa.Decision(pa.WAIT, PowerWait.DELIVERY_UNKNOWN, True))
        followed_other = dict(followed, category="server_5xx")
        self.assertEqual(pa.decide(facts([row(1), followed_other])).word, PowerWait.DELIVERY_UNKNOWN)
        given_up = row(2, "submission_unknown", detected=NOW - 2 * DAY, submitted=NOW - 2 * DAY)
        self.assertEqual(pa.decide(facts([row(1), given_up])).verdict, pa.GO, "not a member, not followed")
        self.assertEqual(pa.decide(facts([row(1), dict(given_up, detected_at=NOW - 60)])).word, PowerEnd.NOT_MET)

    def test_a_policy_not_met_ends_the_batch(self):
        for after in ("all_recovered", "handed_over_too"):
            with self.subTest(after=after):
                self.assertEqual(pa.decide(facts([row(1), row(2, "failed")], arming=armed(after=after))).word,
                                 PowerEnd.NOT_MET)
        self.assertEqual(pa.decide(facts([row(1), row(2, "failed")], arming=armed(after="any_end"))).verdict, pa.GO)

    def test_a_batch_that_ended_long_ago_unseen_is_stale(self):
        ended = [row(1, outcome=NOW - HOUR - 1)]
        self.assertEqual(pa.decide(facts(ended)), pa.Decision(pa.END, PowerEnd.STALE))
        self.assertEqual(pa.decide(facts(ended, saw_open=True)), pa.Decision(pa.GO, None, True))
        self.assertEqual(pa.decide(facts([row(1, outcome=NOW - HOUR + 1)])), pa.Decision(pa.GO))
        self.assertEqual(pa.decide(facts([row(1, outcome=None, detected=NOW - 60, state="recovered")
                                          | {"outcome_at": None}])).verdict, pa.GO, "detected_at, when no outcome")

    def test_go_passes_steps_one_to_ten_and_reads_nothing_itself(self):
        """decide is pure: it is handed what was read and asks nothing of Codex or Windows."""
        self.assertEqual(pa.decide(facts([row(1), row(2, "handed_over")], arming=armed(after="handed_over_too"))),
                         pa.Decision(pa.GO))
        tree = ast.parse((SRC / "poweraction.py").read_text(encoding="utf-8"))
        imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        self.assertLessEqual(imported, {"__future__", "dataclasses", "domain", "domain.power_vocabulary",
                                        "domain.states", "domain.vocabulary", None})


class AfterStepTenTests(unittest.TestCase):
    def test_codex_history_is_trusted_only_when_caught_up_and_the_counts_after(self):
        cases = [({"history": True, "running": 0, "queued": 0}, None),
                 ({"history": False, "running": 0, "queued": 0}, PowerWait.HISTORY_BEHIND),
                 ({"history": False, "running": None, "queued": None}, PowerWait.HISTORY_BEHIND),
                 ({"history": None, "running": 0, "queued": 0}, PowerWait.CODEX_UNKNOWN),
                 ({"history": True, "running": 1, "queued": 3}, PowerWait.TURN_RUNNING),
                 ({"history": True, "running": 0, "queued": 2}, PowerWait.QUEUED_INPUT),
                 ({"history": True, "running": None, "queued": 0}, PowerWait.CODEX_UNKNOWN),
                 ({"history": True, "running": 0, "queued": True}, PowerWait.CODEX_UNKNOWN),
                 ({"history": 1, "running": 0, "queued": 0}, PowerWait.CODEX_UNKNOWN),
                 ({}, PowerWait.CODEX_UNKNOWN), (None, PowerWait.CODEX_UNKNOWN)]
        for found, expected in cases:
            with self.subTest(found=found):
                self.assertEqual(pa.judge_activity(found), expected)

    def test_nobody_else_for_a_shut_down_and_nobody_here_for_any(self):
        for action in pa.ACTIONS:
            with self.subTest(action=action):
                shut = action == PowerAction.SHUT_DOWN
                self.assertEqual(pa.judge_presence(action, 1, 600), PowerWait.OTHER_PEOPLE if shut else None)
                self.assertEqual(pa.judge_presence(action, None, 600), PowerWait.OTHER_PEOPLE if shut else None)
                self.assertIsNone(pa.judge_presence(action, 0, 120))
                self.assertEqual(pa.judge_presence(action, 0, 119.9), PowerWait.PERSON_ACTIVE)
                self.assertEqual(pa.judge_presence(action, 0, None), PowerWait.IDLE_UNKNOWN)
                self.assertEqual(pa.judge_presence(action, 0, float("nan")), PowerWait.IDLE_UNKNOWN)
                self.assertEqual(pa.judge_presence(action, 0, True), PowerWait.IDLE_UNKNOWN)

    def test_a_countdown_ends_on_input_since_it_began_or_a_gap_between_looks(self):
        start = NOW - 100
        self.assertTrue(pa.countdown_holds(start, NOW - 15, NOW, 300))
        self.assertTrue(pa.countdown_holds(start, NOW - 15, NOW, 100))
        self.assertFalse(pa.countdown_holds(start, NOW - 15, NOW, 99), "input after it began")
        self.assertFalse(pa.countdown_holds(start, NOW - 91, NOW, 300), "a gap: a sleep or a stalled tick")
        self.assertFalse(pa.countdown_holds(start, NOW + 91, NOW, 300), "the clock set back")
        self.assertFalse(pa.countdown_holds(start, NOW - 15, NOW, None))
        self.assertTrue(math.isfinite(pa.GAP_SECONDS) and pa.COUNTDOWN_LOOK_SECONDS < pa.GAP_SECONDS)


class EngineActivityTests(unittest.TestCase):
    """engine.activity hands the source the batch's conversations and its own clock, and turns anything
    it cannot say into None, which judge_activity reads as codex_unknown."""

    def engine(self, source, clock=lambda: NOW):
        from codex_auto_resume.engine import Engine
        return Engine(None, source, None, clock=clock)

    def test_the_source_is_asked_with_the_batch_and_the_engine_s_clock(self):
        asked = []

        class Source:
            def activity(self, threads, now):
                asked.append((threads, now))
                return {"history": True, "running": 0, "queued": 0, "extra": "dropped"}
        found = self.engine(Source()).activity(["t1", "t2"])
        self.assertEqual(found, {"history": True, "running": 0, "queued": 0})
        self.assertEqual(asked, [(("t1", "t2"), NOW)])
        self.assertIsNone(pa.judge_activity(found))

    def test_a_source_that_cannot_answer_is_unknown(self):
        class Raising:
            def activity(self, threads, now):
                raise OSError("locked")

        class Odd:
            def activity(self, threads, now):
                return ["not", "a", "dict"]
        for source in (Raising(), Odd(), object()):
            with self.subTest(source=type(source).__name__):
                found = self.engine(source).activity()
                self.assertEqual(found, {"history": None, "running": None, "queued": None})
                self.assertEqual(pa.judge_activity(found), PowerWait.CODEX_UNKNOWN)

    def test_a_real_codex_home_that_lags_holds_the_action(self):
        """Through the real reader: Codex's history behind its file is history_behind, never nothing running."""
        import codexsim
        import tempfile
        import time
        from codex_auto_resume.codex import LocalSource
        with tempfile.TemporaryDirectory() as folder:
            home = codexsim.CodexHome(Path(folder))
            engine = self.engine(LocalSource(home.root), clock=time.time)
            self.assertIsNone(pa.judge_activity(engine.activity()))
            thread = codexsim.new_id()
            home.add_thread(thread)
            home.make_stale(thread)
            self.assertEqual(pa.judge_activity(engine.activity([thread])), PowerWait.HISTORY_BEHIND)
            home.catch_up(thread)
            home.enqueue(thread, "a message of the user's")
            self.assertEqual(pa.judge_activity(engine.activity([thread])), PowerWait.QUEUED_INPUT)


class NonceTests(unittest.TestCase):
    def test_a_nonce_is_sixteen_lowercase_hex_digits(self):
        self.assertTrue(ids.is_power_nonce(NONCE))
        for bad in ("A" * 16, "a" * 15, "a" * 17, "g" * 16, None, 16, b"a" * 16, " " + "a" * 15):
            with self.subTest(bad=bad):
                self.assertFalse(ids.is_power_nonce(bad))


if __name__ == "__main__":
    unittest.main()
