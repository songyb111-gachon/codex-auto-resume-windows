"""The pick's setup window stays until the installer has ended (v0.6.18 live acceptance, B2).

Install another version... -> v0.6.17: the setup window showed the download, then closed part-way. There was no finished
page, no exit code and no "Installed v0.6.17", and an empty "did not finish" box came up although v0.6.17 installed well.
A raw WM_CLOSE that another program posts to the window - an older installer closing this installation's Dashboard
windows as a person closes them (install.ps1, Close-DashboardWindow) - reaches WinForms as TaskManagerClosing, and the
window refused only UserClosing. So the close went through, ShowDialog returned with the run still going, and the pick
read its first outcome, "failed", with nothing under it.

Now every close but Windows ending the session is refused while the run goes on, in the one way the window already had
(installer.progress.busy): a raw WM_CLOSE and the owner's own close alike. The run ends, the finished page shows its exit
code, and the pick reads what the bootstrap printed. Where Windows ends the session first the pick says the work may
still be going on (diag.update_running), and a failure is never shown with nothing under it.

The window is compiled from the shipped sources and shown off screen over a stand-in owner, with a runner that takes a
few seconds. Nothing is installed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import guiscan  # noqa: E402

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
# A failing probe fails its test: never a dialog on the desktop waiting for someone (every handler below exits with 3).
[System.Windows.Forms.Application]::SetUnhandledExceptionMode([System.Windows.Forms.UnhandledExceptionMode]::ThrowException)
function Stop-Probe([object]$Problem) { [Console]::Error.WriteLine('probe failed: ' + $Problem); [Environment]::Exit(3) }
$asm = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$script:any = [Reflection.BindingFlags]'Static,Instance,NonPublic,Public'
Add-Type -ReferencedAssemblies System.Windows.Forms -TypeDefinition @'
using System; using System.Threading; using System.Runtime.InteropServices;
public static class CarPickCloseRunner {
    public static int Ended = int.MinValue;
    public static long EndedAt;
    public static int Run(object flow, Action<string> line, Action<double> unpacked) {
        line("  Installing"); Thread.Sleep(6000); line("  Checking the installation");
        EndedAt = DateTime.UtcNow.Ticks; Ended = 0; return 0;
    }
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, int m, IntPtr w, IntPtr l);
}
'@
$flowType = $asm.GetType('CodexAutoResume.InstallerFlow', $true)
$script:windowType = $asm.GetType('CodexAutoResume.InstallerWindow', $true)
$wordsType = $asm.GetType('CodexAutoResume.InstallerWords', $true)
if ($null -eq $script:windowType.GetField('closingAsked', $script:any)) { Stop-Probe 'InstallerWindow has no closingAsked' }
$flow = [Activator]::CreateInstance($flowType, $script:any, $null,
                                    [object[]]@('update', 'C:\Users\ExampleUser\.codex-auto-resume', 'standard', 'standard', '0.6.17'), $null)
$flowType.GetField('Another', $script:any).SetValue($flow, $true)
$words = [Activator]::CreateInstance($wordsType, $script:any, $null, [object[]]@($null, 'en'), $null)
$runner = [Delegate]::CreateDelegate($script:windowType.GetNestedType('Runner', $script:any), [CarPickCloseRunner].GetMethod('Run'))
$script:window = [Activator]::CreateInstance($script:windowType, $script:any, $null, [object[]]@($flow, $words, $null, $runner, $null, $null), $null)
$script:owner = New-Object System.Windows.Forms.Form
$script:owner.Text = 'car-pick-close-owner'
$script:owner.StartPosition = 'Manual'; $script:owner.Location = New-Object System.Drawing.Point(-4000, -4000)
$script:window.StartPosition = 'Manual'; $script:window.Location = New-Object System.Drawing.Point(-4000, -3000)
$script:events = New-Object System.Collections.ArrayList
$script:result = @{}
$script:window.add_FormClosing({
  param($s, $e)
  try { [void]$script:events.Add('window ' + [string]$e.CloseReason + ' ' + $e.Cancel) } catch { Stop-Probe $_ }
})
$script:owner.add_Shown({
  try {
    # A raw WM_CLOSE, as Process.CloseMainWindow and every other program sends it, then the owner's own close.
    $script:post = New-Object System.Windows.Forms.Timer
    $script:post.Interval = 1500
    $script:post.add_Tick({
      try {
        $script:post.Stop()
        [void][CarPickCloseRunner]::PostMessage($script:window.Handle, 0x10, [IntPtr]::Zero, [IntPtr]::Zero)
      } catch { Stop-Probe $_ }
    })
    $script:post.Start()
    $script:shut = New-Object System.Windows.Forms.Timer
    $script:shut.Interval = 3000
    $script:shut.add_Tick({
      try {
        $script:shut.Stop()
        $script:result.busy = [bool]$script:windowType.GetField('closingAsked', $script:any).GetValue($script:window)
        $script:owner.Close()
      } catch { Stop-Probe $_ }
    })
    $script:shut.Start()
    # Once the run has ended the window may close: the person's Finish.
    $script:done = New-Object System.Windows.Forms.Timer
    $script:done.Interval = 250
    $script:done.add_Tick({
      try {
        if ([CarPickCloseRunner]::Ended -eq 0 -and
            $script:windowType.GetProperty('Page', $script:any).GetValue($script:window) -eq 'finish') {
            $script:done.Stop(); $script:window.Close()
        }
      } catch { Stop-Probe $_ }
    })
    $script:done.Start()
    $null = $script:window.ShowDialog($script:owner)
    $script:result.returned_at = [DateTime]::UtcNow.Ticks
    $script:result.ended_at = [CarPickCloseRunner]::EndedAt
    $script:result.ended = [CarPickCloseRunner]::Ended
    $script:result.code = $script:windowType.GetProperty('Code', $script:any).GetValue($script:window)
    $script:owner.BeginInvoke([Action]{ $script:owner.Close() }) | Out-Null
  } catch { Stop-Probe $_ }
})
[System.Windows.Forms.Application]::Run($script:owner)
$script:result.events = @($script:events)
$script:result | ConvertTo-Json -Compress
"""


def run_probe(probe: Path, arguments: list, timeout: int, **env) -> subprocess.CompletedProcess:
    """Runs `probe` in Windows PowerShell with its output in files beside it, never in pipes: a process a probe left
    behind can hold an inherited pipe past any timeout (tests/test_probe_never_waits.py). A probe that has not ended in
    `timeout` seconds is ended and answers code None."""
    said, errors = probe.with_suffix(".out"), probe.with_suffix(".err")
    try:
        with open(said, "wb") as out, open(errors, "wb") as err:
            code = subprocess.run([str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                   "-File", str(probe), *arguments], stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                  timeout=timeout, creationflags=NO_WINDOW, env=dict(os.environ, **env)).returncode
    except subprocess.TimeoutExpired:
        code = None
    text = lambda path: path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    if code is None:
        return subprocess.CompletedProcess([], None, text(said), "the probe did not end within %d s: %s" % (timeout, text(errors)))
    return subprocess.CompletedProcess([], code, text(said), text(errors))


def body(member: str) -> str:
    return guiscan.member_body("SettingsForm", member)


class SourceTests(unittest.TestCase):
    def test_every_close_but_the_sessions_end_is_refused_while_it_runs(self):
        closing = guiscan.member_body("InstallerWindow", "OnFormClosing")
        self.assertIn("if (running && e.CloseReason != CloseReason.WindowsShutDown)", closing)
        self.assertNotIn("if (running && e.CloseReason == CloseReason.UserClosing)\n", closing,
                         "UserClosing alone let a raw WM_CLOSE (TaskManagerClosing) through")
        self.assertEqual(closing.count("closingAsked = true;"), 1, "one way to refuse: the busy note")

    def test_a_pick_whose_run_never_ended_in_the_window_is_not_a_failure(self):
        pick = body("InstallPick")
        shown = pick.index("window.ShowDialog(this);")
        running = pick.index('if (window.Code == int.MinValue) outcome = "running";')
        self.assertLess(shown, running)
        self.assertLess(running, pick.index("ReportPick(outcome, reason, converted, detail, releases);"))

    def test_a_failure_is_never_shown_with_nothing_under_it(self):
        pick = body("InstallPick")
        fallback = pick.index("if (string.IsNullOrEmpty(detail)) detail = Tail(window.Log);")
        self.assertLess(fallback, pick.index("ReportPick(outcome, reason, converted, detail, releases);"))
        self.assertIn("detail = new InstallerWords(strings, openedLanguage).Outcome(InstallerFlow.Update, window.Code);",
                      pick)


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        exe = Path(cls.folder.name) / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll",
                        "/reference:System.Windows.Forms.dll",
                        *[str(path) for path in guiscan.sources()]],
                       check=True, capture_output=True, timeout=300, creationflags=NO_WINDOW)
        probe = Path(cls.folder.name) / "probe.ps1"
        probe.write_text(PROBE, encoding="utf-8-sig")
        result = run_probe(probe, [], 60, CAR_EXE=str(exe))
        cls.result = result
        lines = result.stdout.strip().splitlines()
        cls.answer = json.loads(lines[-1]) if result.returncode == 0 and lines else {}

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-3000:])

    def test_a_close_while_it_runs_neither_ends_the_window_nor_the_run(self):
        self.assertEqual(self.answer["ended"], 0, "the run ended")
        self.assertGreaterEqual(self.answer["returned_at"], self.answer["ended_at"],
                                "the window was still there when the run ended")
        self.assertEqual(self.answer["code"], 0, "the finished page has the run's exit code")

    def test_each_close_was_refused_the_one_way_and_the_finish_closes_it(self):
        # A refused close never reaches the FormClosing event (OnFormClosing returns before it): the one close the
        # event sees is the Finish, after the run. Before the fix the raw WM_CLOSE went through as TaskManagerClosing.
        self.assertEqual(self.answer["events"], ["window UserClosing False"])
        self.assertTrue(self.answer["busy"], "the raw WM_CLOSE was refused with the busy note")


if __name__ == "__main__":
    unittest.main()
