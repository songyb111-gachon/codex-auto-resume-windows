"""Wake this PC for a reset (v0.6.19, wake_for_reset; plans/v0619-design/D-watcher-ops.md B).

At P8, a waitable timer of the watcher's own set for the earliest time something waits for - core's waiting usage-limit
records, the reset actions' pending rules, the forced stop's held window - less the lead a person chose; moved when that
time changes; cancelled when nothing waits, when that time has come, when Windows does not allow wake timers for the
power source in use, when recovery is paused or the capability is off (the watch), or when the watcher stops (the
handle). Every Windows call is a fake that records it: no timer is set and no power setting is read.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import ctypes as C
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Point  # noqa: E402
from codex_auto_resume_advanced import registry, statement  # noqa: E402
from codex_auto_resume_advanced.engine import wake  # noqa: E402
from codex_auto_resume_advanced.registry import WAKE_FOR_RESET  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Actor, CapabilityKind, Measurement, OptionKey  # noqa: E402
from codex_auto_resume_advanced.win import waketimer  # noqa: E402

CAP = "wake_for_reset"
HOUR = 3600


class View:
    """What core shows a plug at P8, as far as this capability reads it: the records in some states."""

    def __init__(self, rows=()):
        self.rows = list(rows)

    def records_in(self, states):
        return [row for row in self.rows if row["state"] in states]


def waiting(due, category="usage_limit", state="waiting_reset"):
    return {"state": state, "category": category, "next_check_at": due}


class Timer:
    """The timer as the capability uses it: what it is set for, every call, and whether Windows allows it."""

    def __init__(self):
        self.due, self.calls, self.windows_allows = None, [], True

    def allowed(self):
        self.calls.append(("allowed",))
        return self.windows_allows

    def set(self, when):
        self.calls.append(("set", when))
        self.due = when
        return True

    def cancel(self):
        if self.due is None:
            return False
        self.calls.append(("cancel",))
        self.due = None
        return True


class DefinitionTests(unittest.TestCase):
    def test_a_route_at_p8_departing_from_b16_and_c4_resting_on_mwake_shown_after_crash_restart(self):
        self.assertEqual((WAKE_FOR_RESET.kind, WAKE_FOR_RESET.points, WAKE_FOR_RESET.compat),
                         (CapabilityKind.ROUTE, frozenset({Point.TICK}), "engine_present"))
        self.assertEqual(WAKE_FOR_RESET.departs_from, ("B16", "C4"))
        self.assertEqual(WAKE_FOR_RESET.measurements, (Measurement.MWAKE,))
        (option,) = WAKE_FOR_RESET.options
        self.assertEqual((option.key, option.choices, option.default), (OptionKey.WAKE_LEAD_MINUTES, (1, 2, 5), 2))
        self.assertIn(CAP, registry.REGISTRY.ids)
        order = registry.SHOWN_ORDER
        self.assertEqual(order[order.index("crash_restart") + 1], CAP)
        self.assertEqual(statement.CATALOGS.missing(WAKE_FOR_RESET), [])

    def test_its_errand_runs_after_every_other_capability_s_at_p8(self):
        """The reset actions and the forced stop keep their due times in their own errands; this one reads them last."""
        self.assertEqual(registry.REGISTRY.at(Point.TICK)[-1].id, CAP)


class WakeCase(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        self.compat = ac.view(capability="engine_present")
        self.rt = self.runtime(WAKE_FOR_RESET)
        self.rt.arming.catalogs = statement.CATALOGS
        self.code = self.rt._code_of(WAKE_FOR_RESET)
        self.timer = self.code._timer = Timer()
        self.watches = []
        self.code._start = self.watches.append
        self.view = View()

    def on(self, state="armed"):
        result = self.rt.arming.arm(CAP, state=state, revision=WAKE_FOR_RESET.revision,
                                    generation=self.rt.state.meta()["generation"], acknowledged_version=ac.ENGINE,
                                    warnings=[str(w) for w in self.rt.arming.warnings(WAKE_FOR_RESET)],
                                    actor=Actor.DASHBOARD)
        self.assertTrue(result["done"], result)
        self.rt.states(fresh=True)

    def tick(self, after=5):
        """Time passes, then one tick, its errand run - what core does with the answer at P8."""
        self.now += after
        answer = self.rt.tick(self.view)
        if answer is not DEFER:
            answer.run(lambda: None)

    def codes(self):
        return [line["code"] for line in self.rt.state.journal(capability=CAP)]


class OffTests(WakeCase):
    def test_off_or_watched_no_timer_is_ever_set(self):
        self.view = View([waiting(ac.NOW + HOUR)])
        self.tick()
        self.assertEqual(self.timer.calls, [])
        self.on(state="shadow")
        self.tick()
        self.assertEqual(self.timer.calls, [])


class SetTests(WakeCase):
    def test_on_the_timer_is_set_for_the_earliest_usage_limit_less_the_lead(self):
        """Fails with the capability reverted: no timer, the PC sleeps through the reset."""
        self.on()
        self.view = View([waiting(ac.NOW + 2 * HOUR), waiting(ac.NOW + HOUR)])
        self.tick()
        self.assertEqual(self.timer.due, ac.NOW + HOUR - 2 * 60)
        self.assertEqual(len(self.watches), 1, "the watch started")
        self.assertIn("wake.set", self.codes())

    def test_the_lead_a_person_chose(self):
        self.on()
        self.rt.state.set_option(CAP, OptionKey.WAKE_LEAD_MINUTES, 5, generation=self.rt.state.meta()["generation"],
                                 actor=Actor.DASHBOARD)
        self.view = View([waiting(ac.NOW + HOUR)])
        self.tick()
        self.assertEqual(self.timer.due, ac.NOW + HOUR - 5 * 60)

    def test_only_usage_limits_that_wait_count(self):
        self.on()
        self.view = View([waiting(ac.NOW + 600, category="capacity"), waiting(ac.NOW + 700, state="recovered"),
                          waiting(ac.NOW - 60), waiting(None), waiting("soon")])
        self.tick()
        self.assertIsNone(self.timer.due)
        self.assertEqual(self.timer.calls, [])

    def test_moved_when_the_earliest_changes_and_cancelled_when_none_waits(self):
        self.on()
        self.view = View([waiting(ac.NOW + HOUR)])
        self.tick()
        self.view = View([waiting(ac.NOW + 2 * HOUR)])
        self.tick()
        self.assertEqual(self.timer.due, ac.NOW + 2 * HOUR - 120)
        self.tick()
        self.assertEqual([call[0] for call in self.timer.calls].count("set"), 2, "an unchanged time is not set again")
        self.view = View()
        self.tick()
        self.assertIsNone(self.timer.due)
        self.assertIn("wake.cancelled", self.codes())

    def test_once_the_time_has_come_it_is_taken_back(self):
        self.on()
        self.view = View([waiting(ac.NOW + 200)])
        self.tick()
        self.assertEqual(self.timer.due, ac.NOW + 80)
        self.tick(after=100)
        self.assertIsNone(self.timer.due, "the watcher is awake now: nothing to wake")

    def test_windows_not_allowing_wake_timers_sets_nothing_and_is_counted_once(self):
        self.on()
        self.timer.windows_allows = False
        self.view = View([waiting(ac.NOW + HOUR)])
        for _ in range(3):
            self.tick(after=wake.ASK_EVERY)
        self.assertIsNone(self.timer.due)
        self.assertEqual([call for call in self.timer.calls if call[0] == "set"], [])
        self.assertEqual(self.codes().count("wake.not_allowed"), 1)
        self.timer.windows_allows = True
        self.tick(after=wake.ASK_EVERY)
        self.assertEqual(self.timer.due, self.view.rows[0]["next_check_at"] - 120)


class WatchTests(WakeCase):
    def armed_and_set(self):
        self.on()
        self.view = View([waiting(ac.NOW + HOUR)])
        self.tick()
        self.assertIsNotNone(self.timer.due)

    def test_the_watch_keeps_it_while_on_and_ticking(self):
        self.armed_and_set()
        self.now += wake.WATCH_EVERY
        self.assertTrue(self.code.look())
        self.assertIsNotNone(self.timer.due)

    def test_turned_off_the_watch_takes_it_back(self):
        """A capability off is asked nothing at P8, so only the watch can take its timer back."""
        self.armed_and_set()
        self.rt.arming.disarm(CAP, actor=Actor.DASHBOARD)
        self.rt.states(fresh=True)
        self.assertFalse(self.code.look())
        self.assertIsNone(self.timer.due)

    def test_no_tick_for_a_while_a_pause_takes_it_back(self):
        """A pause asks the plug nothing at P8: no tick comes, and after STALE seconds the timer goes."""
        self.armed_and_set()
        self.now += wake.STALE - 1
        self.assertTrue(self.code.look())
        self.now += 2
        self.assertFalse(self.code.look())
        self.assertIsNone(self.timer.due)

    def test_with_nothing_set_the_watch_ends(self):
        self.on()
        self.assertFalse(self.code.look())


class Kernel:
    """kernel32 as WakeTimer calls it, recording every call; ACLineStatus as told."""

    def __init__(self, ac_line=1):
        self.calls, self.ac_line = [], ac_line

    def CreateWaitableTimerExW(self, security, name, flags, access):
        self.calls.append(("create", security, name, flags, access))
        return 501

    def SetWaitableTimer(self, handle, due, period, routine, argument, resume):
        self.calls.append(("set", handle, due._obj.value, period, routine, argument, resume))
        return 1

    def CancelWaitableTimer(self, handle):
        self.calls.append(("cancel", handle))
        return 1

    def CloseHandle(self, handle):
        self.calls.append(("close", handle))
        return 1

    def GetSystemPowerStatus(self, status):
        status._obj.ACLineStatus = self.ac_line
        return 1

    def LocalFree(self, pointer):
        self.calls.append(("free",))
        return None


class Power:
    """powrprof as WakeTimer calls it: the active scheme, and the Allow wake timers value for AC and for DC."""

    def __init__(self, ac_value=1, dc_value=0):
        self.calls, self.values = [], {"ac": ac_value, "dc": dc_value}
        self.scheme = waketimer.GUID()

    def PowerGetActiveScheme(self, root, scheme):
        scheme._obj.contents = self.scheme
        return 0

    def _read(self, which, root, scheme, subgroup, setting, value):
        self.calls.append((which, bytes(subgroup._obj), bytes(setting._obj)))
        value._obj.value = self.values[which]
        return 0

    def PowerReadACValueIndex(self, *arguments):
        return self._read("ac", *arguments)

    def PowerReadDCValueIndex(self, *arguments):
        return self._read("dc", *arguments)


class WakeTimerTests(unittest.TestCase):
    def test_set_makes_one_timer_of_this_process_with_resume_for_an_absolute_time(self):
        kernel = Kernel()
        timer = waketimer.WakeTimer(kernel=kernel, power=Power())
        self.assertTrue(timer.set(ac.NOW))
        self.assertTrue(timer.set(ac.NOW + 60))
        create, first, second = kernel.calls
        self.assertEqual(create, ("create", None, None, 0, waketimer.TIMER_ALL_ACCESS))
        self.assertEqual(first, ("set", 501, waketimer.filetime(ac.NOW), 0, None, None, True))
        self.assertEqual(second[2], waketimer.filetime(ac.NOW + 60))
        self.assertGreater(first[2], 0, "positive: an absolute time")
        self.assertEqual(waketimer.filetime(0), 116444736000000000)
        self.assertEqual(timer.due, ac.NOW + 60)

    def test_cancel_and_close_take_it_back_and_closing_drops_it_as_the_watcher_s_end_does(self):
        kernel = Kernel()
        timer = waketimer.WakeTimer(kernel=kernel, power=Power())
        self.assertFalse(timer.cancel(), "nothing set, nothing to take back")
        timer.set(ac.NOW)
        self.assertTrue(timer.cancel())
        self.assertIsNone(timer.due)
        timer.set(ac.NOW)
        timer.close()
        self.assertEqual(kernel.calls[-1], ("close", 501))
        self.assertIsNone(timer.due)

    def test_allowed_reads_the_power_source_in_use_and_frees_the_scheme(self):
        for ac_line, ac_value, dc_value, expected, which in ((1, 1, 0, True, "ac"), (0, 1, 0, False, "dc"),
                                                             (0, 0, 1, True, "dc"), (255, 1, 0, True, "ac"),
                                                             (1, 2, 2, False, "ac"), (1, 0, 0, False, "ac")):
            with self.subTest(ac_line=ac_line, ac_value=ac_value, dc_value=dc_value):
                kernel, power = Kernel(ac_line), Power(ac_value, dc_value)
                self.assertIs(waketimer.WakeTimer(kernel=kernel, power=power).allowed(), expected)
                ((read, subgroup, setting),) = power.calls
                self.assertEqual(read, which)
                self.assertEqual(subgroup, waketimer.GUID_SLEEP_SUBGROUP.bytes_le)
                self.assertEqual(setting, waketimer.GUID_ALLOW_RTC_WAKE.bytes_le)
                self.assertIn(("free",), kernel.calls)

    def test_what_cannot_be_read_is_not_allowed(self):
        class Broken(Power):
            def PowerGetActiveScheme(self, root, scheme):
                return 5
        self.assertFalse(waketimer.WakeTimer(kernel=Kernel(), power=Broken()).allowed())

    def test_no_power_setting_is_ever_written(self):
        """F1: Allow wake timers is read, never written; nothing machine-wide is changed."""
        text = (Path(waketimer.__file__)).read_text(encoding="utf-8")
        for forbidden in ("PowerWrite", "PowerSetActiveScheme", "SetSuspendState", "SetThreadExecutionState"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
