"""The one-click installer, and the state upgrade it must never destroy.

The installer is a bootstrapper, not a runtime: it may only automate the documented
commands. These tests assert that, and that upgrading keeps pending recoveries.
"""
from __future__ import annotations

from contextlib import closing
import io
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile

from codex_auto_resume.store import SCHEMA_VERSION, Store, StoreError

ROOT = Path(__file__).resolve().parents[1]
INSTALL_DIR = ROOT / "install"
PS1 = INSTALL_DIR / "install.ps1"
BOOTSTRAP = ROOT / "scripts" / "bootstrap.ps1"
JOURNAL = ".codex-auto-resume-install-journal.json"
WINDOWS = os.name == "nt"
POWERSHELL = shutil.which("powershell") or shutil.which("powershell.exe")


def block(text, start, end):
    """One region of a script, lifted verbatim between two markers.

    By marker rather than by line number, so reordering a file cannot quietly point a
    test at something else - and lifted rather than reimplemented, so that editing the
    installer is what these tests react to.
    """
    first = text.index(start)
    return text[first:text.index(end, first)]


def ps_literal(value) -> str:
    # Backslash is not an escape character in PowerShell; a single-quoted string takes
    # everything literally and only a quote needs doubling.
    return "'" + str(value).replace("'", "''") + "'"


# The four reporting helpers the installer defines at the top of the file, so a lifted
# block can talk the way it does in a real run without dragging in the whole script.
VOICE = ("[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false\n"
         "function Step { param([string]$m) Write-Host ('  ' + $m) }\n"
         "function Ok   { param([string]$m) Write-Host ('  [ok] ' + $m) }\n"
         "function Warn { param([string]$m) Write-Host ('  [!]  ' + $m) }\n"
         "function Fail { param([string]$m) Write-Host ('  [x]  ' + $m) }\n")


def run_probe(source: str, script: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as name:
        path = Path(name) / "probe.ps1"
        # PowerShell 5.1 decodes a .ps1 as the ANSI code page unless it carries a UTF-8
        # BOM, so a Unicode path in a probe would arrive mangled.
        path.write_text(source + "\n" + script, encoding="utf-8-sig")
        return subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)


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


class UpgradeKeepsTheOwnersChoiceTests(unittest.TestCase):
    """An upgrade repairs an installation; it does not decide for its owner.

    Plain `setup` runs the engine's `enable` and registers the Windows sign-in entry.
    Run over an existing installation that had recovery paused, that switched recovery
    back on and put back a sign-in entry the owner had removed - silently, under the
    name of an update. `--keep-state` leaves the pause switch alone and only repairs an
    autostart that is already this installation's.

    A first install is the opposite case: there is no decision to preserve, and it has
    to end up enabled and registered or nothing is being watched.
    """

    def setUp(self):
        self.text = PS1.read_text(encoding="utf-8")
        self.bootstrap = BOOTSTRAP.read_text(encoding="utf-8")

    def setup_section(self):
        return block(self.text, "Step 'Setting up the watcher'", "Step 'Checking the installation'")

    def test_the_upgrade_branch_asks_setup_to_keep_the_state(self):
        self.assertIn("if ($upgrade) { $setupArgs += '--keep-state' }", self.setup_section())

    def test_a_first_install_is_still_a_plain_setup(self):
        section = self.setup_section()
        self.assertIn("$setupArgs = @('setup')", section)
        # Nothing else may add the flag: a line carrying it that is not guarded by
        # $upgrade would take the decision away from a first install as well.
        for line in section.splitlines():
            if "--keep-state" in line and not line.strip().startswith("#"):
                self.assertIn("$upgrade", line, line)

    def test_whether_it_is_an_upgrade_is_decided_before_the_files_move(self):
        # $upgrade is `Test-Path $AppDir`, and app\ is about to be moved aside.
        self.assertLess(self.text.index("$upgrade = Test-Path $AppDir"),
                        self.text.index("Move-Item -Path $pair.dst -Destination $aside"))

    def test_the_flag_is_one_the_setup_command_actually_accepts(self):
        # The installer passing a flag the bridge does not define is an argparse error
        # and a failed setup, which is a worse bug than the one it fixes.
        sys.path.insert(0, str(ROOT / "scripts"))
        import plugin_setup
        parsed = plugin_setup.build_parser().parse_args(["setup", "--keep-state"])
        self.assertTrue(parsed.keep_state)

    def test_the_bootstraps_repair_branch_keeps_it_too(self):
        # That branch is reached only when the installed version already matches, so it
        # is by definition a repair and never a first install.
        repair = block(self.bootstrap, "$installed -eq $version", "# No lock is taken")
        self.assertIn("@($setup, 'setup', '--keep-state')", repair)

    def test_the_bootstrap_has_no_other_route_that_runs_setup_itself(self):
        # Every other route goes through install.ps1, which decides for itself.
        self.assertEqual(self.bootstrap.count("'setup'"), 1)


class CrashDuringTheCopyTests(unittest.TestCase):
    """A power cut between the move and the copy must not cost the only good tree.

    The rollback in the installer covers a failure the process survives to catch. It
    cannot cover the machine losing power: the old `app\\` and `runtime\\` are then
    sitting under `*.old-*` names, and the first thing the next run did was sweep every
    `*.old-*` directory away - so the recovery attempt destroyed the installation.

    The journal is what tells that run the difference.
    """

    def setUp(self):
        self.text = PS1.read_text(encoding="utf-8")

    def test_the_journal_lives_at_the_install_root_and_says_whose_it_is(self):
        line = [l for l in self.text.splitlines() if l.startswith("$Journal")][0]
        self.assertIn("Join-Path $InstallHome", line)
        self.assertIn(JOURNAL, line)
        # Never in config\ or logs\: those hold the user's settings and recovery
        # history, and an installer does not write its bookkeeping into them.
        self.assertNotIn("'config'", line)
        self.assertNotIn("'logs'", line)

    def test_it_is_written_before_the_first_move(self):
        self.assertLess(self.text.index("Write-CopyJournal -Path $Journal"),
                        self.text.index("Move-Item -Path $pair.dst -Destination $aside"))

    def test_it_names_what_was_moved_where_and_the_target(self):
        body = block(self.text, "function Write-CopyJournal", "function Restore-InterruptedCopy")
        for field in ("name", "target", "movedAside"):
            self.assertIn(field, body)
        self.assertIn("ConvertTo-Json", body)

    def test_it_is_written_whole_or_not_at_all(self):
        # A half-written journal would be read by the next run as the truth about where
        # the installation went.
        body = block(self.text, "function Write-CopyJournal", "function Restore-InterruptedCopy")
        self.assertIn("$temp = $Path + '.writing'", body)
        self.assertLess(body.index("Set-Content -LiteralPath $temp"),
                        body.index("Move-Item -LiteralPath $temp -Destination $Path -Force"))

    def test_it_is_read_before_anything_is_swept(self):
        self.assertLess(self.text.index("Restore-InterruptedCopy -Path $Journal"),
                        self.text.index("# Sweep up copies moved aside"))

    def test_it_is_read_before_the_run_decides_it_is_a_first_install(self):
        # A restored app\ is an upgrade; the sweep order used to make it look new.
        self.assertLess(self.text.index("Restore-InterruptedCopy -Path $Journal"),
                        self.text.index("$upgrade = Test-Path $AppDir"))

    def test_the_sweep_spares_the_copies_the_journal_claims(self):
        sweep = block(self.text, "# Sweep up copies moved aside", "# Hand over from a running watcher")
        self.assertIn("$claimedAside -contains $canonical", sweep)
        self.assertIn("-Filter '*.old-*'", sweep)

    def test_the_journal_goes_when_the_copy_is_complete(self):
        removal = self.text.index("$null = Remove-OwnedItem $Journal")
        self.assertLess(self.text.index("Copy-Item -Path (Join-Path (Join-Path $Payload $pair.src)"),
                        removal, "it may only go once both trees are in place")
        self.assertLess(removal, self.text.index("Step 'Setting up the watcher'"))

    def test_a_rolled_back_run_leaves_the_journal_behind(self):
        # The undo is best-effort; if any part of it did not take, the journal is the
        # only record of where the tree went.
        rollback = block(self.text, "foreach ($undo in $moved)", "exit 1")
        self.assertNotIn("Remove-OwnedItem $Journal", rollback)

    def test_the_uninstaller_takes_its_own_file_with_it(self):
        # An installation being removed has nothing left to put back, so the journal
        # must not outlive the thing it described.
        section = block(self.text, "if ($Uninstall)", "if (-not (Test-Path $Payload))")
        self.assertIn(JOURNAL, section)


@unittest.skipUnless(WINDOWS and POWERSHELL, "the installer is PowerShell on Windows")
class JournalRecoveryTests(unittest.TestCase):
    """The same contract, run rather than read.

    The two journal functions are lifted out of the installer and driven against real
    directories, because the property that matters - a tree that is missing at its
    target comes back from its aside copy, and nothing else is touched - is behaviour,
    not text.
    """

    def setUp(self):
        text = PS1.read_text(encoding="utf-8")
        self.source = (VOICE
                       + block(text, "function Quote-Argument", "function Invoke-Setup")
                       + block(text, "function Write-CopyJournal", "\nWrite-Host ''"))
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.journal = self.home / JOURNAL

    def entry(self, name, target, aside):
        return {"name": name, "target": str(target), "movedAside": str(aside)}

    def write_journal(self, entries):
        self.journal.write_text(json.dumps(
            {"version": 1, "written": "2026-01-01T01:01:01+09:00",
             "home": str(self.home), "moved": entries}, indent=2), encoding="utf-8")

    def restore(self):
        """Run Restore-InterruptedCopy for real; return (claimed paths, printed text)."""
        out = self.root / "claimed.json"
        done = run_probe(self.source,
                         "$claimed = Restore-InterruptedCopy -Path %s -Root %s\n"
                         "[IO.File]::WriteAllText(%s, (ConvertTo-Json @($claimed) -Compress))\n"
                         % (ps_literal(self.journal), ps_literal(self.home), ps_literal(out)))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        value = json.loads(out.read_text(encoding="utf-8"))
        return ([] if value is None else value if isinstance(value, list) else [value]), done.stdout

    def aside_with_content(self, name="app.old-20260101010101"):
        aside = self.home / name
        aside.mkdir()
        (aside / "keep.txt").write_text("the only copy", encoding="utf-8")
        return aside

    def test_a_tree_left_aside_by_an_interrupted_run_is_put_back(self):
        aside = self.aside_with_content()
        self.write_journal([self.entry("app", self.home / "app", aside)])
        claimed, printed = self.restore()
        self.assertEqual((self.home / "app" / "keep.txt").read_text(encoding="utf-8"),
                         "the only copy")
        self.assertFalse(aside.exists(), "the copy was left in two places")
        self.assertEqual(claimed, [], "once it is back there is nothing left to protect")
        self.assertIn("Putting back", printed)

    def test_a_tree_that_is_still_at_its_target_is_left_alone_but_protected(self):
        # The copy got far enough to recreate the target, so the aside copy is a
        # leftover - but not one this run may sweep, because it is still the last
        # complete one until this run writes its own.
        aside = self.aside_with_content()
        (self.home / "app").mkdir()
        self.write_journal([self.entry("app", self.home / "app", aside)])
        claimed, _ = self.restore()
        self.assertTrue((aside / "keep.txt").is_file())
        self.assertEqual([Path(p).name for p in claimed], [aside.name])

    def test_a_path_outside_the_installation_is_never_moved(self):
        outside = self.root / "elsewhere.old-1"
        outside.mkdir()
        (outside / "theirs.txt").write_text("not ours", encoding="utf-8")
        self.write_journal([self.entry("app", self.root / "elsewhere", outside)])
        claimed, printed = self.restore()
        self.assertTrue((outside / "theirs.txt").is_file(), "a foreign path must survive")
        self.assertFalse((self.root / "elsewhere").exists())
        self.assertEqual(claimed, [])
        self.assertIn("outside this installation", printed)

    def test_a_journal_that_cannot_be_read_destroys_nothing(self):
        aside = self.aside_with_content()
        self.journal.write_text("{ this is not json", encoding="utf-8")
        claimed, printed = self.restore()
        self.assertTrue((aside / "keep.txt").is_file())
        self.assertEqual(claimed, [])
        self.assertIn("cannot be read", printed)

    def test_no_journal_at_all_is_the_ordinary_case(self):
        claimed, printed = self.restore()
        self.assertEqual(claimed, [])
        self.assertEqual(printed.strip(), "")

    def write_copy_journal(self, entries):
        plan = ", ".join("@{ src = %s; dst = %s; aside = %s }"
                         % (ps_literal(name), ps_literal(self.home / name),
                            ps_literal(self.home / (name + ".old-1")))
                         for name in entries)
        done = run_probe(self.source,
                         "$plan = @(%s)\n"
                         "Write-CopyJournal -Path %s -Root %s -Entries $plan\n"
                         % (plan, ps_literal(self.journal), ps_literal(self.home)))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_the_journal_it_writes_is_readable_json_that_names_both_trees(self):
        self.write_copy_journal(["app", "runtime"])
        record = json.loads(self.journal.read_text(encoding="utf-8-sig"))
        self.assertEqual(record["home"], str(self.home))
        moved = {entry["name"]: entry for entry in record["moved"]}
        self.assertEqual(set(moved), {"app", "runtime"})
        self.assertEqual(moved["app"]["target"], str(self.home / "app"))
        self.assertEqual(moved["app"]["movedAside"], str(self.home / "app.old-1"))

    def test_writing_it_leaves_no_half_written_file_beside_it(self):
        self.write_copy_journal(["app"])
        self.write_copy_journal(["app", "runtime"])       # a second run replaces it
        self.assertEqual(sorted(p.name for p in self.home.iterdir()), [JOURNAL])

    def test_what_it_writes_is_what_the_recovery_reads(self):
        # The two halves are written in one file and read in another situation entirely,
        # so they are checked against each other rather than against a fixture.
        aside = self.aside_with_content("app.old-1")
        self.write_copy_journal(["app"])
        claimed, printed = self.restore()
        self.assertEqual((self.home / "app" / "keep.txt").read_text(encoding="utf-8"),
                         "the only copy")
        self.assertEqual(claimed, [])
        self.assertFalse(aside.exists())
        self.assertIn("Putting back", printed)

    def test_the_sweep_keeps_a_claimed_copy_and_removes_an_unclaimed_one(self):
        """The sweep itself, lifted out of the installer and run over real directories."""
        text = PS1.read_text(encoding="utf-8")
        # Remove-OwnedItem sits inside the helper block, so this is the real one too.
        source = VOICE + block(text, "function Quote-Argument", "function Invoke-Setup")
        claimed = self.aside_with_content("app.old-1")
        leftover = self.aside_with_content("runtime.old-0")
        script = ("$OwnedHome = %s\n$claimedAside = @((Resolve-Canonical %s))\n"
                  % (ps_literal(self.home), ps_literal(claimed)))
        script += block(text, "# Sweep up copies moved aside", "# Hand over from a running watcher")
        done = run_probe(source, script)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue((claimed / "keep.txt").is_file(),
                        "the sweep deleted the copy the journal was protecting")
        self.assertFalse(leftover.exists(), "an unclaimed leftover must still be swept")


class PayloadRootTests(unittest.TestCase):
    """The installation home is written by name, never by wildcard.

    The root of the payload used to be copied with `Get-ChildItem -File`, so any file
    that ever appeared there landed in the installation home - including the names this
    product reads as proof that the home is ours (`runtime.json`,
    `.owned-by-codex-auto-resume`) or as its state. An installer authors neither.
    """

    def setUp(self):
        self.text = PS1.read_text(encoding="utf-8")

    def test_the_payload_root_is_not_enumerated(self):
        self.assertNotIn("Get-ChildItem -Path $Payload", self.text)

    def test_the_list_is_fixed_and_holds_the_window_and_its_icon(self):
        self.assertIn("$rootFiles = @('CodexAutoResumeSettings.exe', 'codex-auto-resume.ico')",
                      self.text)
        self.assertIn("foreach ($name in $rootFiles) {", self.text)

    def test_it_is_the_list_the_release_build_puts_there(self):
        # Two lists of the same thing in two languages. They drift.
        build = (ROOT / "build" / "make_release.py").read_text(encoding="utf-8")
        self.assertIn('GUI_EXE = "CodexAutoResumeSettings.exe"', build)
        self.assertIn('stage / "payload" / GUI_EXE', build)
        self.assertIn('stage / "payload" / "codex-auto-resume.ico"', build)

    def test_a_missing_one_fails_the_way_a_missing_runtime_does(self):
        check = block(self.text, "foreach ($name in $rootFiles) {", "# Move everything aside first")
        self.assertIn("Fail ('Payload is incomplete: ' + $name); exit 1", check)

    def test_it_fails_before_anything_has_been_moved(self):
        self.assertLess(self.text.index("Fail ('Payload is incomplete: ' + $name)"),
                        self.text.index("Move-Item -Path $pair.dst -Destination $aside"))

    def test_the_move_aside_rule_still_covers_an_open_settings_window(self):
        copy = block(self.text, "# The settings window and the icon live at the payload root",
                     "foreach ($stale in")
        self.assertIn("$aside = $target + '.old-'", copy)
        self.assertIn("Move-Item -Path $target -Destination $aside", copy)


class ArchiveContentsTests(unittest.TestCase):
    """What the bootstrap accepts as a release of this product.

    The installer copies the payload root by name, so a stray file there is no longer
    copied into the home - but it is still a sign that the archive is not the build it
    claims to be, and this is the last point where anyone looks before it is unpacked
    and run.
    """

    ENTRIES = ("payload/runtime/python.exe",
               "payload/app/src/codex_auto_resume/mcpserver.py",
               "payload/app/mcp/codex-auto-resume-mcp.exe",
               "payload/app/.mcp.json",
               "payload/app/.codex-plugin/plugin.json",
               "payload/app/scripts/plugin_setup.py",
               "payload/CodexAutoResumeSettings.exe",
               "payload/codex-auto-resume.ico",
               "install/install.ps1",
               "Install.cmd")

    def setUp(self):
        self.text = BOOTSTRAP.read_text(encoding="utf-8")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_the_payload_root_is_checked_against_a_fixed_list(self):
        check = block(self.text, "function Test-Archive", "function Get-InstalledVersion")
        self.assertIn("$rootFiles = @('CodexAutoResumeSettings.exe', 'codex-auto-resume.ico')",
                      check)
        self.assertIn("unexpected file at the payload root", check)

    def make_archive(self, name="release.zip", extra=(), omit=()):
        path = self.root / name
        with zipfile.ZipFile(path, "w") as bundle:
            for entry in list(self.ENTRIES) + list(extra):
                if entry in omit:
                    continue
                if entry.endswith(".codex-plugin/plugin.json"):
                    bundle.writestr(entry, json.dumps({"name": "codex-auto-resume",
                                                       "version": "9.9.9"}))
                else:
                    bundle.writestr(entry, "x")
        return path

    def check(self, path):
        source = VOICE + block(self.text, "function Test-Archive", "function Get-InstalledVersion")
        return run_probe(source, "try { Test-Archive -Zip %s -Version '9.9.9'; 'accepted' }\n"
                                 "catch { $_.Exception.Message; exit 1 }\n" % ps_literal(path))

    @unittest.skipUnless(WINDOWS and POWERSHELL, "the bootstrap is PowerShell on Windows")
    def test_an_archive_shaped_like_a_release_is_accepted(self):
        done = self.check(self.make_archive())
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("accepted", done.stdout)

    @unittest.skipUnless(WINDOWS and POWERSHELL, "the bootstrap is PowerShell on Windows")
    def test_an_extra_file_at_the_payload_root_is_refused(self):
        # The name is deliberately one the product treats as proof of ownership.
        done = self.check(self.make_archive(extra=("payload/.owned-by-codex-auto-resume",)))
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("unexpected file at the payload root", done.stdout)

    @unittest.skipUnless(WINDOWS and POWERSHELL, "the bootstrap is PowerShell on Windows")
    def test_a_payload_root_missing_the_icon_is_refused(self):
        done = self.check(self.make_archive(omit=("payload/codex-auto-resume.ico",)))
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("missing payload/codex-auto-resume.ico", done.stdout)

    @unittest.skipUnless(WINDOWS and POWERSHELL, "the bootstrap is PowerShell on Windows")
    def test_a_deeper_file_is_not_mistaken_for_one_at_the_root(self):
        done = self.check(self.make_archive(extra=("payload/app/assets/logo.png",)))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


if __name__ == "__main__":
    unittest.main()
