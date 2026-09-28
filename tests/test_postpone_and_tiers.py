"""v0.6.11: postponing a record, quiet hours, and how much a conversation asks before it resumes.

Each of these can only hold a recovery back, and none is set at the defaults
(tests/test_defaults_golden.py):

* a postponement (`interruptions.not_before`) - a person's, for one exact record, only ever later
  and never more than a week ahead; Retry now brings it forward again;
* quiet hours - a recovery that falls due in them waits until they end, and the time spent in
  them does not count toward giving up on a usage limit;
* a tier - automatic (the default), an objection window before the first send, or a hold for a
  person (ask first, notify only) that only `release_hold`, bound to the exact record, lifts.

All of them are reasons of the consent and schedule gates, asked by the engine, again inside the
claim and at the last look before the send (tests/test_schema_v4.py holds those three places).
"""
from __future__ import annotations

import calendar
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import control, machine, mcpserver, notifier, notify, quiet, settings  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402
from test_control import KEY, OTHER_KEY, THREAD, ControlTestCase, detection  # noqa: E402
from test_engine import RESET, T1, TURN_A, EngineCase  # noqa: E402
from test_mcp import McpTestCase  # noqa: E402

OTHER_THREAD = "0a1b2c3d-0001-7000-8000-000000000009"


# ------------------------------------------------------------------------ a zone of its own
# One hour ahead of UTC, two in summer; summer from 01:00 UTC on 28 March 2027 to 01:00 UTC on
# 31 October 2027, when the clock goes 02:00 -> 03:00 and 03:00 -> 02:00.
SPRING = calendar.timegm((2027, 3, 28, 1, 0, 0))
FALL = calendar.timegm((2027, 10, 31, 1, 0, 0))


def _offset(moment):
    return 7200 if SPRING <= moment < FALL else 3600


def localtime(moment):
    return time.gmtime(moment + _offset(moment))


def mktime(fields):
    naive = calendar.timegm(tuple(fields[:6]))
    for offset in (3600, 7200):
        if _offset(naive - offset) == offset:
            return float(naive - offset)
    return float(naive - 3600)        # a time the spring change skips, taken forward


def local(year, month, day, hour, minute=0):
    return mktime((year, month, day, hour, minute, 0, 0, 0, -1))


def utc(year, month, day, hour, minute=0):
    return float(calendar.timegm((year, month, day, hour, minute, 0)))


def hours(start, end, days="every_day"):
    return {"quiet_hours_start": start, "quiet_hours_end": end, "quiet_hours_days": days}


def until(now, values):
    return quiet.quiet_until(now, values, localtime=localtime, mktime=mktime)


class QuietHoursTests(unittest.TestCase):
    def test_off_is_the_default_and_answers_nothing(self):
        self.assertIsNone(quiet.window(settings.defaults()))
        self.assertIsNone(until(local(2027, 1, 1, 23), settings.defaults()))

    def test_a_window_whose_end_is_its_start_is_none(self):
        self.assertIsNone(quiet.window(hours("22:00", "22:00")))
        self.assertIsNone(quiet.window(hours("22:15", "22:15")))
        self.assertIsNone(quiet.window(hours("24:00", "07:00")), "not a time of day: not a window")
        # v0.6.11: any minute of the day is a time of the person's own (Custom...), and any days they pick.
        self.assertEqual(quiet.window(hours("22:15", "06:45", "mon,wed")), (22 * 60 + 15, 6 * 60 + 45, frozenset({0, 2})))

    def test_a_window_across_midnight(self):
        night = hours("22:00", "07:00")                       # 1 January 2027 is a Friday
        self.assertEqual(until(local(2027, 1, 1, 23), night), local(2027, 1, 2, 7))
        self.assertEqual(until(local(2027, 1, 2, 3), night), local(2027, 1, 2, 7))
        self.assertEqual(until(local(2027, 1, 1, 22), night), local(2027, 1, 2, 7))
        self.assertIsNone(until(local(2027, 1, 2, 7), night), "the end is not inside")
        self.assertIsNone(until(local(2027, 1, 2, 12), night))

    def test_a_window_inside_one_day(self):
        lunch = hours("12:00", "13:30")
        self.assertEqual(until(local(2027, 1, 1, 12, 45), lunch), local(2027, 1, 1, 13, 30))
        self.assertIsNone(until(local(2027, 1, 1, 13, 30), lunch))
        self.assertIsNone(until(local(2027, 1, 1, 11, 59), lunch))

    def test_the_days_are_the_days_a_window_starts_on(self):
        weekdays, weekends = hours("22:00", "07:00", "weekdays"), hours("22:00", "07:00", "weekends")
        # Friday night belongs to Friday, a weekday, all the way to Saturday 07:00.
        self.assertEqual(until(local(2027, 1, 1, 23), weekdays), local(2027, 1, 2, 7))
        self.assertEqual(until(local(2027, 1, 2, 3), weekdays), local(2027, 1, 2, 7))
        # Saturday night is not a weekday's, and Monday before dawn is Sunday night's.
        self.assertIsNone(until(local(2027, 1, 2, 23), weekdays))
        self.assertIsNone(until(local(2027, 1, 4, 3), weekdays))
        self.assertEqual(until(local(2027, 1, 4, 23), weekdays), local(2027, 1, 5, 7))
        self.assertEqual(until(local(2027, 1, 2, 23), weekends), local(2027, 1, 3, 7))
        self.assertEqual(until(local(2027, 1, 4, 3), weekends), local(2027, 1, 4, 7))
        self.assertIsNone(until(local(2027, 1, 1, 23), weekends))

    def test_the_night_the_clock_goes_forward(self):
        """01:00-07:00 on 28 March 2027: the clock skips 02:00-03:00, and the window still ends at
        07:00 on the clock - five hours, not six."""
        night = hours("01:00", "07:00")
        self.assertEqual(until(utc(2027, 3, 28, 0, 30), night), utc(2027, 3, 28, 5))
        self.assertEqual(until(utc(2027, 3, 28, 4, 59), night), utc(2027, 3, 28, 5))
        self.assertIsNone(until(utc(2027, 3, 28, 5), night))

    def test_the_night_the_clock_goes_back(self):
        """22:00-07:00 from Saturday 30 October 2027: the clock repeats 02:00-03:00, and the window
        ends at 07:00 on the clock - ten hours, not nine."""
        night = hours("22:00", "07:00")
        begins = utc(2027, 10, 30, 20)                 # 22:00, two hours ahead of UTC
        self.assertEqual(until(begins, night), utc(2027, 10, 31, 6))
        self.assertEqual(utc(2027, 10, 31, 6) - begins, 10 * 3600)
        self.assertEqual(until(utc(2027, 10, 31, 5, 59), night), utc(2027, 10, 31, 6))

    def test_what_the_settings_layer_would_not_store_is_off(self):
        for broken in ({"quiet_hours_start": "25:00", "quiet_hours_end": "07:00"},
                       {"quiet_hours_start": "22:00", "quiet_hours_end": 7},
                       {"quiet_hours_start": "22:00", "quiet_hours_end": "07:00", "quiet_hours_days": "sundays"},
                       None, "22:00-07:00"):
            with self.subTest(broken=broken):
                self.assertIsNone(quiet.window(broken))

    def test_the_settings_offer_half_hours_and_refuse_anything_else(self):
        self.assertEqual(len(settings.QUIET_TIMES), 48)
        self.assertEqual(settings.validate_update(hours("22:30", "06:00", "weekdays")),
                         hours("22:30", "06:00", "weekdays"))
        # v0.6.11: Custom... - any minute of the day, and any days, each in its one spelling.
        self.assertEqual(settings.validate_update(hours("22:15", "6:45", "fri,mon")), hours("22:15", "06:45", "mon,fri"))
        self.assertEqual(settings.validate_update({"quiet_hours_days": "sat,sun"}), {"quiet_hours_days": "weekends"})
        for bad in ({"quiet_hours_start": "24:00"}, {"quiet_hours_start": "22:60"}, {"quiet_hours_end": "off"},
                    {"quiet_hours_start": "10pm"}, {"quiet_hours_days": "sundays"}, {"quiet_hours_days": ""},
                    {"quiet_hours_days": "mon,,tue"}, {"default_tier": "sometimes"},
                    {"objection_minutes": 0}, {"objection_minutes": 61}):
            with self.subTest(bad=bad), self.assertRaises(settings.SettingsError):
                settings.validate_update(bad)


class PostponementTimeTests(unittest.TestCase):
    def test_the_presets(self):
        now = local(2027, 1, 1, 23, 10)
        self.assertEqual(quiet.postpone_time(now, "30_minutes"), now + 1800)
        self.assertEqual(quiet.postpone_time(now, "1_hour"), now + 3600)
        self.assertEqual(quiet.postpone_time(now, "3_hours"), now + 3 * 3600)
        self.assertEqual(quiet.postpone_time(now, "tomorrow_morning", localtime=localtime, mktime=mktime),
                         local(2027, 1, 2, 9))
        self.assertIsNone(quiet.postpone_time(now, "never"))

    def test_only_ever_later_and_never_past_a_week(self):
        now = 1_800_000_000.0
        problem = quiet.postponement_problem
        self.assertIsNone(problem(now + 60, now))
        self.assertIsNone(problem(now + quiet.MAX_POSTPONE_SECONDS, now))
        self.assertEqual(problem(now, now), "not_later")
        self.assertEqual(problem(now - 1, now), "not_later")
        self.assertEqual(problem(now + 60, now, not_before=now + 120), "not_later")
        self.assertEqual(problem(now + quiet.MAX_POSTPONE_SECONDS + 1, now), "too_far")
        for bad in (None, "soon", True, float("nan"), float("inf")):
            self.assertEqual(problem(bad, now), "invalid_time")


# ------------------------------------------------------------------------------ the store
class StoreTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Store(Path(folder.name) / "state")
        self.addCleanup(self.store.close)
        self.store.set_enabled(True, 100.0)

    def test_a_postponement_is_written_and_journaled_and_only_ever_later(self):
        self.store.register(detection(), 100.0)
        self.assertEqual(self.store.postpone(KEY, THREAD, 5000.0, 200.0, actor="gui"), (True, 5000.0))
        self.assertEqual(self.store.get(KEY)["not_before"], 5000.0)
        self.assertEqual(self.store.postpone(KEY, THREAD, 4000.0, 300.0), (False, "not_later"))
        self.assertEqual(self.store.postpone(KEY, THREAD, 300.0 + 8 * 86400, 300.0), (False, "too_far"))
        self.assertEqual(self.store.get(KEY)["not_before"], 5000.0, "a refusal changes nothing")
        events = [event for event in self.store.events(KEY) if event["code"] == "postponed"]
        self.assertEqual([(event["actor"], event["value"]) for event in events], [("gui", 5000.0)])

    def test_a_postponement_is_bound_to_the_exact_record(self):
        self.store.register(detection(), 100.0)
        self.assertEqual(self.store.postpone(OTHER_KEY, THREAD, 5000.0, 200.0), (False, "unknown_record"))
        self.assertEqual(self.store.postpone(KEY, OTHER_THREAD, 5000.0, 200.0), (False, "thread_mismatch"))
        self.store.cancel_interruption(KEY, 150.0)
        self.assertEqual(self.store.postpone(KEY, THREAD, 5000.0, 200.0), (False, "finished"))

    def test_only_a_waiting_record_can_wait_longer(self):
        self.store.register(detection(), 100.0)
        self.assertTrue(self.store.reserve(KEY, 200.0))
        self.assertEqual(self.store.postpone(KEY, THREAD, 5000.0, 250.0), (False, "claimed"))

    def test_retry_now_never_shortens_a_postponement_or_an_objection_window(self):
        """Each only ever holds a record back; Retry now is not marked as a request that loosens
        anything (H8) and skips no check (A25). It moves the schedule alone, and says the later time."""
        self.store.register(detection(), 100.0)
        self.assertEqual(self.store.request_retry_now(KEY, 150.0), (True, 150.0))
        self.assertIsNone(self.store.get(KEY)["not_before"], "nothing postponed stays nothing")
        self.store.postpone(KEY, THREAD, 5000.0, 200.0)
        self.assertEqual(self.store.request_retry_now(KEY, 300.0), (True, 5000.0))
        self.assertEqual((self.store.get(KEY)["not_before"], self.store.get(KEY)["next_retry_at"]), (5000.0, 300.0))
        self.store.register(detection(key=OTHER_KEY, thread_id=OTHER_THREAD), 100.0)
        self.assertTrue(self.store.open_objection_window(OTHER_KEY, 3700.0, 100.0))
        self.assertEqual(self.store.request_retry_now(OTHER_KEY, 110.0), (True, 3700.0))
        self.assertEqual(self.store.get(OTHER_KEY)["not_before"], 3700.0)

    def test_a_tier_that_asks_holds_what_waits_and_one_that_asks_less_lets_nothing_go(self):
        self.store.register(detection(), 100.0)
        self.assertEqual(self.store.set_thread_tier(THREAD, "ask_first", 200.0), {"tier": "ask_first", "held": 1})
        self.assertEqual(self.store.get(KEY)["hold"], "ask")
        self.assertEqual(self.store.thread_tier(THREAD), "ask_first")
        self.assertEqual(self.store.thread_tiers(), {THREAD: "ask_first"})
        self.assertEqual(self.store.set_thread_tier(THREAD, "automatic", 300.0), {"tier": "automatic", "held": 0})
        self.assertEqual(self.store.get(KEY)["hold"], "ask", "still held until a person lets it go")
        self.assertEqual(self.store.set_thread_tier(THREAD, None, 400.0)["tier"], None)
        self.assertEqual(self.store.thread_tiers(), {})
        self.assertTrue(self.store.thread_enabled(THREAD), "a tier switches nothing off")
        codes = [event["code"] for event in self.store.events()]
        self.assertEqual(codes.count("tier_set"), 3)
        self.assertEqual(codes.count("held"), 1)

    def test_release_is_bound_to_the_exact_held_record(self):
        self.store.register(detection(), 100.0)
        self.assertEqual(self.store.release_hold(KEY, THREAD, 150.0), (False, "not_held"))
        self.store.set_thread_tier(THREAD, "notify_only", 160.0)
        self.assertEqual(self.store.release_hold(KEY, OTHER_THREAD, 170.0), (False, "thread_mismatch"))
        self.assertEqual(self.store.release_hold(OTHER_KEY, THREAD, 170.0), (False, "unknown_record"))
        self.assertEqual(self.store.release_hold(KEY, THREAD, 180.0), (True, "waiting_reset"))
        self.assertIsNone(self.store.get(KEY)["hold"])
        self.assertIn("hold_released", [event["code"] for event in self.store.events(KEY)])

    def test_a_finished_or_cancelled_held_record_is_not_released(self):
        self.store.register(detection(), 100.0, hold="ask")
        self.store.cancel_interruption(KEY, 150.0)
        self.assertEqual(self.store.release_hold(KEY, THREAD, 160.0), (False, "finished"))

    def test_the_objection_window_opens_once_and_a_postponement_never_takes_its_place(self):
        self.store.register(detection(), 100.0)
        self.assertTrue(self.store.open_objection_window(KEY, 500.0, 200.0))
        self.assertEqual(self.store.get(KEY)["objection_at"], 200.0)
        self.assertFalse(self.store.open_objection_window(KEY, 900.0, 600.0), "once per record")
        self.assertEqual(self.store.get(KEY)["not_before"], 500.0)
        # One a person postponed before it opened still gets it, and a postponement still ahead - a
        # person's in the meantime - is kept, never shortened by it.
        self.store.register(detection(key=OTHER_KEY, thread_id=OTHER_THREAD), 100.0)
        self.store.postpone(OTHER_KEY, OTHER_THREAD, 5000.0, 200.0)
        self.assertTrue(self.store.open_objection_window(OTHER_KEY, 800.0, 300.0))
        self.assertEqual(self.store.get(OTHER_KEY)["not_before"], 5000.0)
        self.assertEqual(self.store.get(OTHER_KEY)["objection_at"], 300.0)

    def test_a_hold_given_at_detection_is_kept_and_checked(self):
        from codex_auto_resume.store import StoreError
        self.store.register(detection(), 100.0, hold="notify_only")
        self.assertEqual(self.store.get(KEY)["hold"], "notify_only")
        with self.assertRaises(StoreError):
            self.store.register(detection(key=OTHER_KEY, thread_id=OTHER_THREAD), 100.0, hold="maybe")


# ------------------------------------------------------------------------------ the engine
def local_half_hour(moment) -> int:
    """The half hour of the day `moment` falls in, on this machine's clock, in minutes."""
    now = time.localtime(moment)
    return (now.tm_hour * 60 + now.tm_min) // 30 * 30


def clock(minutes) -> str:
    return "%02d:%02d" % divmod(minutes % (24 * 60), 60)


class QuietHoursEngineTests(EngineCase):
    def quiet_around(self, moment, h=None):
        """Quiet hours from the half hour before `moment` to two and a half hours after it."""
        start = local_half_hour(moment) - 30
        (h or self.h).engine.apply_policy(dict(settings.defaults(), **hours(clock(start), clock(start + 180))))
        return (h or self.h).engine.quiet_until(moment)

    def test_a_recovery_that_falls_due_in_quiet_hours_waits_until_they_end(self):
        self.ready_after_reset()
        ends = self.quiet_around(self.h.now)
        self.assertIsNotNone(ends)
        self.h.tick()
        self.assert_no_send()
        record = self.h.record()
        self.assertEqual(machine.decode_gates(record["gate_eval"])["schedule"], ("WAIT", "quiet_hours"))
        self.assertEqual(record["next_retry_at"], ends)
        self.assertIn(record["state"], machine.WAITING)
        self.h.now = ends - 1
        self.h.tick()
        self.assert_no_send()
        self.h.now = ends + 1
        self.h.tick()
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_the_claim_refuses_quiet_hours_the_engine_did_not_see(self):
        self.ready_after_reset()
        answers = iter([None])
        self.h.engine.quiet_until = lambda now: next(answers, now + 600)
        self.h.tick()
        self.assert_no_send()
        record = self.h.record()
        self.assertEqual(machine.decode_gates(record["gate_eval"])["schedule"], ("WAIT", "quiet_hours"))
        self.assertEqual((record["attempt_count"], record["submitted_at"]), (0, None), "nothing was claimed")

    def test_the_last_look_gives_the_claim_back_for_quiet_hours(self):
        self.ready_after_reset()
        answers = iter([None, None])
        self.h.engine.quiet_until = lambda now: next(answers, now + 600)
        self.h.tick()
        self.assert_no_send()
        self.assertNotIn("queue_submission_started", self.h.codes())
        record = self.h.record()
        self.assertIn(record["state"], machine.WAITING)
        self.assertEqual((record["last_error"], record["attempt_count"], record["submitted_at"]),
                         ("released_before_send", 1, None))

    def test_quiet_time_does_not_count_toward_giving_up_on_a_usage_limit(self):
        def run(with_quiet):
            h = self.fresh()
            h.home.fail_usage(T1, TURN_A, reset=None)
            h.backend.loaded_map[T1] = "loaded"
            h.backend.usage_result = {"available": False, "reset_at": None, "limit_type": "x",
                                      "reason": "blocked"}
            h.tick()
            h.tick(advance=901)                      # the first read: nothing counted yet
            self.assertEqual(h.record()["state"], "waiting_for_usage")
            self.assertIsNotNone(h.record()["usage_probe_at"])
            if with_quiet:
                ends = self.quiet_around(h.now + 901, h)
            h.engine._usage_cache = None
            h.tick(advance=901)
            if with_quiet:
                self.assertIsNone(h.record()["usage_probe_at"], "the read before the quiet is forgotten")
                self.assertEqual(h.record()["next_retry_at"], ends)
                h.now = ends + 1
                h.engine._usage_cache = None
                h.tick()
            self.assert_no_send(h)
            return h.record()["usage_unavailable_seconds"]
        self.assertGreater(run(False), 0)
        self.assertEqual(run(True), 0)


class TierEngineTests(EngineCase):
    def policy(self, **values):
        self.h.engine.apply_policy(dict(settings.defaults(), **values))

    def test_the_objection_window_waits_its_minutes_with_a_card_and_then_sends(self):
        self.policy(default_tier="objection_window", objection_minutes=5)
        self.ready_after_reset()
        self.h.tick()
        self.assert_no_send()
        record = self.h.record()
        self.assertEqual(record["not_before"], self.h.now + 300)
        self.assertEqual(machine.decode_gates(record["gate_eval"])["schedule"], ("WAIT", "postponed"))
        cards = [detail for event, detail in self.h.notifications if event == "objection"]
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["until"], self.h.now + 300)
        self.h.tick(advance=299)
        self.assert_no_send()
        self.h.tick(advance=2)
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertEqual(len([event for event, _ in self.h.notifications if event == "objection"]), 1,
                         "one window per record")

    def test_postponing_before_the_window_only_holds_it_back(self):
        """A postponement of a minute, made before the window opened, used to take its place: the record
        went a minute later instead of the window's hour later, and no card said so. It opens when the
        postponement is over, as it would have with none."""
        self.policy(default_tier="objection_window", objection_minutes=60)
        self.ready_after_reset()
        key = self.h.record()["interruption_id"]
        self.assertEqual(self.h.store.postpone(key, T1, self.h.now + 60, self.h.now, actor="mcp"),
                         (True, self.h.now + 60))
        self.h.tick()
        self.h.tick(advance=61)
        self.assert_no_send()
        cards = [detail for event, detail in self.h.notifications if event == "objection"]
        self.assertEqual(len(cards), 1, "the window opened, with its card")
        self.assertEqual(cards[0]["until"], self.h.now + 3600)
        self.h.tick(advance=3599)
        self.assert_no_send()
        self.h.tick(advance=2)
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_a_postponement_inside_the_window_goes_at_the_time_chosen(self):
        self.policy(default_tier="objection_window", objection_minutes=5)
        self.ready_after_reset()
        self.h.tick()
        key = self.h.record()["interruption_id"]
        self.h.store.postpone(key, T1, self.h.now + 3600, self.h.now)
        self.h.tick(advance=301)
        self.assert_no_send()
        self.h.tick(advance=3300)
        self.assertEqual(len(self.h.backend.send_calls), 1, "no second window after it")

    def test_retry_now_never_ends_the_window(self):
        self.policy(default_tier="objection_window", objection_minutes=60)
        self.ready_after_reset()
        self.h.tick()
        key = self.h.record()["interruption_id"]
        self.assertEqual(self.h.store.request_retry_now(key, self.h.now + 5), (True, self.h.now + 3600))
        self.h.tick(advance=10)
        self.assert_no_send()
        self.h.tick(advance=3600)
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_a_cancel_inside_the_window_stops_the_send(self):
        self.policy(default_tier="objection_window", objection_minutes=5)
        self.ready_after_reset()
        self.h.tick()
        self.h.store.cancel_interruption(self.h.record()["interruption_id"], self.h.now + 10)
        self.h.tick(advance=301)
        self.h.tick(advance=60)
        self.assert_no_send()
        self.assertEqual(self.h.record()["state"], "cancelled")

    def test_a_conversation_of_its_own_tier_opens_one_whatever_the_default(self):
        self.h.store.set_thread_tier(T1, "objection_window", self.h.now)
        self.ready_after_reset()
        self.h.tick()
        self.assert_no_send()
        self.assertIsNotNone(self.h.record()["not_before"])

    def test_ask_first_holds_it_says_so_and_only_a_release_lets_it_go(self):
        self.policy(default_tier="ask_first")
        self.ready_after_reset()
        record = self.h.record()
        self.assertEqual(record["hold"], "ask")
        detected = [detail for event, detail in self.h.notifications if event == "interruption"]
        self.assertEqual(detected[0].get("hold"), "ask")
        for _ in range(3):
            self.h.tick(advance=60)
        self.assert_no_send()
        self.assertEqual(machine.decode_gates(self.h.record()["gate_eval"])["consent"], ("WAIT", "held"))
        self.assertEqual(self.h.store.release_hold(record["interruption_id"], T1, self.h.now), (True, record["state"]))
        self.h.tick(advance=60)
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_notify_only_holds_it_too(self):
        self.h.store.set_thread_tier(T1, "notify_only", self.h.now)
        self.ready_after_reset()
        self.assertEqual(self.h.record()["hold"], "notify_only")
        self.h.tick(advance=3600)
        self.assert_no_send()

    def test_a_tier_chosen_after_the_failure_holds_what_waits(self):
        self.ready_after_reset()
        self.assertIsNone(self.h.record()["hold"])
        self.h.store.set_thread_tier(T1, "ask_first", self.h.now)
        self.h.tick()
        self.assert_no_send()

    def test_at_the_defaults_nothing_is_held_postponed_or_quiet(self):
        self.ready_after_reset()
        self.h.tick()
        record = self.h.record()
        self.assertEqual((record["hold"], record["not_before"], record["objection_at"]), (None, None, None))
        self.assertIsNone(self.h.engine.quiet_until(self.h.now))
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertNotIn("objection", [event for event, _ in self.h.notifications])
        self.assertNotIn("hold", [detail for event, detail in self.h.notifications if event == "interruption"][0])


# ------------------------------------------------------------------------ the notifications
class NoticeTests(unittest.TestCase):
    DETAIL = {"thread_id": T1, "interruption_id": KEY, "category": "usage_limit", "reset_at": RESET}

    def test_a_held_interruption_never_says_it_will_resume(self):
        from codex_auto_resume import l10n
        for hold, key in (("ask", "toast_held"), ("notify_only", "toast_notify_only")):
            with self.subTest(hold):
                notice = notifier.build("interruption", dict(self.DETAIL, hold=hold))
                self.assertEqual(notice.line, l10n.message(key))
                said = " ".join(notice.toast_content()["extra"])
                self.assertIn(l10n.message(key), said)
                self.assertNotIn(l10n.message("toast_usage_soon"), said)
                self.assertEqual([uri for _, uri in notice.actions],
                                 [notify.cancel_uri(KEY), notify.open_uri("pending")])

    def test_the_objection_card_offers_dont_resume_and_the_dashboard_and_nothing_else(self):
        notice = notifier.build("objection", dict(self.DETAIL, until=RESET + 300))
        self.assertEqual(notice.kind, "interruption")
        self.assertEqual([uri for _, uri in notice.actions],
                         [notify.cancel_uri(KEY), notify.open_uri("pending")])
        self.assertIn(time.strftime("%H:%M", time.localtime(RESET + 300)), notice.line)

    def test_the_objection_card_is_told_under_recovery_starting(self):
        values = settings.defaults()
        self.assertTrue(settings.notification_enabled(values, "objection"))
        self.assertFalse(settings.notification_enabled(dict(values, notify_starting=False), "objection"))
        self.assertFalse(settings.notification_enabled(dict(values, notifications=False), "objection"))


# ------------------------------------------------------------------------ the control layer
class ControlTests(ControlTestCase):
    def test_postpone_by_a_preset_by_minutes_or_to_a_time(self):
        self.register()
        before = time.time()
        result = self.control.postpone(KEY, THREAD, preset="1_hour")
        self.assertGreaterEqual(result["not_before"], before + 3600)
        self.assertEqual(result["thread_id"], THREAD)
        later = self.control.postpone(KEY, THREAD, minutes=180)["not_before"]
        self.assertGreater(later, result["not_before"])
        self.assertEqual(self.control.postpone(KEY, THREAD, until=later + 60)["not_before"], later + 60)
        rows = self.control.list_pending()
        self.assertEqual(rows[0]["not_before"], later + 60)
        self.assertEqual(rows[0]["eligible_at"], later + 60)

    def test_a_held_task_has_no_time_and_no_header_says_it_is_checked(self):
        """A held record's schedule passes and nothing sends it: only a person letting it continue does.
        It had a time in the past, so every header said checking, the light breathed and its row said due
        now for as long as it was held (J7). It has none; the headers say waiting."""
        from codex_auto_resume.ui.popup import model
        from codex_auto_resume.ui.tray import model as tray_model
        with Store(self.paths.state_dir) as store:
            store.set_enabled(True, 100.0)
            store.register(detection(), 100.0, hold="ask")
            self.assertIsNone(tray_model.snapshot_from(store, time.time())["next_at"])
        with patch.object(control.Control, "watcher_running", return_value=True):
            rows = self.control.list_pending()
        self.assertEqual(rows[0]["overlays"], ["held"])
        self.assertIsNone(rows[0]["eligible_at"])
        status = {"watcher_running": True, "enabled": True, "codes": {}, "pending": 1}
        self.assertEqual(model.activity(status, rows, time.time()), "waiting")
        # Let it continue, and it has its time again.
        self.control.release_hold(KEY, THREAD)
        self.assertIsNotNone(self.control.list_pending()[0]["eligible_at"])

    def test_retry_now_says_a_postponement_still_holds_it(self):
        self.register()
        until = self.control.postpone(KEY, THREAD, minutes=120)["not_before"]
        reply = self.control.request_retry_now(KEY)
        self.assertEqual(reply["eligible_at"], until)
        self.assertIn("postponed to a later time", reply["note"])
        self.assertEqual(self.control.list_pending()[0]["not_before"], until)

    def test_postponing_refuses_what_is_not_one_later_time(self):
        self.register()
        self.control.postpone(KEY, THREAD, minutes=120)
        for options, code in (({}, "invalid_time"),
                              ({"preset": "1_hour", "minutes": 5}, "invalid_time"),
                              ({"preset": "never"}, "invalid_time"),
                              ({"minutes": 0}, "invalid_time"),
                              ({"minutes": True}, "invalid_time"),
                              ({"minutes": 7 * 24 * 60 + 1}, "too_far"),
                              ({"until": "tomorrow"}, "invalid_time"),
                              ({"until": time.time() - 60}, "not_later"),
                              ({"minutes": 30}, "not_later"),
                              ({"until": time.time() + 8 * 86400}, "too_far")):
            with self.subTest(options=options):
                with self.assertRaises(control.ControlError) as caught:
                    self.control.postpone(KEY, THREAD, **options)
                self.assertEqual(caught.exception.code, code)

    def test_postponing_is_bound_to_the_exact_record(self):
        with self.assertRaises(control.ControlError) as caught:
            self.control.postpone(KEY, THREAD, preset="30_minutes")
        self.assertEqual(caught.exception.code, "no_such_interruption")
        self.register()
        for arguments, code in (((KEY, OTHER_THREAD), "thread_mismatch"),
                                ((KEY[:8], THREAD), "invalid_id"),
                                ((KEY, THREAD.upper()), "invalid_thread_id")):
            with self.subTest(code), self.assertRaises(control.ControlError) as caught:
                self.control.postpone(*arguments, preset="30_minutes")
            self.assertEqual(caught.exception.code, code)
        self.control.cancel_interruption(KEY)
        with self.assertRaises(control.ControlError) as caught:
            self.control.postpone(KEY, THREAD, preset="30_minutes")
        self.assertEqual(caught.exception.code, "already_finished")

    def test_a_tier_from_a_row_holds_what_waits_and_a_release_lets_it_go(self):
        self.register()
        result = self.control.set_thread_tier(THREAD, "ask_first", interruption_id=KEY)
        self.assertEqual(result, {"thread_id": THREAD, "tier": "ask_first", "held": 1})
        row = self.control.list_pending()[0]
        self.assertEqual((row["tier"], row["hold"]), ("ask_first", "ask"))
        self.assertIn("held", row["overlays"])
        released = self.control.release_hold(KEY, THREAD)
        self.assertEqual((released["interruption_id"], released["thread_id"]), (KEY, THREAD))
        self.assertIsNone(self.control.list_pending()[0]["hold"])
        with self.assertRaises(control.ControlError) as caught:
            self.control.release_hold(KEY, THREAD)
        self.assertEqual(caught.exception.code, "not_held")

    def test_release_refuses_a_stale_finished_or_other_conversations_record(self):
        with self.assertRaises(control.ControlError) as caught:
            self.control.release_hold(KEY, THREAD)
        self.assertEqual(caught.exception.code, "no_such_interruption")
        self.register()
        self.control.set_thread_tier(THREAD, "notify_only")
        with self.assertRaises(control.ControlError) as caught:
            self.control.release_hold(KEY, OTHER_THREAD)
        self.assertEqual(caught.exception.code, "thread_mismatch")
        self.control.cancel_interruption(KEY)
        with self.assertRaises(control.ControlError) as caught:
            self.control.release_hold(KEY, THREAD)
        self.assertEqual(caught.exception.code, "already_finished")

    def test_a_tier_is_one_of_the_list_and_a_row_must_still_be_its_record(self):
        self.register()
        for arguments, code in ((("sometimes",), "invalid_tier"),
                                (("ask_first",), "thread_mismatch")):
            with self.subTest(code), self.assertRaises(control.ControlError) as caught:
                self.control.set_thread_tier(OTHER_THREAD if code == "thread_mismatch" else THREAD,
                                             *arguments, interruption_id=KEY)
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.control.set_thread_tier(THREAD, None)["tier"], None)

    def test_none_of_it_sends(self):
        """What the three change: a time, a hold, a tier. Never a claim, a state or an attempt."""
        self.register()
        with Store(self.paths.state_dir) as store:
            before = dict(store.get(KEY))
        self.control.postpone(KEY, THREAD, preset="3_hours")
        self.control.set_thread_tier(THREAD, "ask_first", interruption_id=KEY)
        self.control.release_hold(KEY, THREAD)
        with Store(self.paths.state_dir) as store:
            after = dict(store.get(KEY))
        changed = {name for name in before if before[name] != after[name]}
        self.assertEqual(changed, {"not_before"})


# ------------------------------------------------------------------------------ the popup
class PopupRowMenuTests(unittest.TestCase):
    """The popup's row menu, as data: what each item asks for is the row's own record."""

    def setUp(self):
        from codex_auto_resume import l10n
        from codex_auto_resume.ui import popup
        self.popup = popup
        self.strings = l10n.catalog("en")

    def row(self, **extra):
        return dict({"interruption_id": KEY, "thread_id": THREAD, "state": "waiting_reset",
                     "category": "usage_limit", "eligible_at": 2000.0, "overlays": [],
                     "thread_enabled": True, "hold": None, "tier": None}, **extra)

    def menu(self, row, default="automatic"):
        task = self.popup.task_item(row, self.strings, 1000.0)
        return self.popup.model.row_menu(task, self.strings, default)

    def test_a_waiting_row_can_be_postponed_and_its_tier_chosen_but_not_released(self):
        postpone, release, separator, tiers, *_projects = self.menu(self.row())
        self.assertIsNone(separator)
        self.assertTrue(postpone["enabled"])
        *presets, line, unpostpone = postpone["items"]
        self.assertEqual([item["action"] for item in presets],
                         [("postpone", KEY, THREAD, preset) for preset in quiet.PRESETS])
        self.assertIsNone(line)
        self.assertEqual(unpostpone["action"], ("unpostpone", KEY, THREAD))
        self.assertFalse(unpostpone["enabled"], "nobody postponed it: nothing to take away")
        self.assertEqual(release["action"], ("release", KEY, THREAD))
        self.assertFalse(release["enabled"])
        self.assertEqual([item["action"] for item in tiers["items"]],
                         [("tier", KEY, THREAD, tier) for tier in (None,) + machine.IMPORTANCE_TIERS])
        self.assertEqual([item["checked"] for item in tiers["items"]], [True, False, False, False, False])
        self.assertEqual(tiers["items"][0]["text"],
                         self.strings["choice.tier_default"].replace("{tier}", self.strings["choice.automatic"]))

    def test_a_held_row_says_so_and_offers_its_release(self):
        row = self.row(hold="ask", tier="ask_first", overlays=["held"])
        task = self.popup.task_item(row, self.strings, 1000.0)
        self.assertEqual(task["status"], self.strings["popup.held"])
        self.assertEqual(task["tone"], "paused")
        _, release, _, tiers, *_projects = self.menu(row)
        self.assertTrue(release["enabled"])
        self.assertEqual([item["checked"] for item in tiers["items"]], [False, False, False, True, False])

    def test_a_row_being_sent_cannot_be_postponed(self):
        postpone, release, *_rest = self.menu(self.row(state="submitting"))
        self.assertFalse(postpone["enabled"])
        self.assertFalse(release["enabled"])

    def test_each_item_is_one_control_call_bound_to_its_row(self):
        calls = []

        class Control:
            def postpone(self, *args, **kwargs):
                calls.append(("postpone", args, kwargs))
                return {}

            def release_hold(self, *args, **kwargs):
                calls.append(("release_hold", args, kwargs))
                return {}

            def set_thread_tier(self, *args, **kwargs):
                calls.append(("set_thread_tier", args, kwargs))
                return {}
        for action in (("postpone", KEY, THREAD, "1_hour"), ("release", KEY, THREAD),
                       ("tier", KEY, THREAD, "notify_only")):
            self.assertEqual(self.popup.perform(action, Control()), ("ok", {}))
            self.assertEqual(self.popup.busy_key(action), ("row", KEY))
        self.assertEqual(calls, [("postpone", (KEY, THREAD), {"preset": "1_hour"}),
                                 ("release_hold", (KEY, THREAD), {}),
                                 ("set_thread_tier", (THREAD, "notify_only"), {"interruption_id": KEY})])

    def test_a_refused_row_action_says_the_row_changed(self):
        model = self.popup.PopupModel(self.strings)
        model.apply_outcome(("release", KEY, THREAD), ("refused", "thread_mismatch"), 0.0)
        self.assertEqual(model.notice_key, "popup.stale")
        model.apply_outcome(("postpone", KEY, THREAD, "1_hour"), ("refused", "not_later"), 0.0)
        self.assertEqual(model.notice_key, "action.failed")

    def test_the_menu_windows_draws_is_the_rows_and_its_choice_runs_bound_to_it(self):
        """The Win32 half, against a stand-in for user32: a right click on a drawn row builds that row's
        menu - submenus, a greyed Let it continue, the tier in effect ticked - and the item chosen runs
        exactly that item's action; a click on no row, and a cancelled menu, run nothing."""
        from unittest.mock import patch
        from codex_auto_resume.ui.popup import window as popup_window

        class User32:
            def __init__(self):
                self.appended, self.menus, self.chosen, self.destroyed = [], 0, 0, []

            def CreatePopupMenu(self):
                self.menus += 1
                return 100 + self.menus

            def AppendMenuW(self, menu, flags, item, text):
                self.appended.append((menu, flags, item, text))
                return True

            def TrackPopupMenu(self, *args):
                return self.chosen

            def ScreenToClient(self, hwnd, point):
                return True

            def ClientToScreen(self, hwnd, point):
                return True

            def PostMessageW(self, *args):
                return True

            def DestroyMenu(self, menu):
                self.destroyed.append(menu)
                return True
        user32 = User32()
        shown = self.popup.Popup(strings=self.strings)
        shown.hwnd = 7
        shown.model.rows = [self.row()]
        shown.model.status = {"enabled": True, "settings": {"default_tier": "ask_first"}}
        shown.model.view(1000.0)
        shown._painted_plan = {"rows": [(KEY, (0, 0, 200, 60))], "targets": []}
        ran = []
        shown._run = ran.append
        shown._update = lambda *args: None
        with patch.object(popup_window, "_dll", lambda name: user32):
            user32.chosen = 2                                  # the second leaf: postpone by an hour
            shown._context_menu((30 << 16) | 40)
            self.assertEqual(ran, [("postpone", KEY, THREAD, "1_hour")])
            self.assertEqual(user32.destroyed, [101], "the menu and its submenus are destroyed once")
            flags = {text: flag for _, flag, _, text in user32.appended if text}
            release = flags[self.strings["action.continue"]]
            self.assertTrue(release & popup_window.MF_GRAYED, "nothing held: Let it continue is greyed")
            standing = flags[self.strings["choice.tier_default"].replace("{tier}", self.strings["choice.ask_first"])]
            self.assertTrue(standing & popup_window.MF_CHECKED, "no tier of its own: Settings' is ticked")
            self.assertTrue(flags[self.strings["menu.postpone"]] & popup_window.MF_POPUP)
            # One between the row's own actions and its conversation's, and one before Don't postpone.
            self.assertEqual(sum(1 for _, flag, _, _ in user32.appended if flag & popup_window.MF_SEPARATOR), 2)
            ran.clear()
            user32.chosen = 0                                  # dismissed
            shown.model.busy.clear()
            shown._context_menu((30 << 16) | 40)
            self.assertEqual(ran, [])
            shown._painted_plan = {"rows": [], "targets": []}  # a click on no row
            user32.chosen = 2
            shown._context_menu((30 << 16) | 40)
            self.assertEqual(ran, [])


# ------------------------------------------------------------------------------------ MCP
class McpTests(McpTestCase):
    def test_postpone_is_not_marked_destructive_and_release_is(self):
        tools = {tool["name"]: tool for tool in mcpserver.TOOLS}
        self.assertIs(tools["postpone_recovery"]["annotations"]["destructiveHint"], False)
        self.assertIs(tools["release_hold"]["annotations"]["destructiveHint"], True)
        for name in ("postpone_recovery", "release_hold"):
            self.assertEqual(tools[name]["inputSchema"]["required"], ["interruption_id", "thread_id"])

    def test_postpone_and_release_through_the_server(self):
        self.register()
        reply = self.call("postpone_recovery", {"interruption_id": KEY, "thread_id": THREAD,
                                                "preset": "30_minutes"})["result"]
        self.assertFalse(reply.get("isError", False))
        self.assertGreater(reply["structuredContent"]["not_before"], time.time())
        refused = self.call("release_hold", {"interruption_id": KEY, "thread_id": THREAD})["result"]
        self.assertIs(refused["isError"], True)
        self.assertEqual(refused["structuredContent"], {"error_code": "not_held"})

    def test_quiet_hours_and_the_default_tier_are_settings_codex_may_change(self):
        properties = mcpserver.settings_schema()["properties"]
        for name in ("quiet_hours_start", "quiet_hours_end", "quiet_hours_days", "default_tier",
                     "objection_minutes"):
            self.assertIn(name, properties)
            self.assertNotEqual(properties[name]["description"], "See the settings documentation.")


if __name__ == "__main__":
    unittest.main()
