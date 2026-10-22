"""The pick follows its run to the end when its window is hidden (v0.6.18 live acceptance, B2, candidate 3).

Install another version... -> v0.6.17, twice: part-way through the install the setup window was gone, the Dashboard
minimized in the same quarter second, and a "still working" box came up. The bootstrap ran on for ten seconds more and
installed v0.6.17 well, but there was no finished page, no exit code and no "Installed v0.6.17", and the old Dashboard
stayed open. No close was asked. Minimizing the Dashboard hides the windows it owns (WM_SHOWWINDOW, SW_PARENTCLOSING),
and WinForms ends a modal window's loop once that window is hidden, with no close and no FormClosing. ShowDialog returned
with the run still going. A person's Show desktop does the same.

Now the setup window is not hidden that way while the run goes on. If its loop ends anyway, the pick brings the Dashboard
back and shows the window again until the installer has ended. What the run says while the window has no handle is kept
and told once it has one, so its end is never lost.

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
param([string]$How)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
# A failing probe fails its test: never a dialog on the desktop waiting for someone (every handler below exits with 3).
[System.Windows.Forms.Application]::SetUnhandledExceptionMode([System.Windows.Forms.UnhandledExceptionMode]::ThrowException)
function Stop-Probe([object]$Problem) { [Console]::Error.WriteLine('probe failed: ' + $Problem); [Environment]::Exit(3) }
$asm = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$script:any = [Reflection.BindingFlags]'Static,Instance,NonPublic,Public'
Add-Type -ReferencedAssemblies System.Windows.Forms -TypeDefinition @'
using System; using System.Threading; using System.Runtime.InteropServices;
public static class CarPickHiddenRunner {
    public static int Ended = int.MinValue;
    public static int Run(object flow, Action<string> line, Action<double> unpacked) {
        line("  Installing"); Thread.Sleep(5000); line("  Checking the installation"); Ended = 0; return 0;
    }
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
}
'@
$flowType = $asm.GetType('CodexAutoResume.InstallerFlow', $true)
$script:windowType = $asm.GetType('CodexAutoResume.InstallerWindow', $true)
foreach ($member in @(@('Page', 'Code') + @(if ($How -eq 'gap') { 'Running' }))) {
    if ($null -eq $script:windowType.GetProperty($member, $script:any)) { Stop-Probe ('InstallerWindow has no ' + $member) }
}
$flow = [Activator]::CreateInstance($flowType, $script:any, $null,
                                    [object[]]@('update', 'C:\Users\ExampleUser\.codex-auto-resume', 'standard', 'standard', '0.6.17'), $null)
$flowType.GetField('Another', $script:any).SetValue($flow, $true)
$words = [Activator]::CreateInstance($asm.GetType('CodexAutoResume.InstallerWords', $true), $script:any, $null, [object[]]@($null, 'en'), $null)
$runner = [Delegate]::CreateDelegate($script:windowType.GetNestedType('Runner', $script:any), [CarPickHiddenRunner].GetMethod('Run'))
$script:window = [Activator]::CreateInstance($script:windowType, $script:any, $null, [object[]]@($flow, $words, $null, $runner, $null, $null), $null)
$script:owner = New-Object System.Windows.Forms.Form
$script:owner.StartPosition = 'Manual'; $script:owner.Location = New-Object System.Drawing.Point(-4000, -4000)
$script:window.StartPosition = 'Manual'; $script:window.Location = New-Object System.Drawing.Point(-4000, -3000)
$script:how = $How
$script:r = @{ how = $How }
function Get-Window([string]$Name) { return $script:windowType.GetProperty($Name, $script:any).GetValue($script:window) }
$script:owner.add_Shown({
  try {
    $script:hide = New-Object System.Windows.Forms.Timer; $script:hide.Interval = 1500
    $script:hide.add_Tick({
      try {
        $script:hide.Stop()
        # The Dashboard minimized under the window; or the window hidden outright, which ends the loop whatever it does.
        if ($script:how -eq 'owner') { [void][CarPickHiddenRunner]::ShowWindow($script:owner.Handle, 6) } else { $script:window.Hide() }
      } catch { Stop-Probe $_ }
    })
    $script:hide.Start()
    $script:done = New-Object System.Windows.Forms.Timer; $script:done.Interval = 250
    $script:done.add_Tick({
      try {
        if ([CarPickHiddenRunner]::Ended -eq 0 -and (Get-Window 'Page') -eq 'finish') { $script:done.Stop(); $script:window.Close() }
      } catch { Stop-Probe $_ }
    })
    $script:done.Start()
    $null = $script:window.ShowDialog($script:owner)
    $script:r.first_ended = [CarPickHiddenRunner]::Ended
    $script:r.owner_iconic = [CarPickHiddenRunner]::IsIconic($script:owner.Handle)
    if ($script:how -eq 'gap') {
        # The run ends while the window has no handle; then it is shown again, as SettingsForm.InstallPick does.
        $deadline = (Get-Date).AddSeconds(20)
        while ([CarPickHiddenRunner]::Ended -ne 0 -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 100 }
        Start-Sleep -Milliseconds 500
        $script:r.running_in_gap = [bool](Get-Window 'Running')
        $shows = 0
        while ((Get-Window 'Running') -and -not $script:window.IsDisposed -and $shows -lt 3) {
            $shows++
            $null = $script:window.ShowDialog($script:owner)
        }
        $script:r.shows = $shows
    }
    $script:r.code = Get-Window 'Code'
    $script:r.page = Get-Window 'Page'
    $script:owner.BeginInvoke([Action]{ $script:owner.Close() }) | Out-Null
  } catch { Stop-Probe $_ }
})
[System.Windows.Forms.Application]::Run($script:owner)
$script:r | ConvertTo-Json -Compress
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
    def test_the_pick_follows_its_run_until_it_has_ended(self):
        pick = body("InstallPick")
        first = pick.index("window.ShowDialog(this);")
        loop = pick.index("while (window.Running && !window.IsDisposed)")
        self.assertLess(first, loop)
        again = pick[loop:pick.index("updatingHere = false;")]
        self.assertIn("if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;", again)
        self.assertIn("window.ShowDialog(this);", again)
        self.assertLess(pick.index("updatingHere = false;"), pick.index("ReportPick(outcome, reason, converted, detail, releases);"))

    def test_the_window_is_not_hidden_with_its_owner_while_it_runs(self):
        window = guiscan.type_body("InstallerWindow", "gui/InstallerWindow.cs")
        self.assertIn("if (m.Msg == WM_SHOWWINDOW && running && m.WParam == IntPtr.Zero && m.LParam.ToInt64() == SW_PARENTCLOSING)",
                      window)
        post = guiscan.member_body("InstallerWindow", "Post")
        self.assertIn("waiting.Add(action);", post)
        self.assertIn("foreach (MethodInvoker action in told) BeginInvoke(action);",
                      guiscan.member_body("InstallerWindow", "OnHandleCreated"))


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
        for how in ("owner", "gap"):
            probe.with_name("probe-%s.ps1" % how).write_text(PROBE, encoding="utf-8-sig")
        cls.answers, cls.failures = {}, {}
        for how in ("owner", "gap"):
            result = run_probe(probe.with_name("probe-%s.ps1" % how), ["-How", how], 60, CAR_EXE=str(exe))
            lines = result.stdout.strip().splitlines()
            if result.returncode == 0 and lines:
                cls.answers[how] = json.loads(lines[-1])
            else:
                cls.failures[how] = (result.stderr or result.stdout)[-3000:]

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def answer(self, how: str) -> dict:
        if how not in self.answers:
            self.fail("the probe did not run: " + self.failures.get(how, ""))
        return self.answers[how]

    def test_the_owner_minimized_neither_ends_the_window_nor_hides_the_run(self):
        seen = self.answer("owner")
        self.assertTrue(seen["owner_iconic"], "the stand-in Dashboard was minimized")
        self.assertEqual(seen["first_ended"], 0, "the window stayed until the run had ended")
        self.assertEqual((seen["code"], seen["page"]), (0, "finish"))

    def test_shown_again_after_its_loop_ended_it_still_hears_how_the_run_ended(self):
        seen = self.answer("gap")
        self.assertEqual(seen["first_ended"], -2147483648, "hidden, the loop ended before the run")
        self.assertTrue(seen["running_in_gap"], "the end the run told while the window had no handle was kept")
        self.assertEqual(seen["shows"], 1)
        self.assertEqual((seen["code"], seen["page"]), (0, "finish"), "told once it was shown again")


if __name__ == "__main__":
    unittest.main()
