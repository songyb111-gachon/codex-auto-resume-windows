"""A settings file that cannot be read now is never taken as the defaults (v0.6.18, the core audit's R1).

An antivirus scan, a backup or a sync tool can hold the settings file for a moment (a sharing violation), and a hand
edit can leave a typo in it. Until v0.6.18 that one read handed back the defaults and the watcher acted on them: Observe
only written off in the state, categories switched off recovered again, and every waiting record of an extra Codex home
cancelled for good. Now the watcher keeps the settings in force and reads again at the next tick; with no good read yet
it builds no engine at all, so nothing is sent or cancelled; and a save never writes the defaults over a file it could
not read. Its own module: the scenario modules are frozen (tests/neutral.py MODULES).

Scratch homes only; the Codex engine, the icon and the policy keys are stood in for.
"""
from __future__ import annotations

import contextlib
import os
import pathlib
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from codex_auto_resume import config, homes as configured, l10n, managed, settings
from codex_auto_resume.runtime import homes as runtime_homes
from codex_auto_resume.store import Store
from codex_auto_resume.ui import popup as tray_popup
from codex_auto_resume.windows import AdapterError

from test_watcher_health import FakePort, _reset_logging


@contextlib.contextmanager
def unreadable(path, error=None):
    """Every read of the file at `path` fails as a file another program holds fails."""
    real = pathlib.Path.read_text
    target = os.path.normcase(str(path))

    def read_text(self, *args, **kwargs):
        if os.path.normcase(str(self)) == target:
            raise error or PermissionError(32, "The process cannot access the file")
        return real(self, *args, **kwargs)
    with patch.object(pathlib.Path, "read_text", read_text):
        yield


class ReadTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "settings.json"

    def test_a_held_file_is_unreadable_and_never_the_defaults(self):
        settings.save(self.path, dict(settings.defaults(), observe_only=True))
        with unreadable(self.path), self.assertRaises(settings.Unreadable) as raised:
            settings.read(self.path)
        self.assertTrue(raised.exception.transient)
        self.assertEqual(raised.exception.reason, "PermissionError")
        self.assertNotIn(str(self.path), str(raised.exception), "no path in the words")
        self.assertIs(settings.read(self.path)["observe_only"], True)

    def test_a_typo_is_unreadable_but_not_transient(self):
        self.path.write_text('{"observe_only": true,', encoding="utf-8")
        with self.assertRaises(settings.Unreadable) as raised:
            settings.read(self.path)
        self.assertFalse(raised.exception.transient)

    def test_no_file_is_the_defaults_and_load_keeps_its_fallback(self):
        self.assertEqual(settings.read(self.path), settings.defaults())
        settings.save(self.path, dict(settings.defaults(), observe_only=True))
        with unreadable(self.path):
            self.assertEqual(settings.load(self.path), settings.defaults(), "load is what it was")

    def test_a_save_never_writes_the_defaults_over_a_file_it_could_not_read(self):
        settings.save(self.path, dict(settings.defaults(), observe_only=True, max_recovery_attempts=9))
        before = self.path.read_bytes()
        with unreadable(self.path), self.assertRaises(settings.SettingsError):
            settings.update(self.path, {"notifications": False})
        self.assertEqual(self.path.read_bytes(), before, "the person's file is left as it was")

    def test_a_save_still_repairs_a_file_that_holds_no_settings(self):
        self.path.write_text("{not json", encoding="utf-8")
        saved = settings.update(self.path, {"observe_only": True})
        self.assertIs(saved["observe_only"], True)
        self.assertIs(settings.read(self.path)["observe_only"], True)


class WatcherTests(unittest.TestCase):
    def setUp(self):
        previous = l10n.preference()
        self.addCleanup(l10n.set_preference, previous)
        self.addCleanup(tray_popup.set_theme, tray_popup.THEME_SYSTEM)
        self.addCleanup(tray_popup.set_reduce_motion, False)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.codex = self.root / "codex"
        self.codex.mkdir()
        self.paths = config.Paths(self.root / "home")
        self.paths.state_dir.mkdir(parents=True, exist_ok=True)
        keys = patch("codex_auto_resume.control.policy.managed_policy", return_value=managed.NONE)
        keys.start()
        self.addCleanup(keys.stop)

    def app(self, chosen):
        from codex_auto_resume import app
        settings.save(self.paths.settings_file, dict(settings.defaults(), **chosen))
        return app.App(self.paths, codex_home=self.codex, enable_logging=False)

    def edit(self, **changes):
        """A change to the file, so its stamp moves and the watcher reads it again."""
        values = settings.read(self.paths.settings_file)
        settings.save(self.paths.settings_file, dict(values, **changes))
        status = self.paths.settings_file.stat()
        os.utime(self.paths.settings_file, ns=(status.st_atime_ns, status.st_mtime_ns + 10_000_000))

    def test_a_failed_read_keeps_observe_only_and_the_categories_and_reads_again(self):
        instance = self.app({"observe_only": True, "recover_network_transient": False})
        kept = dict(instance.settings)
        adopted = []
        with Store(self.paths.state_dir) as store:
            store.set_observe_only(True)
            engine = types.SimpleNamespace(store=store, apply_policy=lambda values, keys=None: adopted.append(values))
            self.edit(max_recovery_attempts=7)
            with unreadable(self.paths.settings_file):
                self.assertFalse(instance.refresh_settings(engine))
                self.assertFalse(instance.refresh_settings(engine), "tried again, still kept")
            self.assertEqual(instance.settings, kept, "the settings in force are kept whole")
            self.assertEqual(adopted, [], "the engine was handed nothing")
            self.assertTrue(store.settings()["observe_only"], "Observe only is never written off on a failed read")
            self.assertTrue(instance.refresh_settings(engine), "the next good read takes the edit up")
        self.assertEqual(instance.settings["max_recovery_attempts"], 7)
        self.assertIs(instance.settings["observe_only"], True)
        self.assertIs(instance.settings["recover_network_transient"], False, "a category switched off stays off")

    def test_a_failed_read_never_retires_an_extra_home(self):
        extra = self.root / "second"
        extra.mkdir()
        instance = self.app({configured.FIELD: [{"path": str(extra), "alias": "Second"}]})
        key = configured.key(extra)
        cancelled = []
        store = types.SimpleNamespace(home_keys=lambda: {key},
                                      cancel_home=lambda home, now, reason: cancelled.append(home) or 1)
        engine = types.SimpleNamespace(store=None, apply_policy=lambda values, keys=None: None)
        self.edit(max_recovery_attempts=7)
        with patch.object(instance, "_observe_only"), patch.object(instance, "_managed_pause"), \
                unreadable(self.paths.settings_file):
            instance.refresh_settings(engine)
        homes = runtime_homes.Homes(instance)
        with patch.object(instance, "backend", side_effect=AdapterError("codex_not_found")):
            homes.sync(store)
        self.assertEqual(cancelled, [], "its waiting records are kept")
        self.assertIn(key, homes.configured())

    def test_with_no_good_read_yet_no_engine_is_built(self):
        with unreadable(self.paths.settings_file):
            instance = self.app({"observe_only": True})
        asked = []
        with patch.object(instance, "backend", side_effect=lambda: asked.append("backend")), \
                patch.object(instance, "source", side_effect=lambda: asked.append("source")):
            with Store(self.paths.state_dir) as store, unreadable(self.paths.settings_file):
                with self.assertRaises(settings.Unreadable):
                    instance.engine(store)
                self.assertFalse(store.settings()["observe_only"], "nothing was written into the state")
            self.assertEqual(asked, [], "no Codex was asked")

            class Built(Exception):
                pass

            def source():
                raise Built()
            with patch.object(instance, "source", side_effect=source), Store(self.paths.state_dir) as store:
                with self.assertRaises(Built):
                    instance.engine(store)
        self.assertIs(instance.settings["observe_only"], True, "the good read came first")


class LoopTests(unittest.TestCase):
    """The real loop, once, with a settings file held from the start: no engine, no traceback, one line."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.addCleanup(_reset_logging)
        self.home = Path(folder.name)
        self.scratch = {"LOCALAPPDATA": str(self.home / "none"), "CODEX_HOME": str(self.home / "codex")}

    def test_the_watcher_waits_quietly_for_a_good_read(self):
        from codex_auto_resume.runtime.app import App
        paths = config.Paths(self.home)
        paths.ensure()
        settings.save(paths.settings_file, dict(settings.defaults(), observe_only=True))
        asked = []
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, self.scratch))
            stack.enter_context(patch.object(App, "_read_managed", return_value=managed.NONE))
            stack.enter_context(patch.object(App, "backend", side_effect=lambda: asked.append("backend")))
            stack.enter_context(patch.object(App, "wake_event", side_effect=AdapterError("unavailable")))
            stack.enter_context(patch.object(App, "_start_tray", return_value=None))
            stack.enter_context(patch.object(App, "mutex"))
            stack.enter_context(patch.object(App, "stop_event"))
            stack.enter_context(patch("codex_auto_resume.runtime.health.ownprocess", FakePort()))
            stack.enter_context(unreadable(paths.settings_file))
            app = App(paths, console=False)
            code = app.run(once=True, poll=5)
        self.assertNotEqual(code, 0, "one tick with no engine is not a clean tick")
        self.assertEqual(asked, [])
        log = paths.log_file.read_text(encoding="utf-8")
        self.assertEqual(log.count("the settings file could not be read (PermissionError)"), 1)
        self.assertNotIn("initialising Codex adapter failed", log)
        self.assertFalse(paths.error_log.exists() and "Unreadable" in paths.error_log.read_text(encoding="utf-8"))
        with Store(paths.state_dir) as store:
            self.assertFalse(store.settings()["observe_only"], "nothing written on the defaults")


if __name__ == "__main__":
    unittest.main()
