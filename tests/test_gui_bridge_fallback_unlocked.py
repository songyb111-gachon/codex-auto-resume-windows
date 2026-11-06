"""v0.6.23 (audit A-B1): the one-shot answer after a failed long-lived call runs past the bridge's lock.

When the long-lived bridge failed a call, PersistentBridge.Call answered it through the one-shot bridge while it still
held its lock. The one-shot call can take up to Bridge.CallMilliseconds, so every other read of the window - the
Dashboard's five-second read, the chat's two-second read, the previews - waited behind it: up to about 92 s with no
page refreshed after a pipe that hung (the 30 s reply limit, the 2 s stop, then the 60 s one-shot limit). Now the
one-shot call is made after the lock is left; the one-shot bridge needs none (each call is a process of its own).

The built half compiles the real window and runs its bridge against a stand-in python.exe this test compiles: its
long-lived form reads one line and ends without answering, so every long-lived call fails; its one-shot form answers
the command `slow` only after a few seconds. One worker calls `slow`; while its one-shot answer is on its way, a second
read is made and must come back before it. Nothing of the real installation is read, nothing is shown.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_gui_v0611_access import CSC, NO_WINDOW, POWERSHELL, compile_window, run_probe

FAKE = r"""
using System;
using System.IO;
using System.Threading;
static class Fake {
    static void Say(string text) {
        string said = Environment.GetEnvironmentVariable("CAR_FAKE_LOG");
        for (int i = 0; i < 50; i++) {
            try { File.AppendAllText(said, text + "\n"); return; }
            catch (IOException) { Thread.Sleep(20); }
        }
    }
    static int Main(string[] args) {
        int options = 0;
        while (options + 1 < args.Length && args[options] == "-X") options += 2;
        if (options > 0) { var rest = new string[args.Length - options]; Array.Copy(args, options, rest, 0, rest.Length); args = rest; }
        if (Array.IndexOf(args, "serve") < 0) {
            string command = args.Length > 3 ? args[3] : "";
            Say("once " + command);
            if (Array.IndexOf(args, "-") >= 0) Console.In.ReadToEnd();
            if (command == "slow") { Thread.Sleep(8000); Say("once slow done"); }
            Console.Out.Write("{\"ok\":true,\"by\":\"once\"}");
            return 0;
        }
        // The long-lived form: reads one request and ends without an answer, so every long-lived call fails.
        string line = Console.In.ReadLine();
        Say("serve " + (line == null ? "" : "read"));
        return 0;
    }
}
"""

PROBE = r"""
$ErrorActionPreference = 'Stop'
try {
    Add-Type -AssemblyName System.Windows.Forms
    [Windows.Forms.Application]::SetUnhandledExceptionMode([Windows.Forms.UnhandledExceptionMode]::ThrowException)
    $assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
    $flags = [Reflection.BindingFlags]'Instance,Static,NonPublic,Public'
    $BT = $assembly.GetType('CodexAutoResume.Bridge', $true)
    $PB = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
    $work = [string]$env:CAR_WORK
    $home_ = [string]$env:CAR_HOME
    $log = [string]$env:CAR_FAKE_LOG
    $utf8 = New-Object Text.UTF8Encoding $false
    $oneShot = $BT.GetConstructors($flags)[0].Invoke([object[]]@($home_))
    $bridge = $PB.GetConstructors($flags)[0].Invoke([object[]]@($home_, $oneShot))
    $call = $PB.GetMethod('Call', $flags, $null, [type[]]@([string], [string]), $null)
    $advanced = $PB.GetMethod('CallAdvanced', $flags)
    function Lines { if (Test-Path $log) { return ,@([IO.File]::ReadAllLines($log)) } else { return ,@() } }
    # The slow call on a worker of its own: its long-lived call fails, and its one-shot answer takes seconds.
    $worker = [powershell]::Create()
    [void]$worker.AddScript({ param($m, $b) $m.Invoke($b, [object[]]@('slow', $null)) | Out-Null }).AddArgument($call).AddArgument($bridge)
    $running = $worker.BeginInvoke()
    $clock = [Diagnostics.Stopwatch]::StartNew()
    while (-not ((Lines) -contains 'once slow') -and $clock.ElapsedMilliseconds -lt 60000) { Start-Sleep -Milliseconds 50 }
    $out = @{ started = [bool]((Lines) -contains 'once slow') }
    # A read while the slow call's one-shot answer is on its way.
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $reply = $advanced.Invoke($bridge, [object[]]@('advanced-list', '{}', $false))
    $out.readMs = [int]$clock.ElapsedMilliseconds
    $out.readCode = [string]$reply['error_code']
    $out.beforeSlowEnded = -not ((Lines) -contains 'once slow done')
    $worker.EndInvoke($running) | Out-Null
    $worker.Dispose()
    $out.lines = Lines
    $PB.GetMethod('Stop', $flags).Invoke($bridge, @())
    [IO.File]::WriteAllText((Join-Path $work 'result.json'), (ConvertTo-Json $out -Compress -Depth 4), $utf8)
    exit 0
} catch {
    [IO.File]::WriteAllText((Join-Path $env:CAR_WORK 'probe.failed'), $_.Exception.ToString())
    exit 3
}
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "the window is compiled with the in-box C# compiler")
class FallbackPastTheLockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name).resolve()
        cls.home = work / "home"
        (cls.home / "runtime").mkdir(parents=True)
        (cls.home / "app" / "src").mkdir(parents=True)
        exe = compile_window(work)
        source = work / "fake.cs"
        source.write_text(FAKE, encoding="utf-8")
        for name in ("python.exe", "pythonw.exe"):
            subprocess.run([str(CSC), "/nologo", "/target:exe", "/out:" + str(cls.home / "runtime" / name), str(source)],
                           check=True, capture_output=True, timeout=300, creationflags=NO_WINDOW)
        cls.failed = work / "probe.failed"
        try:
            cls.answer = run_probe(PROBE, work, 300, CAR_EXE=str(exe), CAR_HOME=str(cls.home),
                                   CAR_FAKE_LOG=str(work / "said.txt"))
        except Exception:
            cls.answer = {}

    @classmethod
    def tearDownClass(cls):
        script = ("Get-Process -Name python,pythonw -ErrorAction SilentlyContinue | Where-Object { $_.Path -and "
                  "$_.Path.StartsWith($env:CAR_HOME, [StringComparison]::OrdinalIgnoreCase) } | Stop-Process -Force")
        subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                       timeout=120, creationflags=NO_WINDOW, env=dict(os.environ, CAR_HOME=str(cls.home)))
        cls.folder.cleanup()

    def setUp(self):
        failed = self.failed.read_text(encoding="utf-8") if self.failed.is_file() else ""
        self.assertTrue(self.answer, failed[-3000:] or "the probe wrote no result")
        self.assertTrue(self.answer["started"], "the slow call reached its one-shot answer")

    def test_another_read_is_answered_while_a_one_shot_fallback_runs(self):
        """Fails with the one-shot call back under the lock: the read waits for the slow answer (about 8 s)."""
        self.assertTrue(self.answer["beforeSlowEnded"], "the read came back only after the slow one-shot answer")
        self.assertLess(self.answer["readMs"], 6000)

    def test_the_read_was_still_asked_of_the_long_lived_bridge(self):
        self.assertEqual(self.answer["readCode"], "reconnecting", "it failed there, as the stand-in fails every call")
        self.assertEqual(self.answer["lines"][-1], "once slow done")


if __name__ == "__main__":
    unittest.main()
