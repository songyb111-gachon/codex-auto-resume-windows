"""The shortcut on the Desktop the setup window offers on its Finish page, off unless a person ticks it (the owner, 2026-11-02, 11-05 and 11-07).

The Desktop is the person's, not a singleton of ours, so what is held here is mostly what it may not do:

* WriterTests - the real shortcut.py against a Desktop of the test's own: the same thing as the Start Menu entry, and
  only a shortcut at the exact name with its target inside this installation is ever replaced or removed.
* WindowsDesktopTests - the folder is the one Windows names, not one under %USERPROFILE%. Reads only.
* EngineTests - the core's install leaves the Desktop alone, its uninstall takes ours whichever answer was given about
  the data, and the installer's setup command says what became of it by its exit code.
* ScriptTests - install.ps1 asks about the Desktop only when it was told to, and what fails there fails nothing.
* FlowTests, WindowTests and SourceTests - the box, which pages have it, what the Finish button asks of the installed engine
  (a tick makes ours, an untick removes ours, left as it was nothing), and what the Finish page says when it cannot.

NOTHING HERE MAY REACH THE REAL DESKTOP. `[Environment]::GetFolderPath` and SHGetKnownFolderPath ignore a scratch
USERPROFILE, so every test that makes or removes a shortcut sets shortcut.DESKTOP_ENV, and setUp proves it took; the module
also compares the real Desktop's entry, read only, before and after.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ROOT / "src" / "codex_auto_resume" / "locales"
_BUILD = str(ROOT / "build")
if _BUILD not in sys.path:
    sys.path.insert(0, _BUILD)

import guiscan  # noqa: E402
import languages  # noqa: E402
from test_add_remove import Launcher  # noqa: E402
from test_cli import FakeWinreg  # noqa: E402
from test_installer_window import _build, _powershell, CSC  # noqa: E402

from codex_auto_resume import cli, config, pwsh, shortcut, startup  # noqa: E402
from codex_auto_resume.commands.install import make_desktop_shortcut  # noqa: E402

WINDOWS = os.name == "nt"
POWERSHELL = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
INSTALL_PS1 = (ROOT / "build" / "install" / "install.ps1").read_text(encoding="utf-8")
BOOTSTRAP = (ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")
FLOW = (ROOT / "gui" / "InstallerFlow.cs").read_text(encoding="utf-8")
ENGLISH = json.loads((ROOT / "src" / "codex_auto_resume" / "locales" / "en.json").read_text(encoding="utf-8"))
LABEL = ENGLISH["installer.done.desktop_shortcut"]

_real_before = None


def _the_real_entry():
    saved = os.environ.pop(shortcut.DESKTOP_ENV, None)
    try:
        link = shortcut.desktop_path()
    finally:
        if saved is not None:
            os.environ[shortcut.DESKTOP_ENV] = saved
    try:
        return None if link is None else (link.stat().st_mtime_ns, hashlib.sha256(link.read_bytes()).hexdigest())
    except OSError:
        return None


def setUpModule():
    global _real_before
    _real_before = _the_real_entry()


def tearDownModule():
    if _the_real_entry() != _real_before:
        raise AssertionError("these tests changed the shortcut on this PC's real Desktop")


def _plugin_setup():
    module = sys.modules.get("plugin_setup_desktop_test")
    if module is None:
        spec = importlib.util.spec_from_file_location("plugin_setup_desktop_test", ROOT / "scripts" / "plugin_setup.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.modules["plugin_setup_desktop_test"] = module
    return module


class Scratch(unittest.TestCase):
    """A Desktop, a Start Menu and an installation of the test's own."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name).resolve()
        self.desktop = base / "Desktop"
        self.desktop.mkdir()
        self.home = base / "home"
        self.home.mkdir()
        self.window = self.home / "CodexAutoResumeSettings.exe"
        self.window.write_bytes(b"MZ this is not a real program")
        self.icon = self.home / "codex-auto-resume.ico"
        self.icon.write_bytes(b"\0\0\1\0")
        self.base = base
        guard = patch.dict(os.environ, {shortcut.DESKTOP_ENV: str(self.desktop), "APPDATA": str(base / "AppData")})
        guard.start()
        self.addCleanup(guard.stop)
        self.assertEqual(shortcut.desktop_path(), self.desktop / shortcut.SHORTCUT_NAME, "not on a scratch Desktop")
        self.link = self.desktop / shortcut.SHORTCUT_NAME

    def read(self, link: Path) -> dict:
        script = ("$l = (New-Object -ComObject WScript.Shell).CreateShortcut($env:CAR_LINK); "
                  "ConvertTo-Json @{ target = $l.TargetPath; icon = $l.IconLocation; arguments = $l.Arguments; "
                  "folder = $l.WorkingDirectory; description = $l.Description }")
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", script],
                              capture_output=True, env=dict(os.environ, CAR_LINK=str(link)),
                              creationflags=NO_WINDOW, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr[-500:])
        return json.loads(done.stdout.decode("utf-8", "replace"))

    def someone_elses(self, target: Path, name: str = shortcut.SHORTCUT_NAME) -> Path:
        """A shortcut a person made, at `name` on the Desktop."""
        link = self.desktop / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"MZ")
        script = ("$l = (New-Object -ComObject WScript.Shell).CreateShortcut($env:CAR_LINK); "
                  "$l.TargetPath = $env:CAR_TARGET; $l.Save()")
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                              env=dict(os.environ, CAR_LINK=str(link), CAR_TARGET=str(target)),
                              creationflags=NO_WINDOW, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr[-500:])
        self.assertTrue(link.is_file())
        return link


@unittest.skipUnless(WINDOWS and POWERSHELL.is_file(), "the shortcut is a Windows .lnk")
class WriterTests(Scratch):
    def test_it_opens_what_the_start_menu_entry_opens_with_the_same_name_and_icon(self):
        paths = config.Paths(self.home)
        make_desktop_shortcut(paths)
        self.assertEqual([item.name for item in self.desktop.iterdir()], ["Codex Auto Resume.lnk"])
        from codex_auto_resume.commands.install import _what_the_entry_opens
        shortcut.install(**_what_the_entry_opens(paths))
        self.assertEqual(shortcut.shortcut_path().name, self.link.name)
        self.assertEqual(self.read(self.link), self.read(shortcut.shortcut_path()))
        self.assertEqual(Path(self.read(self.link)["target"]).name, "CodexAutoResumeSettings.exe")
        self.assertIn("codex-auto-resume.ico", self.read(self.link)["icon"])
        self.assertIn(startup.AUMID.encode("utf-16-le"), self.link.read_bytes(), "the same identity as the Start Menu's")

    def test_ours_is_replaced_and_removed_and_removing_twice_is_nothing(self):
        make_desktop_shortcut(config.Paths(self.home))
        make_desktop_shortcut(config.Paths(self.home))
        self.assertTrue(self.link.is_file())
        self.assertTrue(shortcut.uninstall_desktop(self.home))
        self.assertFalse(self.link.exists())
        self.assertFalse(shortcut.uninstall_desktop(self.home))

    def test_a_shortcut_with_our_name_pointing_elsewhere_is_never_touched(self):
        link = self.someone_elses(self.base / "theirs" / "program.exe")
        before = link.read_bytes()
        with self.assertRaises(shortcut.DesktopTaken):
            make_desktop_shortcut(config.Paths(self.home))
        self.assertFalse(shortcut.uninstall_desktop(self.home))
        self.assertEqual(link.read_bytes(), before)

    def test_a_folder_that_only_begins_like_the_installation_is_not_inside_it(self):
        link = self.someone_elses(self.base / "home-other" / "CodexAutoResumeSettings.exe")
        before = link.read_bytes()
        self.assertFalse(shortcut.uninstall_desktop(self.home))
        self.assertEqual(link.read_bytes(), before)

    def test_another_name_is_never_touched_even_with_its_target_inside(self):
        link = self.someone_elses(self.window, "Codex Auto Resume - Copy.lnk")
        before = link.read_bytes()
        self.assertFalse(shortcut.uninstall_desktop(self.home))
        make_desktop_shortcut(config.Paths(self.home))
        self.assertTrue(shortcut.uninstall_desktop(self.home))
        self.assertEqual(link.read_bytes(), before)

    def test_a_file_the_shell_cannot_read_is_not_ours(self):
        self.link.write_bytes(b"not a shortcut")
        self.assertFalse(shortcut.uninstall_desktop(self.home))
        with self.assertRaises(shortcut.DesktopTaken):
            make_desktop_shortcut(config.Paths(self.home))
        self.assertEqual(self.link.read_bytes(), b"not a shortcut")

    def test_what_it_would_open_must_be_inside_the_installation(self):
        with self.assertRaises(shortcut.ShortcutError):
            shortcut.install_desktop(self.home, target=self.base / "elsewhere.exe")
        self.assertEqual(list(self.desktop.iterdir()), [])

    def test_a_desktop_that_is_not_there_is_said_and_writes_nothing(self):
        with patch.dict(os.environ, {shortcut.DESKTOP_ENV: str(self.base / "gone")}):
            with self.assertRaises(shortcut.ShortcutError):
                make_desktop_shortcut(config.Paths(self.home))
        self.assertFalse((self.base / "gone").exists())

    def test_its_values_travel_beside_a_constant_script(self):
        (self.home / "O\u2019Brien.exe").write_bytes(b"MZ")
        self.link.write_bytes(b"x")
        with patch.object(pwsh, "run", return_value=3) as run:
            self.assertFalse(shortcut.uninstall_desktop(self.home))
        script, values = run.call_args.args
        self.assertEqual(script, shortcut._READER)
        self.assertEqual(values["LNK"], self.link)
        self.assertNotIn("Save", shortcut._READER, "reading a shortcut saves nothing")


@unittest.skipUnless(WINDOWS and POWERSHELL.is_file(), "Windows' known folder")
class WindowsDesktopTests(unittest.TestCase):
    """Reads only, and the one place these tests look at the real Desktop."""

    def test_it_is_the_folder_windows_names_whatever_the_profile_variable_says(self):
        environment = {key: value for key, value in os.environ.items() if key != shortcut.DESKTOP_ENV}
        with tempfile.TemporaryDirectory() as scratch, patch.dict(os.environ, dict(environment, USERPROFILE=scratch), clear=True):
            found = shortcut.desktop_dir()
            self.assertIsNotNone(found)
            self.assertNotIn(os.path.normcase(scratch), os.path.normcase(str(found)))
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command",
                               "[Console]::OutputEncoding = New-Object Text.UTF8Encoding $false; "
                               "[Environment]::GetFolderPath('DesktopDirectory')"],
                              capture_output=True, creationflags=NO_WINDOW, timeout=120)
        self.assertEqual(os.path.normcase(done.stdout.decode("utf-8").strip()), os.path.normcase(str(found)))

    def test_nothing_builds_it_from_the_profile(self):
        source = (ROOT / "src" / "codex_auto_resume" / "shortcut.py").read_text(encoding="utf-8")
        body = source[source.index("def desktop_dir"):source.index("def desktop_path")]
        self.assertIn("SHGetKnownFolderPath", body)
        for word in ('"USERPROFILE"', "Path.home", '"Desktop"', "expanduser"):
            self.assertNotIn(word, body)
        self.assertIn("SpecialFolder.DesktopDirectory", FLOW)
        self.assertNotIn("USERPROFILE", guiscan.type_body("DesktopShortcut", FLOW))

    def test_the_two_languages_say_one_name_and_one_variable(self):
        self.assertIn('FileName = "%s"' % shortcut.SHORTCUT_NAME, FLOW)
        self.assertIn('FolderVariable = "%s"' % shortcut.DESKTOP_ENV, FLOW)


@unittest.skipUnless(WINDOWS and POWERSHELL.is_file(), "the shortcut is a Windows .lnk")
class EngineTests(Scratch):
    def setUp(self):
        super().setUp()
        guards = [patch.object(startup, "_winreg", return_value=FakeWinreg()),
                  patch.object(startup, "register_aumid", return_value=True),
                  patch.object(startup, "unregister_aumid", return_value=False),
                  patch.object(shortcut, "install", return_value=True),
                  patch.object(shortcut, "uninstall", return_value=False),
                  patch.dict(os.environ, {"LOCALAPPDATA": str(self.base / "none"), "CODEX_HOME": str(self.base / "codex"),
                                          config.ENV_HOME: str(self.home)})]
        for guard in guards:
            guard.start()
            self.addCleanup(guard.stop)
        # Runs before the folder goes: an open log file holds it on Windows.
        self.addCleanup(self.close_the_logs)

    @staticmethod
    def close_the_logs():
        logger = logging.getLogger("codex_auto_resume")
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

    def run_cli(self, *arguments):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["--home", str(self.home), *arguments])
        return code, out.getvalue()

    def test_the_cores_install_leaves_the_desktop_as_it_is(self):
        self.assertEqual(self.run_cli("install")[0], 0)
        self.assertEqual(list(self.desktop.iterdir()), [], "none is made unasked")
        make_desktop_shortcut(config.Paths(self.home))
        before = (self.link.stat().st_mtime_ns, self.link.read_bytes())
        self.assertEqual(self.run_cli("install")[0], 0)
        self.assertEqual((self.link.stat().st_mtime_ns, self.link.read_bytes()), before, "one that is there stays")

    def test_uninstall_removes_ours_whichever_answer_about_the_data(self):
        for words in (["--keep-state", "--keep-logs"], []):
            with self.subTest(words):
                make_desktop_shortcut(config.Paths(self.home))
                code, out = self.run_cli("uninstall", *words)
                self.assertEqual(code, 0, out)
                self.assertFalse(self.link.exists())
                self.assertIn("desktop shortcut", out)

    def test_uninstall_removes_ours_though_the_notification_identity_is_anothers(self):
        make_desktop_shortcut(config.Paths(self.home))
        with patch.object(startup, "notification_identity_owner", return_value=False):
            self.assertEqual(self.run_cli("uninstall", "--keep-state")[0], 0)
        self.assertFalse(self.link.exists())

    def test_uninstall_leaves_anothers_and_goes_on_past_one_it_cannot_read(self):
        link = self.someone_elses(self.base / "theirs" / "program.exe")
        before = link.read_bytes()
        code, out = self.run_cli("uninstall", "--keep-state")
        self.assertEqual((code, link.read_bytes()), (0, before), out)
        self.assertNotIn("desktop shortcut", out)
        with patch.object(pwsh, "run", return_value=1):
            code, out = self.run_cli("uninstall", "--keep-state")
        self.assertEqual((code, link.read_bytes()), (0, before), out)
        self.assertIn("warning:", out)

    def test_the_setup_command_says_what_became_of_it_by_its_code(self):
        bridge = _plugin_setup()
        def run(*words):
            with patch.dict(os.environ, {bridge.ENV_RUNTIME_HOME: str(self.home)}), contextlib.redirect_stdout(io.StringIO()):
                return bridge.main(["desktop-shortcut", *words])
        self.assertEqual(run("remove"), 0, "nothing there to remove is no failure")
        self.assertEqual(run("make"), 0)
        self.assertTrue(self.link.is_file())
        self.assertEqual(run("remove"), 0)
        self.assertFalse(self.link.exists())
        self.someone_elses(self.base / "theirs" / "program.exe")
        self.assertEqual(run("make"), bridge.EXIT_DESKTOP_TAKEN)
        self.assertEqual(run("remove"), 0)
        self.assertTrue(self.link.is_file(), "someone else's stays")
        self.link.unlink()
        with patch.dict(os.environ, {shortcut.DESKTOP_ENV: str(self.base / "gone")}):
            self.assertEqual(run("make"), bridge.EXIT_ERROR)


@unittest.skipUnless(WINDOWS and POWERSHELL.is_file(), "install.ps1 is Windows PowerShell")
class ScriptTests(unittest.TestCase):
    VOICE = ("function Ok   { param([string]$m) Write-Host ('  [ok] ' + $m) }\n"
             "function Warn { param([string]$m) Write-Host ('  [!]  ' + $m) }\n"
             "function Fail { param([string]$m) Write-Host ('  [x]  ' + $m); $script:Failed = $true }\n")

    def run_function(self, make: bool, remove: bool, code: int):
        """Set-DesktopShortcut as install.ps1 has it, with the setup step stood in for."""
        function = guiscan._block(INSTALL_PS1, INSTALL_PS1.index("function Set-DesktopShortcut"))
        with tempfile.TemporaryDirectory() as folder:
            calls = Path(folder) / "calls.txt"
            source = ("Set-StrictMode -Version 2.0\n$ErrorActionPreference = 'Stop'\n" + self.VOICE +
                      "function Invoke-Setup { param([string[]]$Arguments)\n"
                      "    Add-Content -LiteralPath $env:CAR_CALLS -Value (@($Arguments) -join ' ')\n"
                      "    return [int]$env:CAR_CODE }\n"
                      "$script:Failed = $false\n$DesktopShortcut = $%s\n$NoDesktopShortcut = $%s\n"
                      % ("true" if make else "false", "true" if remove else "false") +
                      function + "\nSet-DesktopShortcut\nWrite-Host ('failed=' + $script:Failed)\nexit 0\n")
            script = Path(folder) / "probe.ps1"
            script.write_text(source, encoding="utf-8-sig")
            done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                                  capture_output=True, encoding="locale", errors="replace", timeout=120, creationflags=NO_WINDOW,
                                  env=dict(os.environ, CAR_CALLS=str(calls), CAR_CODE=str(code)))
            said = calls.read_text(encoding="utf-8").split("\n")[0].strip() if calls.is_file() else None
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("failed=False", done.stdout, "what fails here fails nothing")
        return said, done.stdout

    def test_asked_about_nothing_it_never_goes_near_the_desktop(self):
        self.assertEqual(self.run_function(False, False, 0)[0], None)

    def test_each_switch_is_its_own_word(self):
        self.assertEqual(self.run_function(True, False, 0)[0], "desktop-shortcut make")
        self.assertEqual(self.run_function(False, True, 0)[0], "desktop-shortcut remove")

    def test_what_it_could_not_do_is_said_in_the_lines_the_finish_page_reads(self):
        failed = guiscan.type_body("DesktopShortcut", FLOW)
        taken_line = failed[failed.index('TakenLine = "') + 13:]
        taken_line = taken_line[:taken_line.index('"')]
        failed_line = failed[failed.index('FailedLine = "') + 14:]
        failed_line = failed_line[:failed_line.index('"')]
        self.assertIn(taken_line, self.run_function(True, False, 3)[1])
        self.assertIn(failed_line, self.run_function(True, False, 1)[1])
        self.assertIn(failed_line, self.run_function(False, True, 1)[1])
        self.assertNotIn("[!]", self.run_function(True, False, 0)[1])

    def test_it_runs_after_setup_succeeded_and_never_in_the_uninstall(self):
        self.assertEqual(INSTALL_PS1.count("\n    Set-DesktopShortcut"), 1)
        at = INSTALL_PS1.index("\n    Set-DesktopShortcut")
        self.assertLess(INSTALL_PS1.index("Fail 'Setup did not complete."), at)
        self.assertLess(at, INSTALL_PS1.index("Step 'Checking the installation'"))

    def test_the_switches_are_install_ps1s_and_reach_a_run_outside_another_app(self):
        gate = INSTALL_PS1.index("$outsideCode = Resolve-OutsideRun")
        words = INSTALL_PS1[INSTALL_PS1.index("$outsideSwitches = @("):gate]
        for switch in ("DesktopShortcut", "NoDesktopShortcut"):
            self.assertRegex(INSTALL_PS1, r"param\(\s[\s\S]*\[switch\]\$%s\b" % switch)
            self.assertIn("'%s'" % switch, words)
        self.assertLess(INSTALL_PS1.index("if ($DesktopShortcut -and $NoDesktopShortcut)"), gate,
                        "asking for both stops before anything has happened")

    def test_install_cmd_passes_it_on_and_with_silent_asks_nothing(self):
        code, _, runs = Launcher(self, "Install.cmd").run("-Silent", "-DesktopShortcut", code=0)
        self.assertEqual((code, runs), (0, ["ran: -Silent -DesktopShortcut"]))

    def test_no_update_and_no_pick_passes_it(self):
        for word in ("DesktopShortcut", "desktop-shortcut"):
            self.assertNotIn(word, BOOTSTRAP, "an update with no setup window creates nothing and removes nothing")

    @unittest.skipIf(languages.generated_ko_branch(), "the generated ko branch's GUIDE.md is the Korean guide")
    def test_it_is_documented_beside_silent(self):
        guide = (ROOT / "docs" / "GUIDE.md").read_text(encoding="utf-8")
        silent = guide.index("`-Silent` installs without a question")
        self.assertLess(silent, guide.index("`-DesktopShortcut`"))
        self.assertLess(guide.index("`-DesktopShortcut`"), guide.index("From v0.6.16 an installation also appears"))
        self.assertIn("`-NoDesktopShortcut`", guide)


STUB = r"""
using System;
using System.Diagnostics;
using System.IO;

// Stands for <home>\runtime\python.exe: records what it was asked, then runs the test's own interpreter with the same
// words. Refuses (99) unless its Desktop and its home are folders of the test's own: a probe that lost its variables
// stops here rather than reach the real Desktop.
internal static class Stub
{
    private static int Main()
    {
        string desktop = Environment.GetEnvironmentVariable("CODEX_AUTO_RESUME_DESKTOP") ?? "";
        string home = Environment.GetEnvironmentVariable("CODEX_AUTO_RESUME_PLUGIN_HOME") ?? "";
        string work = Environment.GetEnvironmentVariable("CAR_WORK") ?? "";
        if (work.Length == 0 || !desktop.StartsWith(work, StringComparison.OrdinalIgnoreCase) ||
            !home.StartsWith(work, StringComparison.OrdinalIgnoreCase)) return 99;
        string line = Environment.CommandLine, rest;
        if (line.StartsWith("\""))
        {
            int end = line.IndexOf('"', 1);
            rest = line.Substring(end + 1).TrimStart();
        }
        else
        {
            int space = line.IndexOf(' ');
            rest = space < 0 ? "" : line.Substring(space + 1);
        }
        File.AppendAllText(Environment.GetEnvironmentVariable("CAR_STUB_LOG"), rest + "|" + home + "\r\n");
        var info = new ProcessStartInfo(Environment.GetEnvironmentVariable("CAR_REAL_PYTHON"), rest);
        info.UseShellExecute = false;
        info.CreateNoWindow = true;
        info.RedirectStandardOutput = true;
        info.RedirectStandardError = true;
        using (Process process = Process.Start(info))
        {
            var failure = process.StandardError.ReadToEndAsync();
            string output = process.StandardOutput.ReadToEnd();
            process.WaitForExit();
            Console.Out.Write(output);
            Console.Error.Write(failure.Result);
            return process.ExitCode;
        }
    }
}
"""


def _stub_homes(work: Path) -> dict:
    """Two installations of the test's own: one whose runtime\\python.exe is the stub above (and whose setup script runs
    the repository's), and one with no interpreter at all."""
    source = work / "Stub.cs"
    source.write_text(STUB, encoding="utf-8")
    stub = work / "stub-python.exe"
    done = subprocess.run([str(CSC), "/nologo", "/target:exe", "/out:" + str(stub), str(source)], capture_output=True,
                          encoding="locale", errors="replace", creationflags=NO_WINDOW, timeout=300)
    if done.returncode != 0 or not stub.is_file():
        raise AssertionError("the stand-in interpreter did not compile: " + (done.stdout + done.stderr)[-1500:])
    homes = {}
    for name in ("ok", "bare"):
        home = work / ("home-" + name)
        home.mkdir()
        (home / "CodexAutoResumeSettings.exe").write_bytes(b"MZ")
        homes[name] = home
    (homes["ok"] / "runtime").mkdir()
    shutil.copyfile(stub, homes["ok"] / "runtime" / "python.exe")
    scripts = homes["ok"] / "app" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "plugin_setup.py").write_text(
        "import runpy, sys\nsys.path.insert(0, %r)\nrunpy.run_path(%r, run_name='__main__')\n"
        % (str(ROOT / "src"), str(ROOT / "scripts" / "plugin_setup.py")), encoding="utf-8")
    return homes


FLOW_PROBE = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$any = [Reflection.BindingFlags]'Static,Instance,NonPublic,Public'
$FlowType = $assembly.GetType('CodexAutoResume.InstallerFlow', $true)
$Desktop = $assembly.GetType('CodexAutoResume.DesktopShortcut', $true)
function NewFlow($mode, $installed) {
    $FlowType.GetConstructors($any)[0].Invoke([object[]]@([string]$mode, 'C:\Users\ExampleUser\.codex-auto-resume', 'standard', $installed, '9.9.9'))
}
function Know($flow, $there) { $null = $FlowType.GetMethod('KnowDesktopShortcut', $any).Invoke($flow, [object[]]@([bool]$there)) }
function Field($flow, $name) { $FlowType.GetField($name, $any).GetValue($flow) }
function SetField($flow, $name, $value) { $FlowType.GetField($name, $any).SetValue($flow, $value) }
function Switches($flow, $given) { (@($FlowType.GetMethod('Switches', $any).Invoke($flow, [object[]]@(,[string[]]@($given)))) -join ' ') }
function Asks($flow) { [string]$FlowType.GetMethod('DesktopShortcutChange', $any).Invoke($flow, $null) }
function Offers($flow, $code) { [bool]$FlowType.GetMethod('OffersDesktopShortcut', $any).Invoke($flow, [object[]]@([int]$code)) }
function Case($mode, $installed, $there) {
    $flow = NewFlow $mode $installed
    Know $flow $there
    $flow
}
$out = @{}
$flow = Case 'install' $null $false; $out.first_box = Field $flow 'MakeDesktopShortcut'; $out.first = Switches $flow @(); $out.first_asks = Asks $flow
SetField $flow 'MakeDesktopShortcut' $true; $out.first_ticked = Switches $flow @(); $out.first_ticked_asks = Asks $flow
$flow = Case 'install' 'standard' $true; $out.there_box = Field $flow 'MakeDesktopShortcut'; $out.there = Switches $flow @(); $out.there_asks = Asks $flow
SetField $flow 'MakeDesktopShortcut' $false; $out.there_unticked = Switches $flow @(); $out.there_unticked_asks = Asks $flow
$flow = Case 'install' 'standard' $false; $out.absent_box = Field $flow 'MakeDesktopShortcut'; $out.absent_asks = Asks $flow
SetField $flow 'MakeDesktopShortcut' $true; $out.absent_ticked = Switches $flow @(); $out.absent_ticked_asks = Asks $flow
$flow = Case 'install' 'advanced' $true; SetField $flow 'ChangeEdition' $true; SetField $flow 'MakeDesktopShortcut' $false; $out.edition_unticked = Switches $flow @()
$flow = Case 'update' 'standard' $true; $out.update = Switches $flow @()
$flow = Case 'uninstall' 'standard' $true; $out.uninstall = Switches $flow @()
$flow = NewFlow 'install' 'standard'; SetField $flow 'Maintaining' $true; Know $flow $true; $null = $FlowType.GetMethod('Choose', $any).Invoke($flow, [object[]]@($true)); $out.removed = Switches $flow @()
$flow = Case 'install' $null $false
$out.given_on = Switches $flow @('-DesktopShortcut')
$out.given_off = Switches $flow @('-NoDesktopShortcut')
$out.offers_install = Offers $flow 0
$out.offers_failed = Offers $flow 1
$out.offers_refused = Offers $flow 14
$out.offers_still_running = Offers $flow -2
$out.offers_not_started = Offers $flow -1
$out.offers_update = Offers (Case 'update' 'standard' $true) 0
$flow = Case 'update' 'standard' $true; SetField $flow 'Another' $true; $out.offers_pick = Offers $flow 0
$out.offers_uninstall = Offers (Case 'uninstall' 'standard' $true) 0
$flow = NewFlow 'install' 'standard'; SetField $flow 'Maintaining' $true; $out.offers_repair = Offers $flow 0
$inside = $Desktop.GetMethod('Inside', $any)
$out.inside = @(
    $inside.Invoke($null, [object[]]@('C:\a\home\x.exe', 'C:\a\home')),
    $inside.Invoke($null, [object[]]@('c:\A\HOME\x.exe', 'C:\a\home\')),
    $inside.Invoke($null, [object[]]@('C:\a\home-other\x.exe', 'C:\a\home')),
    $inside.Invoke($null, [object[]]@('C:\a\home\..\x.exe', 'C:\a\home')),
    $inside.Invoke($null, [object[]]@('', 'C:\a\home')))
$ours = $Desktop.GetMethod('OursAt', $any)
$out.ours = @($ours.Invoke($null, [object[]]@($env:CAR_HOME)), $ours.Invoke($null, [object[]]@($env:CAR_OTHER_HOME)))
$env:CODEX_AUTO_RESUME_DESKTOP = $env:CAR_EMPTY
$out.ours_absent = $ours.Invoke($null, [object[]]@($env:CAR_HOME))
$env:CODEX_AUTO_RESUME_DESKTOP = $env:CAR_GARBAGE
$out.ours_garbage = $ours.Invoke($null, [object[]]@($env:CAR_HOME))
[Environment]::SetEnvironmentVariable('CODEX_AUTO_RESUME_DESKTOP', $null)
$out.folder_is_windows = ($Desktop.GetMethod('Folder', $any).Invoke($null, $null) -ceq [Environment]::GetFolderPath('DesktopDirectory'))
# The change itself, on a Desktop and a home of the test's own: the installed engine is asked, and answers by its code.
$change = $Desktop.GetMethod('Change', $any)
function Ask($place, $make) {
    $arguments = [object[]]@([string]$place, [bool]$make, $null)
    $code = $change.Invoke($null, $arguments)
    @($code, [string]$arguments[2])
}
$out.change_nowhere = (Ask $env:CAR_BARE $true)[0]
$env:CODEX_AUTO_RESUME_DESKTOP = $env:CAR_MAKE_DESKTOP
$link = Join-Path $env:CAR_MAKE_DESKTOP 'Codex Auto Resume.lnk'
$out.change_made = (Ask $env:CAR_STUB_HOME $true)[0]
$out.change_made_there = Test-Path -LiteralPath $link
$out.change_removed = (Ask $env:CAR_STUB_HOME $false)[0]
$out.change_removed_there = Test-Path -LiteralPath $link
$out.change_removed_again = (Ask $env:CAR_STUB_HOME $false)[0]
$shell = New-Object -ComObject WScript.Shell
$foreign = $shell.CreateShortcut($link)
$foreign.TargetPath = $env:CAR_FOREIGN
$foreign.Save()
$out.change_taken = (Ask $env:CAR_STUB_HOME $true)[0]
$out.change_taken_kept = ($shell.CreateShortcut($link).TargetPath -ceq $env:CAR_FOREIGN)
$out.change_taken_said = (Ask $env:CAR_STUB_HOME $true)[1]
$out.change_foreign_remove = (Ask $env:CAR_STUB_HOME $false)[0]
$out.change_foreign_remove_kept = ($shell.CreateShortcut($link).TargetPath -ceq $env:CAR_FOREIGN)
$out | ConvertTo-Json -Depth 3 -Compress
"""

WINDOW_PROBE = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
Add-Type -AssemblyName System.Windows.Forms
# A probe that hosts a window never shows .NET's unhandled-exception box on the desktop: it ends non-zero instead.
[System.Windows.Forms.Application]::SetUnhandledExceptionMode('ThrowException')
trap { [Console]::Error.WriteLine(($_ | Out-String)); exit 1 }
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$any = [Reflection.BindingFlags]'Static,Instance,NonPublic,Public'
function T($name) { $assembly.GetType('CodexAutoResume.' + $name, $true) }
$FlowType = T 'InstallerFlow'
$catalog = (T 'Json').GetMethod('Parse', $any).Invoke($null, [object[]]@([IO.File]::ReadAllText($env:CAR_CATALOG, [Text.Encoding]::UTF8)))
$words = (T 'InstallerWords').GetConstructors($any)[0].Invoke([object[]]@($catalog, 'en'))
function Desktop($name) { Join-Path $env:CAR_WORK ('d-' + $name) }
function NewFlow($mode, $installed, $place) {
    $FlowType.GetConstructors($any)[0].Invoke([object[]]@([string]$mode, [string]$place, 'standard', $installed, '9.9.9'))
}
function NewWindow($flow) { (T 'InstallerWindow').GetConstructors($any)[0].Invoke([object[]]@($flow, $words, $null, $null, $null, $null)) }
function CallOn($object, $name, $arguments) { $object.GetType().GetMethod($name, $any).Invoke($object, [object[]]$arguments) }
function Rows($window, $kind) {
    $found = @()
    foreach ($row in @(CallOn $window 'ShownRows' @())) { if ($row.GetType().Name -ceq $kind) { $found += $row } }
    $found
}
function Boxes($window) {
    $found = @()
    foreach ($row in @(Rows $window 'SoftCheck')) {
        if ($row.Text -ceq $env:CAR_LABEL) { $found += (@('off', 'on')[[int][bool]$row.Checked] + ':' + @('switch', 'box')[[int][bool]$row.GetType().GetProperty('Box', $any).GetValue($row, $null)]) }
    }
    $found -join ','
}
function Callouts($window) {
    $found = @()
    foreach ($row in @(Rows $window 'SoftCallout')) { $found += [string]$row.AccessibleName }
    $found -join ' | '
}
function Says($window) {
    $found = @()
    foreach ($row in @(Rows $window 'WrapLabel')) { $found += [string]$row.Text }
    $found
}
function Pump($window, $limit) {
    $clock = [Diagnostics.Stopwatch]::StartNew()
    while (-not $window.IsDisposed -and (CallOn $window 'get_Running' @()) -and $clock.ElapsedMilliseconds -lt $limit) {
        [System.Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 25
    }
    for ($each = 0; $each -lt 8; $each++) { [System.Windows.Forms.Application]::DoEvents() }
}
function Calls() { if (Test-Path -LiteralPath $env:CAR_STUB_LOG) { @(Get-Content -LiteralPath $env:CAR_STUB_LOG).Count } else { 0 } }
function LinkOf($desktop) { Join-Path $desktop 'Codex Auto Resume.lnk' }
# .NET, never Get-FileHash: that cmdlet fails to resolve under the CI runner's PSModulePath.
function Digest($path) { if (-not (Test-Path -LiteralPath $path)) { return '' }
    $sha = [Security.Cryptography.SHA256]::Create()
    try { ([BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes($path))) -replace '-', '') } finally { $sha.Dispose() } }

# One run of the window to its Finish page, then the Finish button once the box is set: `tick` is $true, $false or $null
# (left as it is). The window is built and never shown; its worker's answer is pumped in.
function Run($name, $mode, $installed, $place, $tick, [switch]$maintaining) {
    $env:CODEX_AUTO_RESUME_DESKTOP = Desktop $name
    $flow = NewFlow $mode $installed $place
    if ($maintaining) { $FlowType.GetField('Maintaining', $any).SetValue($flow, $true) }
    $window = NewWindow $flow
    $null = CallOn $window 'Finished' @([int]0, '')
    $null = $window.Handle
    $r = @{}
    $r.page = CallOn $window 'get_Page' @()
    $r.box = Boxes $window
    if ($null -ne $tick) {
        foreach ($row in @(Rows $window 'SoftCheck')) { if ($row.Text -ceq $env:CAR_LABEL) { $row.Checked = [bool]$tick } }
    }
    $calls = Calls
    $before = Digest (LinkOf (Desktop $name))
    $null = CallOn $window 'Forward' @()
    Pump $window 120000
    $r.closed = [bool]$window.IsDisposed
    $r.calls = (Calls) - $calls
    $r.there = Test-Path -LiteralPath (LinkOf (Desktop $name))
    $r.changed = ((Digest (LinkOf (Desktop $name))) -cne $before)
    if (-not $r.closed) {
        $r.callouts = Callouts $window
        $r.log = [string](CallOn $window 'get_Log' @())
        $r.box_after = Boxes $window
        $r.page_after = CallOn $window 'get_Page' @()
        $null = CallOn $window 'Forward' @()
        Pump $window 120000
        $r.closed_next = [bool]$window.IsDisposed
        $r.calls_next = (Calls) - $calls - $r.calls
        if (-not $window.IsDisposed) { $window.Dispose() }
    }
    $r
}

$out = @{}

# The pages before the run: no box on Options, none on Maintain, whichever way it goes.
$env:CODEX_AUTO_RESUME_DESKTOP = Desktop 'first-keep'
$window = NewWindow (NewFlow 'install' $null $env:CAR_HOME_OK)
foreach ($page in @('welcome', 'options')) { $null = CallOn $window 'ShowPage' @($page); $out['first_' + $page] = Boxes $window }
$window = NewWindow (NewFlow 'install' 'standard' $env:CAR_HOME_OK)
$null = CallOn $window 'ShowPage' @('options'); $out.upgrade_options = Boxes $window
$flow = NewFlow 'install' 'standard' $env:CAR_HOME_OK; $FlowType.GetField('Maintaining', $any).SetValue($flow, $true)
$window = NewWindow $flow
$null = CallOn $window 'ShowPage' @('maintain'); $out.maintain = Boxes $window
$width = 480
$out.repair_height = CallOn $window 'Arrange' @([int]$width)
$null = $FlowType.GetMethod('Choose', $any).Invoke($flow, [object[]]@($true))
$out.remove_height = CallOn $window 'Arrange' @([int]$width)
$out.remove = Boxes $window
$null = CallOn $window 'ShowPage' @('confirm'); $out.confirm = Boxes $window
$window = NewWindow (NewFlow 'update' 'standard' $env:CAR_HOME_OK)
$null = CallOn $window 'ShowPage' @('notes'); $out.notes = Boxes $window

# The uninstall page says the shortcut goes only where one of ours is there.
$flow = NewFlow 'uninstall' 'standard' 'C:\Users\ExampleUser\.codex-auto-resume'
$window = NewWindow $flow
$null = CallOn $window 'ShowPage' @('confirm'); $out.confirm_absent = Says $window
$null = $FlowType.GetMethod('KnowDesktopShortcut', $any).Invoke($flow, [object[]]@($true))
$window = NewWindow $flow
$null = CallOn $window 'ShowPage' @('confirm'); $out.confirm_there = Says $window

# The Finish page: the box on a success, not on anything else.
foreach ($case in @(@('failed', 1), @('refused', 14), @('still', -2), @('notstarted', -1))) {
    $env:CODEX_AUTO_RESUME_DESKTOP = Desktop 'first-keep'
    $window = NewWindow (NewFlow 'install' $null $env:CAR_HOME_OK)
    $null = CallOn $window 'Finished' @([int]$case[1], '  [x]  Something did not work.')
    $out['finish_' + $case[0]] = Boxes $window
}
$env:CODEX_AUTO_RESUME_DESKTOP = Desktop 'first-keep'
$window = NewWindow (NewFlow 'uninstall' 'standard' $env:CAR_HOME_OK)
$null = CallOn $window 'Finished' @([int]0, '')
$out.finish_uninstall = Boxes $window
$flow = NewFlow 'update' 'standard' $env:CAR_HOME_OK; $FlowType.GetField('Another', $any).SetValue($flow, $true)
$window = NewWindow $flow
$null = CallOn $window 'Finished' @([int]0, '')
$out.finish_pick = Boxes $window

# What the installer printed of the shortcut when the command line asked for it (-DesktopShortcut) is still said.
$Lines = T 'DesktopShortcut'
$failed = '  ' + $Lines.GetField('FailedLine', $any).GetValue($null) + '. Everything else went on as usual.'
$taken = '  ' + $Lines.GetField('TakenLine', $any).GetValue($null) + '. It was left as it is, and none was made.'
foreach ($case in @(@('failed', $failed, 0), @('taken', $taken, 0), @('quiet', '  [ok] The shortcut on the Desktop is there', 0), @('failed_run', $failed, 1))) {
    $window = NewWindow (NewFlow 'install' $null $env:CAR_HOME_OK)
    $null = CallOn $window 'Finished' @([int]$case[2], [string]$case[1])
    $out['said_' + $case[0]] = Callouts $window
    $out['said_' + $case[0] + '_log'] = [bool]((CallOn $window 'get_Log' @()).Contains($case[1].Trim()))
}

# The Finish button, on Desktops and installations of the test's own.
$out.first_keep = Run 'first-keep' 'install' $null $env:CAR_HOME_OK $null
$out.first_tick = Run 'first-tick' 'install' $null $env:CAR_HOME_OK $true
$out.ours_keep = Run 'ours-keep' 'install' 'standard' $env:CAR_HOME_OK $null
$out.ours_untick = Run 'ours-untick' 'install' 'standard' $env:CAR_HOME_OK $false
$out.repair = Run 'repair' 'install' 'standard' $env:CAR_HOME_OK $null -maintaining
$out.update_tick = Run 'update-tick' 'update' 'standard' $env:CAR_HOME_OK $true
$shell = New-Object -ComObject WScript.Shell
$theirs = $shell.CreateShortcut((LinkOf (Desktop 'taken')))
$theirs.TargetPath = $env:CAR_FOREIGN
$theirs.Save()
$out.taken = Run 'taken' 'install' $null $env:CAR_HOME_OK $true
$out.taken_target = $shell.CreateShortcut((LinkOf (Desktop 'taken'))).TargetPath
$out.bare = Run 'bare' 'install' $null $env:CAR_HOME_BARE $true
$out | ConvertTo-Json -Depth 4 -Compress
"""


def _make_ours(home: Path, desktop: Path) -> None:
    """A shortcut of ours on a Desktop of the test's own, as the engine writes one."""
    with patch.dict(os.environ, {shortcut.DESKTOP_ENV: str(desktop)}):
        shortcut.install_desktop(home, target=home / "CodexAutoResumeSettings.exe")


@unittest.skipUnless(WINDOWS and CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class FlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="desktop-flow-"))
        exe = _build(cls.work)
        desktop = cls.work / "Desktop"
        desktop.mkdir()
        home = cls.work / "home"
        home.mkdir()
        (home / "CodexAutoResumeSettings.exe").write_bytes(b"MZ")
        (cls.work / "home-other").mkdir()
        (cls.work / "empty").mkdir()
        (cls.work / "garbage").mkdir()
        (cls.work / "garbage" / shortcut.SHORTCUT_NAME).write_bytes(b"not a shortcut")
        (cls.work / "make").mkdir()
        homes = _stub_homes(cls.work)
        with patch.dict(os.environ, {shortcut.DESKTOP_ENV: str(desktop), "APPDATA": str(cls.work / "AppData")}):
            shortcut.install_desktop(home, target=home / "CodexAutoResumeSettings.exe")
        environment = {key: value for key, value in os.environ.items()}
        environment.pop(shortcut.DESKTOP_ENV, None)
        cls.log = cls.work / "stub.log"
        with patch.dict(os.environ, environment, clear=True):
            cls.result = _powershell(FLOW_PROBE, cls.work, 600, CAR_EXE=str(exe), CAR_HOME=str(home),
                                     CAR_OTHER_HOME=str(cls.work / "home-other"), CAR_EMPTY=str(cls.work / "empty"),
                                     CAR_GARBAGE=str(cls.work / "garbage"), CODEX_AUTO_RESUME_DESKTOP=str(desktop),
                                     CAR_BARE=str(homes["bare"]), CAR_STUB_HOME=str(homes["ok"]),
                                     CAR_MAKE_DESKTOP=str(cls.work / "make"), CAR_FOREIGN=str(cls.work / "theirs.exe"),
                                     CAR_WORK=str(cls.work), CAR_STUB_LOG=str(cls.log), CAR_REAL_PYTHON=sys.executable,
                                     APPDATA=str(cls.work / "AppData"))
        cls.answer = json.loads(cls.result.stdout) if cls.result.returncode == 0 and cls.result.stdout.strip() else {}
        cls.homes = homes

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-3000:])

    def test_the_box_starts_as_what_is_true_and_the_switches_no_longer_carry_it(self):
        self.assertIs(self.answer["first_box"], False)
        self.assertIs(self.answer["there_box"], True)
        self.assertIs(self.answer["absent_box"], False)
        for case in ("first", "first_ticked", "there", "there_unticked", "absent_ticked", "update"):
            self.assertEqual(self.answer[case], "-Silent", "the box is the Finish page's: the installer is not told")
        self.assertEqual(self.answer["edition_unticked"], "-AllowEditionChange -Silent")
        self.assertEqual(self.answer["uninstall"], "-Uninstall -Silent")
        self.assertEqual(self.answer["removed"], "-Uninstall -Silent", "Remove on the Maintain page")

    def test_the_finish_button_asks_only_for_a_change(self):
        self.assertEqual(self.answer["first_asks"], "", "left off where there is none: nothing")
        self.assertEqual(self.answer["first_ticked_asks"], "make")
        self.assertEqual(self.answer["there_asks"], "", "left as it was, a repair writes nothing")
        self.assertEqual(self.answer["there_unticked_asks"], "remove")
        self.assertEqual(self.answer["absent_asks"], "")
        self.assertEqual(self.answer["absent_ticked_asks"], "make")

    def test_a_switch_the_command_line_was_given_is_passed_on_once_as_it_was(self):
        self.assertEqual(self.answer["given_on"], "-DesktopShortcut -Silent")
        self.assertEqual(self.answer["given_off"], "-NoDesktopShortcut -Silent")

    def test_only_a_run_that_succeeded_and_is_not_an_uninstall_or_a_pick_has_the_box(self):
        for case in ("install", "update", "repair"):
            self.assertIs(self.answer["offers_" + case], True, case)
        for case in ("failed", "refused", "still_running", "not_started", "pick", "uninstall"):
            self.assertIs(self.answer["offers_" + case], False, case)

    def test_inside_means_inside(self):
        self.assertEqual(self.answer["inside"], [True, True, False, False, False])

    def test_the_window_reads_a_real_shortcut_as_the_engine_wrote_it(self):
        self.assertEqual(self.answer["ours"], [True, False], "inside this home, and not inside another")
        self.assertIs(self.answer["ours_absent"], False)
        self.assertIs(self.answer["ours_garbage"], False)

    def test_with_no_seam_set_its_folder_is_the_one_windows_names(self):
        self.assertIs(self.answer["folder_is_windows"], True)

    def test_the_change_asks_the_installed_engine_and_is_told_by_its_code(self):
        self.assertEqual(self.answer["change_nowhere"], 1, "no interpreter in the installation: not changed")
        self.assertEqual(self.answer["change_made"], 0)
        self.assertIs(self.answer["change_made_there"], True)
        self.assertEqual(self.answer["change_removed"], 0)
        self.assertIs(self.answer["change_removed_there"], False)
        self.assertEqual(self.answer["change_removed_again"], 0, "nothing there to remove is no failure")
        self.assertEqual(self.answer["change_taken"], 3, "another shortcut has the name")
        self.assertIs(self.answer["change_taken_kept"], True)
        self.assertTrue(self.answer["change_taken_said"], "and what the engine said comes back for the log")
        self.assertEqual(self.answer["change_foreign_remove"], 0)
        self.assertIs(self.answer["change_foreign_remove_kept"], True, "someone else's is never removed")

    def test_the_interpreter_is_started_the_way_every_other_one_is(self):
        lines = self.log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 6, lines)
        for line in lines:
            words, home = line.rsplit("|", 1)
            self.assertTrue(words.startswith('-X disable-remote-debug "'), words)
            self.assertTrue(words.endswith('plugin_setup.py" desktop-shortcut make') or
                            words.endswith('plugin_setup.py" desktop-shortcut remove'), words)
            self.assertEqual(os.path.normcase(home), os.path.normcase(str(self.homes["ok"])), "the installation it belongs to")
        body = guiscan.type_body("DesktopShortcut", FLOW)
        self.assertIn("info.CreateNoWindow = true;", body)
        self.assertIn("info.UseShellExecute = false;", body)
        self.assertNotIn("pythonw", body)


@unittest.skipUnless(WINDOWS and CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class WindowTests(unittest.TestCase):
    """The window built and never shown, as its layout audit is; its Finish button pressed against Desktops and
    installations of the test's own, the worker's answer pumped in."""

    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="desktop-window-"))
        exe = _build(cls.work)
        homes = _stub_homes(cls.work)
        for name in ("first-keep", "first-tick", "ours-keep", "ours-untick", "repair", "update-tick", "taken", "bare"):
            (cls.work / ("d-" + name)).mkdir()
        for name in ("ours-keep", "ours-untick", "repair"):
            _make_ours(homes["ok"], cls.work / ("d-" + name))
        cls.ours_target = homes["ok"]
        cls.log = cls.work / "stub.log"
        cls.result = _powershell(WINDOW_PROBE, cls.work, 900, CAR_EXE=str(exe), CAR_LABEL=LABEL,
                                 CAR_CATALOG=str(ROOT / "src" / "codex_auto_resume" / "locales" / "en.json"),
                                 CAR_HOME_OK=str(homes["ok"]), CAR_HOME_BARE=str(homes["bare"]),
                                 CAR_WORK=str(cls.work), CAR_STUB_LOG=str(cls.log), CAR_REAL_PYTHON=sys.executable,
                                 CAR_FOREIGN=str(cls.work / "theirs.exe"), APPDATA=str(cls.work / "AppData"),
                                 CODEX_AUTO_RESUME_DESKTOP=str(cls.work / "d-first-keep"))
        cls.answer = json.loads(cls.result.stdout) if cls.result.returncode == 0 and cls.result.stdout.strip() else {}
        cls.homes = homes

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-3000:])

    def test_the_options_and_maintain_pages_have_no_box(self):
        for case in ("first_welcome", "first_options", "upgrade_options", "maintain", "remove", "confirm", "notes"):
            self.assertEqual(self.answer[case], "", case)
        self.assertEqual(self.answer["remove_height"], self.answer["repair_height"],
                         "the Maintain page holds no room for it, whichever way is chosen")

    def test_the_finish_page_of_a_success_has_the_soft_box_off_where_there_is_no_shortcut(self):
        self.assertEqual(self.answer["first_keep"]["page"], "finish")
        self.assertEqual(self.answer["first_keep"]["box"], "off:box", "one box, not ticked, a box and not a switch")

    def test_it_starts_ticked_where_one_of_ours_is_there_on_a_repair_and_an_update(self):
        self.assertEqual(self.answer["ours_keep"]["box"], "on:box")
        self.assertEqual(self.answer["repair"]["box"], "on:box")
        self.assertEqual(self.answer["update_tick"]["box"], "off:box", "the Dashboard's update has it too")

    def test_no_box_after_a_run_that_failed_an_uninstall_or_a_pick(self):
        for case in ("failed", "refused", "still", "notstarted", "uninstall", "pick"):
            self.assertEqual(self.answer["finish_" + case], "", case)

    def test_ticked_on_finish_it_makes_ours_and_closes(self):
        run = self.answer["first_tick"]
        self.assertIs(run["closed"], True)
        self.assertEqual((run["calls"], run["there"]), (1, True))
        self.assertIs(run["changed"], True)

    def test_unticked_on_finish_it_removes_ours_and_closes(self):
        run = self.answer["ours_untick"]
        self.assertIs(run["closed"], True)
        self.assertEqual((run["calls"], run["there"]), (1, False))

    def test_the_dashboards_update_makes_one_when_it_is_ticked(self):
        run = self.answer["update_tick"]
        self.assertIs(run["closed"], True)
        self.assertEqual((run["calls"], run["there"]), (1, True))

    def test_left_as_it_was_nothing_is_asked_and_nothing_changes(self):
        for case, there in (("first_keep", False), ("ours_keep", True), ("repair", True)):
            with self.subTest(case):
                run = self.answer[case]
                self.assertIs(run["closed"], True)
                self.assertEqual((run["calls"], run["there"], run["changed"]), (0, there, False))

    def test_a_shortcut_that_is_not_ours_is_said_in_one_line_and_the_window_stays_until_the_next_finish(self):
        run = self.answer["taken"]
        self.assertIs(run["closed"], False)
        self.assertEqual(run["callouts"], ENGLISH["installer.done.desktop_taken"])
        self.assertIn(guiscan.type_body("DesktopShortcut", FLOW).split('TakenLine = "')[1].split('"')[0], run["log"])
        self.assertEqual(run["page_after"], "finish")
        self.assertEqual(run["box_after"], "on:box", "the page still shows what was asked")
        self.assertEqual((run["calls"], run["calls_next"]), (1, 0), "the next Finish does not ask for the same again")
        self.assertIs(run["closed_next"], True)
        self.assertEqual(Path(self.answer["taken_target"]).name, "theirs.exe", "and theirs was left as it is")

    def test_an_installation_that_cannot_be_asked_says_so_and_stays_open_the_same_way(self):
        run = self.answer["bare"]
        self.assertIs(run["closed"], False)
        self.assertEqual(run["callouts"], ENGLISH["installer.done.desktop_failed"])
        self.assertIn(guiscan.type_body("DesktopShortcut", FLOW).split('FailedLine = "')[1].split('"')[0], run["log"])
        self.assertEqual((run["calls"], run["calls_next"]), (0, 0))
        self.assertIs(run["closed_next"], True)

    def test_no_dialog_is_ever_asked_for(self):
        body = guiscan.member_body("InstallerWindow", "Finish")
        changed = guiscan.member_body("InstallerWindow", "Changed")
        for text in (body, changed):
            self.assertNotIn("MessageBox", text)
            self.assertNotIn("ShowDialog", text)

    def test_the_uninstall_says_it_goes_only_where_one_of_ours_is_there(self):
        said = ENGLISH["installer.uninstall.desktop_shortcut"]
        self.assertIn(said, self.answer["confirm_there"])
        self.assertNotIn(said, self.answer["confirm_absent"])

    def test_the_uninstall_from_settings_apps_knows_as_the_setup_window_does(self):
        remove = (ROOT / "gui" / "SettingsRemove.cs").read_text(encoding="utf-8")
        self.assertIn("flow.KnowDesktopShortcut(DesktopShortcut.OursAt(home));", remove)
        setup = (ROOT / "build" / "setup" / "SetupWindow.cs").read_text(encoding="utf-8")
        self.assertIn("flow.KnowDesktopShortcut(DesktopShortcut.OursAt(home));", setup)

    def test_what_the_installer_printed_of_it_is_still_said_on_the_finish_page(self):
        self.assertEqual(self.answer["said_failed"], ENGLISH["installer.done.desktop_failed"])
        self.assertEqual(self.answer["said_taken"], ENGLISH["installer.done.desktop_taken"])
        self.assertEqual(self.answer["said_quiet"], "")
        self.assertEqual(self.answer["said_failed_run"], "", "a run that failed has more to say than this")
        for case in ("said_failed_log", "said_taken_log"):
            self.assertIs(self.answer[case], True, "and the log has the line")


class SourceTests(unittest.TestCase):
    """Where the box stands, read from the sources: the same on a machine that cannot compile them."""

    WINDOW = (ROOT / "gui" / "InstallerWindow.cs").read_text(encoding="utf-8")

    def test_the_word_is_a_finish_key_in_every_language_and_not_an_options_key(self):
        locales = sorted(LOCALES.glob("*.json"))
        self.assertEqual(len(locales), 19)
        for path in locales:
            with self.subTest(path.stem):
                catalog = json.loads(path.read_text(encoding="utf-8"))
                self.assertIn("installer.done.desktop_shortcut", catalog)
                self.assertNotIn("installer.options.desktop_shortcut", catalog)
        self.assertEqual(LABEL, "Add a shortcut to the desktop")

    def test_the_options_and_maintain_pages_do_not_build_it_and_the_finish_page_does(self):
        for member in ("BuildOptions", "BuildMaintain", "BuildConfirm"):
            self.assertNotIn("DesktopChoice", guiscan.member_body("InstallerWindow", member), member)
        self.assertIn("DesktopChoice", guiscan.member_body("InstallerWindow", "BuildFinish"))
        self.assertIn("flow.OffersDesktopShortcut(code)", guiscan.member_body("InstallerWindow", "BuildFinish"))

    def test_only_the_finish_button_changes_the_desktop(self):
        self.assertEqual(self.WINDOW.count("DesktopShortcut.Change("), 1)
        self.assertIn("DesktopShortcut.Change(", guiscan.member_body("InstallerWindow", "Finish"))
        self.assertNotIn("DesktopShortcut.Change(", guiscan.member_body("InstallerWindow", "Forward"))
        self.assertIn("Finish(); return;", guiscan.member_body("InstallerWindow", "Forward"))
        self.assertNotIn("Desktop", FLOW[FLOW.index("internal List<string> Switches"):FLOW.index("private static bool IsAnswered")])


if __name__ == "__main__":
    unittest.main()
