"""-Silent, and the entry in Add or remove programs (winget's way in and out).

Two things the winget package needs, and one rule for each (docs/STANDARDS.md F2, F5, F12):

* `-Silent` makes Install.cmd and Uninstall.cmd ask nothing and wait for no key, with every exit code and every line
  they have without it; install.ps1 accepts it (it never asks anything itself); the setup program passes it on and,
  with it, does not wait for Enter when it stops (tests/test_setup.py holds that half).
* The installer keeps a copy of itself in the installation, and the engine's setup writes ONE key under the user's
  Uninstall key - by a fixed name per edition - that names it; the engine's uninstall removes the key, and the
  installer the copy, but only what it can prove is its own.

Nothing here touches the real registry, the real installation or a real Codex. The launchers run in a scratch folder
whose "System32" is a copy of the two programs they call, and whose install.ps1 is a stub; the registry is a fake
module in the place startup.py already has for it (`startup._winreg`); the installer's functions are lifted out of
install.ps1 and run against scratch folders, as tests/test_installer.py does.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "build"))

from codex_auto_resume import addremove, config, startup  # noqa: E402
import test_installer as installer  # noqa: E402  (its helpers: block, run_probe, ps_literal, VOICE)

INSTALL_DIR = ROOT / "build" / "install"
PS1 = INSTALL_DIR / "install.ps1"
WINDOWS = os.name == "nt"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SYSTEM32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"

STUB_PS1 = ('Add-Content -LiteralPath $env:STUB_RECORD -Value ("ran: " + ($args -join " "))\r\n'
            "exit ([int]$env:STUB_EXIT)\r\n")


class Launcher:
    """A copy of Install.cmd or Uninstall.cmd in a folder of its own, with a stub install.ps1 beside it, and a
    "SystemRoot" of the test's own holding the two programs the launcher calls by that path (chcp and PowerShell)."""

    def __init__(self, case: unittest.TestCase, name: str):
        self.base = Path(tempfile.mkdtemp(prefix="launcher-"))
        case.addCleanup(shutil.rmtree, self.base, True)
        folder = self.base / "archive"
        (folder / "install").mkdir(parents=True)
        # The launcher names the two programs by %SystemRoot%; here that is the scratch root, set in the text
        # (a changed SystemRoot in the environment would break PowerShell itself).
        text = (INSTALL_DIR / name).read_bytes().decode("utf-8").replace("%SystemRoot%", str(self.base / "root"))
        (folder / name).write_bytes(text.encode("utf-8"))
        (folder / "install" / "install.ps1").write_bytes(STUB_PS1.encode("ascii"))
        shell = self.base / "root" / "System32" / "WindowsPowerShell" / "v1.0"
        shell.mkdir(parents=True)
        shutil.copyfile(SYSTEM32 / "chcp.com", self.base / "root" / "System32" / "chcp.com")
        shutil.copyfile(SYSTEM32 / "WindowsPowerShell" / "v1.0" / "powershell.exe", shell / "powershell.exe")
        self.script = folder / name
        self.record = self.base / "record.txt"

    def run(self, *arguments: str, code: int = 0):
        environment = dict(os.environ, STUB_RECORD=str(self.record), STUB_EXIT=str(code))
        done = subprocess.run([str(SYSTEM32 / "cmd.exe"), "/d", "/c", str(self.script), *arguments],
                              capture_output=True, stdin=subprocess.DEVNULL, env=environment, timeout=120,
                              creationflags=NO_WINDOW, cwd=str(self.base))
        return done.returncode, done.stdout.decode("mbcs", "replace"), self.runs()

    def runs(self) -> list:
        return self.record.read_text(encoding="ascii", errors="replace").splitlines() if self.record.is_file() else []


@unittest.skipUnless(WINDOWS and (SYSTEM32 / "WindowsPowerShell" / "v1.0" / "powershell.exe").is_file(),
                     "the launchers are Windows batch files")
class LauncherTests(unittest.TestCase):
    PAUSE = "Press any key"
    ASK = "Change the edition?"

    def test_install_cmd_without_the_switch_still_pauses_and_still_asks(self):
        code, out, runs = Launcher(self, "Install.cmd").run()
        self.assertEqual((code, runs), (0, ["ran: "]))
        self.assertIn(self.PAUSE, out)
        code, out, runs = Launcher(self, "Install.cmd").run(code=14)
        self.assertEqual(code, 14, "an answer of no leaves the exit code as it was")
        self.assertIn(self.ASK, out)
        self.assertIn("Nothing was changed.", out)
        self.assertIn(self.PAUSE, out)
        self.assertEqual(runs, ["ran: "], "no answer is no, and the installer is not run again")

    def test_install_cmd_with_the_switch_asks_nothing_and_waits_for_no_key(self):
        for exit_code in (0, 1, 14, 3):
            with self.subTest(exit_code):
                code, out, runs = Launcher(self, "Install.cmd").run("-Silent", code=exit_code)
                self.assertEqual(code, exit_code)
                self.assertEqual(runs, ["ran: -Silent"], "passed on to install.ps1, once")
                self.assertNotIn(self.PAUSE, out)
                self.assertNotIn(self.ASK, out)
                self.assertEqual("Installation did not finish" in out, exit_code != 0)

    def test_the_switch_is_found_among_other_switches_in_any_case(self):
        code, out, runs = Launcher(self, "Install.cmd").run("-SkipStartup", "-silent", code=0)
        self.assertEqual((code, runs), (0, ["ran: -SkipStartup -silent"]))
        self.assertNotIn(self.PAUSE, out)
        _, out, _ = Launcher(self, "Install.cmd").run("-SkipStartup")
        self.assertIn(self.PAUSE, out)

    def test_uninstall_cmd_pauses_unless_silent_and_ends_with_the_installers_code(self):
        code, out, runs = Launcher(self, "Uninstall.cmd").run("-Purge", code=1)
        self.assertEqual((code, runs), (1, ["ran: -Uninstall -Purge"]))
        self.assertIn(self.PAUSE, out)
        code, out, runs = Launcher(self, "Uninstall.cmd").run("-Silent", code=1)
        self.assertEqual((code, runs), (1, ["ran: -Uninstall -Silent"]))
        self.assertNotIn(self.PAUSE, out)

    def test_the_launchers_keep_their_line_endings_and_their_one_pause(self):
        for name in ("Install.cmd", "Uninstall.cmd"):
            data = (INSTALL_DIR / name).read_bytes()
            self.assertNotIn(b"\n", data.replace(b"\r\n", b""), name)
            text = data.decode("utf-8")
            self.assertEqual(len(re.findall(r"(?m)^pause\s*$", text)), 0, "every pause waits for the switch")
            self.assertEqual(text.count("if not defined SILENT pause"), 1, name)


@unittest.skipUnless(WINDOWS and installer.POWERSHELL, "the installer is PowerShell on Windows")
class InstallerSwitchTests(unittest.TestCase):
    def test_install_ps1_accepts_the_switch(self):
        """In a home with nothing in it the uninstall branch stops where it should - with a parameter binding
        error instead, it would never reach that line."""
        with tempfile.TemporaryDirectory() as home:
            done = subprocess.run(
                [installer.POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-File", str(PS1), "-Uninstall", "-Silent"],
                capture_output=True, encoding="locale", errors="replace", timeout=120, creationflags=NO_WINDOW,
                # Run here, never again outside: a test run inside the Codex app or Claude would otherwise be
                # relaunched through WMI, out of this test's reach (install.ps1, Resolve-OutsideRun; v0.6.17).
                env=dict(os.environ, CODEX_AUTO_RESUME_PLUGIN_HOME=home, CODEX_AUTO_RESUME_OUTSIDE="1"))
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("No installed runtime found here", done.stdout)
        self.assertNotIn("parameter", (done.stdout + done.stderr).lower())

    def test_it_asks_nothing_itself(self):
        text = PS1.read_text(encoding="utf-8")
        for asking in ("Read-Host", "PromptForChoice", "ReadKey", "Console]::In", "Pause"):
            self.assertNotIn(asking, text)


KEPT = "function Install-KeptUninstaller"
JOURNAL_FUNCTION = "function Write-CopyJournal"


@unittest.skipUnless(WINDOWS and installer.POWERSHELL, "the installer is PowerShell on Windows")
class KeptUninstallerTests(unittest.TestCase):
    """The installer's own function, lifted out of install.ps1 and run against scratch folders."""

    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="kept-"))
        self.addCleanup(shutil.rmtree, self.temp, True)
        self.home = self.temp / "home"
        self.home.mkdir()
        self.source = self.temp / "archive" / "install" / "install.ps1"
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b"# the installer\r\nexit 0\r\n")
        self.outside = self.temp / "outside"
        self.outside.mkdir()

    def keep(self, source=None, before: str = ""):
        text = PS1.read_text(encoding="utf-8")
        helpers = installer.block(text, "function Resolve-Canonical", "function Get-Edition")
        helpers += installer.block(text, "function Remove-OwnedItem", "function Invoke-Setup")
        helpers += installer.block(text, KEPT, JOURNAL_FUNCTION)
        script = ("$OwnedHome = %s\n%s\n$kept = Install-KeptUninstaller -Source %s\n'result: ' + $kept\n"
                  % (installer.ps_literal(self.home), before, installer.ps_literal(source or self.source)))
        return installer.run_probe(installer.VOICE + helpers, script)

    def kept(self) -> Path:
        return self.home / "uninstall" / "install.ps1"

    def test_the_installer_is_copied_whole_into_a_folder_of_the_installations_own(self):
        done = self.keep()
        self.assertIn("result: True", done.stdout, done.stdout + done.stderr)
        self.assertEqual(self.kept().read_bytes(), self.source.read_bytes())
        self.assertEqual(sorted(path.name for path in self.kept().parent.iterdir()), ["install.ps1"],
                         "no half-written copy is left beside it")

    def test_a_second_run_replaces_it_and_the_path_matches_the_one_the_engine_names(self):
        self.keep()
        self.source.write_bytes(b"# the next version\r\n")
        self.assertIn("result: True", self.keep().stdout)
        self.assertEqual(self.kept().read_bytes(), b"# the next version\r\n")
        self.assertEqual(self.kept(), addremove.kept_script(self.home))

    def test_the_kept_copy_itself_as_the_source_is_left_as_it_is(self):
        self.keep()
        done = self.keep(source=self.kept())
        self.assertIn("result: True", done.stdout, done.stdout + done.stderr)
        self.assertEqual(self.kept().read_bytes(), self.source.read_bytes())

    def test_a_junction_where_the_folder_should_be_is_not_followed(self):
        junction = self.home / "uninstall"
        made = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(junction), str(self.outside)],
                              capture_output=True, creationflags=NO_WINDOW)
        if made.returncode != 0:
            self.skipTest("no junction could be made here")
        done = self.keep()
        self.assertIn("result: False", done.stdout, done.stdout + done.stderr)
        self.assertEqual(list(self.outside.iterdir()), [], "nothing was written where the junction points")

    def test_a_junction_to_another_place_inside_the_installation_is_not_followed_either(self):
        inside = self.home / "app"
        inside.mkdir()
        made = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(self.home / "uninstall"), str(inside)],
                              capture_output=True, creationflags=NO_WINDOW)
        if made.returncode != 0:
            self.skipTest("no junction could be made here")
        done = self.keep()
        self.assertIn("result: False", done.stdout, done.stdout + done.stderr)
        self.assertEqual(list(inside.iterdir()), [], "nothing was written through the junction")

    def test_a_file_where_the_folder_should_be_is_left_alone(self):
        (self.home / "uninstall").write_text("not a folder", encoding="utf-8")
        done = self.keep()
        self.assertIn("result: False", done.stdout, done.stdout + done.stderr)
        self.assertEqual((self.home / "uninstall").read_text(encoding="utf-8"), "not a folder")

    def test_a_home_that_cannot_be_written_into_says_so_and_keeps_going(self):
        self.source.unlink()
        done = self.keep()
        self.assertIn("result: False", done.stdout, done.stdout + done.stderr)
        self.assertIn("Could not keep an uninstaller", done.stdout)
        self.assertFalse(self.kept().exists())


@unittest.skipUnless(WINDOWS and installer.POWERSHELL, "the installer is PowerShell on Windows")
class InstallerFlowTests(unittest.TestCase):
    def setUp(self):
        self.text = PS1.read_text(encoding="utf-8")

    def test_it_is_kept_only_for_the_ordinary_home_and_before_the_engine_writes_the_entry(self):
        call = installer.block(self.text, "# The entry in Add or remove programs is written", "Step 'Setting up the watcher'")
        self.assertIn("IsNullOrWhiteSpace($env:CODEX_AUTO_RESUME_PLUGIN_HOME)", call)
        self.assertIn("Install-KeptUninstaller -Source $PSCommandPath", call)
        self.assertLess(self.text.index("Install-KeptUninstaller -Source"), self.text.rindex("$code = Invoke-Setup $setupArgs"))
        self.assertEqual(self.text.count("Install-KeptUninstaller -Source"), 1)

    def test_the_installer_writes_no_registry_key_itself(self):
        # It reads and deletes the one entry (below); it writes nothing.
        for forbidden in ("New-ItemProperty", "Set-ItemProperty", "reg add", "reg.exe", "HKCU:", "CreateSubKey",
                          "SetValue", "HKLM"):
            self.assertNotIn(forbidden, self.text)

    def test_the_uninstall_removes_the_kept_folder_after_the_program_files_and_before_the_proof(self):
        branch = installer.block(self.text, "if ($Uninstall)", "# -------------------------------------------------------------------------- install")
        removal = branch.index("$null = Remove-OwnedItem $kept")
        self.assertGreater(removal, branch.index("Some program files are still in use"))
        self.assertLess(removal, branch.index("'.owned-by-codex-auto-resume'"))
        self.assertIn("-not $keptItem.LinkType", branch)

    def uninstall_tail(self, home: Path, entries: dict | None = None, log: Path | None = None):
        """The uninstall branch from "$codex = Get-CodexCli" on, in a scratch installation. `entries` is the fake
        registry, name -> (install location, uninstall command), and `log` collects the names removed from it."""
        text = self.text
        source = installer.VOICE + installer.block(text, "function Quote-Argument", "function Invoke-Setup")
        source += "\nfunction Fail { param([string]$m) $script:Failed = $true; Write-Host $m }\n"
        source += installer.block(text, "function Remove-OwnUninstallEntry", "function Write-CopyJournal")
        stub = ["$global:Entries = @{}"]
        for name, (location, command) in (entries or {}).items():
            stub.append("$global:Entries[%s] = @{ InstallLocation = %s; UninstallString = %s }"
                        % (installer.ps_literal(name), installer.ps_literal(location), installer.ps_literal(command)))
        stub.append("function Read-UninstallEntry { param([string]$Name) if ($global:Entries.ContainsKey($Name)) { "
                    "return $global:Entries[$Name] } return $null }")
        stub.append("function Remove-UninstallEntry { param([string]$Name) Add-Content -LiteralPath %s -Value $Name; "
                    "$global:Entries.Remove($Name) }" % installer.ps_literal(log or (home.parent / "removed.txt")))
        script = ("$OwnedHome = %s\n$InstallHome = $OwnedHome\n$AppDir = Join-Path $OwnedHome app\n"
                  "$RunDir = Join-Path $OwnedHome runtime\n$PluginCacheRoot = Join-Path $OwnedHome cache\n"
                  "$PluginName = 'fixture-plugin'\n$MarketplaceName = 'fixture-market'\n$script:Failed = $false\n"
                  "$Purge = $false\n" % installer.ps_literal(home))
        script += "\n".join(stub) + "\n"
        script += ("function Get-CodexCli { return $null }\nfunction Get-OwnedMcpProcess { return ,@() }\n")
        branch = installer.block(text, "# ----------------------------------------------------------------------- uninstall",
                                 "# -------------------------------------------------------------------------- install")
        script += "if ($true) {\n" + branch[branch.index("    $codex = Get-CodexCli"):]
        return installer.run_probe(source, script)

    def installation(self, root: Path) -> Path:
        home = root / "home"
        (home / "app").mkdir(parents=True)
        (home / "runtime").mkdir()
        (home / "runtime" / "python.exe").write_text("fixture", encoding="utf-8")
        (home / ".owned-by-codex-auto-resume").write_text("fixture", encoding="utf-8")
        (home / "config").mkdir()
        (home / "config" / "settings.json").write_text("{}", encoding="utf-8")
        (home / "uninstall").mkdir()
        (home / "uninstall" / "install.ps1").write_text("# kept", encoding="utf-8")
        return home

    def test_uninstalling_takes_the_kept_copy_and_keeps_the_settings(self):
        with tempfile.TemporaryDirectory() as name:
            home = self.installation(Path(name))
            done = self.uninstall_tail(home)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertFalse((home / "uninstall").exists(), "the kept uninstaller goes with the program")
            self.assertTrue((home / "config" / "settings.json").is_file())

    def test_a_junction_named_uninstall_is_not_followed_out_of_the_installation(self):
        with tempfile.TemporaryDirectory() as name:
            home = self.installation(Path(name))
            outside = Path(name) / "outside"
            outside.mkdir()
            (outside / "precious.txt").write_text("not ours", encoding="utf-8")
            shutil.rmtree(home / "uninstall")
            made = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(home / "uninstall"), str(outside)],
                                  capture_output=True, creationflags=NO_WINDOW)
            if made.returncode != 0:
                self.skipTest("no junction could be made here")
            done = self.uninstall_tail(home)
            self.assertTrue((outside / "precious.txt").is_file(), done.stdout + done.stderr)


    def entry_for(self, home: Path, location: Path | None = None, script: Path | None = None) -> tuple:
        kept = script or (home / "uninstall" / "install.ps1")
        command = ('"C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoLogo -NoProfile '
                   '-ExecutionPolicy Bypass -File "%s" -Uninstall' % kept)
        return (str(location or home), command)

    def test_the_entry_goes_when_everything_else_has_and_not_before(self):
        with tempfile.TemporaryDirectory() as name:
            home = self.installation(Path(name))
            log = Path(name) / "removed.txt"
            done = self.uninstall_tail(home, {"CodexAutoResume": self.entry_for(home)}, log)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertEqual(log.read_text(encoding="utf-8").split(), ["CodexAutoResume"])
            self.assertIn("Removing the entry in Add or remove programs", done.stdout)
            self.assertFalse((home / "app").exists())

    def test_the_entry_the_installer_window_runs_goes_too(self):
        """v0.6.16 writes the entry as the installation's own program with --uninstall and the kept script
        (addremove.uninstall_command), and the installer matched only PowerShell's `-File "<script>"`: every
        successful uninstall from Settings > Apps left its entry behind, pointing at a program that was gone. Both
        forms are this installation's; the window form naming another home's script is still not."""
        with tempfile.TemporaryDirectory() as name:
            home = self.installation(Path(name))
            log = Path(name) / "removed.txt"
            command = " ".join(startup.quote_argument(argument) for argument in
                               (str(home / addremove.WINDOW), addremove.WINDOW_SWITCH, str(addremove.kept_script(home))))
            self.assertTrue(addremove.owned({"InstallLocation": str(home), "UninstallString": command}, home),
                            "the engine's own rule reads it as this installation's")
            done = self.uninstall_tail(home, {"CodexAutoResumeAdvanced": (str(home), command)}, log)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertTrue(log.exists(), "the entry was left behind: " + done.stdout)
            self.assertEqual(log.read_text(encoding="utf-8").split(), ["CodexAutoResumeAdvanced"])
        with tempfile.TemporaryDirectory() as name:
            home = self.installation(Path(name))
            other = Path(name) / "other-home"
            log = Path(name) / "removed.txt"
            command = " ".join(startup.quote_argument(argument) for argument in
                               (str(home / addremove.WINDOW), addremove.WINDOW_SWITCH,
                                str(other / "uninstall" / "install.ps1")))
            done = self.uninstall_tail(home, {"CodexAutoResumeAdvanced": (str(home), command)}, log)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertFalse(log.exists(), "an entry that runs another home's script was removed")

    def test_a_failed_uninstall_stays_listed_and_can_be_run_again(self):
        """A program file held open: the uninstall stops with 1 and the entry, the kept uninstaller and the
        program are all still there, so Settings > Apps offers the same uninstall again."""
        with tempfile.TemporaryDirectory() as name:
            home = self.installation(Path(name))
            window = home / "CodexAutoResumeSettings.exe"
            window.write_text("fixture", encoding="utf-8")
            log = Path(name) / "removed.txt"
            with window.open("rb"):
                done = self.uninstall_tail(home, {"CodexAutoResume": self.entry_for(home)}, log)
            self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
            self.assertIn("run this uninstaller again", done.stdout)
            self.assertFalse(log.exists(), "the entry was removed although the uninstall failed")
            self.assertTrue((home / "app").is_dir())
            self.assertTrue((home / "uninstall" / "install.ps1").is_file())

    def test_an_entry_that_is_not_this_installations_is_left_where_it_is(self):
        with tempfile.TemporaryDirectory() as name:
            home = self.installation(Path(name))
            other = Path(name) / "other-home"
            other.mkdir()
            log = Path(name) / "removed.txt"
            entries = {"CodexAutoResume": self.entry_for(home, location=other),
                       "CodexAutoResumeAdvanced": self.entry_for(home, script=other / "uninstall" / "install.ps1")}
            done = self.uninstall_tail(home, entries, log)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertFalse(log.exists(), "an entry of another installation was removed")

    def test_the_engine_is_told_to_leave_the_entry_for_the_end(self):
        branch = installer.block(self.text, "if ($Uninstall)",
                                 "# -------------------------------------------------------------------------- install")
        self.assertLess(branch.index("$env:CODEX_AUTO_RESUME_KEEP_ENTRY = '1'"), branch.index("Invoke-Setup $setupArgs"))
        self.assertIn("finally { $env:CODEX_AUTO_RESUME_KEEP_ENTRY = $null }", branch)
        self.assertGreater(branch.index("Remove-OwnUninstallEntry $OwnedHome"),
                           branch.index("Some program files are still in use"))
        self.assertEqual(branch.count("Remove-OwnUninstallEntry $OwnedHome"), 1)
        self.assertEqual(addremove.KEEP_ENTRY_ENV, "CODEX_AUTO_RESUME_KEEP_ENTRY")

    def test_the_two_registry_calls_are_the_only_ones_and_only_open_and_delete_the_uninstall_key(self):
        calls = re.findall(r"\[Microsoft\.Win32\.Registry\]::\w+\.\w+\(", self.text)
        self.assertEqual(sorted(calls), ["[Microsoft.Win32.Registry]::CurrentUser.DeleteSubKey(",
                                         "[Microsoft.Win32.Registry]::CurrentUser.OpenSubKey("])
        self.assertEqual(self.text.count("Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\"), 2)


def short_name(path: Path) -> str:
    """The 8.3 short name Windows gives `path`, or the path itself where the volume makes none."""
    import ctypes
    size = ctypes.windll.kernel32.GetShortPathNameW(str(path), None, 0)
    if not size:
        return str(path)
    buffer = ctypes.create_unicode_buffer(size)
    ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, size)
    return buffer.value


@unittest.skipUnless(WINDOWS and installer.POWERSHELL, "the installer is PowerShell on Windows")
class UpdateFromTheDashboardTests(unittest.TestCase):
    """GitHub #43. The Dashboard starts every update, and Repair, with CODEX_AUTO_RESUME_PLUGIN_HOME set to its own root
    (gui/DashboardMaintenance.cs, StartBootstrap and RunRepair), and install.ps1 kept the uninstaller only where that
    variable was empty - so an update from the Dashboard kept none, and the engine's setup, which writes the entry in
    Settings > Apps only where the kept uninstaller is (addremove.register), wrote none. The variable naming the ordinary
    home, in any spelling of it, keeps it now; a home really placed elsewhere still gets neither.

    The install path's own lines run, lifted out of install.ps1 from the comment above the call to the step after it,
    in a scratch profile with the variable set as the Dashboard sets it; the engine's half is addremove.register over
    a fake registry (startup._winreg), for the home plugin_setup.runtime_home() reads from the same variable."""

    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="dashboard-update-"))
        self.addCleanup(shutil.rmtree, self.temp, True)
        self.profile = self.temp / "Profile Of ExampleUser"
        self.home = self.profile / ".codex-auto-resume"
        (self.home / "app").mkdir(parents=True)
        self.text = PS1.read_text(encoding="utf-8")

    def update(self, variable: str | None) -> subprocess.CompletedProcess:
        """install.ps1's lines from the entry's comment to "Setting up the watcher", as the in-app update runs them: the
        variable as given, $OwnedHome the folder it resolves to (install.ps1 takes it from claim-home and
        Resolve-Canonical), the kept uninstaller's source this probe itself."""
        text = self.text
        helpers = installer.block(text, "function Resolve-Canonical", "function Get-Edition")
        helpers += installer.block(text, "function Remove-OwnedItem", "function Invoke-Setup")
        helpers += installer.block(text, KEPT, JOURNAL_FUNCTION)
        call = installer.block(text, "    # The entry in Add or remove programs is written", "    Step 'Setting up the watcher'")
        script = "# the installer that ran\n$env:USERPROFILE = %s\n" % installer.ps_literal(self.profile)
        if variable is None:
            script += "$env:CODEX_AUTO_RESUME_PLUGIN_HOME = $null\n$OwnedHome = Resolve-Canonical %s\n" % (
                installer.ps_literal(self.home))
        else:
            script += ("$env:CODEX_AUTO_RESUME_PLUGIN_HOME = %s\n"
                       "$OwnedHome = Resolve-Canonical $env:CODEX_AUTO_RESUME_PLUGIN_HOME\n" % installer.ps_literal(variable))
        script += "if ($true) {\n" + call + "}\n'kept: ' + (Test-Path -LiteralPath (Join-Path $OwnedHome 'uninstall\\install.ps1'))\n"
        return installer.run_probe(installer.VOICE + helpers, script)

    def entry_written(self, variable: str | None) -> list:
        """What the engine's setup does about the entry afterwards, for the home it reads from the same variable."""
        import plugin_setup
        environment = {"USERPROFILE": str(self.profile)}
        if variable is not None:
            environment[plugin_setup.ENV_RUNTIME_HOME] = variable
        registry = FakeWinreg()
        with patch.dict(os.environ, environment), patch.object(startup, "_winreg", return_value=registry):
            if variable is None:
                os.environ.pop(plugin_setup.ENV_RUNTIME_HOME, None)
            return addremove.register(plugin_setup.runtime_home(), "standard", "0.6.17", "Codex Auto Resume")

    def spellings(self) -> dict:
        home = str(self.home)
        found = {
            "as the Dashboard passes it": home,
            "another case": home.upper(),
            "a trailing separator": home + "\\",
            "two trailing separators": home + "\\\\",
            "dot and dot-dot": str(self.profile) + "\\.\\app-elsewhere\\..\\.codex-auto-resume",
            "forward slashes": home.replace("\\", "/"),
            "extended-length prefix": "\\\\?\\" + home,
        }
        short = short_name(self.home)
        if short.lower() != home.lower():
            found["an 8.3 short name"] = short
        return found

    def test_the_ordinary_home_named_by_the_variable_keeps_the_uninstaller_and_gets_the_entry(self):
        for name, variable in sorted(self.spellings().items()):
            with self.subTest(name, variable=variable):
                shutil.rmtree(self.home / "uninstall", ignore_errors=True)
                done = self.update(variable)
                self.assertIn("kept: True", done.stdout, done.stdout + done.stderr)
                kept = self.home / "uninstall" / "install.ps1"
                self.assertIn("# the installer that ran", kept.read_text(encoding="utf-8-sig"))
                self.assertEqual(self.entry_written(variable), ["wrote CodexAutoResume"],
                                 "the engine wrote no entry in Settings > Apps")
        if "an 8.3 short name" not in self.spellings():
            self.skipTest("this volume gives no 8.3 short names; every other spelling passed")

    def test_with_no_variable_it_is_kept_as_before(self):
        done = self.update(None)
        self.assertIn("kept: True", done.stdout, done.stdout + done.stderr)
        self.assertEqual(self.entry_written(None), ["wrote CodexAutoResume"])

    def test_a_home_placed_elsewhere_still_gets_neither(self):
        for elsewhere in (self.temp / "Elsewhere" / ".codex-auto-resume",       # the same name in another folder
                          self.profile / ".codex-auto-resume-2",              # a name beside it
                          self.profile / ".codex-auto-resume" / "inner",      # inside it
                          self.profile):                                       # the profile itself
            with self.subTest(elsewhere=str(elsewhere)):
                (elsewhere / "app").mkdir(parents=True, exist_ok=True)
                done = self.update(str(elsewhere))
                self.assertIn("kept: False", done.stdout, done.stdout + done.stderr)
                self.assertFalse((elsewhere / "uninstall").exists())
                self.assertEqual(self.entry_written(str(elsewhere)), [])

    def test_a_variable_naming_the_home_through_an_environment_variable_is_another_folder(self):
        """$InstallHome takes the variable as written, so `%USERPROFILE%` in it is a folder of that name and not the
        profile: the files go there, and the comparison is about where they went."""
        literal = self.temp / "%USERPROFILE%" / ".codex-auto-resume"
        (literal / "app").mkdir(parents=True)
        done = self.update(str(literal))
        self.assertIn("kept: False", done.stdout, done.stdout + done.stderr)

    def test_the_call_asks_about_the_root_this_run_installed(self):
        call = installer.block(self.text, "# The entry in Add or remove programs is written", "Step 'Setting up the watcher'")
        self.assertIn("Test-DefaultHome -Root $OwnedHome -Profile $env:USERPROFILE", call)
        self.assertEqual(self.text.count("function Test-DefaultHome"), 1)


class UninstallWithTheDashboardOpenTests(unittest.TestCase):
    """The v0.6.16 acceptance's uninstall ran with the Dashboard open. It removed the watcher, the sign-in start,
    the Start menu entry and the plugin, then could not remove the program files - the Dashboard and the runtime
    python.exe it started held them - and stopped with exit 1 and half a product left. The uninstall now asks the
    Dashboard to close first, as an update does (the event, then WM_CLOSE for a window that does not answer), and
    before its first removal names whatever still holds the files and stops there, having changed nothing."""

    def setUp(self):
        self.text = PS1.read_text(encoding="utf-8")

    def run_uninstall(self, home: Path, windows=(), holders=(), entries=None):
        """The uninstall branch from its check on, in a scratch installation: `windows` are stand-in Dashboard
        windows (process id, command line, kind - as test_upgrade_handover's run_close), `holders` stand-in
        processes still running there; the engine's step, Codex and the registry are stubs."""
        text = self.text
        log = home.parent / "steps.txt"
        source = installer.VOICE + installer.block(text, "function Quote-Argument", "function Invoke-Setup")
        source += "\nfunction Fail { param([string]$m) $script:Failed = $true; Write-Host $m }\n"
        source += installer.block(text, "function Remove-OwnUninstallEntry", "function Write-CopyJournal")
        stub = ["$global:Entries = @{}"]
        for name, (location, command) in (entries or {}).items():
            stub.append("$global:Entries[%s] = @{ InstallLocation = %s; UninstallString = %s }"
                        % (installer.ps_literal(name), installer.ps_literal(location), installer.ps_literal(command)))
        fakes = ", ".join("@{ ProcessId = %d; CommandLine = %s; Kind = %s; Alive = $true }"
                          % (pid, installer.ps_literal(line), installer.ps_literal(kind)) for pid, line, kind in windows)
        held = ", ".join("[pscustomobject]@{ Name = %s; ProcessId = %d; ExecutablePath = %s }"
                         % (installer.ps_literal(name), pid, installer.ps_literal(path)) for name, pid, path in holders)
        stub += [
            "function Read-UninstallEntry { param([string]$Name) if ($global:Entries.ContainsKey($Name)) { "
            "return $global:Entries[$Name] } return $null }",
            "function Remove-UninstallEntry { param([string]$Name) Add-Content -LiteralPath %s -Value ('entry ' + $Name); "
            "$global:Entries.Remove($Name) }" % installer.ps_literal(log),
            "$global:Fakes = @(%s)" % fakes,
            "function Get-OwnedDashboardProcess {",
            "    foreach ($f in $global:Fakes) {",
            "        if (-not $f.Alive -or $null -eq $script:DashboardsAskedAt) { continue }",
            "        if ($f.Kind -eq 'unsaved') { Set-Content -LiteralPath (Join-Path (Join-Path $InstallHome 'config') "
            "('update-unsaved-' + $f.ProcessId + '.txt')) -Value 'unsaved' }",
            "        if ($f.Kind -eq 'new') { Set-Content -LiteralPath (Join-Path (Join-Path $InstallHome 'config') "
            "('reopen-after-update-' + $f.ProcessId + '.txt')) -Value '--page=pending --reopened=1'; $f.Alive = $false }",
            "    }",
            "    return ,@($global:Fakes | Where-Object { $_.Alive } | ForEach-Object { [pscustomobject]@{ "
            "ProcessId = $_.ProcessId; CommandLine = $_.CommandLine } })",
            "}",
            "function Close-DashboardWindow { param([int]$ProcessId) Add-Content -LiteralPath %s -Value ('closed ' + $ProcessId); "
            "$f = @($global:Fakes | Where-Object { $_.ProcessId -eq $ProcessId })[0]; if ($f.Kind -eq 'old') { $f.Alive = $false }; "
            "return $true }" % installer.ps_literal(log),
            "function Get-InstallationHolder { return ,@(%s) }" % held,
            "function Invoke-Setup { param([string[]]$Arguments) Add-Content -LiteralPath %s -Value ('setup ' + ($Arguments -join ' ')); "
            "return 0 }" % installer.ps_literal(log),
            "function Get-CodexCli { return $null }",
            "function Get-OwnedMcpProcess { return ,@() }",
            "$PSDefaultParameterValues['Close-OwnedDashboard:AnswerSeconds'] = 1",
            "$PSDefaultParameterValues['Close-OwnedDashboard:CloseSeconds'] = 1",
        ]
        script = ("$OwnedHome = %s\n$InstallHome = $OwnedHome\n$AppDir = Join-Path $OwnedHome app\n"
                  "$RunDir = Join-Path $OwnedHome runtime\n$Python = Join-Path $RunDir python.exe\n"
                  "$PluginCacheRoot = Join-Path $OwnedHome cache\n$PluginName = 'fixture-plugin'\n"
                  "$MarketplaceName = 'fixture-market'\n$script:Failed = $false\n$Purge = $false\n"
                  "$script:DashboardsAskedAt = $null\n$script:DashboardsFallback = @()\n" % installer.ps_literal(home))
        script += "\n".join(stub) + "\n"
        branch = installer.block(text, "# ----------------------------------------------------------------------- uninstall",
                                 "# -------------------------------------------------------------------------- install")
        script += "if ($true) {\n" + branch[branch.index("    # Before the first removal:"):]
        done = installer.run_probe(source, script)
        steps = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
        return done, steps

    def installation(self, root: Path) -> Path:
        home = InstallerFlowTests.installation(self, root)
        (home / addremove.WINDOW).write_text("fixture", encoding="utf-8")
        return home

    def entry(self, home: Path) -> dict:
        command = " ".join(startup.quote_argument(argument) for argument in
                           (str(home / addremove.WINDOW), addremove.WINDOW_SWITCH, str(addremove.kept_script(home))))
        return {"CodexAutoResumeAdvanced": (str(home), command)}

    def assert_nothing_removed(self, home: Path, done, steps):
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("nothing was removed", done.stdout)
        self.assertFalse([step for step in steps if step.startswith(("setup", "entry"))],
                         "something was removed before the check: %s" % steps)
        for kept in ("app", "runtime/python.exe", "uninstall/install.ps1", addremove.WINDOW, "config/settings.json"):
            self.assertTrue((home / kept).exists(), kept)

    def test_a_dashboard_with_unsaved_changes_stops_it_before_anything_is_removed(self):
        with tempfile.TemporaryDirectory() as name:
            home = self.installation(Path(name))
            done, steps = self.run_uninstall(home, windows=[(401, "x", "unsaved")], entries=self.entry(home))
            self.assert_nothing_removed(home, done, steps)
            self.assertIn("unsaved Settings changes", done.stdout)
            self.assertNotIn("closed 401", steps, "a window keeping unsaved changes is never sent WM_CLOSE")

    def test_what_still_runs_there_stops_it_and_is_named(self):
        """The runtime python.exe the Dashboard started, or any program of the installation's still running that
        the uninstall does not stop itself, is named, and nothing is removed."""
        with tempfile.TemporaryDirectory() as name:
            home = self.installation(Path(name))
            done, steps = self.run_uninstall(home, holders=[("python.exe", 4242, str(home / "runtime" / "python.exe"))],
                                             entries=self.entry(home))
            self.assert_nothing_removed(home, done, steps)
            self.assertIn("python.exe (process 4242) is running", done.stdout)

    def test_a_program_file_held_open_stops_it_before_anything_is_removed(self):
        with tempfile.TemporaryDirectory() as name:
            home = self.installation(Path(name))
            with (home / addremove.WINDOW).open("rb"):
                done, steps = self.run_uninstall(home, entries=self.entry(home))
            self.assert_nothing_removed(home, done, steps)
            self.assertIn("is in use", done.stdout)

    def test_an_older_dashboard_is_closed_first_and_the_uninstall_goes_on_to_the_end(self):
        """A Dashboard of an earlier version, which does not answer the event, is sent WM_CLOSE and closes; then the
        uninstall runs whole, and its Apps entry goes with it."""
        with tempfile.TemporaryDirectory() as name:
            home = self.installation(Path(name))
            done, steps = self.run_uninstall(home, windows=[(501, "x --page=pending", "old")], entries=self.entry(home))
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertEqual(steps[0], "closed 501", steps)
            self.assertIn("setup uninstall", steps)
            self.assertIn("entry CodexAutoResumeAdvanced", steps)
            self.assertIn("Closing the Dashboard so its files can be removed", done.stdout)
            self.assertFalse((home / "app").exists())
            self.assertTrue((home / "config" / "settings.json").is_file())

    def test_a_dashboard_of_this_version_closes_and_leaves_no_record_to_open_again(self):
        """The v0.6.17 acceptance: the uninstall closed the open Dashboard, which wrote where it was
        (config/reopen-after-update-<pid>.txt) as it does for an update; config/ is kept by a keep-data uninstall, and
        the reinstall after it, no update, never swept the record. An uninstall opens nothing again: it removes them."""
        with tempfile.TemporaryDirectory() as name:
            home = self.installation(Path(name))
            done, steps = self.run_uninstall(home, windows=[(601, "x --page=pending", "new")], entries=self.entry(home))
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertIn("The Dashboard closed", done.stdout)
            self.assertEqual(sorted(p.name for p in (home / "config").glob("reopen-after-update*")), [],
                             "the record the closed window wrote is gone")
            self.assertTrue((home / "config" / "settings.json").is_file(), "the settings are kept")
        with tempfile.TemporaryDirectory() as name:
            home = self.installation(Path(name))
            done, steps = self.run_uninstall(home, windows=[(602, "x", "new"), (603, "x", "unsaved")],
                                             entries=self.entry(home))
            self.assert_nothing_removed(home, done, steps)
            self.assertEqual(sorted(p.name for p in (home / "config").glob("reopen-after-update*")), [],
                             "nor when the uninstall stops for a window that keeps unsaved changes")

    def test_with_nothing_open_it_runs_as_before(self):
        with tempfile.TemporaryDirectory() as name:
            home = self.installation(Path(name))
            done, steps = self.run_uninstall(home, entries=self.entry(home))
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertEqual(steps, ["setup uninstall", "entry CodexAutoResumeAdvanced"])
            self.assertNotIn("Closing the Dashboard", done.stdout)

    def test_the_check_comes_before_the_first_removal(self):
        branch = installer.block(self.text, "if ($Uninstall)", "# -------------------------------------------------------------------------- install")
        self.assertLess(branch.index("$blockers = Get-UninstallBlocker"), branch.index("$code = Invoke-Setup $setupArgs"))
        self.assertGreater(branch.index("$blockers = Get-UninstallBlocker"), branch.index("$OwnedHome = Resolve-Canonical"))

    @unittest.skipUnless(WINDOWS, "Windows processes")
    def test_a_program_running_from_the_installation_holds_it_but_the_watcher_and_its_children_do_not(self):
        """Get-InstallationHolder against real processes, read-only: a program started from a scratch installation's
        runtime folder holds it; spared as the watcher - or as what a spared process started - it does not."""
        ping = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "PING.EXE"
        if not ping.is_file():
            self.skipTest("no ping.exe to stand in for a program")
        with tempfile.TemporaryDirectory() as name:
            home = InstallerFlowTests.installation(self, Path(name))
            program = home / "runtime" / "stand-in.exe"
            shutil.copyfile(ping, program)
            child = subprocess.Popen([str(program), "-n", "60", "127.0.0.1"], stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
            try:
                source = installer.VOICE + installer.block(self.text, "function Quote-Argument", "function Invoke-Setup")
                results = {}
                for case, watcher in (("held", "@()"), ("watcher", "@([pscustomobject]@{ ProcessId = %d })" % child.pid),
                                      ("parent", "@([pscustomobject]@{ ProcessId = %d })" % os.getpid())):
                    script = ("$OwnedHome = %s\n$InstallHome = $OwnedHome\n$PluginCacheRoot = Join-Path $OwnedHome cache\n"
                              "function Get-OwnedWatcherProcess { return ,%s }\n"
                              "function Get-OwnedMcpProcess { return ,@() }\n"
                              "$found = Get-InstallationHolder -Seconds 0\n"
                              "Write-Output ('FOUND ' + (@($found | ForEach-Object { $_.ProcessId }) -join ','))\n"
                              % (installer.ps_literal(home), watcher))
                    done = installer.run_probe(source, script)
                    line = next((l for l in done.stdout.splitlines() if l.startswith("FOUND")), done.stdout + done.stderr)
                    results[case] = line
                self.assertEqual(results["held"], "FOUND %d" % child.pid)
                self.assertEqual(results["watcher"], "FOUND ", "the watcher is the uninstall's own to stop")
                self.assertEqual(results["parent"], "FOUND ", "what a spared process started is spared with it")
            finally:
                child.kill()
                child.wait(30)


# ---------------------------------------------------------------------------------------------------- the key

class FakeWinreg:
    """The slice of winreg the entry uses, over a dict: key path -> {value name: (value, kind)}."""
    HKEY_CURRENT_USER = object()
    KEY_READ, KEY_SET_VALUE = 1, 2
    REG_SZ, REG_DWORD = 1, 4

    def __init__(self):
        self.keys: dict = {}
        self.writes = []

        class Key:
            def __init__(inner, path):
                inner.path = path

            def __enter__(inner):
                return inner

            def __exit__(inner, *exc):
                return False

        self.Key = Key

    def OpenKey(self, root, path, reserved, access):
        if path not in self.keys:
            raise FileNotFoundError(path)
        return self.Key(path)

    def CreateKeyEx(self, root, path, reserved, access):
        self.keys.setdefault(path, {})
        self.writes.append(path)
        return self.Key(path)

    def QueryValueEx(self, key, name):
        values = self.keys.get(key.path, {})
        if name not in values:
            raise FileNotFoundError(name)
        return values[name]

    def SetValueEx(self, key, name, reserved, kind, value):
        self.keys.setdefault(key.path, {})[name] = (value, kind)

    def DeleteKey(self, root, path):
        if path not in self.keys:
            raise FileNotFoundError(path)
        del self.keys[path]


class Entry(unittest.TestCase):
    """A scratch home with a kept uninstaller, and a fake registry in startup's place for it."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / ".codex-auto-resume"
        (self.home / "uninstall").mkdir(parents=True)
        (self.home / "uninstall" / "install.ps1").write_text("# kept", encoding="utf-8")
        self.registry = FakeWinreg()
        guard = patch.object(startup, "_winreg", return_value=self.registry)
        guard.start()
        self.addCleanup(guard.stop)

    def values(self, edition="standard"):
        return {name: value for name, (value, kind) in self.registry.keys[addremove.key_path(edition)].items()}


@unittest.skipUnless(WINDOWS, "the registry is Windows'")
class KeyTests(Entry):
    def test_one_key_with_the_values_windows_and_winget_read(self):
        done = addremove.register(self.home, "standard", "1.2.3", "Codex Auto Resume")
        self.assertEqual(done, ["wrote CodexAutoResume"])
        self.assertEqual(list(self.registry.keys),
                         [r"Software\Microsoft\Windows\CurrentVersion\Uninstall\CodexAutoResume"])
        values = self.values()
        self.assertEqual({key: values[key] for key in ("DisplayName", "DisplayVersion", "Publisher")},
                         {"DisplayName": "Codex Auto Resume", "DisplayVersion": "1.2.3",
                          "Publisher": "songyb111-gachon"})
        self.assertEqual(values["InstallLocation"], str(self.home))
        self.assertEqual((values["NoModify"], values["NoRepair"]), (1, 1))
        kinds = {name: kind for name, (value, kind) in self.registry.keys[addremove.key_path("standard")].items()}
        self.assertEqual(kinds["NoModify"], FakeWinreg.REG_DWORD)
        self.assertEqual(kinds["UninstallString"], FakeWinreg.REG_SZ)
        self.assertEqual(sorted(values), sorted(["DisplayName", "DisplayVersion", "Publisher", "InstallLocation",
                                                 "UninstallString", "QuietUninstallString", "NoModify", "NoRepair"]))

    def test_the_entry_shows_the_installed_programs_icon(self):
        """The v0.6.16 acceptance found DisplayIcon empty, so Settings > Apps showed the entry with no icon. It
        names the icon file the installer puts in the home, else the Dashboard program's own first icon; a home
        with neither gets no DisplayIcon rather than one naming nothing, and an update adds it to an entry written
        without it."""
        addremove.register(self.home, "standard", "1.2.3", "Codex Auto Resume")
        self.assertNotIn("DisplayIcon", self.values(), "nothing there to name")
        (self.home / addremove.WINDOW).write_bytes(b"MZ not a program")
        self.assertEqual(addremove.register(self.home, "standard", "1.2.3", "Codex Auto Resume"),
                         ["wrote CodexAutoResume"], "the icon is added to an entry that had none")
        self.assertEqual(self.values()["DisplayIcon"], str(self.home / "CodexAutoResumeSettings.exe") + ",0")
        (self.home / "codex-auto-resume.ico").write_bytes(b"\x00\x00\x01\x00")
        addremove.register(self.home, "standard", "1.2.3", "Codex Auto Resume")
        self.assertEqual(self.values()["DisplayIcon"], str(self.home / "codex-auto-resume.ico"))
        self.assertEqual(addremove.register(self.home, "standard", "1.2.3", "Codex Auto Resume"), [],
                         "a repeat writes nothing: the icon is read back with the rest")
        self.assertEqual(addremove.ICON, config.Paths(self.home).icon_file.name)

    def test_the_commands_run_the_kept_installer_by_full_paths_and_the_quiet_one_adds_the_switch(self):
        addremove.register(self.home, "standard", "1.2.3", "Codex Auto Resume")
        values = self.values()
        loud, quiet = startup.parse_command(values["UninstallString"]), startup.parse_command(values["QuietUninstallString"])
        self.assertEqual(loud[0].lower(), str(addremove.powershell()).lower())
        self.assertEqual(loud[1:], ["-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                    str(self.home / "uninstall" / "install.ps1"), "-Uninstall"])
        self.assertEqual(quiet, loud + ["-Silent"])

    def test_with_the_dashboard_program_there_the_command_a_person_runs_opens_the_installer_window(self):
        """v0.6.16: Settings > Apps runs the installation's own Dashboard program with --uninstall and the kept
        script (gui/SettingsRemove.cs), which shows the uninstall in the installer window; the quiet command, the
        one winget runs, is the kept script itself with -Silent and no window, as it was. Either names the kept
        script, so the key is this installation's by the same rule."""
        (self.home / addremove.WINDOW).write_bytes(b"MZ not a program")
        addremove.register(self.home, "standard", "1.2.3", "Codex Auto Resume")
        values = self.values()
        loud, quiet = startup.parse_command(values["UninstallString"]), startup.parse_command(values["QuietUninstallString"])
        self.assertEqual(loud, [str(self.home / "CodexAutoResumeSettings.exe"), "--uninstall",
                                str(self.home / "uninstall" / "install.ps1")])
        self.assertEqual(quiet[0].lower(), str(addremove.powershell()).lower())
        self.assertEqual(quiet[-2:], ["-Uninstall", "-Silent"])
        self.assertTrue(addremove.owned(values, self.home))
        window = (ROOT / "gui" / "SettingsRemove.cs").read_text(encoding="utf-8")
        self.assertIn('internal const string Asked = "%s";' % addremove.WINDOW_SWITCH, window)
        # A command line that is not the installation's own says so in the uninstall's window, finished before it
        # began, never in Windows' own box (tests/test_gui_v066_dialog.py counts the one box the program keeps).
        self.assertNotIn("MessageBox.Show", window)
        self.assertIn("window.Finished(InstallerFlow.NotStarted, NotItsOwn", window)

    def test_a_home_with_spaces_is_one_argument(self):
        home = Path(self.temp.name) / "Example User" / ".codex-auto-resume"
        (home / "uninstall").mkdir(parents=True)
        (home / "uninstall" / "install.ps1").write_text("# kept", encoding="utf-8")
        addremove.register(home, "standard", "1.2.3", "Codex Auto Resume")
        argv = startup.parse_command(self.values()["QuietUninstallString"])
        self.assertIn(str(home / "uninstall" / "install.ps1"), argv)
        self.assertTrue(addremove.owned(self.registry.keys[addremove.key_path("standard")] and
                                        {k: v for k, (v, _) in self.registry.keys[addremove.key_path("standard")].items()},
                                        home))

    def test_the_other_editions_key_has_its_own_fixed_name(self):
        self.assertEqual((addremove.key_name("standard"), addremove.key_name("advanced")),
                         ("CodexAutoResume", "CodexAutoResumeAdvanced"))
        addremove.register(self.home, "advanced", "1.2.3", "Codex Auto Resume Advanced")
        self.assertEqual(list(self.registry.keys), [addremove.key_path("advanced")])
        self.assertEqual(self.values("advanced")["DisplayName"], "Codex Auto Resume Advanced")

    def test_an_update_rewrites_the_one_key_and_a_repeat_writes_nothing(self):
        addremove.register(self.home, "standard", "1.2.3", "Codex Auto Resume")
        writes = len(self.registry.writes)
        self.assertEqual(addremove.register(self.home, "standard", "1.2.3", "Codex Auto Resume"), [])
        self.assertEqual(len(self.registry.writes), writes, "the same entry is not written again")
        self.assertEqual(addremove.register(self.home, "standard", "1.2.4", "Codex Auto Resume"), ["wrote CodexAutoResume"])
        self.assertEqual(self.values()["DisplayVersion"], "1.2.4")
        self.assertEqual(len(self.registry.keys), 1)

    def test_an_edition_change_leaves_exactly_one_key(self):
        addremove.register(self.home, "standard", "1.2.3", "Codex Auto Resume")
        done = addremove.register(self.home, "advanced", "1.2.3", "Codex Auto Resume Advanced")
        self.assertEqual(done, ["wrote CodexAutoResumeAdvanced", "removed CodexAutoResume"])
        self.assertEqual(list(self.registry.keys), [addremove.key_path("advanced")])
        done = addremove.register(self.home, "standard", "1.2.3", "Codex Auto Resume")
        self.assertEqual(list(self.registry.keys), [addremove.key_path("standard")])
        self.assertEqual(done, ["wrote CodexAutoResume", "removed CodexAutoResumeAdvanced"])

    def test_nothing_is_written_without_a_kept_uninstaller_or_a_known_version(self):
        (self.home / "uninstall" / "install.ps1").unlink()
        self.assertEqual(addremove.register(self.home, "standard", "1.2.3", "x"), [])
        (self.home / "uninstall" / "install.ps1").write_text("# kept", encoding="utf-8")
        for version in ("", "unknown"):
            self.assertEqual(addremove.register(self.home, "standard", version, "x"), [])
        self.assertEqual(addremove.register(self.home, "sideways", "1.2.3", "x"), [])
        self.assertEqual(self.registry.keys, {})

    def junction(self, link: Path, target: Path):
        made = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(link), str(target)], capture_output=True,
                              creationflags=NO_WINDOW)
        if made.returncode != 0:
            self.skipTest("no junction could be made here")

    def test_a_junction_where_the_kept_folder_should_be_gets_no_entry(self):
        """The installer refuses a junction as the kept folder and keeps nothing; the engine must not then write a key
        whose command runs whatever the junction points at (F4)."""
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (outside / "install.ps1").write_text("# someone else's", encoding="utf-8")
        shutil.rmtree(self.home / "uninstall")
        self.junction(self.home / "uninstall", outside)
        self.assertTrue(addremove.kept_script(self.home).is_file(), "is_file() follows it: the thing to refuse")
        self.assertEqual(addremove.register(self.home, "standard", "1.2.3", "Codex Auto Resume"), [])
        self.assertEqual(self.registry.keys, {})

    def test_a_junction_in_the_place_of_the_kept_script_gets_no_entry_either(self):
        outside = Path(self.temp.name) / "outside-folder"
        outside.mkdir()
        (self.home / "uninstall" / "install.ps1").unlink()
        self.junction(self.home / "uninstall" / "install.ps1", outside)
        self.assertEqual(addremove.register(self.home, "standard", "1.2.3", "Codex Auto Resume"), [])
        self.assertEqual(self.registry.keys, {})

    def test_an_ordinary_kept_folder_and_script_are_plain(self):
        self.assertTrue(addremove.kept_uninstaller_present(self.home))
        self.assertFalse(addremove.kept_uninstaller_present(Path(self.temp.name) / "nowhere"))

    def test_the_display_name_is_the_installed_manifests_and_the_publisher_is_the_plugin_author(self):
        manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(addremove.display_name(ROOT / ".codex-plugin" / "plugin.json"), manifest["interface"]["displayName"])
        self.assertEqual(addremove.display_name(ROOT / "no-such-manifest.json"), "Codex Auto Resume")
        self.assertEqual(addremove.PUBLISHER, manifest["author"]["name"])


@unittest.skipUnless(WINDOWS, "the registry is Windows'")
class ProvenanceTests(Entry):
    """Only a key that can be proved this installation's is overwritten or deleted."""

    def foreign(self, **changes):
        addremove.register(self.home, "standard", "1.2.3", "Codex Auto Resume")
        key = self.registry.keys[addremove.key_path("standard")]
        for name, value in changes.items():
            key[name] = (value, FakeWinreg.REG_SZ)
        return dict(key)

    def test_unregister_removes_this_installations_key(self):
        addremove.register(self.home, "standard", "1.2.3", "Codex Auto Resume")
        self.assertEqual(addremove.unregister(self.home), ["CodexAutoResume"])
        self.assertEqual(self.registry.keys, {})
        self.assertEqual(addremove.unregister(self.home), [], "nothing to remove is not an error")

    def test_a_key_of_that_name_for_another_home_is_kept_and_not_overwritten(self):
        other = Path(self.temp.name) / "other-home"
        before = self.foreign(InstallLocation=str(other))
        self.assertEqual(addremove.unregister(self.home), [])
        self.assertEqual(addremove.register(self.home, "standard", "9.9.9", "x"), [])
        self.assertEqual(dict(self.registry.keys[addremove.key_path("standard")]), before)

    def test_a_key_whose_uninstall_command_is_not_this_homes_kept_installer_is_kept(self):
        before = self.foreign(UninstallString='"C:\\Other\\uninstall.exe" /S')
        self.assertEqual(addremove.unregister(self.home), [])
        self.assertEqual(dict(self.registry.keys[addremove.key_path("standard")]), before)

    def test_a_key_that_only_names_the_home_is_not_enough(self):
        before = self.foreign(UninstallString='"C:\\Other\\uninstall.exe" /S')
        self.assertFalse(addremove.owned({"InstallLocation": str(self.home), "UninstallString": "x"}, self.home))
        self.assertFalse(addremove.owned(None, self.home))
        self.assertFalse(addremove.owned({}, self.home))
        self.assertIsNotNone(before)

    def test_an_edition_change_does_not_take_a_foreign_key_of_the_other_name(self):
        other = Path(self.temp.name) / "other-home"
        self.registry.keys[addremove.key_path("standard")] = {
            "InstallLocation": (str(other), 1), "UninstallString": ("x", 1)}
        addremove.register(self.home, "advanced", "1.2.3", "Codex Auto Resume Advanced")
        self.assertIn(addremove.key_path("standard"), self.registry.keys)

    def test_no_other_key_is_ever_touched(self):
        unrelated = {r"Software\Microsoft\Windows\CurrentVersion\Uninstall\SomethingElse": {"DisplayName": ("x", 1)},
                     startup.RUN_KEY: {"CodexAutoResume": ("run", 1)}}
        self.registry.keys.update({key: dict(value) for key, value in unrelated.items()})
        addremove.register(self.home, "standard", "1.2.3", "Codex Auto Resume")
        addremove.register(self.home, "advanced", "1.2.3", "Codex Auto Resume Advanced")
        addremove.unregister(self.home)
        self.assertEqual(self.registry.keys, unrelated)
        self.assertEqual(set(self.registry.writes), {addremove.key_path("standard"), addremove.key_path("advanced")})


@unittest.skipUnless(WINDOWS, "the registry is Windows'")
class WiringTests(Entry):
    """The two commands that reach it: the plugin bridge's setup and the engine's uninstall."""

    def test_the_engines_uninstall_removes_the_entry_and_says_so(self):
        from codex_auto_resume import cli, shortcut
        addremove.register(self.home, "standard", "1.2.3", "Codex Auto Resume")
        out = io.StringIO()
        with patch.object(shortcut, "uninstall", return_value=False), patch.dict(
                os.environ, {"LOCALAPPDATA": str(Path(self.temp.name) / "none"),
                             "CODEX_HOME": str(Path(self.temp.name) / "codex"), config.ENV_HOME: str(self.home)}), \
                contextlib.redirect_stdout(out):
            code = cli.main(["--home", str(self.home), "uninstall", "--keep-state"])
        self.assertEqual(code, 0, out.getvalue())
        self.assertNotIn(addremove.key_path("standard"), self.registry.keys)
        self.assertIn("entry in Add or remove programs", out.getvalue())

    def uninstall(self, **environment):
        from codex_auto_resume import cli, shortcut
        out = io.StringIO()
        with patch.object(shortcut, "uninstall", return_value=False), patch.dict(
                os.environ, dict({"LOCALAPPDATA": str(Path(self.temp.name) / "none"),
                                  "CODEX_HOME": str(Path(self.temp.name) / "codex"),
                                  config.ENV_HOME: str(self.home)}, **environment)), \
                contextlib.redirect_stdout(out):
            code = cli.main(["--home", str(self.home), "uninstall", "--keep-state"])
        return code, out.getvalue()

    def test_asked_to_keep_the_entry_the_engines_uninstall_leaves_it_for_the_installer(self):
        addremove.register(self.home, "standard", "1.2.3", "Codex Auto Resume")
        code, out = self.uninstall(**{addremove.KEEP_ENTRY_ENV: "1"})
        self.assertEqual(code, 0, out)
        self.assertIn(addremove.key_path("standard"), self.registry.keys, "the engine removed it early")
        self.assertNotIn("entry in Add or remove programs", out)
        code, out = self.uninstall()
        self.assertEqual(code, 0, out)
        self.assertNotIn(addremove.key_path("standard"), self.registry.keys, "asked nothing, it still removes it")

    def test_the_bridges_setup_registers_only_through_this_module(self):
        text = (ROOT / "scripts" / "plugin_setup.py").read_text(encoding="utf-8")
        self.assertIn("addremove.register(home, edition.name().value, config.version(),", text)
        self.assertIn("addremove.display_name(config.PROJECT_ROOT / config.PLUGIN_MANIFEST))", text)
        setup = text[text.index("def cmd_setup"):text.index("def cmd_enable")]
        self.assertEqual(setup.count("addremove."), 2)
        for forbidden in ("winreg", "CurrentVersion"):
            self.assertNotIn(forbidden, text)

    def test_the_bridges_setup_writes_the_entry_after_the_protocol_and_before_the_watcher_starts(self):
        text = (ROOT / "scripts" / "plugin_setup.py").read_text(encoding="utf-8")
        setup = text[text.index("def cmd_setup"):text.index("def cmd_enable")]
        self.assertLess(setup.index("startup.install_protocol"), setup.index("addremove.register"))
        self.assertLess(setup.index("addremove.register"), setup.index("start_watcher(home)"))

    def test_the_only_registry_code_added_lives_in_the_one_module(self):
        found = []
        for path in (ROOT / "src" / "codex_auto_resume").rglob("*.py"):
            if "CurrentVersion\\Uninstall" in path.read_text(encoding="utf-8", errors="replace"):
                found.append(path.name)
        self.assertEqual(found, ["addremove.py"])


@unittest.skipUnless(WINDOWS, "the registry is Windows'")
class RemoveEntryTests(Entry):
    """`plugin_setup.py remove-entry`: what a hand-over to an older version runs first."""

    def remove(self):
        import plugin_setup
        out = io.StringIO()
        with patch.dict(os.environ, {plugin_setup.ENV_RUNTIME_HOME: str(self.home)}), contextlib.redirect_stdout(out):
            code = plugin_setup.cmd_remove_entry(None)
        return code, out.getvalue().strip()

    def test_the_entry_and_the_kept_uninstaller_are_both_taken_away(self):
        addremove.register(self.home, "standard", "1.2.3", "Codex Auto Resume")
        code, out = self.remove()
        self.assertEqual((code, out), (0, "entry: removed"))
        self.assertEqual(self.registry.keys, {})
        self.assertFalse((self.home / "uninstall").exists(), "the script and its folder go with it")
        self.assertEqual(self.remove(), (0, "entry: none"))

    def test_an_entry_of_another_installation_stays_and_so_does_what_is_not_ours(self):
        addremove.register(self.home, "standard", "1.2.3", "Codex Auto Resume")
        key = self.registry.keys[addremove.key_path("standard")]
        key["InstallLocation"] = (str(Path(self.temp.name) / "other"), 1)
        (self.home / "uninstall" / "notes.txt").write_text("not ours", encoding="utf-8")
        code, out = self.remove()
        self.assertEqual(code, 0, out)
        self.assertIn(addremove.key_path("standard"), self.registry.keys)
        self.assertTrue((self.home / "uninstall" / "notes.txt").is_file())
        self.assertFalse((self.home / "uninstall" / "install.ps1").exists())

    def test_a_junction_is_not_followed_when_the_kept_uninstaller_is_removed(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (outside / "install.ps1").write_text("# someone else's", encoding="utf-8")
        shutil.rmtree(self.home / "uninstall")
        made = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(self.home / "uninstall"), str(outside)],
                              capture_output=True, creationflags=NO_WINDOW)
        if made.returncode != 0:
            self.skipTest("no junction could be made here")
        self.assertFalse(addremove.remove_kept(self.home))
        self.assertTrue((outside / "install.ps1").is_file())

    def test_the_command_is_the_one_the_bootstrap_runs(self):
        import plugin_setup
        parsed = plugin_setup.build_parser().parse_args(["remove-entry"])
        self.assertEqual(parsed.command, "remove-entry")
        self.assertIs(plugin_setup.COMMANDS["remove-entry"], plugin_setup.cmd_remove_entry)


BOOTSTRAP = ROOT / "scripts" / "bootstrap.ps1"


@unittest.skipUnless(WINDOWS and installer.POWERSHELL, "the bootstrap is PowerShell on Windows")
class HandOverTests(unittest.TestCase):
    """The bootstrap's hand-over to a version that does not know the entry, both ways: the entry goes first when
    the picked version is older than the one that has it, and stays for any other."""

    def setUp(self):
        self.text = BOOTSTRAP.read_text(encoding="utf-8")

    def decide(self, installed: str, target: str, code: int = 0) -> tuple:
        text = self.text
        source = installer.VOICE
        source += installer.block(text, "function Get-VersionParts", "function Format-UnreadVersion")
        source += installer.block(text, "function Compare-ProductVersion", "function Get-NewestPublishedVersion")
        source += installer.block(text, "function Remove-EntryBeforeOlder", "function Start-CurrentWatcher")
        source += re.search(r"(?m)^\$EntryFrom = '[^']+'$", text).group(0) + "\n"
        script = ("$global:calls = @()\n"
                  "function Invoke-InstalledSetup { param([string]$Home_, [string[]]$Arguments) "
                  "$global:calls += ($Arguments -join ' '); "
                  "return [pscustomobject]@{ Printed = @(); Code = %d } }\n"
                  "$answer = Remove-EntryBeforeOlder -Home_ 'C:\\scratch' -Installed %s -Target %s\n"
                  "'answer: ' + $answer\n'calls: ' + ($global:calls -join '|')\n"
                  % (code, installer.ps_literal(installed), installer.ps_literal(target)))
        done = installer.run_probe(source, script)
        answer = re.search(r"answer: (\w+)", done.stdout)
        calls = re.search(r"calls: (.*)", done.stdout)
        self.assertTrue(answer and calls, done.stdout + done.stderr)
        return answer.group(1), calls.group(1).strip()

    def test_going_back_to_a_version_before_the_entry_removes_it_first(self):
        for installed, target in (("0.6.16", "0.6.15"), ("0.6.17", "0.6.14"), ("0.6.16", "0.6.16-beta.3"),
                                  ("0.6.16-beta.4", "0.6.12"), ("0.6.16", "0.6.2")):
            with self.subTest(installed=installed, target=target):
                self.assertEqual(self.decide(installed, target), ("removed", "remove-entry"))

    def test_any_other_pick_leaves_the_entry_alone(self):
        for installed, target in (("0.6.16", "0.6.16"), ("0.6.17", "0.6.16"), ("0.6.16", "0.6.17"),
                                  ("0.6.16", "0.6.18-beta.2")):
            with self.subTest(installed=installed, target=target):
                self.assertEqual(self.decide(installed, target), ("kept", ""))

    def test_an_installation_older_than_the_entry_has_no_such_command_to_run(self):
        for installed, target in (("0.6.15", "0.6.12"), ("0.6.12", "0.6.11"), ("0.6.15", "0.6.16")):
            with self.subTest(installed=installed, target=target):
                self.assertEqual(self.decide(installed, target), ("none", ""))

    def test_a_removal_that_failed_says_so_and_an_engine_without_the_command_is_not_a_failure(self):
        self.assertEqual(self.decide("0.6.16", "0.6.15", code=1), ("failed", "remove-entry"))
        self.assertEqual(self.decide("0.6.16-beta.3", "0.6.15", code=2), ("none", "remove-entry"))

    def test_an_unreadable_version_runs_nothing(self):
        self.assertEqual(self.decide("garbage", "0.6.15"), ("none", ""))

    def test_it_runs_for_a_pick_after_the_state_is_converted_and_before_the_installer(self):
        text = self.text
        call = text.index("Remove-EntryBeforeOlder -Home_ $installHome")
        self.assertGreater(call, text.index("Convert-StateForOlder -Home_ $installHome -To $pickSchema"))
        self.assertLess(call, text.index("& $installer @arguments"))
        self.assertIn("    if ($Pick) {\n        $entry = Remove-EntryBeforeOlder", text.replace("\r\n", "\n"))
        self.assertEqual(text.count("Remove-EntryBeforeOlder -Home_"), 1)

    def test_one_number_for_the_first_version_in_every_place(self):
        from codex_auto_resume import addremove as module
        import winget_manifests
        found = re.search(r"(?m)^\$EntryFrom = '([^']+)'$", self.text).group(1)
        self.assertEqual(found, module.FIRST_VERSION)
        self.assertEqual(found, winget_manifests.UNATTENDED_FROM)


if __name__ == "__main__":
    unittest.main()
