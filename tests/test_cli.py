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

from codex_auto_resume import cli, config, logbook, settings, shortcut, startup
from codex_auto_resume.app import DEFAULT_POLL, App
from codex_auto_resume.store import Store, StoreError

THREAD = "0a1b2c3d-0001-7000-8000-000000000001"


def _split_command(command: str) -> list[str]:
    """Parse a Windows command line exactly as CreateProcess/CommandLineToArgvW would."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
        shell32.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
        count = ctypes.c_int()
        pointer = shell32.CommandLineToArgvW(command, ctypes.byref(count))
        if not pointer:
            raise OSError("CommandLineToArgvW failed")
        try:
            return [pointer[i] for i in range(count.value)]
        finally:
            kernel32.LocalFree(pointer)
    import shlex
    return shlex.split(command)


def _reset_logging():
    logger = logging.getLogger(logbook.LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()




class FakeWinreg:
    """A small key tree, not a single flat namespace.

    The tool now writes under two different roots (the Run key and the user's class
    registration for the notification button), so a fake that models only one of them
    would hide a mistake in the other.
    """

    HKEY_CURRENT_USER = object()
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self):
        self.keys: dict[str, dict[str, tuple[str, int]]] = {}

        class Key:
            def __init__(self_inner, path):
                self_inner.path = path

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *args):
                return False

        self.Key = Key

    # Convenience for tests that only care about the Run key.
    @property
    def values(self) -> dict[str, tuple[str, int]]:
        return self.keys.get(startup.RUN_KEY, {})

    def OpenKey(self, root, path, reserved, access):
        if path not in self.keys:
            raise FileNotFoundError(path)
        return self.Key(path)

    def CreateKeyEx(self, root, path, reserved, access):
        self.keys.setdefault(path, {})
        return self.Key(path)

    def QueryValueEx(self, key, name):
        values = self.keys.get(key.path, {})
        if name not in values:
            raise FileNotFoundError(name)
        return values[name]

    def SetValueEx(self, key, name, reserved, kind, value):
        self.keys.setdefault(key.path, {})[name] = (value, kind)

    def DeleteValue(self, key, name):
        values = self.keys.get(key.path, {})
        if name not in values:
            raise FileNotFoundError(name)
        del values[name]

    def DeleteKey(self, root, path):
        if path not in self.keys:
            raise FileNotFoundError(path)
        if any(other.startswith(path + "\\") for other in self.keys):
            raise OSError("key has subkeys")    # real winreg refuses this too
        del self.keys[path]


# Module-wide, not per class: `install` writes a real Start Menu entry and `uninstall`
# deletes one, so a single unguarded test class would edit the user's actual Start Menu.
# A per-class guard was missed once already; this cannot be missed.
_SHORTCUT_GUARDS = []


def setUpModule():
    for name, result in (("install", True), ("uninstall", False)):
        guard = patch.object(shortcut, name, return_value=result)
        guard.start()
        _SHORTCUT_GUARDS.append(guard)


def tearDownModule():
    while _SHORTCUT_GUARDS:
        _SHORTCUT_GUARDS.pop().stop()


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
        # Safety net: no CLI test may ever reach the real HKCU Run key. cmd_uninstall
        # deletes that value, so an unpatched call would wipe the user's autostart.
        self._winreg_guard = patch.object(startup, "_winreg", return_value=FakeWinreg())
        self._winreg_guard.start()
        self.addCleanup(self._winreg_guard.stop)
        # Same reason as the registry guard: `install` writes a real Start Menu entry
        # and `uninstall` deletes one, so an unguarded CLI test would edit the user's
        # actual Start Menu - and would shell out to PowerShell on every run.
        for name, result in (("install", True), ("uninstall", False)):
            guard = patch.object(shortcut, name, return_value=result)
            guard.start()
            self.addCleanup(guard.stop)

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
            store.register({"thread_id": THREAD, "turn_id": "0a1b2c3d-0002-7000-8000-000000000002",
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
        self.assertEqual(config.load_settings(config.Paths(self.home))["detection_lookback_hours"],
                         settings.DEFAULTS["detection_lookback_hours"])

    def test_command_line_edit_leaves_the_other_settings_alone(self):
        # The command line, the settings window and the Codex skill share one file. A
        # front end that names one field and rewrites the rest silently discards
        # whatever the others saved, which is invisible until recovery stops happening.
        paths = config.Paths(self.home)
        config.update_settings(paths, {"recover_timeout": False, "notify_starting": False,
                                       "max_recovery_attempts": 9})
        self.cli("enable", "--lookback-hours", "3")
        stored = config.load_settings(paths)
        self.assertEqual(stored["detection_lookback_hours"], 3.0)
        self.assertIs(stored["recover_timeout"], False)
        self.assertIs(stored["notify_starting"], False)
        self.assertEqual(stored["max_recovery_attempts"], 9)

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
        # Both calls must stay inside the registry patch: cmd_uninstall deletes the
        # HKCU Run value, so an unpatched call would wipe the real user's autostart.
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


class UninstallSafetyTests(unittest.TestCase):
    """Uninstall must delete ONLY files this tool created, and never while a watcher runs."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name) / "home"
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(_reset_logging)
        self.env = patch.dict(os.environ, {"LOCALAPPDATA": str(Path(self.temp.name) / "no-codex"),
                                           config.ENV_HOME: str(self.home)})
        self.env.start()
        self.addCleanup(self.env.stop)
        # Safety net: no CLI test may ever reach the real HKCU Run key. cmd_uninstall
        # deletes that value, so an unpatched call would wipe the user's autostart.
        self._winreg_guard = patch.object(startup, "_winreg", return_value=FakeWinreg())
        self._winreg_guard.start()
        self.addCleanup(self._winreg_guard.stop)
        # Same reason as the registry guard: `install` writes a real Start Menu entry
        # and `uninstall` deletes one, so an unguarded CLI test would edit the user's
        # actual Start Menu - and would shell out to PowerShell on every run.
        for name, result in (("install", True), ("uninstall", False)):
            guard = patch.object(shortcut, name, return_value=result)
            guard.start()
            self.addCleanup(guard.stop)

    def cli(self, *argv):
        return run_cli("--quiet", *argv)

    def test_uninstall_refuses_directories_it_did_not_create(self):
        # A pre-existing config/ and logs/ that this tool never made: user files with
        # matching names must survive untouched.
        (self.home / "config").mkdir(parents=True)
        (self.home / "logs").mkdir(parents=True)
        victim_state = self.home / "config" / "state.sqlite"
        victim_log = self.home / "logs" / "errors.log"
        victim_state.write_text("someone else's database", encoding="utf-8")
        victim_log.write_text("someone else's log", encoding="utf-8")
        paths = config.Paths(self.home)
        self.assertFalse(paths.owns(paths.state_dir))
        self.assertEqual(paths.owned_state_files(), [])
        self.assertEqual(paths.owned_log_files(), [])
        with patch.object(startup, "_winreg", return_value=FakeWinreg()):
            code, out, _ = self.cli("uninstall")
        self.assertEqual(code, 0)
        self.assertTrue(victim_state.exists(), "a file we never created must never be deleted")
        self.assertTrue(victim_log.exists())
        self.assertIn("no provenance marker", out)

    def test_uninstall_removes_only_marked_directories_contents(self):
        self.cli("install")
        paths = config.Paths(self.home)
        self.assertTrue(paths.owns(paths.state_dir), "install must leave a provenance marker")
        stranger = self.home / "logs" / "not-ours.txt"
        stranger.write_text("keep me", encoding="utf-8")
        with patch.object(startup, "_winreg", return_value=FakeWinreg()):
            code, _, _ = self.cli("uninstall")
        self.assertEqual(code, 0)
        self.assertFalse((self.home / "config" / "state.sqlite").exists())
        self.assertTrue(stranger.exists(), "unmatched names in our own dir are still left alone")

    def test_uninstall_aborts_when_watcher_state_is_unknown(self):
        self.cli("install")
        app = App(config.Paths(self.home), console=False, enable_logging=False)
        for probe, label in ((None, "unknown"), (True, "running")):
            with patch.object(App, "watcher_running", return_value=probe), \
                 patch.object(startup, "_winreg", return_value=FakeWinreg()):
                code, out, _ = self.cli("uninstall")
            self.assertEqual(code, 1, label)
            self.assertIn("uninstall aborted", out)
            self.assertTrue((self.home / "config" / "state.sqlite").exists(),
                            "state must survive an aborted uninstall (%s)" % label)
        del app


class WatcherLoopTests(unittest.TestCase):
    def test_transient_adapter_failure_does_not_end_the_watcher(self):
        # A codex.exe probe failure at logon (antivirus scan, in-progress update) must
        # defer the tick and retry, not terminate the watcher for the whole session.
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.addCleanup(_reset_logging)
        home = Path(temp.name)
        with patch.dict(os.environ, {"LOCALAPPDATA": str(home / "none")}):
            app = App(config.Paths(home), console=False)
        ticks = []
        attempts = {"n": 0}

        class OneTickEngine:
            def tick(self_inner):
                ticks.append(1)

        def flaky_engine(store, **kwargs):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise config.ConfigError("codex binary temporarily unavailable")
            return OneTickEngine()

        stops = iter([False, False, False, True])
        with patch.object(App, "engine", side_effect=flaky_engine), \
             patch.object(App, "mutex"), patch.object(App, "stop_event") as stop_event:
            stop_event.return_value.__enter__.return_value.wait.side_effect = lambda s: next(stops)
            code = app.run(once=False, poll=5)
        self.assertEqual(code, 0, "the watcher survived the transient failures")
        self.assertGreaterEqual(attempts["n"], 3, "engine construction was retried")
        self.assertTrue(ticks, "it eventually ticked once the adapter recovered")

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
            # Assert the parsed argv, not the exact quoting: quotes are added only where needed.
            self.assertEqual(_split_command(command),
                             ["C:\\py\\pythonw.exe", "C:\\x\\src\\auto_resume.py", "--home", "C:\\x", "run"])
            self.assertTrue(startup.install(command))
            self.assertFalse(startup.install(command))
            self.assertEqual(len(fake.values), 1)
            self.assertEqual(startup.current_value(), command)
            self.assertTrue(startup.uninstall())
            self.assertFalse(startup.uninstall())
            self.assertIsNone(startup.current_value())

    def test_registered_command_always_pins_the_effective_home(self):
        # With CODEX_AUTO_RESUME_HOME set and no --home, the Run value must still carry
        # the home; otherwise the login watcher uses a different state DB and mutex.
        fake = FakeWinreg()
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "envhome"
            with patch.dict(os.environ, {"LOCALAPPDATA": str(Path(temp) / "none"),
                                         config.ENV_HOME: str(home)}), \
                    patch.object(startup, "_winreg", return_value=fake):
                code, out, _ = run_cli("--quiet", "install", "--startup")
                self.assertEqual(code, 0)
                registered = fake.values[startup.VALUE_NAME][0]
            self.assertIn("--home", registered)
            self.assertIn(str(home.resolve()), registered)
            _reset_logging()

    def test_command_line_survives_a_trailing_backslash_home(self):
        # A drive-root home must not let the closing quote be escaped, which would
        # swallow the `run` subcommand.
        command = startup.command_line(Path("C:/x/src/auto_resume.py"), Path("D:/"), Path("C:/py/pythonw.exe"))
        parsed = _split_command(command)
        self.assertEqual(parsed[-1], "run")
        self.assertIn("--home", parsed)
        self.assertEqual(parsed[parsed.index("--home") + 1].rstrip("\\"), "D:")

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


class EntryPointTests(unittest.TestCase):
    """The documented command has to work with the interpreter that actually ships.

    The embeddable Python in the release replaces sys.path from its own `._pth` file,
    which turns off the usual "the script's directory is importable" rule. So the entry
    point sets the path itself, and this runs it the way the README tells a person to -
    from an unrelated working directory, with nothing on PYTHONPATH.
    """

    ENTRY = Path(__file__).resolve().parents[1] / "src" / "auto_resume.py"

    def test_it_runs_with_no_pythonpath_from_an_unrelated_directory(self):
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        with tempfile.TemporaryDirectory() as elsewhere:
            completed = subprocess.run(
                [sys.executable, str(self.ENTRY), "--help"],
                capture_output=True, text=True, timeout=120,
                cwd=elsewhere, env=environment)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("usage", completed.stdout.lower())

    def test_it_puts_its_own_package_first(self):
        # Prepended, not appended: an unrelated `codex_auto_resume` earlier on the path
        # would otherwise decide which engine runs.
        text = self.ENTRY.read_text(encoding="utf-8")
        self.assertIn("sys.path.insert(0,", text)


class CommandQuotingTests(unittest.TestCase):
    r"""Every command written to the registry, checked against the real parser.

    These exist because the previous tests only round-tripped: they parsed a command
    back and compared the arguments, which passes whether or not anything is quoted.
    The defect they missed is that `subprocess.list2cmdline` quotes only tokens that
    contain a space, so an installation under a path without one produced a completely
    unquoted Run value - and the same command under `C:\Users\John Smith\...` is read
    as the program `C:\Users\John`, so the watcher never starts at sign-in.

    `_split_command` is CommandLineToArgvW itself on Windows, which is what actually
    parses these, so agreement with it is the property worth asserting.
    """

    AWKWARD = [
        r"C:\Users\John Smith\.codex-auto-resume\runtime\pythonw.exe",
        r"D:\ ",
        "D:\\",
        r"C:\a\b",
        'has"quote',
        r"trailing\\",
        "plain",
        "",
    ]

    def test_quoting_agrees_with_the_windows_parser(self):
        # Never in first position: CommandLineToArgvW parses argv[0] by different rules
        # - it is the program name, so backslashes there are not escape characters and a
        # round trip through that slot proves nothing about the quoting of the rest.
        for value in self.AWKWARD:
            with self.subTest(value=value):
                command = " ".join([startup.quote_argument("prog.exe"),
                                    startup.quote_argument(value),
                                    startup.quote_argument("run")])
                self.assertEqual(_split_command(command), ["prog.exe", value, "run"])

    def test_every_argument_is_quoted(self):
        command = startup.command_line(Path(r"C:\home\watcher-launcher.py"), Path(r"C:\home"),
                                       launcher=Path(r"C:\py\pythonw.exe"))
        for token in command.split(" "):
            self.assertTrue(token.startswith('"') and token.endswith('"'), command)

    def test_a_home_with_a_space_still_names_the_right_program(self):
        # The failure this whole class exists for.
        launcher = Path(r"C:\Users\John Smith\.codex-auto-resume\runtime\pythonw.exe")
        script = Path(r"C:\Users\John Smith\.codex-auto-resume\watcher-launcher.py")
        argv = _split_command(startup.command_line(script, None, launcher=launcher))
        self.assertEqual(argv[0], str(launcher))
        self.assertEqual(argv[1], str(script))
        self.assertEqual(argv[-1], "run")

    def test_a_trailing_backslash_does_not_swallow_the_next_argument(self):
        # The original reason list2cmdline was used; the replacement must keep it.
        argv = _split_command(startup.command_line(Path(r"C:\a\entry.py"), Path("D:\\"),
                                                   launcher=Path(r"C:\py\pythonw.exe")))
        self.assertIn("--home", argv)
        self.assertEqual(argv[argv.index("--home") + 1], "D:\\")
        self.assertEqual(argv[-1], "run")

    def test_the_protocol_handler_is_quoted_and_keeps_its_placeholder(self):
        command = startup.protocol_command_line(Path(r"C:\Users\John Smith\a\entry.py"),
                                                Path(r"C:\Users\John Smith\a"),
                                                launcher=Path(r"C:\py\pythonw.exe"))
        self.assertTrue(command.endswith(' "%1"'))
        argv = _split_command(command)
        self.assertEqual(argv[0], r"C:\py\pythonw.exe")
        self.assertEqual(argv[-1], "%1")
        self.assertIn("activate", argv)

    def test_ownership_still_recognises_a_quoted_command(self):
        home = Path(r"C:\Users\John Smith\.codex-auto-resume")
        command = startup.command_line(home / "watcher-launcher.py", None,
                                       launcher=home / "runtime" / "pythonw.exe")
        self.assertTrue(startup.belongs_to(command, home))
