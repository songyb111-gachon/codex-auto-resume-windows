"""The one-click installer, and the state upgrade it must never destroy.

The installer is a bootstrapper, not a runtime: it may only automate the documented
commands. These tests assert that, and that upgrading keeps pending recoveries.
"""
from __future__ import annotations

from contextlib import closing
import io
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
        """A database exactly as schema 1 wrote it - by the tagged v0.3.2 store code
        itself - with one pending record."""
        from test_control_v3 import legacy_store_module
        old = legacy_store_module("v0.3.2")
        store = old.Store(self.root)
        store.register(failure(), 111.0, state="waiting_reset", next_retry_at=222.0)
        store.close()
        return self.root / "state.sqlite"

    def test_upgrading_preserves_the_pending_record(self):
        path = self.make_schema_1()
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
        # Only an opener allowed to migrate - the watcher, or one holding its mutex -
        # upgrades; it goes 1 -> 2 -> 3 in one transaction.
        store = Store(self.root, migrate=True)
        self.addCleanup(store.close)
        records = store.all_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["state"], "waiting_reset")
        self.assertEqual(records[0]["next_retry_at"], 222.0)

    def test_upgraded_rows_default_to_the_only_category_schema_1_could_record(self):
        self.make_schema_1()
        store = Store(self.root, migrate=True)
        self.addCleanup(store.close)
        row = store.all_records()[0]
        self.assertEqual(row["category"], "usage_limit")
        self.assertEqual(row["recovery_attempts"], 0)
        self.assertEqual(row["no_progress_count"], 0)

    def test_the_upgrade_is_recorded_and_not_repeated(self):
        path = self.make_schema_1()
        Store(self.root, migrate=True).close()
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
        store = Store(self.root)          # opening again must be a no-op
        self.addCleanup(store.close)
        self.assertEqual(len(store.all_records()), 1)

    def test_a_future_schema_is_still_refused(self):
        self.make_schema_1()
        Store(self.root, migrate=True).close()
        with closing(sqlite3.connect(self.root / "state.sqlite")) as db:
            db.execute("PRAGMA user_version=%d" % (SCHEMA_VERSION + 1))
            db.commit()
        with self.assertRaises(StoreError):
            Store(self.root)


class InPlaceUpgradeTests(unittest.TestCase):
    """An upgrade must survive the product's own processes being alive.

    Codex keeps this plugin's MCP server running, which holds the bundled interpreter's
    DLLs open. A loaded DLL cannot be deleted, so removing the runtime directory failed
    part-way through and left the installation half-replaced: the application updated,
    the interpreter gone. Windows does allow renaming the directory that contains an
    open file, so the installer moves the old copy aside instead.
    """

    def setUp(self):
        self.text = PS1.read_text(encoding="utf-8")

    def test_program_directories_are_moved_aside_not_deleted(self):
        self.assertIn("Move-Item -Path $pair.dst -Destination $aside", self.text)
        self.assertNotIn("if (Test-Path $pair.dst) { Remove-Item -Recurse -Force $pair.dst }", self.text)

    def test_a_failure_at_either_step_puts_the_installation_back(self):
        # The first version of this rolled back a failed move but not a failed copy, and
        # left the application present with the interpreter missing - which is how the
        # bug it fixes was reproduced in the first place.
        move = self.text.index("Move-Item -Path $pair.dst -Destination $aside")
        copy = self.text.index("Copy-Item -Path (Join-Path (Join-Path $Payload $pair.src)")
        rollback = self.text.index("foreach ($undo in $moved)")
        self.assertLess(move, copy, "moves must all happen before any copy")
        self.assertLess(copy, rollback, "the rollback must cover the copy as well")
        self.assertIn("nothing was changed", self.text)

    def test_the_rollback_clears_a_partly_copied_directory_first(self):
        # Moving the original back over a half-written directory would merge the two.
        rollback = self.text[self.text.index("foreach ($undo in $moved)"):]
        self.assertLess(rollback.index("Remove-OwnedItem $undo.to"),
                        rollback.index("Move-Item -Path $undo.from"))

    @unittest.skipUnless(shutil.which("powershell") or shutil.which("powershell.exe"),
                         "PowerShell is unavailable")
    def test_join_path_is_never_given_three_path_segments(self):
        """Windows PowerShell's Join-Path takes two paths.

        A third is bound as a parameter and fails the whole script - which is how an
        upgrade got as far as moving the old installation aside and then stopped. Text
        matching cannot see this (the first argument is often a parenthesised
        expression containing spaces), so the check runs PowerShell's own parser and
        counts the positional arguments of every Join-Path command.
        """
        script = (
            "$ast=[System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$null,[ref]$null);"
            "$bad=$ast.FindAll({param($n) $n -is "
            "[System.Management.Automation.Language.CommandAst] -and "
            "$n.GetCommandName() -eq 'Join-Path'}, $true) | Where-Object {"
            "  ($_.CommandElements | Select-Object -Skip 1 | Where-Object {"
            "     $_ -isnot [System.Management.Automation.Language.CommandParameterAst] }).Count -gt 2 };"
            "if ($bad) { $bad[0].Extent.Text; exit 1 } else { 'OK' }"
        ) % str(PS1).replace("'", "''")
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_it_tells_the_user_what_to_do_when_it_cannot_replace(self):
        self.assertIn("Close the ChatGPT/Codex app and run this installer again", self.text)

    def test_leftovers_are_swept_up_on_a_later_run(self):
        # The moved-aside copy is only removable once the process using it has exited.
        self.assertIn("-Filter '*.old-*'", self.text)

    def test_state_directories_are_never_replaced(self):
        # config/ and logs/ hold pending recoveries and must survive every upgrade.
        for name in ("'config'", "'logs'"):
            replaced = ("$pairs = @(@{ src = 'app'" in self.text) and (name in self.text.split("$pairs =")[1][:400])
            self.assertFalse(replaced, name)


class PluginUpgradeUnderUseTests(unittest.TestCase):
    """Codex cannot replace the plugin while it is running the plugin.

    Codex starts this plugin's MCP launcher, and the launcher lives inside the plugin -
    it has to, because Codex accepts a plugin command only as a path contained in the
    plugin. So `codex plugin add` fails to back up the cache directory with an access
    error whenever Codex is open, which for most people is always.
    """

    def setUp(self):
        self.text = PS1.read_text(encoding="utf-8")

    def test_the_access_error_is_recognised(self):
        self.assertIn("os error 5", self.text)
        self.assertIn("back up plugin cache", self.text)

    def test_only_our_own_launchers_are_stopped(self):
        # Never Codex, never the app-server, never anything else holding a file.
        self.assertIn("Name='codex-auto-resume-mcp.exe'", self.text)
        for forbidden in ("Stop-Process -Name 'codex'", "Stop-Process -Name 'ChatGPT'",
                          "Name='codex.exe'", "Name='ChatGPT.exe'"):
            self.assertNotIn(forbidden, self.text)

    def test_it_retries_once_after_releasing_the_files(self):
        release = self.text.index("Releasing the plugin files")
        retry = self.text.index("plugin", release)
        self.assertGreater(retry, release)
        self.assertEqual(self.text.count("Step 'Releasing the plugin files"), 1)

    def test_a_still_failing_upgrade_says_what_to_do_and_does_not_stop_the_install(self):
        self.assertIn("Close the ChatGPT/Codex app and run this installer again to finish it", self.text)
        # The watcher is the product; a stale plugin skill must not fail the install.
        self.assertIn("the watcher and its settings still work", self.text)


class UninstallKeepsStateTests(unittest.TestCase):
    """An ordinary uninstall keeps what the user would expect to keep.

    The installer's own message said settings and pending recoveries were kept, while
    the command it ran deleted both - so uninstalling and reinstalling silently lost
    every queued recovery. Purging is still available, but it has to be asked for.
    """

    def setUp(self):
        self.text = PS1.read_text(encoding="utf-8")
        self.bridge = (ROOT / "scripts" / "plugin_setup.py").read_text(encoding="utf-8")
        self.cli = (ROOT / "src" / "codex_auto_resume" / "cli.py").read_text(encoding="utf-8")

    def test_the_cli_can_be_asked_to_keep_state(self):
        self.assertIn('"--keep-state"', self.cli)

    def test_the_plugin_bridge_keeps_state_unless_purging(self):
        self.assertIn('flags = [] if getattr(args, "purge", False) else ["--keep-state"]', self.bridge)

    def test_the_installer_only_purges_when_asked(self):
        section = self.text[self.text.index("if ($Uninstall)"):self.text.index("# ---", self.text.index("if ($Uninstall)"))]
        self.assertIn("if ($Purge) { $setupArgs += '--purge' }", section)

    def test_the_promise_and_the_behaviour_agree(self):
        # The message only appears on the non-purge path, which is now the keep path.
        self.assertIn("Settings and pending recoveries were kept", self.text)

    def test_uninstall_sweeps_its_own_leftovers(self):
        section = self.text[self.text.index("Removing program files"):]
        self.assertIn("'*.old-*'", section)


class UninstallStatePreservationTests(unittest.TestCase):
    """The same contract, exercised rather than read."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)

    def build_state(self):
        from codex_auto_resume import config, settings
        paths = config.Paths(self.home)
        paths.ensure()
        settings.save(paths.settings_file, dict(settings.defaults(), max_no_progress=7))
        store = Store(paths.state_dir)
        store.register(failure(), 111.0, state="waiting_reset", next_retry_at=222.0)
        store.close()
        return paths

    def run_uninstall(self, *flags):
        from unittest.mock import patch
        from codex_auto_resume import cli
        args = cli.build_parser().parse_args(
            ["--home", str(self.home), "--quiet", "uninstall", *flags])
        with patch.object(cli.startup, "current_value", return_value=None), \
             patch.object(cli.startup, "unregister_aumid", return_value=False), \
             patch.object(cli.startup, "protocol_value", return_value=None), \
             patch.object(cli.shortcut, "uninstall", return_value=False), \
             patch.object(cli.App, "watcher_running", return_value=False), \
             patch("sys.stdout", io.StringIO()):
            return cli.cmd_uninstall(args)

    def test_keep_state_leaves_settings_and_pending_recoveries(self):
        paths = self.build_state()
        self.run_uninstall("--keep-state")
        self.assertTrue(paths.settings_file.is_file(), "settings were deleted")
        self.assertTrue((paths.state_dir / "state.sqlite").is_file(), "pending state was deleted")

    def test_a_kept_database_still_holds_the_pending_record(self):
        paths = self.build_state()
        self.run_uninstall("--keep-state")
        with Store(paths.state_dir) as store:
            self.assertEqual(len(store.pending()), 1)

    def test_without_the_flag_state_is_removed_as_before(self):
        paths = self.build_state()
        self.run_uninstall()
        self.assertFalse(paths.settings_file.exists())
        self.assertFalse((paths.state_dir / "state.sqlite").exists())


if __name__ == "__main__":
    unittest.main()
