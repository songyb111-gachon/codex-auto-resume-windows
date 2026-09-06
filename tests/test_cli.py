"""CLI, configuration, logging and autostart behaviour in an isolated owned home."""
from __future__ import annotations

import contextlib
import io
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from codex_auto_resume import cli, config, logbook, startup
from codex_auto_resume.app import DEFAULT_POLL, App
from codex_auto_resume.store import Store, StoreError

THREAD = "0a1b2c3d-0101-7000-8000-000000000101"


def _reset_logging():
    logger = logging.getLogger(logbook.LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()




class FakeWinreg:
    HKEY_CURRENT_USER = object()
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self):
        self.values: dict[str, tuple[str, int]] = {}
        outer = self

        class Key:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *args):
                return False

        self.Key = Key

    def OpenKey(self, root, path, reserved, access):
        assert path == startup.RUN_KEY
        return self.Key()

    def CreateKeyEx(self, root, path, reserved, access):
        return self.OpenKey(root, path, reserved, access)

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name]

    def SetValueEx(self, key, name, reserved, kind, value):
        self.values[name] = (value, kind)

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name) / "home"
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(_reset_logging)
        # Point official-binary discovery at an empty directory so no Codex process is ever spawned.
        self.env = patch.dict(os.environ, {"LOCALAPPDATA": str(Path(self.temp.name) / "no-codex"),
                                           config.ENV_HOME: str(self.home)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def cli(self, *argv):
        return run_cli("--quiet", *argv)

    def test_install_enable_status_disable_cycle(self):
        code, out, _ = self.cli("install")
        self.assertEqual(code, 0)
        self.assertTrue((self.home / "config" / "state.sqlite").is_file())
        self.assertIn("not requested", out)
        code, out, _ = self.cli("enable")
        self.assertEqual(code, 0)
        self.assertIn("enabled", out)
        with Store(self.home / "config") as store:
            self.assertTrue(store.settings()["enabled"])
        code, out, _ = self.cli("status")
        self.assertEqual(code, 0)
        self.assertIn("ENABLED", out)
        self.assertIn("codex engine     : unavailable", out)
        code, out, _ = self.cli("disable")
        self.assertEqual(code, 0)
        with Store(self.home / "config") as store:
            self.assertFalse(store.settings()["enabled"])
        code, out, _ = self.cli("status")
        self.assertIn("auto-resume      : disabled", out)

    def test_thread_enable_disable_and_cancel(self):
        self.cli("enable", THREAD)
        with Store(self.home / "config") as store:
            self.assertTrue(store.thread_enabled(THREAD))
        self.cli("disable", THREAD)
        with Store(self.home / "config") as store:
            self.assertFalse(store.thread_enabled(THREAD))
        code, out, _ = self.cli("cancel", THREAD)
        self.assertEqual(code, 0)
        self.assertIn("cancelled", out)
        for bad in ("--last", THREAD.upper(), "not-a-uuid", THREAD + " & calc"):
            code, _, err = self.cli("cancel", "--", bad) if bad.startswith("-") else self.cli("cancel", bad)
            self.assertEqual(code, 1, bad)
            self.assertIn("canonical UUID", err)

    def test_pending_lists_records_and_json(self):
        code, out, _ = self.cli("pending")
        self.assertEqual(code, 0)
        self.assertIn("no pending", out)
        with Store(self.home / "config") as store:
            store.register({"thread_id": THREAD, "turn_id": "0a1b2c3d-0102-7000-8000-000000000102",
                            "completed_at": 1788628349.0, "started_at": 1788627820.0, "ordinal": 1,
                            "interruption_id": "a" * 64, "reset_at": 1788645827.0,
                            "limit_type": "codex:primary_hint", "uncertain": True}, 1788628400.0)
        code, out, _ = self.cli("pending")
        self.assertIn(THREAD, out)
        self.assertIn("waiting_reset", out)
        self.assertIn(logbook.format_local(1788645827), out)
        code, out, _ = self.cli("pending", "--json")
        self.assertIn('"state": "waiting_reset"', out)
        self.assertNotIn("marker", out)

    def test_lookback_setting_persisted_and_validated(self):
        code, _, _ = self.cli("enable", "--lookback-hours", "2")
        self.assertEqual(code, 0)
        self.assertEqual(config.load_settings(config.Paths(self.home))["detection_lookback_hours"], 2.0)
        code, _, err = self.cli("enable", "--lookback-hours", "99999")
        self.assertEqual(code, 1)
        self.assertEqual(config.load_settings(config.Paths(self.home))["detection_lookback_hours"], 2.0)
        (self.home / "config" / "settings.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(config.load_settings(config.Paths(self.home))["detection_lookback_hours"], config.LOOKBACK_HOURS_DEFAULT)

    def test_logs_command_and_rotation_setup(self):
        self.cli("enable")
        self.cli("disable")
        code, out, _ = self.cli("logs", "-n", "5")
        self.assertEqual(code, 0)
        self.assertIn("kill switch", out)
        handler_types = {type(h).__name__ for h in logging.getLogger(logbook.LOGGER_NAME).handlers}
        self.assertIn("RotatingFileHandler", handler_types)

    def test_run_once_without_engine_fails_closed(self):
        self.cli("enable")
        code, _, _ = self.cli("run", "--once")
        self.assertEqual(code, 1)
        text = (self.home / "logs" / "auto-resume.log").read_text(encoding="utf-8")
        self.assertIn("initialising Codex adapter failed", text)
        self.assertIn("no submission was made", text)
        self.assertTrue((self.home / "logs" / "errors.log").is_file())

    def test_uninstall_removes_only_owned_files(self):
        self.cli("install")
        self.cli("enable")
        keep = self.home / "config" / "user-note.txt"
        keep.write_text("keep me", encoding="utf-8")
        with patch.object(startup, "_winreg", return_value=FakeWinreg()):
            code, out, _ = self.cli("uninstall")
        self.assertEqual(code, 0)
        self.assertFalse((self.home / "config" / "state.sqlite").exists())
        self.assertFalse((self.home / "logs" / "auto-resume.log").exists())
        self.assertTrue(keep.exists(), "unknown files are never deleted")
        code, out, _ = self.cli("uninstall")
        self.assertEqual(code, 0)
        self.assertIn("nothing", out)

    def test_stop_without_watcher(self):
        code, out, _ = self.cli("stop")
        self.assertEqual(code, 0)
        self.assertIn("no running watcher", out)


class ConfinementTests(unittest.TestCase):
    """Owned directories/files must never escape the home via a link or NTFS junction."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.outside = self.root / "outside"
        self.outside.mkdir()
        self.home.mkdir()
        self.addCleanup(self.temp.cleanup)

    def _make_junction(self, link: Path, target: Path) -> bool:
        # mklink /J needs no administrator rights; skip if it is unavailable.
        if sys.platform != "win32":
            return False
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                                capture_output=True, text=True)
        return result.returncode == 0 and link.exists()

    def test_confined_detects_junction_escape(self):
        paths = config.Paths(self.home)
        self.assertTrue(paths.confined(self.home / "config"))
        junction = self.home / "config"
        if not self._make_junction(junction, self.outside):
            self.skipTest("could not create a junction on this platform")
        self.assertFalse(paths.confined(junction))
        with self.assertRaises(config.ConfigError):
            paths.ensure()

    def test_owned_log_files_ignores_junctioned_logs_dir(self):
        # A logs dir that is a junction to an outside folder must yield NO deletable files,
        # so uninstall can never remove an unrelated user file that happens to match.
        (self.outside / "errors.log").write_text("someone else's file", encoding="utf-8")
        logs = self.home / "logs"
        if not self._make_junction(logs, self.outside):
            self.skipTest("could not create a junction on this platform")
        paths = config.Paths(self.home)
        self.assertEqual(paths.owned_log_files(), [])

    def test_settings_temp_is_unique_and_errors_are_wrapped(self):
        paths = config.Paths(self.home)
        paths.ensure()
        config.save_settings(paths, {"detection_lookback_hours": 3.0})
        self.assertEqual(config.load_settings(paths)["detection_lookback_hours"], 3.0)
        # No fixed-name temp is left behind, and an atomic-replace failure raises ConfigError.
        self.assertEqual(list(paths.state_dir.glob("settings.*.tmp")), [])
        with patch.object(config.os, "replace", side_effect=OSError("boom")):
            with self.assertRaises(config.ConfigError):
                config.save_settings(paths, {"detection_lookback_hours": 4.0})
        self.assertEqual(list(paths.state_dir.glob("settings.*.tmp")), [], "temp cleaned up on failure")


class WatcherLoopTests(unittest.TestCase):
    def test_poll_interval_survives_store_read_failure(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)       # runs AFTER _reset_logging (LIFO): file handle freed first
        self.addCleanup(_reset_logging)
        with patch.dict(os.environ, {"LOCALAPPDATA": str(Path(temp.name) / "none")}):
            app = App(config.Paths(temp.name), console=False)

        class BadStore:
            def settings(self):
                raise StoreError("database is locked")

        # A transient store failure must fall back to a safe default, never propagate.
        self.assertEqual(app._poll_interval(BadStore(), None), DEFAULT_POLL)
        # An explicit --poll bypasses the store entirely and is clamped.
        self.assertEqual(app._poll_interval(BadStore(), 7), 7)
        self.assertEqual(app._poll_interval(BadStore(), 999999), 3600)


class StartupTests(unittest.TestCase):
    def test_install_is_idempotent_and_uninstall_clean(self):
        fake = FakeWinreg()
        with patch.object(startup, "_winreg", return_value=fake):
            command = startup.command_line(Path("C:/x/src/auto_resume.py"), Path("C:/x"), Path("C:/py/pythonw.exe"))
            self.assertEqual(command, '"C:\\py\\pythonw.exe" "C:\\x\\src\\auto_resume.py" --home "C:\\x" run')
            self.assertTrue(startup.install(command))
            self.assertFalse(startup.install(command))
            self.assertEqual(len(fake.values), 1)
            self.assertEqual(startup.current_value(), command)
            self.assertTrue(startup.uninstall())
            self.assertFalse(startup.uninstall())
            self.assertIsNone(startup.current_value())

    def test_cli_install_startup_registers_once(self):
        fake = FakeWinreg()
        with tempfile.TemporaryDirectory() as temp, \
                patch.dict(os.environ, {"LOCALAPPDATA": str(Path(temp) / "none")}), \
                patch.object(startup, "_winreg", return_value=fake):
            code, out, _ = run_cli("--quiet", "--home", temp, "install", "--startup")
            self.assertEqual(code, 0)
            self.assertIn("registered", out)
            code, out, _ = run_cli("--quiet", "--home", temp, "install", "--startup")
            self.assertIn("already registered", out)
            self.assertEqual(len(fake.values), 1)
            self.assertIn("run", fake.values[startup.VALUE_NAME][0])
            _reset_logging()


class LogbookTests(unittest.TestCase):
    def test_render_messages_are_static_and_safe(self):
        self.assertEqual(logbook.render(THREAD, "loaded", None), "thread %s: loaded" % THREAD)
        text = logbook.render(THREAD, "waiting_for_loaded_thread", "notLoaded")
        self.assertIn("notLoaded", text)
        self.assertIn("waiting until user opens this thread in ChatGPT app", text)
        # The engine passes untrusted values as the `detail` argument; it must never leak.
        self.assertNotIn("secret", logbook.render(THREAD, "usageLimitExceeded_detected", None, "secret prompt text"))
        self.assertIn("unknown-time", logbook.render(THREAD, "reset_expected", None, "not-a-number"))
        self.assertNotIn("evil", logbook.render("evil\nthread", "loaded", None))
        stamp = logbook.render(THREAD, "reset_expected", None, "1788645827")
        self.assertIn(logbook.format_local(1788645827), stamp)

    def test_format_local_uses_windows_local_timezone(self):
        text = logbook.format_local(1788645827)
        self.assertRegex(text, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [+-]\d{2}:\d{2}")
        import datetime as dt
        expected = dt.datetime.fromtimestamp(1788645827).strftime("%Y-%m-%d %H:%M:%S")
        self.assertTrue(text.startswith(expected))


class DiscoveryTests(unittest.TestCase):
    def test_discovery_requires_single_compatible_binary(self):
        with tempfile.TemporaryDirectory() as temp:
            bin_dir = Path(temp) / "OpenAI" / "Codex" / "bin"
            with patch.dict(os.environ, {"LOCALAPPDATA": temp}, clear=False):
                with self.assertRaises(config.ConfigError):
                    config.discover_codex_exe(None, lambda p: None)
                for name in ("aaaa", "bbbb"):
                    (bin_dir / name).mkdir(parents=True)
                    (bin_dir / name / "codex.exe").write_bytes(b"")

                def only_a(path):
                    if "aaaa" not in str(path):
                        raise RuntimeError("unsupported")

                self.assertEqual(config.discover_codex_exe(None, only_a).name, "codex.exe")
                self.assertIn("aaaa", str(config.discover_codex_exe(None, only_a)))
                with self.assertRaises(config.ConfigError):
                    config.discover_codex_exe(None, lambda p: None)  # two compatible -> ambiguous
                explicit = bin_dir / "bbbb" / "codex.exe"
                self.assertEqual(config.discover_codex_exe(str(explicit), lambda p: None), explicit.resolve())
                with self.assertRaises(config.ConfigError):
                    config.discover_codex_exe(str(bin_dir / "missing.exe"), lambda p: None)


if __name__ == "__main__":
    unittest.main()
