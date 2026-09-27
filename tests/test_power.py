"""v0.6.11: sleep-safe waiting, keeping this PC awake while a task waits, and waiting for the network.

Stage 2 items 6, 7 and 8, each off by default (power.py). At the defaults no wake is listened for, no
clock is compared, no power request is made, Windows is not asked about the internet, and usage is
read as v0.6.10 read it. Every Windows call is behind a port - win/power.py and win/network.py - and a
fake stands in for it here: no test registers for power notifications, asks for this PC to stay awake
or asks Windows about the network of the machine it runs on.

What each keeps: a wake only runs the checks sooner and forgets what was read before the sleep; a long
sleep only holds what fell due during it, for a person, who lets each continue from Pending (the card
offers Open Dashboard and nothing else, A28); keeping awake is a request the thread that ticks makes
and takes back - when nothing waits, when its hours are up, on a pause, a failed tick and a stop - and
changes no setting of Windows; and a PC Windows reports offline waits without reading usage, while a
question Windows cannot answer leaves v0.6.10's path exactly as it was (E1).
"""
from __future__ import annotations

import ast
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import machine, notifier, notify, power, settings  # noqa: E402
from codex_auto_resume.runtime import loop as watch_loop  # noqa: E402
from codex_auto_resume.runtime.waking import Waking  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402
from test_control import ControlTestCase  # noqa: E402
from test_engine import T1, T2, TURN_A, EngineCase  # noqa: E402

HOUR = 3600.0
# A time of the watcher's heartbeat, in realistic seconds.
RESET = 1_790_000_000.0
SRC = Path(_HERE).parent / "src" / "codex_auto_resume"


def values(**changes) -> dict:
    return dict(settings.defaults(), **changes)


# ------------------------------------------------------------------------------ the policy
class PolicyTests(unittest.TestCase):
    def test_at_the_defaults_nothing_is_asked_of_windows(self):
        defaults = settings.defaults()
        self.assertEqual(power.keep_awake(defaults), "off")
        self.assertIsNone(power.sleep_threshold(defaults))
        self.assertFalse(power.waits_for_network(defaults))
        self.assertFalse(power.listens(defaults))

    def test_the_settings_take_only_their_closed_lists(self):
        for name, good, bad in (("ask_after_sleep_minutes", "h2", "h5"), ("keep_awake", "on_ac", "on"),
                                ("keep_awake_hours", "h24", "h48"), ("wait_for_network", True, "true")):
            with self.subTest(name):
                self.assertEqual(settings.validate_update({name: good}), {name: good})
                with self.assertRaises(settings.SettingsError):
                    settings.validate_update({name: bad})
                self.assertEqual(settings.coerce({name: bad})[name], settings.DEFAULTS[name])

    def test_thresholds_and_caps_are_the_times_they_name(self):
        self.assertEqual(power.sleep_threshold(values(ask_after_sleep_minutes="m30")), 1800)
        self.assertEqual(power.sleep_threshold(values(ask_after_sleep_minutes="h12")), 12 * HOUR)
        self.assertEqual(power.awake_cap(values()), 6 * HOUR)
        self.assertEqual(power.awake_cap(values(keep_awake_hours="h1")), HOUR)
        self.assertEqual(power.awake_cap({"keep_awake_hours": "forever"}), 6 * HOUR)
        self.assertTrue(power.listens(values(ask_after_sleep_minutes="h1")))
        self.assertTrue(power.listens(values(keep_awake="always")))

    def test_a_sleep_is_what_the_wall_clock_moved_beyond_the_time_awake(self):
        self.assertEqual(power.asleep((1000.0, 50.0), (1000.0 + 3 * HOUR + 30, 80.0)), 3 * HOUR)
        # Awake throughout, a little drift, a clock set back, a missing or broken reading: no sleep.
        self.assertEqual(power.asleep((1000.0, 50.0), (1600.0, 650.0)), 0.0)
        self.assertEqual(power.asleep((1000.0, 50.0), (1040.0, 50.0)), 0.0)
        self.assertEqual(power.asleep((1000.0, 50.0), (-5000.0, 60.0)), 0.0)
        self.assertEqual(power.asleep(None, (1000.0, 1.0)), 0.0)
        self.assertEqual(power.asleep((1000.0, None), (9000.0, 1.0)), 0.0)
        self.assertEqual(power.asleep((1000.0, 0.0), (float("inf"), 1.0)), 0.0)

    def test_only_what_fell_due_inside_the_gap_counts(self):
        row = {"state": "waiting_reset", "next_retry_at": 100.0, "reset_at": 200.0, "not_before": None}
        self.assertTrue(power.fell_due(row, 150.0, 300.0))
        self.assertTrue(power.fell_due(row, 199.0, 200.0), "the end of the gap is inside it")
        self.assertFalse(power.fell_due(row, 200.0, 300.0), "due at the last look: that look had it")
        self.assertFalse(power.fell_due(row, 50.0, 150.0), "due after the wake: its time is still to come")
        self.assertFalse(power.fell_due(dict(row, hold="ask"), 150.0, 300.0), "a held record has no time")
        self.assertFalse(power.fell_due(dict(row, state="queued"), 150.0, 300.0))

    def test_what_waits_for_a_pc_kept_awake(self):
        rows = [{"state": "waiting_reset", "next_retry_at": 1.0},
                {"state": "waiting_retry", "next_retry_at": 1.0, "hold": "ask"},
                {"state": "waiting_retry", "next_retry_at": 1.0, "cancel_requested": True},
                {"state": "queued", "next_retry_at": 1.0}]
        self.assertEqual(power.waiting(rows), 1)

    def test_on_mains_only_is_honoured(self):
        self.assertTrue(power.wants_awake("always", 1, False))
        self.assertTrue(power.wants_awake("on_ac", 1, True))
        self.assertFalse(power.wants_awake("on_ac", 1, False))
        self.assertFalse(power.wants_awake("on_ac", 1, None), "power Windows cannot name is not mains")
        self.assertFalse(power.wants_awake("always", 0, True))
        self.assertFalse(power.wants_awake("off", 3, True))


# ------------------------------------------------------------------------------ the network
class Counted:
    """Wraps one backend method and counts its calls."""

    def __init__(self, method):
        self.method, self.calls = method, 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return self.method(*args, **kwargs)


class OfflineTests(EngineCase):
    def setUp(self):
        super().setUp()
        self.asked = []
        self.answer = False
        self.h.backend.usage = self.usage = Counted(self.h.backend.usage)
        self.h.engine.connectivity = self.connectivity

    def connectivity(self):
        self.asked.append(self.h.now)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer

    def test_at_the_defaults_windows_is_not_asked_and_usage_is_read(self):
        self.ready_after_reset()
        self.h.tick()
        self.assertEqual(self.asked, [])
        self.assertGreaterEqual(self.usage.calls, 1)
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_offline_waits_without_reading_usage(self):
        self.h.engine.apply_policy(values(wait_for_network=True))
        self.ready_after_reset()
        self.h.tick()
        self.assertEqual(len(self.asked), 1)
        self.assertEqual(self.usage.calls, 0, "no App Server is started for usage")
        self.assert_no_send()
        record = self.h.record()
        self.assertEqual((record["state"], record["last_error"]), ("waiting_for_usage", "offline"))
        self.assertEqual(machine.decode_gates(record["gate_eval"])["usage"], ("WAIT", "offline"))
        self.assertEqual(record["next_retry_at"], self.h.now + 60)
        self.assertIsNone(record["usage_probe_at"], "time offline counts toward no expiry")
        self.assertEqual((record["attempt_count"], record["submitted_at"]), (0, None), "nothing was claimed")
        # Windows reports the internet again: the next look reads usage and sends, every gate included.
        self.answer = True
        self.h.tick(advance=61)
        self.assertGreaterEqual(self.usage.calls, 1)
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_a_question_windows_cannot_answer_leaves_the_old_path(self):
        def unanswered():
            return None

        def refused():
            raise OSError("COM could not be brought up")

        for question in (unanswered, refused):
            with self.subTest(question.__name__):
                h = self.fresh()
                h.backend.usage = usage = Counted(h.backend.usage)
                h.engine.connectivity = question
                h.engine.apply_policy(values(wait_for_network=True))
                self.ready_after_reset(h)
                h.tick()
                self.assertGreaterEqual(usage.calls, 1)
                self.assertEqual(len(h.backend.send_calls), 1)

    def test_an_offline_answer_is_asked_only_where_usage_would_be_read(self):
        """A record that waits for anything earlier - here, its conversation not open - never asks."""
        self.h.engine.apply_policy(values(wait_for_network=True))
        self.ready_after_reset(loaded=False)
        self.h.tick()
        self.assertEqual(self.asked, [])


# ------------------------------------------------------------------------------ a long sleep
class SleepTests(EngineCase):
    def waiting(self, h=None):
        h = h or self.h
        h.home.fail_usage(T1, TURN_A)
        h.backend.loaded_map[T1] = "loaded"
        h.tick()
        record = h.record()
        due = machine.eligible_at(record)
        self.assertIsNotNone(due)
        return record, due

    def test_a_wake_forgets_what_was_read_before_it(self):
        engine = self.h.engine
        engine._usage_cache = (self.h.now, {"available": True})
        engine._loaded_cache[T1] = (self.h.now, "loaded")
        self.assertEqual(engine.after_sleep(self.h.now - 10, 0.0), 0)
        self.assertIsNone(engine._usage_cache)
        self.assertEqual(engine._loaded_cache, {})

    def test_off_holds_nothing_however_long_the_sleep(self):
        record, due = self.waiting()
        self.h.now = due + HOUR
        self.assertEqual(self.h.engine.after_sleep(due - HOUR, 10 * HOUR), 0)
        self.assertIsNone(self.h.record()["hold"])
        self.assertEqual([event for event, _ in self.h.notifications if event == "after_sleep"], [])

    def test_what_fell_due_inside_a_long_sleep_waits_for_a_person(self):
        record, due = self.waiting()
        self.h.engine.apply_policy(values(ask_after_sleep_minutes="h1"))
        self.h.now = due + 2 * HOUR
        self.assertEqual(self.h.engine.after_sleep(due - HOUR, 3 * HOUR), 1)
        held = self.h.record()
        self.assertEqual((held["hold"], held["state"]), ("after_sleep", record["state"]))
        self.assertIn("held", self.h.events(held["interruption_id"]))
        [(event, detail)] = [entry for entry in self.h.notifications if entry[0] == "after_sleep"]
        self.assertEqual(detail, {"slept": 3 * HOUR, "count": 1})
        # Held: every tick after it sends nothing, and the claim would refuse it too.
        self.h.tick(advance=61)
        self.assert_no_send()
        self.assertEqual(machine.decode_gates(self.h.record()["gate_eval"])["consent"], ("WAIT", "held"))
        # Let it continue - bound to this record and this conversation - and every gate decides again.
        self.assertEqual(self.h.store.release_hold(held["interruption_id"], T2, self.h.now), (False, "thread_mismatch"))
        self.assertEqual(self.h.store.release_hold(held["interruption_id"], T1, self.h.now)[0], True)
        self.h.tick(advance=61)
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_a_sleep_shorter_than_the_setting_holds_nothing(self):
        record, due = self.waiting()
        self.h.engine.apply_policy(values(ask_after_sleep_minutes="h2"))
        self.h.now = due + HOUR
        self.assertEqual(self.h.engine.after_sleep(due - HOUR, 90 * 60.0), 0)
        self.assertIsNone(self.h.record()["hold"])

    def test_only_records_that_fell_due_in_the_gap_are_held(self):
        for name, since, now, expected in (("due after the wake", -4 * HOUR, -1.0, None),
                                           ("due before the last look", 10.0, 3 * HOUR, None),
                                           ("due inside", -10.0, 3 * HOUR, "after_sleep")):
            with self.subTest(name):
                h = self.fresh()
                record, due = self.waiting(h)
                h.engine.apply_policy(values(ask_after_sleep_minutes="m30"))
                h.now = due + now
                h.engine.after_sleep(due + since, 3 * HOUR)
                self.assertEqual(h.record()["hold"], expected)

    def test_a_cancelled_or_already_held_record_is_left_as_it_is(self):
        for how in ("cancelled", "held"):
            with self.subTest(how):
                h = self.fresh()
                record, due = self.waiting(h)
                if how == "cancelled":
                    h.store.cancel_interruption(record["interruption_id"], h.now)
                else:
                    h.store.hold_waiting([record["interruption_id"]], "ask", h.now)
                before = h.record()
                h.engine.apply_policy(values(ask_after_sleep_minutes="m30"))
                h.now = due + HOUR
                self.assertEqual(h.engine.after_sleep(due - HOUR, 2 * HOUR), 0)
                self.assertEqual(h.record()["hold"], before["hold"])


class PopupTests(unittest.TestCase):
    def test_an_offline_row_says_why_before_its_next_check(self):
        from codex_auto_resume import l10n
        from codex_auto_resume.ui import popup
        from codex_auto_resume.ui.words import countdown
        strings = l10n.catalog("en")
        row = {"interruption_id": "a" * 64, "thread_id": T1, "state": "waiting_for_usage",
               "category": "usage_limit", "eligible_at": 1060.0, "overlays": [], "thread_enabled": True,
               "hold": None, "tier": None, "reason": "offline"}
        task = popup.task_item(row, strings, 1000.0)
        self.assertEqual(task["status"], strings["popup.offline"].replace("{time}", countdown(60)))
        other = popup.task_item(dict(row, reason="usage_unknown"), strings, 1000.0)
        self.assertEqual(other["status"], strings["popup.until_retry"].replace("{time}", countdown(60)))


# ------------------------------------------------------------------------------ the notice
class NoticeTests(unittest.TestCase):
    def test_its_one_button_opens_pending_and_nothing_else(self):
        notice = notifier.build("after_sleep", {"slept": 3 * HOUR + 600, "count": 2})
        self.assertEqual(notice.kind, "after_sleep")
        self.assertIsNone(notice.key, "about no one conversation: it replaces no card")
        self.assertEqual(len(notice.actions), 1)
        [(label, uri)] = notice.actions
        self.assertEqual(notify.parse_open_uri(uri), "pending")
        self.assertIsNone(notify.parse_cancel_uri(uri))
        self.assertIn("3", notice.title)
        self.assertIn("2", notice.line)

    def test_it_is_told_under_the_interruption_switch(self):
        self.assertTrue(settings.notification_enabled(settings.defaults(), "after_sleep"))
        self.assertFalse(settings.notification_enabled(values(notify_interruption=False), "after_sleep"))
        self.assertFalse(settings.notification_enabled(values(notifications=False), "after_sleep"))

    def test_how_long_it_slept_is_said_in_hours_and_minutes(self):
        self.assertEqual(notify.slept_for(59), notify.l10n.text("time.minutes", notify.l10n.current(), n=1))
        text = notify.slept_for(3 * HOUR + 600)
        self.assertIn("3", text)
        self.assertIn("10", text)
        self.assertEqual(notify.slept_for("nonsense"), notify.slept_for(60))


# ------------------------------------------------------------------------------ the watcher's side
class FakePort:
    """win/power.py's four names, writing down every call and the thread it came from."""

    def __init__(self):
        self.calls, self.mains, self.awake, self.accepts = [], True, 1000.0, True
        self.listeners = []

    def awake_seconds(self):
        self.calls.append(("awake_seconds", threading.get_ident()))
        return self.awake

    def on_mains(self):
        self.calls.append(("on_mains", threading.get_ident()))
        return self.mains

    def keep_awake(self, on):
        self.calls.append(("keep_awake", on, threading.get_ident()))
        return self.accepts

    def WakeListener(self, on_wake):  # noqa: N802 - the port's class, as win/power.py names it
        port = self

        class Listener:
            def __init__(self):
                self.on_wake, self.started, self.stopped = on_wake, False, False
                port.listeners.append(self)

            def start(self):
                self.started = True
                port.calls.append(("listen", threading.get_ident()))
                return True

            def stop(self):
                self.stopped = True
                port.calls.append(("deafen", threading.get_ident()))
        return Listener()

    def requests(self):
        return [call[1] for call in self.calls if call[0] == "keep_awake"]


class FakeEngine:
    def __init__(self):
        self.told, self.fail = [], False

    def after_sleep(self, since, slept):
        if self.fail:
            raise RuntimeError("store busy")
        self.told.append((since, slept))
        return 0


class RowsStore:
    def __init__(self, rows):
        self.rows = rows

    def records_in(self, states):
        return [row for row in self.rows if row.get("state") in states]


WAITING_ROW = {"state": "waiting_reset", "next_retry_at": 1.0, "reset_at": None}


class WakingTests(unittest.TestCase):
    def setUp(self):
        self.port, self.clock, self.signals, self.lines = FakePort(), [10_000.0], [], []
        self.waking = Waking(signal=lambda: self.signals.append(1), log=self.lines.append,
                             port=self.port, clock=lambda: self.clock[0])

    def test_at_the_defaults_windows_is_asked_nothing(self):
        engine, store = FakeEngine(), RowsStore([WAITING_ROW])
        for _ in range(3):
            self.waking.before(engine, settings.defaults())
            self.assertIsNone(self.waking.after(store, settings.defaults(), ok=True, paused=False))
        self.waking.stop()
        self.assertEqual(self.port.calls, [])
        self.assertEqual(engine.told, [])

    def test_it_listens_only_while_a_setting_wants_it(self):
        engine = FakeEngine()
        self.waking.before(engine, values(ask_after_sleep_minutes="h1"))
        self.assertEqual(len(self.port.listeners), 1)
        self.assertTrue(self.port.listeners[0].started)
        self.waking.before(engine, values(ask_after_sleep_minutes="h1"))
        self.assertEqual(len(self.port.listeners), 1, "one listener, however many ticks")
        self.waking.before(engine, settings.defaults())
        self.assertTrue(self.port.listeners[0].stopped)

    def test_the_clocks_tell_the_engine_of_a_sleep(self):
        engine, on = FakeEngine(), values(ask_after_sleep_minutes="h1")
        self.waking.before(engine, on)
        self.assertEqual(engine.told, [], "the first look only takes a reading")
        self.clock[0] += 30.0
        self.port.awake += 30.0
        self.waking.before(engine, on)
        self.assertEqual(engine.told, [], "awake the whole time")
        before = self.clock[0]
        self.clock[0] += 3 * HOUR + 20.0
        self.port.awake += 20.0
        self.assertEqual(self.waking.before(engine, on), 3 * HOUR)
        self.assertEqual(engine.told, [(before, 3 * HOUR)])

    def test_a_sleep_the_engine_could_not_be_told_of_is_seen_again(self):
        engine, on = FakeEngine(), values(ask_after_sleep_minutes="h1")
        self.waking.before(engine, on)
        before = self.clock[0]
        self.clock[0] += 2 * HOUR
        engine.fail = True
        with self.assertRaises(RuntimeError):
            self.waking.before(engine, on)
        engine.fail = False
        self.clock[0] += 5.0
        self.port.awake += 5.0
        self.waking.before(engine, on)
        self.assertEqual(engine.told, [(before, 2 * HOUR)])

    def test_a_wake_heard_signals_the_loop_and_the_next_tick_forgets(self):
        engine, on = FakeEngine(), values(keep_awake="always")
        self.waking.before(engine, on)
        self.port.listeners[0].on_wake()        # as Windows would, from a thread of its own
        self.assertEqual(self.signals, [1])
        self.waking.before(engine, on)
        self.assertEqual(engine.told, [(self.clock[0], 0.0)], "caches dropped; nothing held for no sleep")
        self.waking.before(engine, on)
        self.assertEqual(len(engine.told), 1, "told once per wake")

    def test_kept_awake_only_while_a_task_waits_and_let_go_when_none_does(self):
        on, store = values(keep_awake="always"), RowsStore([WAITING_ROW])
        self.assertEqual(self.waking.after(store, on, ok=True, paused=False), self.clock[0])
        self.waking.after(store, on, ok=True, paused=False)
        self.assertEqual(self.port.requests(), [True], "asked once, held across ticks")
        store.rows = [dict(WAITING_ROW, hold="after_sleep")]
        self.assertIsNone(self.waking.after(store, on, ok=True, paused=False))
        self.assertEqual(self.port.requests(), [True, False])

    def test_let_go_on_a_pause_a_failed_tick_and_a_stop(self):
        on, store = values(keep_awake="always"), RowsStore([WAITING_ROW])
        for how in ("paused", "failed", "stop", "setting off"):
            with self.subTest(how):
                self.waking.after(store, on, ok=True, paused=False)
                if how == "stop":
                    self.waking.stop()
                elif how == "setting off":
                    self.waking.after(store, settings.defaults(), ok=True, paused=False)
                else:
                    self.waking.after(store, on, ok=how != "failed", paused=how == "paused")
                self.assertIsNone(self.waking.awake_since)
                self.assertEqual(self.port.requests()[-1], False)

    def test_the_hours_chosen_are_a_cap_for_each_stretch_of_waiting(self):
        on, store = values(keep_awake="always", keep_awake_hours="h1"), RowsStore([WAITING_ROW])
        self.waking.after(store, on, ok=True, paused=False)
        self.clock[0] += HOUR - 1
        self.assertIsNotNone(self.waking.after(store, on, ok=True, paused=False))
        self.clock[0] += 2
        self.assertIsNone(self.waking.after(store, on, ok=True, paused=False))
        self.clock[0] += HOUR
        self.assertIsNone(self.waking.after(store, on, ok=True, paused=False), "spent until nothing waits")
        self.assertEqual(self.port.requests(), [True, False])
        # A failed tick in between does not start the hours again; nothing waiting does.
        self.waking.after(store, on, ok=False, paused=False)
        self.assertIsNone(self.waking.after(store, on, ok=True, paused=False))
        store.rows = []
        self.waking.after(store, on, ok=True, paused=False)
        store.rows = [WAITING_ROW]
        self.assertIsNotNone(self.waking.after(store, on, ok=True, paused=False))

    def test_on_mains_only_lets_it_sleep_on_battery(self):
        on, store = values(keep_awake="on_ac"), RowsStore([WAITING_ROW])
        self.port.mains = False
        self.assertIsNone(self.waking.after(store, on, ok=True, paused=False))
        self.assertEqual(self.port.requests(), [])
        self.port.mains = True
        self.assertIsNotNone(self.waking.after(store, on, ok=True, paused=False))
        self.port.mains = None
        self.assertIsNone(self.waking.after(store, on, ok=True, paused=False))
        self.assertEqual(self.port.requests(), [True, False])

    def test_every_request_is_made_and_taken_back_on_the_thread_that_ticks(self):
        on, store = values(keep_awake="always"), RowsStore([WAITING_ROW])
        self.waking.after(store, on, ok=True, paused=False)
        self.waking.stop()
        threads = {call[2] for call in self.port.calls if call[0] == "keep_awake"}
        self.assertEqual(threads, {threading.get_ident()})

    def test_a_request_windows_refuses_is_not_said_to_be_held(self):
        self.port.accepts = False
        self.assertIsNone(self.waking.after(RowsStore([WAITING_ROW]), values(keep_awake="always"),
                                            ok=True, paused=False))


class LoopTests(unittest.TestCase):
    """The loop's own step: a failure while keeping this PC awake lets go, and costs nothing else."""

    def loop(self):
        instance = watch_loop.WatchLoop.__new__(watch_loop.WatchLoop)
        instance.settings = values(keep_awake="always")
        instance.managed = type("Managed", (), {"disable_auto_resume": False})()
        instance.failures = []
        instance._record_failure = instance.failures.append
        return instance

    def test_no_waking_is_no_request(self):
        self.assertIsNone(self.loop()._keep_awake(None, None, True))

    def test_a_store_that_cannot_be_read_lets_go(self):
        loop, port = self.loop(), FakePort()
        waking = Waking(signal=lambda: None, log=lambda line: None, port=port, clock=lambda: 5.0)
        waking.after(RowsStore([WAITING_ROW]), loop.settings, ok=True, paused=False)

        class Broken:
            def settings(self):
                raise OSError("locked")
        self.assertIsNone(loop._keep_awake(waking, Broken(), True))
        self.assertEqual(port.requests(), [True, False])
        self.assertEqual(loop.failures, ["keeping this PC awake"])


class HeartbeatTests(unittest.TestCase):
    def test_since_when_it_keeps_the_pc_awake_is_kept_and_cleared(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / "state")
            try:
                beat = dict(pid=1, session_id="s", started_at=RESET, ok=True, engine_state="verified",
                            code_version="0.6.11")
                store.heartbeat(RESET + 10, awake_since=RESET + 5, **beat)
                self.assertEqual(store.watcher_status()["awake_since"], RESET + 5)
                store.heartbeat(RESET + 20, **beat)
                self.assertIsNone(store.watcher_status()["awake_since"])
                store.heartbeat(RESET + 30, awake_since=float("nan"), **beat)
                self.assertIsNone(store.watcher_status()["awake_since"])
            finally:
                store.close()


class WatcherViewTests(ControlTestCase):
    def test_since_when_is_said_only_of_a_running_watcher(self):
        store = Store(self.paths.state_dir)
        try:
            store.heartbeat(RESET + 10, pid=1, session_id="s", started_at=RESET, ok=True,
                            engine_state="verified", code_version="0.6.11", awake_since=RESET + 5)
            self.assertIsNone(self.control._watcher(store)["awake_since"], "its request ended with it")
            with patch.object(type(self.control), "watcher_running", return_value=True):
                self.assertEqual(self.control._watcher(store)["awake_since"], RESET + 5)
        finally:
            store.close()


# ------------------------------------------------------------------------------ the adapters
class AdapterTests(unittest.TestCase):
    """What the two Windows modules may reach: documented calls through ctypes, no socket, no process."""

    def imports(self, name):
        tree = ast.parse((SRC / "win" / (name + ".py")).read_text(encoding="utf-8"))
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                found.add((node.module or "").split(".")[0])
        return found

    def test_neither_reaches_the_network_or_starts_a_process(self):
        for name in ("power", "network"):
            with self.subTest(name):
                self.assertLessEqual(self.imports(name), {"__future__", "ctypes", "os"})

    def test_the_engine_is_handed_the_question_and_imports_no_windows_module(self):
        for path in (SRC / "engine").glob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("win.network", text, path.name)
            self.assertNotIn("win.power", text, path.name)


if __name__ == "__main__":
    unittest.main()
