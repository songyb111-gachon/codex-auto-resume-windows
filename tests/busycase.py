r"""What the tests of the header light while an action is in flight share (v0.6.20; test_gui_busy_light, and the advanced
edition's test_advanced_busy_light).

The real window is compiled by the caller and runs against a stand-in `python.exe` this module compiles into a home of its
own: the window's long-lived bridge starts it, and it answers every command at once with an empty result - except the
ones named in CAR_FAKE_HOLD, which it answers only once the file CAR_FAKE_GATE exists - and `dashboard` with the case's own snapshot
(CAR_FAKE_SNAPSHOT, set by the probe for each), so the re-read after a change shows what the window already shows. So an action can be held in flight,
the header's light read, and the action let go. Nothing of the real installation is read or written; nothing is shown.

Not a test module (no `test_` prefix), so discovery does not collect it.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile

from codex_auto_resume import l10n
from test_gui_v0611_access import CSC, NO_WINDOW, POWERSHELL, run_probe
from test_gui_layout import fullest_snapshot

FAKE = r"""
using System;
using System.IO;
using System.Text.RegularExpressions;
using System.Threading;
static class Fake {
    static int Main(string[] args) {
        int options = 0;
        while (options + 1 < args.Length && args[options] == "-X") options += 2;
        if (options > 0) { var rest = new string[args.Length - options]; Array.Copy(args, options, rest, 0, rest.Length); args = rest; }
        if (Array.IndexOf(args, "serve") < 0) { Console.Out.Write("{\"ok\":true,\"result\":{}}"); return 0; }
        string[] hold = (Environment.GetEnvironmentVariable("CAR_FAKE_HOLD") ?? "").Split(',');
        string gate = Environment.GetEnvironmentVariable("CAR_FAKE_GATE");
        string line;
        while ((line = Console.In.ReadLine()) != null) {
            string id = Regex.Match(line, "\"id\":(\\d+)").Groups[1].Value;
            string name = Regex.Match(line, "\"command\":\"([a-z_-]+)\"").Groups[1].Value;
            if (Array.IndexOf(hold, name) >= 0) while (!File.Exists(gate)) Thread.Sleep(20);
            string reply = name == "dashboard"
                ? File.ReadAllText(Environment.GetEnvironmentVariable("CAR_FAKE_SNAPSHOT"))
                : "{\"ok\":true,\"result\":{}}";
            Console.Out.Write("{\"id\":" + id + ",\"reply\":" + reply + "}\n");
            Console.Out.Flush();
        }
        return 0;
    }
}
"""

# The window made on the stand-in bridge, given a snapshot, on its Pending page with a row chosen; `Pump` runs its messages.
# $kind is "standard" (Retry now, Rescan: the window's own methods) or "advanced" (AdvancedCall, with an action).
PROBE = r"""
$ErrorActionPreference = 'Stop'
try {
    Add-Type -AssemblyName System.Drawing
    Add-Type -AssemblyName System.Windows.Forms
    [Windows.Forms.Application]::SetUnhandledExceptionMode([Windows.Forms.UnhandledExceptionMode]::ThrowException)
    [Windows.Forms.Application]::EnableVisualStyles()
    $assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
    $flags = [Reflection.BindingFlags]'Instance,Static,NonPublic,Public'
    $F = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
    $PB = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
    $BT = $assembly.GetType('CodexAutoResume.Bridge', $true)
    $J = $assembly.GetType('CodexAutoResume.Json', $true)
    $work = [string]$env:CAR_WORK
    $home_ = [string]$env:CAR_HOME
    $gate = [string]$env:CAR_FAKE_GATE
    $utf8 = New-Object Text.UTF8Encoding $false
    function Parse($name) { return ,$J.GetMethod('Parse', $flags).Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $work $name), $utf8))) }
    function Field($form, $name) { return $F.GetField($name, $flags).GetValue($form) }
    function Call($form, $name, $arguments) { return $F.GetMethod($name, $flags).Invoke($form, [object[]]$arguments) }
    function Light($form) { $dot = Field $form 'stateDot'; return [string]$dot.GetType().GetProperty('State', $flags).GetValue($dot) }
    function Pump($form, $until) {
        $end = [DateTime]::UtcNow.AddSeconds(30)
        while (-not (& $until) -and [DateTime]::UtcNow -lt $end) { [Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 20 }
        for ($i = 0; $i -lt 10; $i++) { [Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 20 }
    }
    $catalog = Parse 'strings.json'
    $out = @{}
    foreach ($case in (Get-Content (Join-Path $work 'cases.json') -Raw | ConvertFrom-Json)) {
        if (Test-Path $gate) { Remove-Item $gate }
        # The stand-in answers `dashboard` with this case's own snapshot (it inherits the environment it starts in).
        $env:CAR_FAKE_SNAPSHOT = Join-Path $work $case.snapshot
        $one = $BT.GetConstructors($flags)[0].Invoke([object[]]@($home_))
        $bridge = $PB.GetConstructors($flags)[0].Invoke([object[]]@($home_, $one))
        $make = $F.GetConstructor($flags, $null, [type[]]@($PB, [Collections.Generic.Dictionary[string,object]], [Drawing.Font]), $null)
        $form = $make.Invoke([object[]]@($bridge, $catalog, [Drawing.SystemFonts]::MessageBoxFont))
        $F.GetField('auditing', $flags).SetValue($form, $true)
        $form.TopLevel = $false
        $form.ClientSize = New-Object Drawing.Size 1100, 760
        $null = $form.Handle
        $snapshot = Parse $case.snapshot
        Call $form 'ApplySnapshot' @($snapshot) | Out-Null
        Call $form 'ShowPage' @('pending') | Out-Null
        Call $form 'UpdateCountdowns' @() | Out-Null
        $list = Field $form 'pendingList'
        $null = $list.Handle
        $list.Items[0].Selected = $true
        $result = @{ before = (Light $form) }
        $busy = $F.GetField('busy', $flags)
        $F.GetField('DialogAnswers', $flags).SetValue($null, [Func[string,string,bool]]{ param($text, $affirm) $true })
        if ($case.action -eq 'start') {
            # Start watcher (v0.6.20): not an action SetBusy counts, but "Starting the watcher..." in the headline - and the light.
            Call $form 'StartWatcher' @() | Out-Null
            $result.during = (Light $form)
            $result.headline = [string](Field $form 'headline').Text
            $F.GetField('DialogAnswers', $flags).SetValue($null, $null)
            $form.Dispose()
            $PB.GetMethod('Stop', $flags).Invoke($bridge, @())
            $out[[string]$case.name] = $result
            continue
        }
        if ($case.action -eq 'retry') { Call $form 'RetryNow' @() | Out-Null }
        elseif ($case.action -eq 'rescan') { Call $form 'Rescan' @() | Out-Null }
        else {
            # The advanced edition's call with an action, as its buttons make it (Turn on, Keep it on, ...): off auditing,
            # which makes no call.
            $F.GetField('auditing', $flags).SetValue($form, $false)
            $done = [Action[Collections.Generic.Dictionary[string,object]]]{ param($reply) }
            Call $form 'AdvancedCall' @([string]$case.command, '{}', $true, $done) | Out-Null
            $F.GetField('auditing', $flags).SetValue($form, $true)
        }
        $result.busy_while = [int]$busy.GetValue($form)
        $result.during = (Light $form)
        # The second's tick, as it comes: the light stays.
        Call $form 'UpdateCountdowns' @() | Out-Null
        $result.during_tick = (Light $form)
        New-Item -ItemType File -Path $gate -Force | Out-Null
        Pump $form { [int]$busy.GetValue($form) -eq 0 }
        $result.busy_after = [int]$busy.GetValue($form)
        $result.after = (Light $form)
        $F.GetField('DialogAnswers', $flags).SetValue($null, $null)
        $form.Dispose()
        $PB.GetMethod('Stop', $flags).Invoke($bridge, @())
        $out[[string]$case.name] = $result
    }
    [IO.File]::WriteAllText((Join-Path $work 'result.json'), (ConvertTo-Json $out -Compress -Depth 4), $utf8)
    exit 0
} catch {
    [IO.File]::WriteAllText((Join-Path $env:CAR_WORK 'probe.failed'), $_.Exception.ToString())
    exit 3
}
"""


def snapshots(now: float) -> dict:
    """The fullest snapshot (a recovery running in Codex: the watcher's own light is "recovering"), the same with the
    watcher not running ("idle"), and with an older watcher still owning the state ("attention")."""
    running = fullest_snapshot(now)
    stopped = copy.deepcopy(running)
    stopped["status"]["watcher_running"] = False
    stopped["status"]["watcher"]["running"] = False
    attention = copy.deepcopy(running)
    attention["status"]["upgrade_pending"] = True
    return {"running": running, "stopped": stopped, "attention": attention}


class BusyCase:
    """Compiles the stand-in, runs the probe for `cases` ([{name, snapshot, action | command}]) against the window at
    `exe`, and holds the answer in `answer`. Call `start` from setUpClass and `stop` from tearDownClass."""

    def __init__(self, exe: Path, work: Path, cases: list, hold: str):
        self.work, self.exe = work, exe
        self.home = work / "home"
        (self.home / "runtime").mkdir(parents=True)
        (self.home / "app" / "src").mkdir(parents=True)
        source = work / "fake.cs"
        source.write_text(FAKE, encoding="utf-8")
        for name in ("python.exe", "pythonw.exe"):
            subprocess.run([str(CSC), "/nologo", "/target:exe", "/out:" + str(self.home / "runtime" / name), str(source)],
                           check=True, capture_output=True, timeout=300, creationflags=NO_WINDOW)
        (work / "strings.json").write_text(json.dumps({"ok": True, "language": "en", "strings": l10n.catalog("en")},
                                                      ensure_ascii=False), encoding="utf-8")
        shots = snapshots(1_800_000_000.0)
        for name, shot in shots.items():
            (work / ("snapshot-%s.json" % name)).write_text(json.dumps(shot), encoding="utf-8")
        (work / "cases.json").write_text(json.dumps([dict(case, snapshot="snapshot-%s.json" % case["snapshot"])
                                                     for case in cases]), encoding="utf-8")
        self.failed = work / "probe.failed"
        self.hold = hold

    def run(self) -> dict:
        try:
            return run_probe(PROBE, self.work, 600, CAR_EXE=str(self.exe), CAR_HOME=str(self.home),
                             CAR_FAKE_HOLD=self.hold, CAR_FAKE_GATE=str(self.work / "gate"))
        except Exception:
            return {}

    def failure(self) -> str:
        return self.failed.read_text(encoding="utf-8") if self.failed.is_file() else ""

    def stop(self) -> None:
        script = ("Get-Process -Name python,pythonw -ErrorAction SilentlyContinue | Where-Object { $_.Path -and "
                  "$_.Path.StartsWith($env:CAR_HOME, [StringComparison]::OrdinalIgnoreCase) } | Stop-Process -Force")
        subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                       timeout=120, creationflags=NO_WINDOW, env=dict(os.environ, CAR_HOME=str(self.home)))
