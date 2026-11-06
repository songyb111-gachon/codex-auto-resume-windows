"""The shortcut on the Desktop the setup window offers, off unless a person ticks it (the owner, 2026-11-02 and 11-05).

The Desktop is the person's, not a singleton of ours, so what is held here is mostly what it may not do:

* WriterTests - the real shortcut.py against a Desktop of the test's own: the same thing as the Start Menu entry, and
  only a shortcut at the exact name with its target inside this installation is ever replaced or removed.
* WindowsDesktopTests - the folder is the one Windows names, not one under %USERPROFILE%. Reads only.
* EngineTests - the core's install leaves the Desktop alone, its uninstall takes ours whichever answer was given about
  the data, and the installer's setup command says what became of it by its exit code.
* ScriptTests - install.ps1 asks about the Desktop only when it was told to, and what fails there fails nothing.
* FlowTests and WindowTests - the box, the switches it becomes, and what the Finish page says.

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
LABEL = ENGLISH["installer.options.desktop_shortcut"]

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
                                  capture_output=True, text=True, timeout=120, creationflags=NO_WINDOW,
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
function Know($flow, $there, $given) { $null = $FlowType.GetMethod('KnowDesktopShortcut', $any).Invoke($flow, [object[]]@([bool]$there, [string[]]@($given))) }
function Field($flow, $name) { $FlowType.GetField($name, $any).GetValue($flow) }
function SetField($flow, $name, $value) { $FlowType.GetField($name, $any).SetValue($flow, $value) }
function Switches($flow, $given) { (@($FlowType.GetMethod('Switches', $any).Invoke($flow, [object[]]@(,[string[]]@($given)))) -join ' ') }
function Case($mode, $installed, $there, $given) {
    $flow = NewFlow $mode $installed
    Know $flow $there $given
    $flow
}
$out = @{}
$flow = Case 'install' $null $false @(); $out.first_box = Field $flow 'MakeDesktopShortcut'; $out.first = Switches $flow @()
SetField $flow 'MakeDesktopShortcut' $true; $out.first_ticked = Switches $flow @()
$flow = Case 'install' 'standard' $true @(); $out.there_box = Field $flow 'MakeDesktopShortcut'; $out.there = Switches $flow @()
SetField $flow 'MakeDesktopShortcut' $false; $out.there_unticked = Switches $flow @()
$flow = Case 'install' 'standard' $false @(); $out.absent_box = Field $flow 'MakeDesktopShortcut'; $out.absent = Switches $flow @()
SetField $flow 'MakeDesktopShortcut' $true; $out.absent_ticked = Switches $flow @()
$flow = Case 'install' 'advanced' $true @(); SetField $flow 'ChangeEdition' $true; SetField $flow 'MakeDesktopShortcut' $false; $out.edition_unticked = Switches $flow @()
$flow = Case 'update' 'standard' $true @(); $out.update = Switches $flow @()
$flow = Case 'uninstall' 'standard' $true @(); $out.uninstall = Switches $flow @()
$flow = NewFlow 'install' 'standard'; SetField $flow 'Maintaining' $true; Know $flow $true @(); $null = $FlowType.GetMethod('Choose', $any).Invoke($flow, [object[]]@($true)); $out.removed = Switches $flow @()
$flow = Case 'install' $null $false @('-DesktopShortcut'); $out.given_on_box = Field $flow 'MakeDesktopShortcut'; $out.given_on = Switches $flow @('-DesktopShortcut')
$flow = Case 'install' 'standard' $true @('-NoDesktopShortcut'); $out.given_off_box = Field $flow 'MakeDesktopShortcut'; $out.given_off = Switches $flow @('-NoDesktopShortcut')
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
$out | ConvertTo-Json -Depth 3 -Compress
"""

WINDOW_PROBE = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$any = [Reflection.BindingFlags]'Static,Instance,NonPublic,Public'
function T($name) { $assembly.GetType('CodexAutoResume.' + $name, $true) }
$FlowType = T 'InstallerFlow'
$catalog = (T 'Json').GetMethod('Parse', $any).Invoke($null, [object[]]@([IO.File]::ReadAllText($env:CAR_CATALOG, [Text.Encoding]::UTF8)))
$words = (T 'InstallerWords').GetConstructors($any)[0].Invoke([object[]]@($catalog, 'en'))
function NewFlow($installed, $there) {
    $flow = $FlowType.GetConstructors($any)[0].Invoke([object[]]@('install', 'C:\Users\ExampleUser\.codex-auto-resume', 'standard', $installed, '9.9.9'))
    $null = $FlowType.GetMethod('KnowDesktopShortcut', $any).Invoke($flow, [object[]]@([bool]$there, [string[]]@()))
    $flow
}
function NewWindow($flow) { (T 'InstallerWindow').GetConstructors($any)[0].Invoke([object[]]@($flow, $words, $null, $null, $null, $null)) }
function CallOn($object, $name, $arguments) { $object.GetType().GetMethod($name, $any).Invoke($object, [object[]]$arguments) }
function Boxes($window) {
    $found = @()
    foreach ($row in @(CallOn $window 'ShownRows' @())) {
        if ($row.GetType().Name -ceq 'SoftCheck' -and $row.Text -ceq $env:CAR_LABEL) {
            $found += ,@([bool]$row.Checked, [bool]$row.GetType().GetProperty('Box', $any).GetValue($row, $null))
        }
    }
    ,$found
}
function Callouts($window) {
    $found = @()
    foreach ($row in @(CallOn $window 'ShownRows' @())) { if ($row.GetType().Name -ceq 'SoftCallout') { $found += [string]$row.AccessibleName } }
    ,$found
}
$out = @{}
$window = NewWindow (NewFlow $null $false)
$null = CallOn $window 'ShowPage' @('options'); $out.first = Boxes $window
$window = NewWindow (NewFlow 'standard' $true)
$null = CallOn $window 'ShowPage' @('options'); $out.upgrade_there = Boxes $window
$flow = NewFlow 'standard' $true; $FlowType.GetField('Maintaining', $any).SetValue($flow, $true)
$window = NewWindow $flow
$null = CallOn $window 'ShowPage' @('maintain'); $out.repair = Boxes $window
$width = 480
$out.repair_height = CallOn $window 'Arrange' @([int]$width)
$null = $FlowType.GetMethod('Choose', $any).Invoke($flow, [object[]]@($true))
$out.remove_height = CallOn $window 'Arrange' @([int]$width)
$out.remove = Boxes $window
function Says($window) {
    $found = @()
    foreach ($row in @(CallOn $window 'ShownRows' @())) { if ($row.GetType().Name -ceq 'WrapLabel') { $found += [string]$row.Text } }
    ,$found
}
$flow = $FlowType.GetConstructors($any)[0].Invoke([object[]]@('uninstall', 'C:\Users\ExampleUser\.codex-auto-resume', 'standard', 'standard', '9.9.9'))
$window = NewWindow $flow
$null = CallOn $window 'ShowPage' @('confirm'); $out.confirm_absent = Says $window
$null = $FlowType.GetMethod('KnowDesktopShortcut', $any).Invoke($flow, [object[]]@($true, [string[]]@()))
$window = NewWindow $flow
$null = CallOn $window 'ShowPage' @('confirm'); $out.confirm_there = Says $window
$Lines = T 'DesktopShortcut'
$failed = '  ' + $Lines.GetField('FailedLine', $any).GetValue($null) + '. Everything else went on as usual.'
$taken = '  ' + $Lines.GetField('TakenLine', $any).GetValue($null) + '. It was left as it is, and none was made.'
foreach ($case in @(@('failed', $failed, 0), @('taken', $taken, 0), @('quiet', '  [ok] The shortcut on the Desktop is there', 0), @('failed_run', $failed, 1))) {
    $window = NewWindow (NewFlow $null $false)
    $null = CallOn $window 'Finished' @([int]$case[2], [string]$case[1])
    $out[$case[0]] = Callouts $window
    $out[$case[0] + '_log'] = [bool]((CallOn $window 'get_Log' @()).Contains($case[1].Trim()))
}
$out | ConvertTo-Json -Depth 4 -Compress
"""


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
        with patch.dict(os.environ, {shortcut.DESKTOP_ENV: str(desktop), "APPDATA": str(cls.work / "AppData")}):
            shortcut.install_desktop(home, target=home / "CodexAutoResumeSettings.exe")
        environment = {key: value for key, value in os.environ.items()}
        environment.pop(shortcut.DESKTOP_ENV, None)
        with patch.dict(os.environ, environment, clear=True):
            cls.result = _powershell(FLOW_PROBE, cls.work, 300, CAR_EXE=str(exe), CAR_HOME=str(home),
                                     CAR_OTHER_HOME=str(cls.work / "home-other"), CAR_EMPTY=str(cls.work / "empty"),
                                     CAR_GARBAGE=str(cls.work / "garbage"), CODEX_AUTO_RESUME_DESKTOP=str(desktop))
        cls.answer = json.loads(cls.result.stdout) if cls.result.returncode == 0 and cls.result.stdout.strip() else {}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-3000:])

    def test_a_first_installation_starts_off_and_ticked_asks_for_it(self):
        self.assertIs(self.answer["first_box"], False)
        self.assertEqual(self.answer["first"], "-Silent", "not ticked: today's command line exactly")
        self.assertEqual(self.answer["first_ticked"], "-DesktopShortcut -Silent")

    def test_over_an_installation_it_starts_as_what_is_true_and_only_a_change_removes(self):
        self.assertIs(self.answer["there_box"], True)
        self.assertEqual(self.answer["there"], "-DesktopShortcut -Silent", "left on, a repair writes it again")
        self.assertEqual(self.answer["there_unticked"], "-NoDesktopShortcut -Silent")
        self.assertEqual(self.answer["edition_unticked"], "-AllowEditionChange -NoDesktopShortcut -Silent")
        self.assertIs(self.answer["absent_box"], False)
        self.assertEqual(self.answer["absent"], "-Silent")
        self.assertEqual(self.answer["absent_ticked"], "-DesktopShortcut -Silent")

    def test_an_update_with_no_box_and_an_uninstall_say_nothing_about_it(self):
        self.assertEqual(self.answer["update"], "-Silent")
        self.assertEqual(self.answer["uninstall"], "-Uninstall -Silent")
        self.assertEqual(self.answer["removed"], "-Uninstall -Silent", "Remove on the Maintain page")

    def test_a_switch_it_was_given_is_the_boxs_first_answer_and_is_passed_once(self):
        self.assertIs(self.answer["given_on_box"], True)
        self.assertEqual(self.answer["given_on"], "-DesktopShortcut -Silent")
        self.assertIs(self.answer["given_off_box"], False)
        self.assertEqual(self.answer["given_off"], "-NoDesktopShortcut -Silent")

    def test_inside_means_inside(self):
        self.assertEqual(self.answer["inside"], [True, True, False, False, False])

    def test_the_window_reads_a_real_shortcut_as_the_engine_wrote_it(self):
        self.assertEqual(self.answer["ours"], [True, False], "inside this home, and not inside another")
        self.assertIs(self.answer["ours_absent"], False)
        self.assertIs(self.answer["ours_garbage"], False)

    def test_with_no_seam_set_its_folder_is_the_one_windows_names(self):
        self.assertIs(self.answer["folder_is_windows"], True)


@unittest.skipUnless(WINDOWS and CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class WindowTests(unittest.TestCase):
    """The window built and never shown, as its layout audit is."""

    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="desktop-window-"))
        exe = _build(cls.work)
        cls.result = _powershell(WINDOW_PROBE, cls.work, 300, CAR_EXE=str(exe), CAR_LABEL=LABEL,
                                 CAR_CATALOG=str(ROOT / "src" / "codex_auto_resume" / "locales" / "en.json"))
        cls.answer = json.loads(cls.result.stdout) if cls.result.returncode == 0 and cls.result.stdout.strip() else {}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-3000:])

    def test_the_options_page_has_the_soft_box_off_on_a_first_installation(self):
        self.assertEqual(self.answer["first"], [[False, True]], "one box, not ticked, a box and not a switch")

    def test_over_an_installation_it_shows_what_is_true(self):
        self.assertEqual(self.answer["upgrade_there"], [[True, True]])

    def test_repair_has_it_and_remove_has_it_gone_with_no_room_kept(self):
        self.assertEqual(self.answer["repair"], [[True, True]])
        self.assertEqual(self.answer["remove"], [])
        self.assertLess(self.answer["remove_height"], self.answer["repair_height"])

    def test_the_uninstall_says_it_goes_only_where_one_of_ours_is_there(self):
        said = ENGLISH["installer.uninstall.desktop_shortcut"]
        self.assertIn(said, self.answer["confirm_there"])
        self.assertNotIn(said, self.answer["confirm_absent"])

    def test_the_uninstall_from_settings_apps_knows_as_the_setup_window_does(self):
        remove = (ROOT / "gui" / "SettingsRemove.cs").read_text(encoding="utf-8")
        self.assertIn("flow.KnowDesktopShortcut(DesktopShortcut.OursAt(home), null);", remove)
        setup = (ROOT / "build" / "setup" / "SetupWindow.cs").read_text(encoding="utf-8")
        self.assertIn("flow.KnowDesktopShortcut(DesktopShortcut.OursAt(home), arguments);", setup)

    def test_the_finish_page_says_what_could_not_be_done(self):
        self.assertEqual(self.answer["failed"], [ENGLISH["installer.done.desktop_failed"]])
        self.assertEqual(self.answer["taken"], [ENGLISH["installer.done.desktop_taken"]])
        self.assertEqual(self.answer["quiet"], [])
        self.assertEqual(self.answer["failed_run"], [], "a run that failed has more to say than this")
        for case in ("failed_log", "taken_log"):
            self.assertIs(self.answer[case], True, "and the log has the line")


if __name__ == "__main__":
    unittest.main()
