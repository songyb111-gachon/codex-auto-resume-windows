r"""Starting the Dashboard while one is open brings that one forward and starts no second window (v0.6.20 final).

The v0.6.20 final's live acceptance (2026-11-01) started the Dashboard from the Start menu while one was open and got a
second Dashboard process. Issue #55's fix had the watcher's opens ask the open window first (win/handover.py, the window's
TakeOpenRequest); a start of the program itself asked nothing. Now Program.Main asks the same way before it builds
anything (SettingsForm.HandOverTo): a window of this very program that is open - top-level, visible, unowned, a Windows
Forms window of a process running the same file - takes the request, comes forward on the page the command line names or
where it is, and the new process ends. Only a start whose command line an open request carries whole asks
(HandsOverOnStart): a reopen, the chat a notice opens and a capture start as they always did.

The window stand-in is the one tests/test_tray_reuses_window.py uses: a real window of this test process, off every screen
and never activated, under a Windows Forms class name, answering as the settings window does. The compiled window's
HandOverTo is called through reflection from a PowerShell process, asked for windows of this Python's program. No real
window is started or asked.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import guiscan
from codex_auto_resume.win import handover

from test_tray_reuses_window import StandIn

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

DECIDE = r"""
$ErrorActionPreference = 'Stop'
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$any = [Reflection.BindingFlags]'Static,NonPublic,Public'
$form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$asks = $form.GetMethod('HandsOverOnStart', $any)
$page = $form.GetMethod('HandOverPage', $any)
$out = New-Object System.Collections.ArrayList
foreach ($case in (ConvertFrom-Json $env:CAR_CASES)) {
    $argv = [string[]]@($case.argv | ForEach-Object { [string]$_ })
    $call = [object[]]::new(2); $call[0] = $argv; $call[1] = [bool]$case.capture
    $one = [object[]]::new(1); $one[0] = $argv
    [void]$out.Add(@([bool]$asks.Invoke($null, $call), [string]$page.Invoke($null, $one)))
}
ConvertTo-Json -InputObject $out -Compress
"""

ASK = r"""
$ErrorActionPreference = 'Stop'
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$any = [Reflection.BindingFlags]'Static,NonPublic,Public'
$form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$call = [object[]]::new(2); $call[0] = [string]$env:CAR_PROGRAM; $call[1] = [string]$env:CAR_PAGE
[bool]$form.GetMethod('HandOverTo', $any).Invoke($null, $call)
"""

# (command line, a capture's?) -> (asks, the page it asks for)
CASES = [
    ([], False, True, ""),
    (["--page=history"], False, True, "history"),
    (["--settings"], False, True, "settings"),
    (["--outside", "--page=pending"], False, True, "pending"),
    (["--outside"], False, True, ""),
    ([], True, False, ""),
    (["--page=pending", "--bounds=10,20,800,600", "--reopened=1"], False, False, "pending"),
    # Opened again by the installer after an update: the window it replaces is gone, so it asks (fails with it asking nothing).
    (["--page=pending", "--bounds=10,20,800,600", "--reopened=1", "--after-update"], False, True, "pending"),
    (["--reopened=1", "--after-update"], True, False, ""),
    (["--page=advanced", "--capability=codex_chat", "--chat=11111111-0000-7000-8000-000000000000"], False, False, ""),
    (["--page=nowhere"], False, False, ""),
    (["--section=general"], False, False, ""),
    (["--theme=dark"], False, False, ""),
]


@unittest.skipUnless(os.name == "nt" and CSC.is_file() and POWERSHELL.is_file(), "needs Windows, its compiler and PowerShell")
class StartHandsOverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        cls.exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(cls.exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll", "/reference:System.Windows.Forms.dll",
                        *[str(path) for path in guiscan.sources()]],
                       check=True, capture_output=True, timeout=300, creationflags=NO_WINDOW)
        cls.decide = work / "decide.ps1"
        cls.decide.write_text(DECIDE, encoding="utf-8")
        cls.ask_script = work / "ask.ps1"
        cls.ask_script.write_text(ASK, encoding="utf-8")
        # This test process's own program, as Windows names it: the stand-in's windows are windows of it.
        cls.program = handover._image(os.getpid())

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def run_script(self, script, **env):
        return subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-File", str(script)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=300, env=dict(os.environ, CAR_EXE=str(self.exe), **env), creationflags=NO_WINDOW)

    def ask(self, program, page):
        result = self.run_script(self.ask_script, CAR_PROGRAM=str(program), CAR_PAGE=page)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        return result.stdout.strip() == "True"

    def test_only_a_start_an_open_request_carries_whole_asks(self):
        cases = [{"argv": argv, "capture": capture} for argv, capture, _, _ in CASES]
        result = self.run_script(self.decide, CAR_CASES=json.dumps(cases))
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        answer = json.loads(result.stdout)
        for (argv, capture, asks, page), (asked, wanted) in zip(CASES, answer):
            with self.subTest(argv=argv, capture=capture):
                self.assertEqual(asked, asks)
                if asks:
                    self.assertEqual(wanted, page)

    def test_an_open_window_of_the_same_program_takes_the_start_on_its_page(self):
        self.assertIsNotNone(self.program, "this process's program could not be read")
        with StandIn() as window:
            self.assertTrue(self.ask(self.program, "history"))
            self.assertTrue(self.ask(self.program, ""))
        self.assertEqual(window.asked, ["history", ""])

    def test_a_window_that_does_not_take_it_leaves_the_start_to_go_on(self):
        with StandIn(takes=False) as window:
            self.assertFalse(self.ask(self.program, "pending"))
        self.assertEqual(window.asked, ["pending"])

    def test_a_window_of_another_program_is_never_asked(self):
        with StandIn() as window:
            self.assertFalse(self.ask(self.exe, "history"))
        self.assertEqual(window.asked, [])


class StartSourceTests(unittest.TestCase):
    def test_main_asks_before_it_builds_anything(self):
        main = guiscan.member_body("Program", "Main")
        asks = main.index("SettingsForm.HandsOverOnStart(argv, Soft.StillReady != null)")
        self.assertLess(main.index("SettingsForm.RenderFrames(renderJob)"), asks, "a render job never asks")
        self.assertLess(asks, main.index("HostApp.Inside()"))
        self.assertLess(asks, main.index("new Bridge(root)"))
        self.assertLess(asks, main.index("new SettingsForm("))
        self.assertIn("SettingsForm.HandOverTo(Application.ExecutablePath, SettingsForm.HandOverPage(argv))", main)

    def test_it_asks_only_windows_forms_windows_of_other_processes_under_the_one_mark(self):
        body = guiscan.member_body("SettingsForm", "HandOverTo")
        self.assertIn("process == own", body)
        self.assertIn("StartsWith(FormsClass, StringComparison.Ordinal)", body)
        self.assertIn("GetWindow(window, GwOwner) != IntPtr.Zero", body)
        ask = guiscan.member_body("SettingsForm", "AskToComeForward")
        self.assertIn("copy.Data = new IntPtr(OpenRequestMark);", ask)
        self.assertIn("answer.ToInt64() == OpenRequestTaken", ask)
        self.assertIn('FormsClass = "%s"' % handover.FORMS_CLASS, guiscan.type_body("SettingsForm", "gui/WindowReopen.cs"))


if __name__ == "__main__":
    unittest.main()
