"""Where core asks the edition's plug, and what it does with each answer: the second half of tests/test_plug_points.py.

The capabilities that move a record's waits within core's own bounds - a capacity error retried sooner (CAPACITY), a
usage limit looked at early (EARLY), an uncertain continuation sent once more (RESEND) and Send now (SEND_NOW) - each
held where core asks for it, against the same real store, Codex home and simulated backend as the first half. They were
one file with it, the longest of the suite but two, and one file is what scripts/test_parts.py deals into a CI part;
so they are a module of their own, with the first half's harness (PluggedCase, Asked and the failures it makes)
imported from it rather than copied.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)        # the simulated Codex home and the engine's harness live next to this file

from codexsim import new_id  # noqa: E402
from test_engine import T1, T2, TURN_A, TURN_B, fail_turn  # noqa: E402
# The first half's harness; its cases are not bound here, so each runs in its own module alone.
from test_plug_points import (OVERLOADED, Asked, Fixed, PluggedCase, QueueAdd, Resume,  # noqa: E402
                              admissions, admitting, failed, holding)
from codex_auto_resume import ladder, machine, managed, settings  # noqa: E402
from codex_auto_resume.domain import ids  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Alternative, Point, guard  # noqa: E402
from codex_auto_resume.machine import TERMINAL, WAITING  # noqa: E402


class CapacityTests(PluggedCase):
    """CAPACITY: a capacity error the plug vouches for retries sooner and more often, within core's
    own bounds - a minute, two, four and five, each lengthened by up to a fifth, a minute apart, 48
    a day, for twelve hours on the clock from its task's first failure - however long a plug says so."""

    def vouched(self, h=None, draw=0.0, plug=None):
        h = h or self.h
        failed(h, OVERLOADED)
        engine = self.plugged(plug or admitting(Alternative.CAPACITY), h)
        engine._random = Fixed(draw)
        h.backend.after_accept = "queue"
        h.tick()
        return engine

    def continue_and_fail(self, h, step=10):
        """The continuation that is due goes, Codex runs it, and it fails at capacity again: the
        record of that failure."""
        sent = len(h.backend.send_calls)
        for _ in range(60):
            h.tick(advance=step)
            if len(h.backend.send_calls) > sent:
                break
        self.assertEqual(len(h.backend.send_calls), sent + 1, "a continuation was sent")
        turn = h.home.dispatch(T1, status="inProgress", progress=False)
        fail_turn(h.home, T1, turn, error_json=OVERLOADED)
        h.tick(advance=1)
        return h.records()[-1]

    def test_the_first_wait_is_a_minute_lengthened_by_up_to_a_fifth(self):
        for draw, wait in ((0.0, 60), (0.5, 66), (0.99, 72)):
            with self.subTest(draw=draw):
                h = self.fresh()
                plug = admitting(Alternative.CAPACITY)
                self.vouched(h, draw, plug)
                (facts,) = admissions(plug)
                self.assertEqual(facts["takes"], {Alternative.CAPACITY})
                row = h.record()
                self.assertEqual((row["category"], row["next_retry_at"] - h.now), ("server_5xx", wait))

    def test_it_retries_at_two_four_and_five_minutes_past_the_standard_floor_and_budgets(self):
        h = self.h
        self.vouched(h)
        times = []
        h.backend.on_send = lambda thread, prompt: times.append(h.now)
        waits = [self.continue_and_fail(h)["next_retry_at"] - h.now for _ in range(8)]
        self.assertEqual(waits, [120, 240, 300, 300, 300, 300, 300, 300])
        gaps = [later - earlier for earlier, later in zip(times, times[1:])]
        self.assertTrue(all(ladder.CAPACITY_SPACING <= gap < ladder.SPACING for gap in gaps), gaps)
        # Eight continuations in an hour: more than the standard edition's five a day, four attempts
        # and six continuations of one task.
        self.assertEqual(len(h.backend.send_calls), 8)
        self.assertNotIn(h.records()[-1]["state"], TERMINAL)

    def test_never_more_than_core_allows_however_long_the_plug_says_so(self):
        h = self.h
        self.vouched(h)
        for _ in range(60):
            if h.records()[-1]["state"] in TERMINAL:
                break
            self.continue_and_fail(h, step=60)
        self.assertEqual(len(h.backend.send_calls), ladder.CAPACITY_PER_DAY)
        self.assertIn(h.records()[-1]["state"], ("no_progress_exhausted", "retry_budget_exhausted"))
        self.assertLess(h.now - h.records()[0]["detected_at"], ladder.CAPACITY_MAX_SECONDS)

    def test_an_administrators_max_recovery_attempts_still_holds_it(self):
        """CAPACITY passes the person's own budgets, never the administrator's ceiling (managed.clamp):
        with MaxRecoveryAttempts at 2, two continuations go and the task ends on its attempt budget."""
        h = self.h
        failed(h, OVERLOADED)
        engine = self.plugged(admitting(Alternative.CAPACITY), h)
        engine.apply_policy(settings.defaults(), managed.Managed(max_recovery_attempts=2))
        engine._random = Fixed(0.0)
        h.backend.after_accept = "queue"
        h.tick()
        self.assertEqual(engine.capacity_limits()["max_recovery_attempts"], 2)
        for _ in range(2):
            self.continue_and_fail(h)
        for _ in range(30):
            h.tick(advance=60)
        row = h.records()[-1]
        self.assertEqual((row["state"], row["last_error"]), ("retry_budget_exhausted", "recovery_budget"))
        self.assertEqual(len(h.backend.send_calls), 2)
        engine.apply_policy(settings.defaults())
        self.assertEqual(engine.capacity_limits()["max_recovery_attempts"], ladder.CAPACITY_PER_DAY)

    def test_twelve_hours_on_the_clock_end_it_whatever_it_waited_aside(self):
        h = self.h
        self.vouched(h)
        for _ in range(5):
            self.continue_and_fail(h)          # past the standard edition's four attempts
        origin, sent = h.records()[0], len(h.backend.send_calls)
        holding = Asked(wants=True, admission=Alternative.CAPACITY, gate=lambda name, record, facts: (
            Alternative.HOLD if name == "usage" else Alternative.CAPACITY if name == "known_failure"
            else DEFER))
        self.plugged(holding)._random = Fixed(0.0)
        while h.now + 600 - origin["detected_at"] < ladder.CAPACITY_MAX_SECONDS:
            h.tick(advance=600)
            self.assertNotIn(h.records()[-1]["state"], TERMINAL)
        h.tick(advance=600)                    # and now twelve hours on the clock have passed
        row = h.records()[-1]
        self.assertEqual((row["state"], row["last_error"]), ("retry_budget_exhausted", "recovery_budget"))
        self.assertEqual(len(h.backend.send_calls), sent)
        # Held at the usage gate all that time, which counts toward no time ceiling: on the clock it
        # is twelve hours, counted it is a few minutes - and the clock is what bounds CAPACITY.
        self.assertLess(h.now - row["chain_first_detected_at"], 3600)

    def test_another_server_error_is_never_vouched_for(self):
        rows = []
        for plug in (None, admitting(Alternative.CAPACITY)):
            h = self.fresh()
            failed(h, json.dumps({"codexErrorInfo": "internalServerError"}))
            self.plugged(plug, h)
            h.tick()
            rows.append((h.record()["state"], h.record()["next_retry_at"]))
            if plug is not None:
                self.assertEqual(admissions(plug), [])
        self.assertEqual(rows[0], rows[1])

    def test_the_claim_takes_a_capacity_retry_only_within_its_twelve_hours(self):
        self.vouched()
        row = self.h.record()
        ledger, key = guard(admitting(Alternative.CAPACITY)), row["interruption_id"]
        late = row["detected_at"] + ladder.CAPACITY_MAX_SECONDS
        for at, options in ((late, {"ledger": ledger, "carried": {Point.GATES}}),
                            (row["next_retry_at"], {"ledger": None, "carried": {Point.GATES}}),
                            (row["next_retry_at"], {"ledger": ledger, "carried": frozenset()})):
            with self.subTest(at=at - row["detected_at"], options=sorted(options)):
                self.assertEqual(self.h.store.reserve_detailed(key, at, relaxed="capacity", **options),
                                 (False, "chain_budget", "capacity_window"))
        self.assertEqual(self.h.store.reserve_detailed(key, late - 1, relaxed="capacity", ledger=ledger,
                                                       carried={Point.GATES}), (True, None, None))

    def test_a_task_older_than_twelve_hours_is_not_offered_capacity(self):
        """At P17 too: a capacity failure of a task that first failed twelve hours ago on the clock is
        offered nothing, and is registered as the standard edition registers it."""
        h = self.h
        self.vouched(h)
        h.now = h.records()[0]["detected_at"] + ladder.CAPACITY_MAX_SECONDS
        plug = Asked(wants=True, admission=Alternative.CAPACITY)
        engine = self.plugged(plug)
        child = self.continue_and_fail(h)
        self.assertEqual(admissions(plug), [])
        self.assertEqual(child["next_retry_at"] - h.now, engine.first_delay("server_5xx"))


NO_USAGE = {"available": False, "reset_at": None, "limit_type": "exposed_windows", "reason": "ok"}


class EarlyTests(PluggedCase):
    """EARLY (P7 before its time): a record that waits for a usage limit to reset may be looked at
    early, once a window for every record together - and a look that finds no usage, or meets any
    other wait, leaves it exactly as it was."""

    def waiting(self, h=None, thread=T1, turn=TURN_A):
        h = h or self.h
        h.home.fail_usage(thread, turn)
        h.backend.loaded_map[thread] = "loaded"
        h.tick()
        row = h.record(thread)
        self.assertEqual(row["state"], "waiting_reset")
        return row

    def test_only_a_record_waiting_for_a_usage_reset_is_looked_at_early(self):
        before = self.waiting()
        self.plugged(Asked(wants=True, schedule=Alternative.EARLY))
        self.h.tick(advance=60)
        self.assertLess(self.h.now, before["reset_at"])
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertEqual(self.h.record()["state"], "queued")
        h = self.fresh()
        failed(h, json.dumps({"codexErrorInfo": "internalServerError"}))
        plug = Asked(wants=True, schedule=Alternative.EARLY)
        self.plugged(plug, h)
        h.tick()
        h.tick(advance=1)
        # P7 may be asked about it for a person's Send now (SEND_NOW), which this plug never says;
        # it is never looked at early, and no early window opens for it.
        self.assertEqual((h.backend.send_calls, h.engine._early_at, h.engine._early_look), ([], None, None))
        # NULL is never asked early, and a plug that wants no schedule is not either.
        for plug in (None, Asked(schedule=Alternative.EARLY)):
            h = self.fresh()
            self.waiting(h)
            self.plugged(plug, h)
            h.tick(advance=60)
            self.assertEqual(h.backend.send_calls, [])

    def test_a_look_that_finds_no_usage_or_any_other_wait_leaves_the_record_as_it_was(self):
        kept = ("state", "last_error", "next_retry_at", "usage_probe_at", "usage_unavailable_seconds",
                "reset_at", "attempt_count")
        for how in ("no_usage", "held", "loaded_recheck"):
            with self.subTest(how):
                h = self.fresh()
                before = self.waiting(h)
                plug = Asked(wants=True, schedule=Alternative.EARLY, gate=(
                    lambda name, record, facts: Alternative.HOLD if name == "usage" else DEFER)
                    if how == "held" else DEFER)
                self.plugged(plug, h)
                if how == "no_usage":
                    h.backend.usage_result = dict(NO_USAGE)
                elif how == "loaded_recheck":
                    real = h.backend.loaded
                    looks = []

                    def loaded(thread_id, app):
                        looks.append(thread_id)
                        return real(thread_id, app) if len(looks) == 1 else "notLoaded"
                    h.backend.loaded = loaded
                h.tick(advance=60)
                after = h.record()
                self.assertEqual(h.backend.send_calls, [])
                self.assertEqual({key: after[key] for key in kept}, {key: before[key] for key in kept})
                self.assertEqual(plug.hooks().count("schedule"), 1)
                # It was looked at: the wait it met is written down, and that is all.
                self.assertEqual(json.loads(after["gate_eval"])["schedule"], ["PASS", "plugged"])
                if how == "loaded_recheck":
                    self.assertEqual(len(looks), 2, "the look in the lock found it no longer open")

    def test_the_claim_skips_a_reset_only_as_a_relaxation_its_ledger_pays_for(self):
        row = self.waiting()
        ledger = guard(Asked(wants=True))
        key, at = row["interruption_id"], self.h.now + 60
        self.assertEqual(self.h.store.reserve_detailed(key, at), (False, "schedule", "not_due"))
        for options in ({"ledger": None, "carried": {Point.SCHEDULE}},
                        {"ledger": ledger, "carried": frozenset()},
                        {"ledger": ledger, "carried": {Point.GATES}}):
            with self.subTest(options=sorted(options)):
                self.assertEqual(self.h.store.reserve_detailed(key, at, relaxed="early", **options),
                                 (False, "schedule", "not_due"))
        self.assertEqual(self.h.store.reserve_detailed(key, at, relaxed="early", ledger=ledger,
                                                       carried={Point.SCHEDULE}), (True, None, None))
        h = self.fresh()
        failed(h, json.dumps({"codexErrorInfo": "internalServerError"}))
        h.tick()
        other = h.record()
        self.assertEqual(h.store.reserve_detailed(other["interruption_id"], h.now, relaxed="early",
                                                  ledger=ledger, carried={Point.SCHEDULE}),
                         (False, "schedule", "not_due"))

    def test_a_postponement_and_quiet_hours_still_hold(self):
        for how in ("postponed", "quiet_hours"):
            with self.subTest(how):
                h = self.fresh()
                row = self.waiting(h)
                plug = Asked(wants=True, schedule=Alternative.EARLY)
                engine = self.plugged(plug, h)
                if how == "postponed":
                    self.assertTrue(h.store.postpone(row["interruption_id"], T1, h.now + 7200, h.now)[0])
                else:
                    engine.quiet_until = lambda now: now + 3600
                h.tick(advance=60)
                self.assertEqual(h.backend.send_calls, [])
                self.assertEqual(plug.hooks().count("schedule"), 0)

    def test_a_usage_limit_a_usage_read_found_waiting_for_is_looked_at_early_and_sent(self):
        """v0.6.14: a usage-limited record a usage read found waiting - none available when it fell due -
        is looked at early too (waiting_for_usage), only while the plug wants the schedule; and the claim
        takes that look as it takes one at a reset, so it is sent. NULL never looks early, and a plug that
        wants no schedule is not asked."""
        for plug, sent in ((None, 0), (Asked(schedule=Alternative.EARLY), 0),
                           (Asked(wants=True, schedule=Alternative.EARLY), 1)):
            with self.subTest(plug=None if plug is None else plug.answers.get("wants", False)):
                h = self.fresh()
                self.ready_after_reset(h)
                h.backend.usage_result = dict(NO_USAGE)
                h.tick()
                row = h.record()
                self.assertEqual(row["state"], "waiting_for_usage")
                self.assertGreater(row["next_retry_at"], h.now + 120, "its own next look is far off")
                h.backend.usage_result = {"available": True, "reset_at": None, "limit_type": "exposed_windows",
                                          "reason": "ok"}
                self.plugged(plug, h)
                h.tick(advance=60)
                self.assertEqual(len(h.backend.send_calls), sent)
                self.assertEqual(h.record()["state"], "queued" if sent else "waiting_for_usage")

    def test_the_claim_takes_an_early_look_at_a_record_waiting_for_usage_as_its_ledger_pays_for_it(self):
        h = self.h
        self.ready_after_reset(h)
        h.backend.usage_result = dict(NO_USAGE)
        h.tick()
        row = h.record()
        self.assertEqual(row["state"], "waiting_for_usage")
        key, at = row["interruption_id"], h.now + 60
        self.assertEqual(h.store.reserve_detailed(key, at), (False, "schedule", "not_due"))
        self.assertEqual(h.store.reserve_detailed(key, at, relaxed="early", ledger=guard(Asked(wants=True)),
                                                  carried={Point.SCHEDULE}), (True, None, None))

    def test_one_window_in_five_minutes_serves_every_record_with_one_usage_reading(self):
        h = self.h
        self.waiting(h, T1, TURN_A)
        self.waiting(h, T2, TURN_B)
        h.backend.usage_result = dict(NO_USAGE)
        reads, real = [], h.backend.usage
        h.backend.usage = lambda: (reads.append(h.now), real())[1]
        plug = Asked(wants=True, schedule=Alternative.EARLY)
        self.plugged(plug)

        def asked():
            return sorted(arguments[0]["thread_id"] for hook, arguments in plug.asked if hook == "schedule")
        h.tick(advance=60)
        self.assertEqual((asked(), len(reads)), (sorted([T1, T2]), 1))
        h.tick(advance=60)
        h.tick(advance=60)
        self.assertEqual((asked(), len(reads)), (sorted([T1, T2]), 1))
        h.tick(advance=ladder.EARLY_SPACING - 120)
        self.assertEqual((asked(), len(reads)), (sorted([T1, T1, T2, T2]), 2))
        self.assertEqual(h.backend.send_calls, [])



def resend_answer(record, due):
    """P7 as a capability that sends an uncertain submission once more answers it."""
    return Alternative.RESEND if record["state"] == "submission_unknown" else DEFER


def resending(**answers):
    return Asked(schedule=resend_answer, **answers)


def unknown_asked(plug, hook="schedule"):
    """The records `hook` was asked about while core held them as uncertain submissions."""
    return [arguments for name, arguments in plug.asked if name == hook
            and isinstance(arguments[0], dict) and arguments[0].get("state") == "submission_unknown"]


class ResendTests(PluggedCase):
    """RESEND (P7, v0.6.14): an uncertain submission sent once more, where the plug asks and core
    proves no copy of it anywhere. Driven by ticks and the clock alone, so the watch's own fifteen
    minutes between looks are what each test meets: no column is set by hand to make it due."""

    def uncertain(self, h=None, plug=None):
        """A usage-limited record whose continuation went out with an unknown answer, sent by an
        engine that holds `plug` from before the send; Codex accepts the next send."""
        h = h or self.h
        plug = plug if plug is not None else resending()
        self.plugged(plug, h)
        self.due(h)
        h.backend.default_outcome = "unknown"
        h.tick()
        row = h.record()
        self.assertEqual((row["state"], row["last_error"]),
                         ("submission_unknown", "queue_result_unknown_do_not_resend"))
        h.backend.default_outcome = "accepted"
        return row, plug

    def hours(self, h, hours, step=900):
        for _ in range(int(hours * 3600 // step)):
            h.tick(advance=step)

    def test_it_goes_once_after_fifteen_minutes_with_its_words_and_marker_and_charges_nothing(self):
        h = self.h
        first, _plug = self.uncertain()
        h.tick(advance=1)                          # the watch's first look: nothing, and 15 minutes on
        h.tick(advance=898)
        self.assertEqual(len(h.backend.send_calls), 1, "nothing before fifteen minutes")
        h.tick(advance=2)                          # its next look, past fifteen minutes
        self.assertEqual(len(h.backend.send_calls), 2)
        self.assertEqual(h.backend.send_calls[1], h.backend.send_calls[0], "the same thread, words, marker")
        self.assertTrue(self.prompt().endswith(first["marker"]))
        row = h.record()
        self.assertTrue(machine.was_resent(row))
        self.assertEqual((row["attempt_count"], row["recovery_attempts"], row["chain_continuations"]),
                         (2, first["recovery_attempts"], first["chain_continuations"]))
        self.follow()
        row = h.record()
        self.assertEqual(row["state"], "recovered")
        self.assertNotIn("ambiguous_receipt", [event["reason"] for event in h.store.events(row["interruption_id"])])
        self.hours(h, 7)
        self.assertEqual(len(h.backend.send_calls), 2)

    def test_after_six_hours_nothing_is_resent(self):
        asks = {"now": False}
        h = self.h
        self.uncertain(plug=Asked(schedule=lambda record, due: resend_answer(record, due)
                                  if asks["now"] else DEFER))
        self.hours(h, 6.25)
        asks["now"] = True
        self.hours(h, 2)
        self.assertEqual(len(h.backend.send_calls), 1)
        self.assertEqual(h.record()["state"], "submission_unknown")

    def test_a_look_that_raises_or_one_the_budget_skips_resends_nothing(self):
        for how in ("raises", "skipped"):
            with self.subTest(how):
                h = self.fresh()
                self.uncertain(h)
                h.tick(advance=1)
                if how == "raises":
                    with patch.object(type(h.source), "marker_rows", side_effect=OSError("locked")):
                        h.tick(advance=900)
                else:
                    h.engine.options["watch_budget_seconds"] = -1
                    h.tick(advance=900)
                    h.engine.options["watch_budget_seconds"] = 5
                self.assertEqual(len(h.backend.send_calls), 1)
                h.tick(advance=1)                  # a look that reads Codex, and finds nothing
                self.assertEqual(len(h.backend.send_calls), 2)

    def test_its_marker_in_codexs_history_or_queue_stops_it(self):
        for where in ("history", "queue"):
            with self.subTest(where):
                h = self.fresh()
                row, _plug = self.uncertain(h)
                if where == "history":
                    h.home.add_turn(T1, None, "completed", user_text="go on\n\n" + row["marker"])
                else:
                    h.home.enqueue(T1, "go on\n\n" + row["marker"])
                self.hours(h, 6)
                self.assertEqual(len(h.backend.send_calls), 1)
                self.assertFalse(machine.was_resent(h.record()))

    def test_one_seen_in_codexs_queue_and_gone_from_it_is_never_resent(self):
        """Removed in Codex by a person, its reason still the unknown send's: core's own words for
        what a person decided, never overridden. Seen as it was queued, seen in place after an
        unknown answer with or without a client id of Codex's, or sent before the sightings were
        forgotten."""
        for how in ("queued", "seen with codex's id", "seen with none", "forgotten"):
            with self.subTest(how):
                h = self.fresh()
                plug = resending()
                self.plugged(plug, h)
                self.due(h)
                h.backend.after_accept = "queue"
                if how == "queued":
                    h.tick()
                    self.assertEqual(h.record()["state"], "queued")
                elif how == "forgotten":
                    h.backend.default_outcome = "unknown"
                    h.tick()
                else:
                    client = new_id() if how == "seen with codex's id" else None
                    h.backend.default_outcome = "unknown"
                    h.backend.on_send = lambda thread, prompt: h.home.enqueue(thread, prompt, client_id=client)
                    h.tick()
                    h.backend.on_send = None
                    h.watch(advance=1)
                    self.assertEqual(h.home.queued(T1), [h.record()["queue_id"]])
                for queue_id in h.home.queued(T1):
                    h.home.remove_queued(queue_id)
                if how == "forgotten":                 # one more than it remembers: all forgotten
                    for index in range(4097):
                        h.engine._sighted("%064x" % index)
                    self.assertEqual(h.engine._seen_queued_cleared_at, h.now)
                h.backend.default_outcome = "accepted"
                self.hours(h, 6)
                row = h.record()
                self.assertEqual(row["state"], "submission_unknown")
                self.assertIn(row["last_error"], machine.RESENDABLE)
                self.assertEqual(len(h.backend.send_calls), 1)

    def test_a_later_turn_or_someones_queued_input_stops_it(self):
        for how in ("turn", "queued"):
            with self.subTest(how):
                h = self.fresh()
                self.uncertain(h)
                if how == "turn":
                    h.home.add_turn(T1, None, "completed", user_text="their own message")
                else:
                    h.home.enqueue(T1, "their own message")
                self.hours(h, 6)
                self.assertEqual(len(h.backend.send_calls), 1)

    def test_a_history_seen_behind_since_the_send_or_a_watcher_started_since_stops_it(self):
        for how in ("behind", "restarted"):
            with self.subTest(how):
                h = self.fresh()
                self.uncertain(h)
                if how == "behind":
                    h.home.make_stale(T1)
                    h.tick(advance=1)
                    h.home.catch_up(T1)
                else:
                    self.plugged(resending(), h)
                self.hours(h, 6)
                self.assertEqual(len(h.backend.send_calls), 1)

    def test_no_other_uncertain_reason_is_resent(self):
        for reason in ("duplicate_marker", "ambiguous_receipt", "withdraw_unconfirmed",
                       "queue_cleanup_unconfirmed", "released_before_send", "queue_process_not_started"):
            with self.subTest(reason):
                h = self.fresh()
                row, _plug = self.uncertain(h)
                h.store.update(row["interruption_id"], at=h.now, last_error=reason)
                self.hours(h, 6)
                self.assertEqual(len(h.backend.send_calls), 1)

    def test_a_spent_attempt_budget_the_persons_or_the_administrators_stops_it(self):
        sent = {}
        for how in ("budget left", "persons", "administrators"):
            with self.subTest(how):
                h = self.fresh()
                engine = self.plugged(resending(), h)
                if how == "persons":
                    engine.apply_policy(dict(settings.defaults(), max_recovery_attempts=1))
                elif how == "administrators":
                    engine.apply_policy(settings.defaults(), managed.Managed(max_recovery_attempts=1))
                failed(h, OVERLOADED)
                h.tick()
                h.now = h.record()["next_retry_at"] + 1
                h.backend.default_outcome = "unknown"
                h.tick()
                self.assertEqual((h.record()["state"], h.record()["recovery_attempts"]), ("submission_unknown", 1))
                h.backend.default_outcome = "accepted"
                self.hours(h, 1)
                sent[how] = len(h.backend.send_calls)
        self.assertEqual(sent, {"budget left": 2, "persons": 1, "administrators": 1})

    def test_a_hold_at_any_gate_a_send_passes_sends_nothing_and_writes_nothing(self):
        for name in ("submission_safe", "chain_budget", "no_progress_budget", "thread_available",
                     "attempt_budget", "usage"):
            with self.subTest(name):
                h = self.fresh()
                plug = resending(gate=lambda gate, record, facts, name=name: (
                    Alternative.HOLD if gate == name and record["state"] == "submission_unknown" else DEFER))
                first, _plug = self.uncertain(h, plug)
                self.hours(h, 1)
                row = h.record()
                self.assertEqual(len(h.backend.send_calls), 1)
                self.assertEqual((row["state"], row["attempt_count"], row["gate_eval"]),
                                 ("submission_unknown", 1, first["gate_eval"]))
                held = [arguments[0] for hook, arguments in plug.asked
                        if hook == "gate" and arguments[1]["state"] == "submission_unknown"]
                self.assertIn(name, held, "the plug was asked at that gate, of the uncertain record")

    def test_a_resent_continuation_is_never_resent_again(self):
        h = self.h
        self.uncertain()
        h.backend.default_outcome = "unknown"
        self.hours(h, 7)
        row = h.record()
        self.assertEqual(len(h.backend.send_calls), 2)
        self.assertEqual((row["state"], row["last_error"]),
                         ("submission_unknown", "queue_result_unknown_do_not_resend"))
        self.assertTrue(machine.was_resent(row))

    def test_given_back_before_its_send_or_never_started_it_stays_uncertain_and_never_waits(self):
        for how in ("pre-send look", "not started", "consent refused at the guard"):
            with self.subTest(how):
                h = self.fresh()
                first, _plug = self.uncertain(h)
                key = first["interruption_id"]
                before = len(h.store.events(key))
                if how == "pre-send look":
                    h.engine.presend_problem = lambda claim: ("waiting_retry", "released_before_send", 60)
                elif how == "not started":
                    h.backend.default_outcome = "not_started"
                else:
                    real = h.engine.presend_problem

                    def look_then_pause(claim):
                        found = real(claim)
                        h.store.set_enabled(False, h.now)
                        return found
                    h.engine.presend_problem = look_then_pause
                h.tick(advance=1)
                h.tick(advance=900)
                row = h.record()
                self.assertEqual(row["state"], "submission_unknown")
                self.assertTrue(machine.was_resent(row))
                h.store.set_enabled(True, h.now)
                h.backend.default_outcome = "accepted"
                self.hours(h, 6)
                self.assertEqual(h.record()["state"], "submission_unknown")
                moves = [event["to_state"] for event in h.store.events(key)[before:]]
                self.assertIn("submitting", moves)
                self.assertEqual([state for state in moves if state in WAITING], [])
                self.assertEqual(len(h.backend.send_calls), 2 if how == "not started" else 1)

    def test_a_pause_or_observe_only_that_takes_a_queued_resend_back_ends_it_failed(self):
        for how in ("pause", "observe only"):
            with self.subTest(how):
                h = self.fresh()
                self.uncertain(h)
                h.backend.after_accept = "queue"
                h.tick(advance=1)
                h.tick(advance=900)
                self.assertEqual((len(h.backend.send_calls), h.record()["state"]), (2, "queued"))
                if how == "pause":
                    h.store.set_enabled(False, h.now)
                else:
                    h.store.set_observe_only(True)
                h.tick(advance=1)
                self.assertEqual(h.record()["state"], "withdrawn_unconfirmed")
                self.assertEqual(h.record()["withdraw_reason"],
                                 "paused_unknown" if how == "pause" else "observe_only_unknown")
                h.tick(advance=181)
                self.assertEqual(h.record()["state"], "failed")
                h.store.set_enabled(True, h.now)
                h.store.set_observe_only(False)
                self.hours(h, 6)
                self.assertEqual((len(h.backend.send_calls), h.record()["state"]), (2, "failed"))

    def test_a_pause_observe_only_a_cancel_or_a_conversation_off_is_never_put_to_p7(self):
        for how in ("pause", "observe only", "cancel", "conversation off"):
            with self.subTest(how):
                h = self.fresh()
                row, plug = self.uncertain(h)
                if how == "pause":
                    h.store.set_enabled(False, h.now)
                elif how == "observe only":
                    h.store.set_observe_only(True)
                elif how == "cancel":
                    h.store.cancel_interruption(row["interruption_id"], h.now)
                else:
                    h.store.set_thread_enabled(T1, False, at=h.now)
                self.hours(h, 2)
                self.assertEqual(unknown_asked(plug), [])
                self.assertEqual(len(h.backend.send_calls), 1)

    def test_its_ledger_is_told_the_send_carries_the_schedule_and_a_hold_sends_nothing(self):
        told = []

        def ledger(connection, record, now, carried):
            told.append((record["state"], carried))
            return Alternative.HOLD if record["state"] == "submission_unknown" else DEFER
        h = self.h
        first, _plug = self.uncertain(plug=resending(claim_ledger=ledger))
        h.tick(advance=1)
        h.tick(advance=900)
        self.assertIn(("submission_unknown", frozenset({Point.SCHEDULE})), told)
        row = h.record()
        self.assertEqual(len(h.backend.send_calls), 1)
        self.assertEqual((row["state"], row["attempt_count"], row["gate_eval"]),
                         ("submission_unknown", 1, first["gate_eval"]))

    def test_one_first_sent_with_no_marker_goes_again_only_through_a_channel_under_its_id(self):
        for how in ("channel", "no channel"):
            with self.subTest(how):
                h = self.fresh()
                channel = QueueAdd(h, outcome="unknown", queued=False)
                plug = resending(sender=channel, delivery=Alternative.CLIENT_ID)
                row, _plug = self.uncertain(h, plug)
                key = row["interruption_id"]
                self.assertEqual(row["recovery_client_id"], ids.continuation_client_id(key))
                channel.outcome, channel.queued = "accepted", True
                if how == "no channel":
                    plug.answers["sender"] = DEFER
                h.tick(advance=1)
                h.tick(advance=900)
                self.assert_no_send(h)
                if how == "no channel":
                    self.assertEqual(len(channel.calls), 1)
                    self.assertFalse(machine.was_resent(h.record()))
                    continue
                self.assertEqual(len(channel.calls), 2)
                self.assertEqual(channel.calls[1][:3], channel.calls[0][:3])
                self.follow(h)
                self.assertEqual(h.record()["state"], "recovered")

    def test_an_uncertain_route_is_never_resent(self):
        h = self.h
        route = Resume("unknown")
        plug = resending(unloaded=route)
        self.plugged(plug)
        self.ready_after_reset(loaded=False)
        h.tick()
        self.assertEqual(h.record()["state"], "submission_unknown")
        h.backend.loaded_map[T1] = "loaded"
        self.hours(h, 6)
        self.assertEqual((len(route.calls), h.backend.send_calls), (1, []))

    def test_a_resend_found_twice_after_it_ran_is_written_so(self):
        for when in ("running", "ended"):
            with self.subTest(when):
                h = self.fresh()
                row, _plug = self.uncertain(h)
                h.backend.turn_status = "inProgress" if when == "running" else "completed"
                h.tick(advance=1)
                h.tick(advance=900)
                self.follow(h)
                self.assertEqual(h.record()["state"], "turn_started" if when == "running" else "recovered")
                late = h.home.add_turn(T1, None, "completed", user_text="go on\n\n" + row["marker"])
                self.assertTrue(late)
                h.tick(advance=61)
                found = h.record()
                self.assertEqual(found["last_error"], "duplicate_marker")
                self.assertEqual(found["state"], "outcome_unverified" if when == "running" else "recovered")
                self.assertEqual(len(h.backend.send_calls), 2)



def send_now_answer(record, due):
    """P7 as a person's Send now, made in the Dashboard, answers it: for a record that waits."""
    return Alternative.SEND_NOW if record["state"] in WAITING else DEFER


class SendNowTests(PluggedCase):
    """SEND_NOW (P7, v0.6.14): a waiting record a person asked to send now passes its retry's wait,
    a postponement, the objection window, the spacing between two continuations and an attempt budget
    of the person's own - and nothing else, in the engine and again in the claim."""

    def waiting(self, h=None, error=OVERLOADED):
        """A temporary failure, registered and waiting for its retry, an engine with a plug that
        defers in place; `asks()` turns the person's Send now on."""
        h = h or self.h
        plug = Asked(wants=True)
        self.plugged(plug, h)
        failed(h, error)
        h.tick()
        row = h.record()
        self.assertEqual(row["state"], "waiting_backoff")
        self.assertGreater(row["next_retry_at"], h.now + 1)
        return row, plug

    @staticmethod
    def asks(plug):
        plug.answers["schedule"] = send_now_answer

    def test_it_passes_a_retry_wait_a_postponement_and_an_objection_window(self):
        for how in ("retry wait", "postponed", "objection window"):
            for asked in (False, True):
                with self.subTest(how, asked=asked):
                    h = self.fresh()
                    row, plug = self.waiting(h)
                    if how == "postponed":
                        h.now = row["next_retry_at"] + 1
                        self.assertTrue(h.store.postpone(row["interruption_id"], T1, h.now + 7200, h.now)[0])
                    elif how == "objection window":
                        h.now = row["next_retry_at"] + 1
                        h.engine.apply_policy(dict(settings.defaults(), default_tier="objection_window",
                                                   objection_minutes=60))
                    if asked:
                        self.asks(plug)
                    h.tick(advance=1)
                    self.assertEqual(len(h.backend.send_calls), 1 if asked else 0)
                    if asked:
                        self.assertEqual(json.loads(h.record()["gate_eval"])["schedule"][0], "PASS")
                        self.follow(h)
                        self.assertEqual(h.record()["state"], "recovered")

    def test_it_passes_the_spacing_after_a_send_that_never_started(self):
        for asked in (False, True):
            with self.subTest(asked=asked):
                h = self.fresh()
                row, plug = self.waiting(h)
                h.now = row["next_retry_at"] + 1
                h.backend.default_outcome = "not_started"
                h.tick()
                self.assertEqual(h.record()["last_error"], "queue_process_not_started")
                h.backend.default_outcome = "accepted"
                if asked:
                    self.asks(plug)
                h.now = h.record()["next_retry_at"] + 1          # due, inside the fifteen minutes
                h.tick()
                self.assertEqual(len(h.backend.send_calls), 2 if asked else 1)
                if not asked:
                    self.assertEqual(h.record()["last_error"], "thread_submission_cooldown")

    def test_it_passes_the_persons_own_attempt_budget_and_never_the_administrators(self):
        ends = {}
        for who in ("person", "administrator"):
            for asked in (False, True):
                with self.subTest(who, asked=asked):
                    h = self.fresh()
                    row, plug = self.waiting(h)
                    if who == "person":
                        h.engine.apply_policy(dict(settings.defaults(), max_recovery_attempts=1))
                    else:
                        h.engine.apply_policy(settings.defaults(), managed.Managed(max_recovery_attempts=1))
                    h.now = row["next_retry_at"] + 1
                    h.backend.default_outcome = "not_started"      # an attempt spent, nothing refunded
                    h.tick()
                    self.assertEqual(h.record()["recovery_attempts"], 1)
                    h.backend.default_outcome = "accepted"
                    if asked:
                        self.asks(plug)
                    h.now = h.record()["next_retry_at"] + 1
                    h.tick()
                    ends[who, asked] = (len(h.backend.send_calls), h.record()["state"])
        self.assertEqual(ends, {("person", False): (1, "retry_budget_exhausted"),
                                ("person", True): (2, "queued"),
                                ("administrator", False): (1, "retry_budget_exhausted"),
                                ("administrator", True): (1, "retry_budget_exhausted")})

    def test_it_never_passes_anything_else(self):
        """A reset ahead, quiet hours (a person's or an administrator's: both are quiet_until's),
        the day's five, a Pause, a history behind, a conversation the app does not hold, someone's
        queued input, usage, and a hold of the plug's own at another gate."""
        for how in ("reset ahead", "quiet hours", "daily five", "paused", "history behind",
                    "notLoaded", "queued input", "no usage", "held"):
            with self.subTest(how):
                h = self.fresh()
                if how == "reset ahead":
                    plug = Asked(wants=True)
                    self.plugged(plug, h)
                    h.home.fail_usage(T1)
                    h.backend.loaded_map[T1] = "loaded"
                    h.tick()
                else:
                    _row, plug = self.waiting(h)
                self.asks(plug)
                if how == "quiet hours":
                    h.engine.quiet_until = lambda now: now + 3600
                elif how == "daily five":
                    h.store.recent_claim_count = lambda *arguments: 5
                elif how == "paused":
                    h.store.set_enabled(False, h.now)
                elif how == "history behind":
                    h.home.make_stale(T1)
                    h.tick(advance=1)
                    h.tick(advance=200)
                elif how == "notLoaded":
                    h.backend.loaded_map[T1] = "notLoaded"
                elif how == "queued input":
                    h.home.enqueue(T1, "their own message")
                elif how == "no usage":
                    h.backend.usage_result = dict(NO_USAGE)
                elif how == "held":
                    plug.answers["gate"] = lambda name, record, facts: (
                        Alternative.HOLD if name == "thread_available" else DEFER)
                h.tick(advance=1)
                self.assert_no_send(h)
                self.assertNotIn(h.record()["state"], TERMINAL)

    def test_the_claim_takes_it_only_as_its_ledger_pays_for_the_schedule(self):
        row, _plug = self.waiting()
        key, at = row["interruption_id"], self.h.now + 1
        ledger = guard(Asked(wants=True))
        limits = self.h.engine.limits()
        self.assertEqual(self.h.store.reserve_detailed(key, at, limits=limits, forced=True)[:2],
                         (False, "schedule"))
        for options in ({"ledger": None, "carried": {Point.SCHEDULE}},
                        {"ledger": ledger, "carried": frozenset()}, {"ledger": ledger, "carried": {Point.GATES}}):
            with self.subTest(options=sorted(options)):
                self.assertEqual(self.h.store.reserve_detailed(key, at, limits=limits, forced=True, **options)[:2],
                                 (False, "schedule"))
        self.assertEqual(self.h.store.reserve_detailed(key, at, limits=limits, forced=True, ledger=ledger,
                                                       carried={Point.SCHEDULE}), (True, None, None))

    def test_the_claim_holds_it_to_the_administrators_ceiling_and_quiet_hours(self):
        h = self.h
        row, _plug = self.waiting()
        key = row["interruption_id"]
        h.store.update(key, at=h.now, recovery_attempts=4)
        ledger = guard(Asked(wants=True))
        limits = dict(h.engine.limits(), max_recovery_attempts=2)
        options = {"forced": True, "ledger": ledger, "carried": {Point.SCHEDULE}, "gates": None}
        refused = h.store.reserve_detailed(key, h.now + 1, limits=dict(limits, managed_max_recovery_attempts=4),
                                           **options)
        self.assertEqual(refused, (False, "attempt_budget", "recovery_budget"))
        self.assertEqual(h.store.reserve_detailed(key, h.now + 1, limits=limits, quiet_until=h.now + 3600,
                                                  **options), (False, "schedule", "quiet_hours"))
        self.assertEqual(h.store.reserve_detailed(key, h.now + 1, limits=dict(limits, managed_max_recovery_attempts=5),
                                                  **options), (True, None, None))

    def test_the_pre_send_look_still_stops_it(self):
        """All but a postponement, which a postponed record sent now carries into its claim (above)."""
        for how in ("cancelled", "paused"):
            with self.subTest(how):
                h = self.fresh()
                row, plug = self.waiting(h)
                self.asks(plug)
                key = row["interruption_id"]
                real = h.store.reserve_detailed

                def claim_then(*arguments, **options):
                    found = real(*arguments, **options)
                    if found[0] and how == "cancelled":
                        h.store.cancel_interruption(key, h.now)
                    elif found[0]:
                        h.store.set_enabled(False, h.now)
                    return found
                h.store.reserve_detailed = claim_then
                h.tick(advance=1)
                self.assert_no_send(h)
                self.assertNotEqual(h.record()["state"], "submitting")

    def test_deferring_at_a_refused_schedule_leaves_every_row_as_it_was(self):
        h = self.h
        row, plug = self.waiting()
        before = h.store.all_records()
        h.tick(advance=1)
        self.assertEqual(h.store.all_records(), before)
        self.assertIn("schedule", plug.hooks())
        self.assert_no_send()


if __name__ == "__main__":
    unittest.main()
