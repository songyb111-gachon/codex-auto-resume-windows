"""The one-click installer, and the state upgrade it must never destroy.

The installer is a bootstrapper, not a runtime: it may only automate the documented
commands. These tests assert that, and that upgrading keeps pending recoveries.
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import unittest

from codex_auto_resume.store import SCHEMA_VERSION, Store, StoreError

ROOT = Path(__file__).resolve().parents[1]
INSTALL_DIR = ROOT / "install"
PS1 = INSTALL_DIR / "install.ps1"


def failure(interruption="a" * 64, ordinal=5):
    return {"thread_id": "0a1b2c3d-0001-7000-8000-000000000001",
            "turn_id": "0a1b2c3d-0002-7000-8000-000000000002",
            "completed_at": 1788600100.0, "started_at": 1788600000.0, "ordinal": ordinal,
            "interruption_id": interruption, "reset_at": 1788645827.0,
            "limit_type": "codex:primary", "uncertain": False}


class PackagingTests(unittest.TestCase):
    def test_the_expected_files_exist(self):
        for name in ("Install.cmd", "Uninstall.cmd", "install.ps1", "README.txt"):
            self.assertTrue((INSTALL_DIR / name).is_file(), name)

    def test_batch_files_use_windows_line_endings(self):
        for name in ("Install.cmd", "Uninstall.cmd"):
            data = (INSTALL_DIR / name).read_bytes()
            self.assertIn(b"\r\n", data, name)
            self.assertNotIn(b"\r\r", data, name)

    def test_the_launcher_only_calls_the_script_shipped_beside_it(self):
        for name in ("Install.cmd", "Uninstall.cmd"):
            text = (INSTALL_DIR / name).read_text(encoding="utf-8")
            # Relative to the launcher, never an absolute or PATH-resolved script.
            self.assertIn('"%~dp0install', text)
            self.assertIn("-ExecutionPolicy Bypass", text)

    def test_no_engine_is_duplicated_into_the_installer(self):
        # The installer must ship commands, never a second copy of the runtime.
        for entry in INSTALL_DIR.iterdir():
            self.assertIn(entry.suffix.lower(), (".cmd", ".ps1", ".txt"), entry.name)


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.text = PS1.read_text(encoding="utf-8")

    def test_it_never_requires_administrator_rights(self):
        for forbidden in ("RunAs", "-Verb Runas", "Start-Process -Verb", "requireAdministrator"):
            self.assertNotIn(forbidden, self.text)

    def test_it_creates_no_service_and_no_scheduled_task(self):
        for forbidden in ("New-Service", "sc.exe", "schtasks", "Register-ScheduledTask", "New-ScheduledTask"):
            self.assertNotIn(forbidden, self.text)

    def test_it_writes_no_machine_wide_registry(self):
        self.assertNotIn("HKLM", self.text)
        self.assertNotIn("HKEY_LOCAL_MACHINE", self.text)

    def test_it_replaces_program_files_but_never_state(self):
        """An upgrade may replace the program; it must not touch the recovery history."""
        install_section = self.text[self.text.index("# ---"):]
        # The replace list is exactly the two program directories.
        self.assertIn("src = 'app'", install_section)
        self.assertIn("src = 'runtime'", install_section)
        # Settings, state and logs are only ever removed under an explicit -Purge.
        purge = self.text.index("if ($Purge)")
        for state in ("'config'", "'logs'"):
            first = self.text.index(state)
            self.assertGreater(first, purge, "%s must only be removed under -Purge" % state)

    def test_purge_is_opt_in(self):
        self.assertIn("[switch]$Purge", self.text)
        # The default uninstall says so, rather than silently keeping or silently deleting.
        self.assertIn("Settings and pending recoveries were kept", self.text)

    def test_it_downloads_nothing_at_install_time(self):
        """The runtime ships in the archive; an installer must not fetch code."""
        for forbidden in ("Invoke-WebRequest", "Start-BitsTransfer", "winget install",
                          "choco install", "DownloadFile", "Invoke-RestMethod"):
            self.assertNotIn(forbidden, self.text)

    def test_it_uses_the_bundled_runtime_not_a_system_python(self):
        self.assertIn("Join-Path $RunDir 'python.exe'", self.text)
        self.assertIn("no system Python needed", self.text)
        # No PATH lookup for an interpreter anywhere.
        self.assertNotIn("Get-Command python", self.text)

    def test_it_delegates_setup_rather_than_reimplementing_it(self):
        self.assertIn("plugin_setup.py", self.text)
        for verb in ("setup", "doctor", "uninstall"):
            self.assertIn("'" + verb + "'", self.text)
        # It must not register autostart or the protocol itself.
        self.assertNotIn("CurrentVersion\\Run", self.text)
        self.assertNotIn("URL Protocol", self.text)

    def test_it_reports_the_bundled_runtime_version(self):
        # There is no version floor to enforce any more - we ship the interpreter - but
        # the installer must still prove which one it deployed.
        self.assertIn("sys.version_info", self.text)
        self.assertIn("Bundled Python", self.text)

    def test_uninstall_removes_the_watcher_before_the_plugin(self):
        # The watcher must be torn down while its runtime still exists.
        watcher = self.text.index("Removing the watcher")
        plugin = self.text.index("Removing the Codex plugin")
        files = self.text.index("Removing program files")
        self.assertLess(watcher, plugin)
        self.assertLess(plugin, files)

    def test_native_calls_do_not_redirect_stderr_into_powershell(self):
        """PowerShell 5.1 turns native stderr into a terminating error, and codex
        writes ordinary progress there."""
        code = [line for line in self.text.splitlines() if not line.strip().startswith("#")]
        self.assertNotIn("2>&1", "\n".join(code))
        self.assertIn("Invoke-Codex", self.text)

    def test_an_existing_marketplace_is_repointed_not_fatal(self):
        self.assertIn("already added from a different source", self.text)


@unittest.skipUnless(shutil.which("powershell") or shutil.which("powershell.exe"),
                     "PowerShell is unavailable")
class ParseTests(unittest.TestCase):
    def test_the_installer_parses_as_powershell(self):
        script = (
            "$e=$null;"
            "[void][System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$null,[ref]$e);"
            "if($e -and $e.Count -gt 0){$e[0].Message; exit 1} else {'OK'}"
        ) % str(PS1).replace("'", "''")
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


class StateUpgradeTests(unittest.TestCase):
    """An update of this tool must never cost the user a pending recovery."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def make_schema_1(self):
        """A database exactly as schema 1 wrote it, with one pending record."""
        store = Store(self.root)
        store.register(failure(), 111.0, state="waiting_reset", next_retry_at=222.0)
        store.close()
        path = self.root / "state.sqlite"
        with closing(sqlite3.connect(path)) as db:
            for name, _definition in (("category", ""), ("recovery_attempts", ""), ("no_progress_count", "")):
                db.execute("ALTER TABLE interruptions DROP COLUMN %s" % name)
            db.execute("PRAGMA user_version=1")
            db.commit()
        return path

    def test_upgrading_preserves_the_pending_record(self):
        path = self.make_schema_1()
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
        store = Store(self.root)
        self.addCleanup(store.close)
        records = store.all_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["state"], "waiting_reset")
        self.assertEqual(records[0]["next_retry_at"], 222.0)

    def test_upgraded_rows_default_to_the_only_category_schema_1_could_record(self):
        self.make_schema_1()
        store = Store(self.root)
        self.addCleanup(store.close)
        row = store.all_records()[0]
        self.assertEqual(row["category"], "usage_limit")
        self.assertEqual(row["recovery_attempts"], 0)
        self.assertEqual(row["no_progress_count"], 0)

    def test_the_upgrade_is_recorded_and_not_repeated(self):
        path = self.make_schema_1()
        Store(self.root).close()
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
        store = Store(self.root)          # opening again must be a no-op
        self.addCleanup(store.close)
        self.assertEqual(len(store.all_records()), 1)

    def test_a_future_schema_is_still_refused(self):
        self.make_schema_1()
        Store(self.root).close()
        with closing(sqlite3.connect(self.root / "state.sqlite")) as db:
            db.execute("PRAGMA user_version=%d" % (SCHEMA_VERSION + 1))
            db.commit()
        with self.assertRaises(StoreError):
            Store(self.root)


if __name__ == "__main__":
    unittest.main()
