"""v0.6.11: the watcher's memory guard, how it ended, the status file, and Codex's copy of the plugin.

Stage 2 items 9 and 17 (memguard.py, statusfile.py, runtime/health.py), and a defect the owner found:
after an edition change Codex keeps its copy of this plugin on the old edition until the installer can
add the plugin again (edition.cached_copy, control.plugin_copy, build/install/install.ps1).

At the defaults the memory guard is off and the status file is not written: the watcher only asks
Windows about its own memory and keeps the peak in its heartbeat. Every Windows question is behind a
port (win/ownprocess.py) and a fake stands in for it where an answer matters; no test reads the real
installation, the real Codex home or the registry's policy keys, and nothing here raises a real toast.

What each keeps: the guard stops the watcher only after a tick has ended, with its own exit code that
the launcher never starts again; warn says so once; a watcher that stops on purpose says how, and one
that is gone without saying so is called "stopped unexpectedly" only in the same sign-in of the same
start of Windows - never on a guess; the status file holds its allowlisted keys and nothing else, is
written whole, is removed when its setting is off, and an administrator's DisableStatusFile keeps it
off; and Diagnostics reads which edition Codex's copy of the plugin is, and does nothing about it.
"""
from __future__ import annotations

import ast
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import (config, edition, machine, managed, memguard, notifier,  # noqa: E402
                               notify, settings, statusfile)
from codex_auto_resume.app import EXIT_MEMORY_GUARD, App  # noqa: E402
from codex_auto_resume.control import watcher as control_watcher  # noqa: E402
from codex_auto_resume.domain.vocabulary import WatcherEnd  # noqa: E402
from codex_auto_resume.runtime.health import Health  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402
from codex_auto_resume.windows import AdapterError  # noqa: E402
from test_cli import _reset_logging  # noqa: E402
from test_control import ControlTestCase  # noqa: E402

ROOT = Path(_HERE).parent
SRC = ROOT / "src" / "codex_auto_resume"
MIB = 1024 * 1024
NOW = 1_790_000_000.0
THREAD = "0a1b2c3d-0001-7000-8000-00000000c0de"
TURN = "0a1b2c3d-0002-7000-8000-00000000c0de"
RECORD = "c0de" * 16
SIGN_IN = "00000000000a1b2c"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
POWERSHELL = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"


def values(**changes) -> dict:
    return dict(settings.defaults(), **changes)


class FakePort:
    """win/ownprocess.py's three questions, answered from here."""

    def __init__(self, memory=(40 * MIB, 48 * MIB), sign_in=SIGN_IN, booted_at=NOW - 3600):
        self.reading, self._sign_in, self._booted_at = memory, sign_in, booted_at
        self.asked = 0

    def memory(self):
        self.asked += 1
        return self.reading

    def sign_in(self):
        return self._sign_in

    def booted_at(self):
        return self._booted_at


class Notices:
    def __init__(self):
        self.raised = []

    def __call__(self, event, detail, *, final=False):
        self.raised.append((event, dict(detail), final))
        return True


def a_record(store, at=NOW):
    store.register({"thread_id": THREAD, "turn_id": TURN, "completed_at": at - 10, "started_at": at - 20,
                    "ordinal": 2, "interruption_id": RECORD, "reset_at": None, "limit_type": "x",
                    "uncertain": False, "category": "server_5xx"}, at, state="waiting_backoff",
                   next_retry_at=at + 600)


# ------------------------------------------------------------------------------ the policy
class PolicyTests(unittest.TestCase):
    def test_at_the_defaults_nothing_is_acted_on_and_no_file_is_written(self):
        self.assertEqual(memguard.mode(settings.defaults()), "off")
        self.assertEqual(memguard.verdict(settings.defaults(), 64 * 1024 * MIB, False), memguard.OK)
        self.assertFalse(statusfile.wanted(settings.defaults()))

    def test_the_settings_take_only_their_closed_lists(self):
        # v0.6.11: a limit of the person's own (Custom...), in whole MiB from 128 to 16384.
        self.assertEqual(settings.validate_update({"memory_guard_limit": "mb300"}), {"memory_guard_limit": "mb300"})
        self.assertEqual(memguard.limit_mib({"memory_guard_limit": "mb300"}), 300)
        for name, value in (("memory_guard", "kill"), ("memory_guard", True), ("memory_guard_limit", "mb100"),
                            ("memory_guard_limit", "mb16385"), ("memory_guard_limit", "mb1k"),
                            ("memory_guard_limit", 512), ("status_file", "true"), ("status_file", 1)):
            with self.subTest(name=name, value=value):
                with self.assertRaises(settings.SettingsError):
                    settings.validate_update({name: value})
        self.assertEqual(settings.validate_update({"memory_guard": "stop", "memory_guard_limit": "mb256",
                                                   "status_file": True}),
                         {"memory_guard": "stop", "memory_guard_limit": "mb256", "status_file": True})
        self.assertEqual([memguard.limit_mib({"memory_guard_limit": limit}) for limit in memguard.LIMITS],
                         [256, 512, 768, 1024, 1536, 2048])

    def test_warn_says_so_once_and_stop_only_over_the_limit(self):
        over, under = 600 * MIB, 500 * MIB
        for mode, private, warned, answer in (
                ("off", over, False, memguard.OK), ("warn", under, False, memguard.OK),
                ("warn", over, False, memguard.WARN), ("warn", over, True, memguard.OK),
                ("stop", under, False, memguard.OK), ("stop", over, False, memguard.STOP),
                ("stop", over, True, memguard.STOP), ("stop", None, False, memguard.OK),
                ("stop", True, False, memguard.OK), ("stop", 512 * MIB, False, memguard.OK)):
            with self.subTest(mode=mode, private=private, warned=warned):
                chosen = values(memory_guard=mode, memory_guard_limit="mb512")
                self.assertEqual(memguard.verdict(chosen, private, warned), answer)

    def test_a_little_over_is_never_read_as_the_limit(self):
        self.assertEqual(memguard.mib(512 * MIB + 1), 513)
        self.assertEqual(memguard.mib(512 * MIB), 512)
        self.assertIsNone(memguard.mib(-1))
        self.assertIsNone(memguard.mib(True))

    def test_its_notices_open_a_page_and_nothing_else(self):
        """A28: a notice's buttons cancel one exact interruption or open one page; these open one."""
        for event, page in (("memory_warning", "diagnostics"), ("memory_stopped", "overview")):
            with self.subTest(event):
                notice = notifier.build(event, {"used": 1100, "limit": 1024})
                self.assertIsNone(notice.key)
                uris = [uri for _label, uri in notice.actions]
                self.assertEqual([notify.parse_open_uri(uri) for uri in uris], [page])
                self.assertEqual([notify.parse_cancel_uri(uri) for uri in uris], [None])

    def test_its_notices_are_under_the_notifications_switch(self):
        for event in ("memory_warning", "memory_stopped"):
            self.assertTrue(settings.notification_enabled(settings.defaults(), event))
            self.assertFalse(settings.notification_enabled(values(notifications=False), event))


# ------------------------------------------------------------------------------ the watcher's side
class HealthCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.paths = config.Paths(Path(folder.name) / "home")
        self.paths.ensure()
        self.store = Store(self.paths.state_dir)
        self.addCleanup(self.store.close)
        self.port, self.notices, self.lines = FakePort(), Notices(), []
        self.health = Health(paths=self.paths, log=self.lines.append, notice=self.notices, port=self.port,
                             clock=lambda: NOW)


class MemoryTests(HealthCase):
    def test_the_peak_is_kept_whatever_the_setting(self):
        self.health.look()
        self.assertEqual((self.health.private, self.health.peak), (40 * MIB, 48 * MIB))
        self.port.reading = (30 * MIB, 30 * MIB)      # a peak Windows says is lower never lowers it
        self.health.look()
        self.assertEqual(self.health.peak, 48 * MIB)
        self.assertFalse(self.health.over(settings.defaults()))
        self.assertEqual(self.notices.raised, [])

    def test_warn_says_so_once_and_goes_on(self):
        self.port.reading = (1100 * MIB, 1100 * MIB)
        self.health.look()
        chosen = values(memory_guard="warn")
        self.assertFalse(self.health.over(chosen))
        self.assertFalse(self.health.over(chosen))
        self.assertEqual(self.notices.raised, [("memory_warning", {"used": 1100, "limit": 1024}, False)])

    def test_stop_is_said_once_as_windows_own_toast_and_answered(self):
        self.port.reading = (1100 * MIB, 1200 * MIB)
        self.health.look()
        self.assertTrue(self.health.over(values(memory_guard="stop")))
        self.assertEqual(self.notices.raised, [("memory_stopped", {"used": 1100, "limit": 1024}, True)])

    def test_a_reading_windows_cannot_give_is_never_over(self):
        self.port.reading = None
        self.health.look()
        self.assertIsNone(self.health.private)
        self.assertFalse(self.health.over(values(memory_guard="stop", memory_guard_limit="mb256")))


class StatusFileTests(HealthCase):
    def write(self, **changes):
        self.health.status(self.store, values(**changes), running=True, engine="verified")

    def test_off_writes_nothing_and_removes_its_own_file_once(self):
        self.write()
        self.assertFalse(self.paths.status_file.exists())
        self.write(status_file=True)
        self.assertTrue(self.paths.status_file.is_file())
        self.write()
        self.assertFalse(self.paths.status_file.exists())
        self.paths.status_file.write_text('{"format": "codex-auto-resume/status/1"}', encoding="utf-8")
        self.write()
        self.assertTrue(self.paths.status_file.exists(), "removed once, when it went off - not every tick")

    def test_it_holds_the_allowlisted_keys_and_no_id_label_or_path(self):
        a_record(self.store)
        self.store.heartbeat(NOW, pid=1, session_id="s", started_at=NOW - 60, ok=True, engine_state="verified",
                             code_version="0.6.11",
                             usage=(NOW - 5, [{"bucket": "codex", "window": "primary", "used_percent": 42.0,
                                               "window_minutes": 300, "reset_at": int(NOW) + 3600}]))
        self.write(status_file=True)
        text = self.paths.status_file.read_text(encoding="utf-8")
        written = json.loads(text)
        self.assertEqual(tuple(written), statusfile.KEYS)
        self.assertEqual((written["watcher"], written["recovery"], written["engine"], written["pending"]),
                         ("running", "paused", "verified", 1))
        self.assertEqual(sum(written["states"].values()), 1)
        self.assertLessEqual(set(written["states"]), set(machine.PUBLIC_CODES))
        self.assertEqual(written["next_check_at"], NOW + 600)
        self.assertEqual(written["usage"]["windows"][0]["used_percent"], 42.0)
        for secret in (THREAD, TURN, RECORD, RECORD[:12], str(self.paths.home), "\\", "home"):
            self.assertNotIn(secret, text, secret)

    def test_a_stopping_watcher_says_so(self):
        self.health.status(self.store, values(status_file=True), running=False, engine="unknown")
        self.assertEqual(json.loads(self.paths.status_file.read_text(encoding="utf-8"))["watcher"], "stopped")

    def test_it_is_replaced_whole_and_never_over_a_file_that_is_not_it(self):
        self.write(status_file=True)
        self.write(status_file=True)
        self.assertEqual(sorted(path.name for path in self.paths.state_dir.glob("status*")), ["status.json"])
        self.paths.status_file.write_text("somebody else's", encoding="utf-8")
        with self.assertRaises(OSError):
            self.write(status_file=True)
        self.assertFalse(statusfile.remove(self.paths.status_file))
        self.assertEqual(self.paths.status_file.read_text(encoding="utf-8"), "somebody else's")

    def test_anything_but_the_allowlist_is_refused(self):
        good = statusfile.content(now=NOW, version="0.6.11", running=True, enabled=True, observe_only=False,
                                  engine="verified", rows=[], reading=None)
        for bad in (dict(good, thread_id=THREAD), dict(good, states={"not_a_code": 1}),
                    dict(good, version="C:\\Users\\ExampleUser"), dict(good, watcher="crashed"),
                    dict(good, pending=3), dict(good, usage={"read_at": NOW, "windows": [{"account": "x"}]})):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    statusfile.clean(bad)

    def test_an_administrators_key_keeps_it_off(self):
        held = managed.Managed(disable_status_file=True)
        self.assertEqual(managed.fields(held), frozenset({"status_file"}))
        clamped = managed.clamp(values(status_file=True), held)
        self.assertFalse(statusfile.wanted(clamped))
        self.assertEqual(managed.admit({"status_file": True}, clamped, held), ({}, "status_file"))
        self.write(status_file=True)
        self.health.status(self.store, clamped, running=True, engine="verified")
        self.assertFalse(self.paths.status_file.exists(), "the key's arrival removes the file")


# ------------------------------------------------------------------------------ how it ended
class EndedTests(unittest.TestCase):
    BEAT = {"end_mark": "running", "ended_at": None, "last_tick_at": NOW - 30, "sign_in": SIGN_IN,
            "booted_at": NOW - 3600.0}

    def test_how_a_watcher_that_is_not_running_ended(self):
        ended = control_watcher.how_it_ended
        here = (SIGN_IN, NOW - 3600.0)
        for status, running, now, answer in (
                (self.BEAT, False, here, ("unexpected", NOW - 30)),
                (self.BEAT, True, here, (None, None)),
                (self.BEAT, None, here, (None, None)),
                (dict(self.BEAT, end_mark="clean", ended_at=NOW - 20), False, here, ("clean", NOW - 20)),
                (dict(self.BEAT, end_mark="memory_guard", ended_at=NOW - 20), False, here,
                 ("memory_guard", NOW - 20)),
                # ended with an earlier sign-in, or an earlier start of Windows: no surprise
                (self.BEAT, False, ("00000000000fffff", NOW - 3600.0), (None, None)),
                (self.BEAT, False, (SIGN_IN, NOW - 60.0), (None, None)),
                (self.BEAT, False, (SIGN_IN, NOW - 3600.0 + 120), ("unexpected", NOW - 30)),
                # nothing to compare with, or a heartbeat from before v0.6.11: never a guess
                (self.BEAT, False, (None, None), (None, None)),
                (dict(self.BEAT, sign_in=None), False, here, (None, None)),
                (dict(self.BEAT, end_mark=None), False, here, (None, None)),
                (None, False, here, (None, None))):
            with self.subTest(status=status, running=running, now=now):
                self.assertEqual(ended(status, running, *now), answer)

    def test_the_heartbeat_says_running_until_a_stop_on_purpose_says_how(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "state")
            try:
                self.assertFalse(store.watcher_ended(NOW, WatcherEnd.CLEAN), "no heartbeat, nothing to say it of")
                beat = dict(pid=1, session_id="s", started_at=NOW - 60, ok=True, engine_state="verified",
                            code_version="0.6.11", memory_peak=48 * MIB, sign_in=SIGN_IN, booted_at=NOW - 3600)
                store.heartbeat(NOW, **beat)
                status = store.watcher_status()
                self.assertEqual((status["end_mark"], status["ended_at"], status["memory_peak"], status["sign_in"],
                                  status["booted_at"]), ("running", None, 48 * MIB, SIGN_IN, NOW - 3600))
                self.assertTrue(store.watcher_ended(NOW + 1, WatcherEnd.MEMORY_GUARD))
                self.assertEqual((store.watcher_status()["end_mark"], store.watcher_status()["ended_at"]),
                                 ("memory_guard", NOW + 1))
                store.heartbeat(NOW + 2, **beat)
                self.assertEqual(store.watcher_status()["end_mark"], "running", "a new watcher runs")
                with self.assertRaises(ValueError):
                    store.watcher_ended(NOW + 3, WatcherEnd.UNEXPECTED)
                store.heartbeat(NOW + 4, **dict(beat, memory_peak=-1, sign_in="C:\\x", booted_at=float("nan")))
                status = store.watcher_status()
                self.assertEqual((status["memory_peak"], status["sign_in"], status["booted_at"]), (None, None, None))
            finally:
                store.close()


class WatcherViewTests(ControlTestCase):
    def test_the_view_says_how_it_ended_only_of_a_watcher_that_is_not_running(self):
        store = Store(self.paths.state_dir)
        try:
            store.heartbeat(NOW, pid=1, session_id="s", started_at=NOW - 60, ok=True, engine_state="verified",
                            code_version="0.6.11", memory_peak=48 * MIB, sign_in=SIGN_IN, booted_at=NOW - 3600)
            with patch.object(control_watcher.ownprocess, "sign_in", return_value=SIGN_IN), \
                    patch.object(control_watcher.ownprocess, "booted_at", return_value=NOW - 3600.0):
                view = self.control._watcher(store)
                self.assertEqual((view["ended"], view["ended_at"], view["memory_peak"]), ("unexpected", NOW, 48 * MIB))
                store.watcher_ended(NOW + 5, WatcherEnd.CLEAN)
                self.assertEqual((self.control._watcher(store)["ended"], self.control._watcher(store)["ended_at"]),
                                 ("clean", NOW + 5))
                with patch.object(type(self.control), "watcher_running", return_value=True):
                    view = self.control._watcher(store)
                    self.assertEqual((view["ended"], view["ended_at"], view["memory_peak"]), (None, None, 48 * MIB))
        finally:
            store.close()


# ------------------------------------------------------------------------------ the loop
class LoopTests(unittest.TestCase):
    """The real loop, with a stand-in engine, a scratch home and no Windows but its own process's."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.addCleanup(_reset_logging)
        self.home = Path(folder.name)
        self.scratch = {"LOCALAPPDATA": str(self.home / "none"), "CODEX_HOME": str(self.home / "codex")}
        with patch.dict(os.environ, self.scratch), patch.object(App, "_read_managed", return_value=managed.NONE):
            self.app = App(config.Paths(self.home), console=False)
        self.ticks, self.notices = [], Notices()

    def run_watcher(self, chosen, *, memory, once=False, stops=(True,)):
        settings.save(self.app.paths.settings_file, chosen)
        self.app._stored = settings.load(self.app.paths.settings_file)
        self.app.settings = dict(self.app._stored)
        ticks = self.ticks

        class Engine:
            def tick(self_inner):
                ticks.append(time.monotonic())

        pending = iter(stops)
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, self.scratch))
            stack.enter_context(patch.object(App, "engine", side_effect=lambda store, **kwargs: Engine()))
            stack.enter_context(patch.object(App, "wake_event", side_effect=AdapterError("unavailable")))
            stack.enter_context(patch.object(App, "_start_tray", return_value=None))
            stack.enter_context(patch.object(App, "_read_managed", return_value=managed.NONE))
            stack.enter_context(patch.object(App, "_watcher_notice", side_effect=self.notices))
            stack.enter_context(patch.object(App, "mutex"))
            stop_event = stack.enter_context(patch.object(App, "stop_event"))
            waited = stop_event.return_value.__enter__.return_value.wait
            waited.side_effect = lambda seconds: next(pending)
            port = FakePort(memory=memory)
            stack.enter_context(patch("codex_auto_resume.runtime.health.ownprocess", port))
            code = self.app.run(once=once, poll=5)
        return code, waited

    def status(self):
        with Store(self.app.paths.state_dir) as store:
            return store.watcher_status()

    def test_over_the_limit_it_stops_after_the_tick_with_its_own_code(self):
        code, waited = self.run_watcher(values(memory_guard="stop", memory_guard_limit="mb256"),
                                        memory=(300 * MIB, 300 * MIB))
        self.assertEqual(code, EXIT_MEMORY_GUARD)
        self.assertEqual(len(self.ticks), 1, "the tick it was in ended first")
        waited.assert_not_called()
        self.assertEqual(self.status()["end_mark"], "memory_guard")
        self.assertEqual(self.notices.raised, [("memory_stopped", {"used": 300, "limit": 256}, True)])

    def test_warn_goes_on_and_a_stop_asked_for_is_a_clean_end(self):
        code, waited = self.run_watcher(values(memory_guard="warn", memory_guard_limit="mb256"),
                                        memory=(300 * MIB, 300 * MIB), stops=(False, True))
        self.assertEqual(code, 0)
        self.assertEqual(len(self.ticks), 2)
        self.assertEqual([event for event, _detail, _final in self.notices.raised], ["memory_warning"])
        status = self.status()
        self.assertEqual((status["end_mark"], status["memory_peak"]), ("clean", 300 * MIB))

    def test_at_the_defaults_it_only_keeps_the_peak(self):
        code, _ = self.run_watcher(settings.defaults(), memory=(3000 * MIB, 3000 * MIB), stops=(False, True))
        self.assertEqual(code, 0)
        self.assertEqual(len(self.ticks), 2)
        self.assertEqual(self.notices.raised, [])
        self.assertFalse(self.app.paths.status_file.exists())
        status = self.status()
        self.assertEqual((status["memory_peak"], status["sign_in"], status["end_mark"]), (3000 * MIB, SIGN_IN, "clean"))

    def test_a_status_file_on_is_written_every_tick_and_says_stopped_at_the_end(self):
        code, _ = self.run_watcher(values(status_file=True), memory=(40 * MIB, 40 * MIB), once=True)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(self.app.paths.status_file.read_text(encoding="utf-8"))["watcher"], "stopped")

    def test_a_watcher_that_dies_says_nothing_of_how_it_ended(self):
        class Crash(BaseException):
            pass

        def dies(store, **kwargs):
            class Engine:
                def tick(self_inner):
                    raise Crash()
            return Engine()

        settings.save(self.app.paths.settings_file, settings.defaults())
        with patch.dict(os.environ, self.scratch), patch.object(App, "engine", side_effect=dies), \
                patch.object(App, "wake_event", side_effect=AdapterError("unavailable")), \
                patch.object(App, "_start_tray", return_value=None), \
                patch.object(App, "_read_managed", return_value=managed.NONE), \
                patch.object(App, "mutex"), patch.object(App, "stop_event"), \
                patch("codex_auto_resume.runtime.health.ownprocess", FakePort()):
            with Store(self.app.paths.state_dir, migrate=True) as store:
                store.heartbeat(NOW, pid=1, session_id="s", started_at=NOW - 60, ok=True, engine_state="verified",
                                code_version="0.6.11", sign_in=SIGN_IN, booted_at=NOW - 3600)
            with self.assertRaises(Crash):
                self.app.run(once=False, poll=5)
        self.assertEqual(self.status()["end_mark"], "running", "a crash writes no end")


class LauncherTests(unittest.TestCase):
    """The memory guard's exit code is returned as it is and never starts a watcher again."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name)
        copy = self.home / "watcher-launcher.py"
        shutil.copyfile(ROOT / "scripts" / "watcher_launcher.py", copy)
        (self.home / "runtime.json").write_text(json.dumps({"home": str(self.home)}), encoding="utf-8")
        spec = importlib.util.spec_from_file_location("watcher_launcher_health", copy)
        self.launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.launcher)
        saved = list(sys.path)
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), saved))
        environment = patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop(self.launcher.RELAUNCH_MARK, None)

    def test_only_a_newer_state_is_started_again(self):
        self.assertEqual(self.launcher.EXIT_MEMORY_GUARD, EXIT_MEMORY_GUARD)
        for code in (0, 1, 3, self.launcher.EXIT_SCHEMA_NEWER, EXIT_MEMORY_GUARD):
            with self.subTest(code=code):
                with patch.object(self.launcher, "resolve_plugin_root", return_value=ROOT), \
                        patch("codex_auto_resume.cli.main", return_value=code), \
                        patch.object(self.launcher, "_relaunch_once") as relaunch, \
                        patch.object(self.launcher, "_supervise"):
                    self.assertEqual(self.launcher.main([]), code)
                self.assertEqual(relaunch.called, code == self.launcher.EXIT_SCHEMA_NEWER)


# ------------------------------------------------------------------------------ Codex's copy of the plugin
class PluginCopyTests(ControlTestCase):
    def copy(self, codex, version, edition_word, *, marketplace=edition.MARKETPLACE, when=None):
        root = codex / "plugins" / "cache" / marketplace / edition.PLUGIN / version
        (root / "src" / "codex_auto_resume").mkdir(parents=True)
        if edition_word == "advanced":
            (root / "src" / edition.ADVANCED_PACKAGE).mkdir()
            (root / "src" / edition.ADVANCED_PACKAGE / "__init__.py").write_text("", encoding="utf-8")
        if when is not None:
            os.utime(root, (when, when))
        return root

    def answer(self, codex):
        with patch.object(config, "codex_home", return_value=codex):
            return self.control.plugin_copy()

    def test_it_compares_the_newest_copy_and_does_nothing_about_it(self):
        codex = self.home / "codex"
        self.assertEqual(self.answer(codex), {"installed": "standard", "copy": None, "matches": True})
        self.copy(codex, "0.6.10", "standard", when=NOW - 100)
        self.assertEqual(self.answer(codex), {"installed": "standard", "copy": "standard", "matches": True})
        newest = self.copy(codex, "0.6.11", "advanced", when=NOW)
        before = sorted(str(path) for path in codex.rglob("*"))
        self.assertEqual(self.answer(codex), {"installed": "standard", "copy": "advanced", "matches": False})
        self.assertEqual(sorted(str(path) for path in codex.rglob("*")), before, "read only")
        os.utime(newest, (NOW - 200, NOW - 200))
        self.assertEqual(self.answer(codex)["copy"], "standard", "the newest by its time, as the launcher finds it")

    def test_only_this_products_copies_count(self):
        codex = self.home / "codex"
        self.copy(codex, "1.0.0", "advanced", marketplace="someone-else")
        (codex / "plugins" / "cache" / edition.MARKETPLACE / edition.PLUGIN / "junk").mkdir(parents=True)
        self.assertEqual(self.answer(codex)["copy"], None)


@unittest.skipUnless(POWERSHELL.is_file(), "the installer is PowerShell on Windows")
class InstallerTests(unittest.TestCase):
    """What a failed `codex plugin add` says, lifted out of build/install/install.ps1 and run alone."""

    SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:CAR_INSTALLER, [ref]$null, [ref]$errors)
if ($errors -and $errors.Count) { throw 'install.ps1 does not parse' }
foreach ($node in $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    if ($node.Name -in @('Warn', 'Write-PluginNotUpdated')) { Invoke-Expression $node.Extent.Text }
}
Write-PluginNotUpdated -From 'standard' -To 'advanced'
Write-Host '--'
Write-PluginNotUpdated -From 'advanced' -To 'standard'
Write-Host '--'
Write-PluginNotUpdated
"""

    def test_after_an_edition_change_it_says_what_is_new_already_and_what_waits(self):
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-Command", self.SCRIPT], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                              encoding="utf-8", errors="replace", timeout=120, creationflags=NO_WINDOW,
                              env=dict(os.environ, CAR_INSTALLER=str(ROOT / "build" / "install" / "install.ps1")))
        self.assertEqual(done.returncode, 0, done.stdout)
        up, down, same = [" ".join(part.split()) for part in done.stdout.split("--")]
        self.assertIn("Codex still has the Standard edition's copy of it.", up)
        self.assertIn("Its tools already run the Advanced edition installed here", up)
        self.assertIn("only the skill's text is still the old one", up)
        self.assertIn("Close the ChatGPT/Codex app and run this installer again", up)
        self.assertIn("Codex still has the Advanced edition's copy of it.", down)
        self.assertIn("Its tools already run the Standard edition installed here", down)
        self.assertIn("Could not update the Codex plugin; the watcher and its settings still work.", same)
        self.assertNotIn("edition", same)

    def test_the_installer_says_it_where_the_edition_changed(self):
        text = (ROOT / "build" / "install" / "install.ps1").read_text(encoding="utf-8")
        failed = text[text.index("if ($installed.Code -ne 0) {\n    # After an edition change"):]
        self.assertIn("if ($editionChange) { Write-PluginNotUpdated -From $previousEdition -To $edition }",
                      failed[:400])


# ------------------------------------------------------------------------------ what each reaches
class AdapterTests(unittest.TestCase):
    def imports(self, path):
        found = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                found.add((node.module or "").split(".")[0])
        return found

    def test_the_windows_questions_start_nothing_and_reach_no_network(self):
        self.assertLessEqual(self.imports(SRC / "win" / "ownprocess.py"), {"__future__", "ctypes", "os", "time"})

    def test_the_engine_never_asks_them_and_the_status_file_is_never_read_back(self):
        for path in list((SRC / "engine").glob("*.py")) + [SRC / "store" / "claims.py"]:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("ownprocess", text, path.name)
            self.assertNotIn("statusfile", text, path.name)
            self.assertNotIn("memguard", text, path.name)
        readers = [path.relative_to(SRC).as_posix() for path in SRC.rglob("*.py")
                   if re.search(r"\.status_file\b", path.read_text(encoding="utf-8"))]
        self.assertEqual(sorted(readers), ["config.py", "runtime/health.py"],
                         "only the watcher writes it; nothing reads it back")


if __name__ == "__main__":
    unittest.main()
