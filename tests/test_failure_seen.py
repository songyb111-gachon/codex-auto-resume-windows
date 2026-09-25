"""A certain failure stays red on the icon until somebody has seen it (v0.6.8).

The user chose it: "확인할 때까지 빨강". A recovery that ended `failed` turns the notification-area icon and the
settings window's taskbar button red - sweeping, quickly - until a person has seen it (the popup opened from the icon,
or the Dashboard in front) or a new recovery has been on its way since. What decides it is the records (Store.failure_marks),
never the journal, and when a person last saw a failure is one forward-only number in config/failure-seen.json
(control.acknowledge_failure). A missing or unreadable file shows nothing, and the watcher writes its start as the
baseline, so a failure from before an upgrade never lights the icon.

Every test runs against an isolated home; nothing touches the real install, its registry or its state.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
import sys
import tempfile
import guiscan
import unittest
from unittest.mock import patch

from codex_auto_resume import app, config, control, controlcli
from codex_auto_resume.ui import tray
from codex_auto_resume.control import seen  # where the mutex is taken
from codex_auto_resume.store import Store

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from test_control import ControlTestCase, detection  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def marks(failed=None, started=None):
    return {"failed_at": failed, "started_at": started}


class RuleTests(unittest.TestCase):
    """control.unseen_failure: the one rule the icon, get_status and the taskbar button all read."""

    def test_a_failure_nobody_has_seen_and_nothing_followed_is_shown(self):
        self.assertEqual(control.unseen_failure(marks(200.0, 150.0), 100.0), 200.0)
        self.assertEqual(control.unseen_failure(marks(200.0, None), 100.0), 200.0)

    def test_the_failed_record_s_own_moment_keeps_it_red(self):
        self.assertEqual(control.unseen_failure(marks(200.0, 200.0), 100.0), 200.0)

    def test_a_recovery_on_its_way_after_it_is_what_it_was_waiting_for(self):
        self.assertIsNone(control.unseen_failure(marks(200.0, 200.5), 100.0))

    def test_seen_at_or_after_it_is_seen(self):
        self.assertIsNone(control.unseen_failure(marks(200.0, 150.0), 200.0))
        self.assertIsNone(control.unseen_failure(marks(200.0, 150.0), 999.0))

    def test_nothing_to_believe_is_nothing_shown(self):
        for given, seen in ((marks(200.0, 150.0), None), (marks(None, 150.0), 100.0), (None, 100.0), ({}, 100.0),
                            ("marks", 100.0)):
            with self.subTest(given=given, seen=seen):
                self.assertIsNone(control.unseen_failure(given, seen))


class SeenFileTests(ControlTestCase):
    """config/failure-seen.json: read by stamp, written atomically, only ever forward."""

    def write(self, text):
        self.paths.failure_seen_file.write_text(text, encoding="utf-8")

    def test_no_file_is_no_time_and_reading_writes_nothing(self):
        self.assertIsNone(self.control.failure_seen_at())
        self.assertFalse(self.paths.failure_seen_file.exists())

    def test_an_acknowledgement_writes_the_time_and_reads_back(self):
        answer = self.control.acknowledge_failure(1000.0)
        self.assertEqual(answer, {"seen_at": 1000.0, "written": True})
        self.assertEqual(json.loads(self.paths.failure_seen_file.read_text(encoding="utf-8")), {"seen_at": 1000.0})
        self.assertEqual(self.control.failure_seen_at(), 1000.0)
        self.assertEqual(control.Control(self.paths).failure_seen_at(), 1000.0, "another process reads it too")
        self.assertEqual(list(self.paths.state_dir.glob("failure-seen.*.tmp")), [])

    def test_the_time_only_moves_forward(self):
        self.control.acknowledge_failure(1000.0)
        self.assertEqual(self.control.acknowledge_failure(900.0)["seen_at"], 1000.0)
        self.assertEqual(control.Control(self.paths).failure_seen_at(), 1000.0)
        self.control.acknowledge_failure(1100.0)
        self.assertEqual(control.Control(self.paths).failure_seen_at(), 1100.0)

    def test_the_baseline_is_written_only_where_there_is_no_time_to_believe(self):
        self.assertEqual(self.control.acknowledge_failure(500.0, baseline=True)["seen_at"], 500.0)
        self.assertEqual(self.control.acknowledge_failure(900.0, baseline=True), {"seen_at": 500.0, "written": False})
        self.write("not json")
        self.assertIsNone(control.Control(self.paths).failure_seen_at())
        self.assertEqual(control.Control(self.paths).acknowledge_failure(900.0, baseline=True)["seen_at"], 900.0)

    def test_a_file_that_cannot_be_believed_is_no_time(self):
        for text in ("", "[]", "{}", '{"seen_at": "soon"}', '{"seen_at": true}', '{"seen_at": -1}',
                     '{"seen_at": NaN}', '{"seen_at": Infinity}', '{"seen_at": 1%s}' % ("0" * 400),
                     # Valid, and too big: only the size limit refuses it.
                     '{"seen_at": 1000.0%s}' % (" " * control.SEEN_LIMIT)):
            with self.subTest(text=text[:30]):
                self.write(text)
                self.assertIsNone(control.Control(self.paths).failure_seen_at())

    def test_a_number_too_big_for_a_float_is_no_time_and_never_breaks_the_status(self):
        self.write('{"seen_at": 1%s}' % ("0" * 400))
        self.assertIsNone(self.control.failure_seen_at())
        self.assertIs(self.control.get_status()["failure_unseen"], False)
        self.assertIs(self.control.acknowledge_failure(500.0, baseline=True)["written"], True)

    def test_a_file_that_could_not_be_read_just_now_is_never_overwritten_by_the_baseline(self):
        self.control.acknowledge_failure(1000.0)
        with patch.object(Path, "stat", side_effect=PermissionError("sharing violation")):
            self.assertEqual(control.Control(self.paths).acknowledge_failure(9000.0, baseline=True),
                             {"seen_at": None, "written": False})
        self.assertEqual(control.Control(self.paths).failure_seen_at(), 1000.0)

    def test_a_seen_time_a_clock_ahead_wrote_is_not_believed_beyond_now(self):
        self.control.acknowledge_failure(100000.0)                        # the clock was hours ahead
        self.assertEqual(control.Control(self.paths).acknowledge_failure(500.0, baseline=True)["seen_at"], 500.0)
        self.control.acknowledge_failure(100000.0)
        self.assertEqual(control.Control(self.paths).acknowledge_failure(600.0)["seen_at"], 600.0)

    def test_an_acknowledgement_covers_a_failure_stamped_ahead_of_the_clock(self):
        self.register()
        StoreMarkTests.set_row(self, detection()["interruption_id"], state="failed", outcome_at=5000.0,
                               submitted_at=None, first_queued_at=4000.0)
        self.control.acknowledge_failure(100.0, baseline=True)
        self.assertIs(control.Control(self.paths).get_status()["failure_unseen"], True)
        self.assertEqual(self.control.acknowledge_failure(200.0)["seen_at"], 5000.0)
        self.assertIs(control.Control(self.paths).get_status()["failure_unseen"], False)

    def test_the_write_is_a_new_file_of_a_name_nobody_can_plant(self):
        names = []
        real = os.replace

        def spy(source, target):
            names.append(Path(source).name)
            return real(source, target)
        with patch.object(os, "replace", spy):
            self.control.acknowledge_failure(1000.0)
            self.control.acknowledge_failure(2000.0)
        self.assertEqual(len(names), 2)
        self.assertNotEqual(names[0], names[1])
        for name in names:
            self.assertTrue(name.startswith("failure-seen.") and name.endswith(".tmp"), name)
            self.assertNotIn(str(os.getpid()), name)

    def test_both_writers_take_one_lock(self):
        taken = []

        class Lock:
            def __init__(self, name, timeout=5.0):
                taken.append(name)

            def __enter__(self):
                return self

            def __exit__(self, *unused):
                taken.append("released")
        with patch.object(seen, "Mutex", Lock):
            self.control.acknowledge_failure(1000.0)
        self.assertEqual(taken, [str(self.paths.failure_seen_file), "released"])

    def test_a_changed_file_is_read_again_and_an_unchanged_one_is_not(self):
        self.control.acknowledge_failure(1000.0)
        self.assertEqual(self.control.failure_seen_at(), 1000.0)
        with patch.object(Path, "read_text", side_effect=AssertionError("read again")):
            self.assertEqual(self.control.failure_seen_at(), 1000.0)
        self.write('{"seen_at": 2000.5}')
        os.utime(self.paths.failure_seen_file, ns=(1, 1))
        self.assertEqual(self.control.failure_seen_at(), 2000.5)

    def test_a_write_windows_refuses_is_a_miss_and_not_an_error(self):
        self.control.acknowledge_failure(1000.0)
        with patch.object(os, "replace", side_effect=PermissionError("in use")):
            self.assertEqual(self.control.acknowledge_failure(2000.0), {"seen_at": 1000.0, "written": False})
        self.assertEqual(self.control.failure_seen_at(), 1000.0)
        self.assertEqual(list(self.paths.state_dir.glob("failure-seen.*.tmp")), [])

    def test_no_state_directory_is_no_write(self):
        with tempfile.TemporaryDirectory() as empty:
            paths = config.Paths(Path(empty) / "not-installed")
            self.assertEqual(control.Control(paths).acknowledge_failure(1.0), {"seen_at": None, "written": False})
            self.assertFalse(paths.state_dir.exists())

    def test_the_file_is_the_product_s_own_and_uninstall_takes_it(self):
        self.control.acknowledge_failure(1000.0)
        (self.paths.state_dir / "failure-seen.123.tmp").write_text("{}", encoding="utf-8")
        owned = self.paths.owned_state_files()
        self.assertIn(self.paths.failure_seen_file, owned)
        self.assertIn(self.paths.state_dir / "failure-seen.123.tmp", owned)


class StoreMarkTests(ControlTestCase):
    """Store.failure_marks: from the records, a `failed` outcome not hidden by Clear history, and the newest claim."""

    def set_row(self, key, **columns):
        import sqlite3
        connection = sqlite3.connect(str(self.paths.state_dir / "state.sqlite"))
        try:
            assignments = ", ".join("%s=?" % name for name in columns)
            connection.execute("UPDATE interruptions SET %s WHERE interruption_id=?" % assignments,
                               (*columns.values(), key))
            connection.commit()
        finally:
            connection.close()

    def marks(self):
        with Store(self.paths.state_dir) as store:
            return store.failure_marks()

    def test_an_empty_store_has_neither(self):
        self.register()
        self.assertEqual(self.marks(), marks(None, None))

    def test_the_newest_failure_and_the_newest_recovery_on_its_way(self):
        self.register(key="a" * 64)
        self.register(key="b" * 64, thread_id="0a1b2c3d-0001-7000-8000-00000000000b")
        self.register(key="c" * 64, thread_id="0a1b2c3d-0001-7000-8000-00000000000c")
        self.set_row("a" * 64, state="failed", outcome_at=300.0, first_queued_at=280.0)
        self.set_row("b" * 64, state="failed", outcome_at=250.0, first_queued_at=240.0)
        self.set_row("c" * 64, submitted_at=310.0)
        self.assertEqual(self.marks(), marks(300.0, 310.0))
        self.set_row("c" * 64, submitted_at=None, turn_started_at=320.0)
        self.assertEqual(self.marks(), marks(300.0, 320.0))

    def test_a_claim_handed_back_unsent_is_no_recovery_on_its_way(self):
        """release_claim keeps last_claim_at and clears submitted_at: nothing was sent, and the red stays."""
        self.register(key="a" * 64)
        self.register(key="b" * 64, thread_id="0a1b2c3d-0001-7000-8000-00000000000b")
        self.set_row("a" * 64, state="failed", outcome_at=300.0, first_queued_at=280.0)
        self.set_row("b" * 64, last_claim_at=310.0, submitted_at=None)
        self.assertEqual(self.marks(), marks(300.0, 280.0))

    def test_a_failure_cleared_from_history_or_without_an_outcome_time_counts_for_nothing(self):
        self.register(key="a" * 64)
        self.register(key="b" * 64, thread_id="0a1b2c3d-0001-7000-8000-00000000000b")
        self.set_row("a" * 64, state="failed", outcome_at=300.0, history_hidden_at=400.0)
        self.set_row("b" * 64, state="failed", outcome_at=None)
        self.assertEqual(self.marks()["failed_at"], None)

    def test_only_a_certain_failure_is_a_failure(self):
        for index, state in enumerate(("submission_unknown", "terminal_failure", "retry_budget_exhausted",
                                       "cancelled")):
            key = "%x" % (index + 10) * 64
            self.register(key=key[:64], thread_id="0a1b2c3d-0001-7000-8000-%012d" % index)
            self.set_row(key[:64], state=state, outcome_at=300.0 + index, submitted_at=290.0)
        self.assertEqual(self.marks()["failed_at"], None)

    def test_get_status_says_whether_one_is_unseen(self):
        self.register()
        self.set_row(detection()["interruption_id"], state="failed", outcome_at=300.0, first_queued_at=290.0)
        self.assertIs(self.control.get_status()["failure_unseen"], False, "no seen time: nothing is shown")
        self.control.acknowledge_failure(200.0, baseline=True)           # the watcher's start, before the failure
        self.assertIs(control.Control(self.paths).get_status()["failure_unseen"], True)
        self.control.acknowledge_failure(301.0)
        self.assertIs(control.Control(self.paths).get_status()["failure_unseen"], False)


class BridgeTests(ControlTestCase):
    def test_the_dashboard_in_front_acknowledges_through_the_bridge(self):
        reply = controlcli.dispatch(self.control, "failure-seen", {})
        self.assertIs(reply["ok"], True)
        self.assertIs(reply["result"]["written"], True)
        self.assertIsNotNone(control.Control(self.paths).failure_seen_at())


class WatcherTests(ControlTestCase):
    def test_the_watcher_writes_its_start_as_the_baseline_once(self):
        watcher = app.App.__new__(app.App)
        watcher.paths = self.paths
        watcher.logger = type("Log", (), {"info": lambda *args: None})()
        with patch.object(time, "time", return_value=5000.0):
            watcher._failure_baseline()
        self.assertEqual(control.Control(self.paths).failure_seen_at(), 5000.0)
        with patch.object(time, "time", return_value=9000.0):
            watcher._failure_baseline()
        self.assertEqual(control.Control(self.paths).failure_seen_at(), 5000.0, "a baseline never moves a time")

    def test_the_watcher_makes_the_baseline_good_as_it_starts_and_at_every_tick(self):
        """Read from the loop's source: at the start, and after every tick but a single one (--once)."""
        import inspect
        source = inspect.getsource(app.App._loop)
        self.assertEqual(source.count("self._failure_baseline()"), 2)
        self.assertLess(source.index("self._failure_baseline()"), source.index("self._start_tray(stop)"))
        self.assertIn("if not once:\n                    self._failure_baseline()", source)


class FakeControl:
    def __init__(self, seen_at=None, fail=False):
        self.seen_at, self.fail, self.acknowledged = seen_at, fail, []

    def failure_unseen(self, marks):
        if self.fail:
            raise OSError("unreadable")
        return control.unseen_failure(marks, self.seen_at) is not None

    def acknowledge_failure(self):
        self.acknowledged.append(True)
        self.seen_at = 10 ** 10


class IconTests(unittest.TestCase):
    """The notification-area icon: red while unseen, asked every second, and seen when the popup is opened."""

    def test_every_second_the_icon_asks_and_the_shell_is_told_what_it_found(self):
        told = []
        icon = self.icon(FakeControl(100.0))
        icon.strings = {"tray.title": "Codex Auto Resume", "tray.failed": "A recovery failed"}
        icon.update({"enabled": True, "waiting": 0, "running": 0, "next_at": None, "failures": marks(200.0, 150.0)})
        icon._notify = lambda action: told.append(tray.tooltip(icon._shown(), icon.strings, 0))
        icon._sync_motion = lambda: None
        icon._adopt_reduce_motion = lambda popup: None
        icon._refresh()
        self.assertTrue(icon._failed)
        self.assertEqual(told, ["Codex Auto Resume\nA recovery failed"], "the shell's tip is the red one")
        icon._last_tip = told[-1]
        icon._refresh()
        self.assertEqual(len(told), 1, "and it is not told again every second")
        icon.control.seen_at = 300.0
        icon._refresh()
        self.assertFalse(icon._failed)
        self.assertEqual(told[-1], "Codex Auto Resume\nNothing waiting")

    def test_a_click_that_opens_the_popup_sees_the_failure(self):
        layer = FakeControl(100.0)
        icon = self.icon(layer)
        icon._failed = True
        icon._refresh = lambda: setattr(icon, "_refresh_calls", icon._refresh_calls + 1)
        icon._adopt_settings = lambda: None
        icon._popup_for_click = lambda: type("Popup", (), {"on_select": lambda self, keyboard=False: None})()
        icon._select()
        self.assertEqual((layer.acknowledged, icon._refresh_calls), ([True], 1))

    def icon(self, control_layer):
        icon = tray.Tray(strings={}, control=control_layer)
        icon._refresh_calls = 0
        return icon

    def test_the_icon_asks_the_control_layer_and_nothing_else_decides(self):
        snapshot = {"failures": marks(200.0, 150.0)}
        self.assertTrue(self.icon(FakeControl(100.0))._failure_unseen(snapshot))
        self.assertFalse(self.icon(FakeControl(300.0))._failure_unseen(snapshot))
        self.assertFalse(self.icon(FakeControl(None))._failure_unseen(snapshot), "no seen time: nothing")
        self.assertFalse(self.icon(FakeControl(100.0, fail=True))._failure_unseen(snapshot), "a read that fails")
        self.assertFalse(self.icon(None)._failure_unseen(snapshot), "no control layer")
        self.assertFalse(self.icon(FakeControl(100.0))._failure_unseen({}), "an old snapshot")

    def test_a_failure_turns_the_icon_red_and_says_so_when_hovered(self):
        self.assertEqual(tray.icon_state({"enabled": True}, failed=True), "failed")
        self.assertEqual(tray.icon_state({"enabled": False}, attention=True, failed=True), "failed")
        strings = {"tray.title": "Codex Auto Resume", "tray.failed": "A recovery failed"}
        self.assertEqual(tray.tooltip({"enabled": True, "failed": True}, strings, 0), "Codex Auto Resume\nA recovery failed")
        self.assertEqual(tray.tooltip({"enabled": True}, strings, 0), "Codex Auto Resume\nNothing waiting")

    def test_opening_the_popup_sees_it_and_only_when_it_is_shown(self):
        layer = FakeControl(100.0)
        icon = self.icon(layer)
        icon._refresh = lambda: setattr(icon, "_refresh_calls", icon._refresh_calls + 1)
        icon._failed = False
        icon._failure_seen()
        self.assertEqual((layer.acknowledged, icon._refresh_calls), ([], 0), "nothing red, nothing written")
        icon._failed = True
        icon._failure_seen()
        self.assertEqual((layer.acknowledged, icon._refresh_calls), ([True], 1), "written, and the icon asked again")

    def test_every_language_says_it(self):
        from codex_auto_resume import l10n
        for locale in l10n.LOCALES:
            with self.subTest(locale):
                self.assertTrue(l10n.catalog(locale).get("tray.failed"))
                self.assertNotEqual(l10n.catalog(locale)["tray.failed"], "tray.failed")


class WindowSourceTests(unittest.TestCase):
    """The settings window: red on its taskbar button by the icon's rule, and seen once it is in front."""

    def setUp(self):
        self.dashboard = guiscan.dashboard()

    def test_the_taskbar_button_is_red_for_the_same_status_key(self):
        activity = self.dashboard[self.dashboard.index("internal static string TrayActivity("):]
        activity = activity[:activity.index("\n        }\n")]
        self.assertIn('if (Equals(Get(status, "failure_unseen"), true)) return "failed";', activity)
        self.assertLess(activity.index('"watcher_running"'), activity.index('"failure_unseen"'),
                        "no watcher of this version, no red: it would be an icon that is not there")

    def test_the_window_in_front_acknowledges_through_the_bridge_and_reads_again(self):
        tell = self.dashboard[self.dashboard.index("private void TellTaskbar("):]
        tell = tell[:tell.index("\n        }\n")]
        self.assertIn("ActiveForm == this", tell)
        self.assertIn("!auditing", tell, "a layout audit or a picture build never writes the file")
        self.assertIn("AcknowledgeFailure();", tell)
        acknowledge = self.dashboard[self.dashboard.index("private void AcknowledgeFailure("):]
        acknowledge = acknowledge[:acknowledge.index("\n        }\n")]
        self.assertIn('bridge.Call("failure-seen", null)', acknowledge)
        self.assertIn("RefreshAfterChange()", acknowledge)
        self.assertIn("AcknowledgeEveryMs", acknowledge, "never in a loop, whatever the answer")
        self.assertIn("RefreshFailure()", acknowledge, "the Settings page, which reads no snapshot, reads the status")

    def test_the_settings_page_still_reads_whether_a_failure_is_unseen(self):
        clock = self.dashboard[self.dashboard.index("clock.Tick += delegate"):]
        clock = clock[:clock.index("clock.Start();")]
        self.assertIn("else if (ticks % 5 == 0) RefreshFailure();", clock)
        refresh = self.dashboard[self.dashboard.index("private void RefreshFailure("):]
        refresh = refresh[:refresh.index("\n        }\n")]
        self.assertIn('bridge.Call("status", null)', refresh)
        self.assertIn('held["failure_unseen"]', refresh)
        self.assertNotIn("ApplyStatus", refresh, "an unsaved edit on the page is never put back")


if __name__ == "__main__":
    unittest.main()
