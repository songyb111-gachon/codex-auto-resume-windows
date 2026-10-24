r"""v0.6.19 (issue #50; the owner, 2026-10-24): "check one" - Retry now - is offered where it reads usage, and the window's
own click reaches the engine's usage read.

beta.2 taught Retry now to read Codex's usage once for a recovery that waits for a usage reset still ahead - and left the
window's button greyed exactly there (CanRetryNow refused every reset ahead), so its headline could not be clicked. The
button's rule and the control's must agree - a parity test: the rows here are the control's own Pending rows, read by the compiled window
through its own JSON reader, and the click is the window's own handler (RetryNow, through UpdatePendingButtons' Enabled)
with the bridge answered by a recorder - whose request is then handed to the bridge's own dispatch, and the engine ticks.

* Offered on a usage limit's reset ahead, and the click asks for a reading (`usage_check` asked).
* Not offered where it can do nothing and the reason is in view: recovery paused, the conversation off, held for a
  person, a postponement of the person's own still ahead - and the control asks nothing there either.
* Offered under Observe only, where the control answers why it read nothing (the click says it in words).
Either side drifting fails it: the window offering where the control asks nothing, or the control asking where the
window greys the button (the reachability audit of 2026-10-24).

* The window's click: the button enabled, its handler's request, the bridge's dispatch of it, one usage read at the
  engine's next look, and the recovery goes on (Codex says the limit lifted).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import guiscan
from test_engine import T1, TURN_A, Harness  # noqa: E402
from codex_auto_resume import config, control, controlcli, l10n  # noqa: E402
from codex_auto_resume.control import actions as control_actions  # noqa: E402

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")

PROBE = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
# Never a dialog on anyone's desktop: an unhandled exception throws here instead of showing .NET's box.
[Windows.Forms.Application]::SetUnhandledExceptionMode([Windows.Forms.UnhandledExceptionMode]::ThrowException)
Add-Type -TypeDefinition @'
using System.Collections.Generic;
public static class Recorder
{
    public static readonly List<string> Calls = new List<string>();
    public static readonly Dictionary<string, Dictionary<string, object>> Replies = new Dictionary<string, Dictionary<string, object>>();
    public static Dictionary<string, object> Answer(string command, string argument)
    {
        lock (Calls) Calls.Add(command + "\n" + (argument ?? ""));
        Dictionary<string, object> reply;
        lock (Replies) if (Replies.TryGetValue(command, out reply)) return reply;
        var none = new Dictionary<string, object>();
        none["ok"] = false;
        none["error"] = "not answered here";
        return none;
    }
    public static bool Yes(string text, string affirm)
    {
        lock (Calls) Calls.Add("dialog\n" + text);
        return affirm != null;
    }
    public static string[] Seen() { lock (Calls) return Calls.ToArray(); }
}
'@
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$F = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$PB = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
$BT = $assembly.GetType('CodexAutoResume.Bridge', $true)
$J = $assembly.GetType('CodexAutoResume.Json', $true)
$Soft = $assembly.GetType('CodexAutoResume.Soft', $true)
$flags = [Reflection.BindingFlags]'Instance,Static,NonPublic,Public'
$utf8 = New-Object Text.UTF8Encoding $false
function Parse($name) { return ,$J.GetMethod('Parse', $flags).Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $env:CAR_WORK $name), $utf8))) }
$out = @{ retry = @{} }
try {
    $Soft.GetField('StillNow', $flags).SetValue($null, [double]$env:CAR_NOW)
    $can = $F.GetMethod('CanRetryNow', $flags)
    $rows = Parse 'rows.json'
    foreach ($name in @($rows.Keys)) {
        $out.retry[$name] = [bool]$can.Invoke($null, [object[]]@($rows[$name], $true, [double]$env:CAR_NOW))
    }
    $answer = [Delegate]::CreateDelegate($PB.GetField('Answers', $flags).FieldType, [Recorder].GetMethod('Answer'))
    $PB.GetField('Answers', $flags).SetValue($null, $answer)
    $dialogs = $F.GetField('DialogAnswers', $flags)
    if ($dialogs) { $dialogs.SetValue($null, [Delegate]::CreateDelegate($dialogs.FieldType, [Recorder].GetMethod('Yes'))) }
    $dashboard = Parse 'dashboard.json'
    [Recorder]::Replies['dashboard'] = $dashboard
    [Recorder]::Replies['retry-now'] = (Parse 'retry.json')
    [string]$nowhere = Join-Path $env:CAR_WORK 'nowhere'
    $bridge = $BT.GetConstructor($flags, $null, [type[]]@([string]), $null).Invoke([object[]]@($nowhere))
    $persistent = $PB.GetConstructor($flags, $null, [type[]]@([string], $BT), $null).Invoke([object[]]@($nowhere, $bridge))
    $catalog = (Parse 'strings.json')['strings']
    $make = $F.GetConstructor($flags, $null, [type[]]@($PB, [Collections.Generic.Dictionary[string,object]], [Drawing.Font]), $null)
    $form = $make.Invoke([object[]]@($persistent, $catalog, [Drawing.SystemFonts]::MessageBoxFont))
    $F.GetField('auditing', $flags).SetValue($form, $true)
    $form.TopLevel = $false
    $form.ClientSize = New-Object Drawing.Size 1100, 760
    $null = $form.Handle
    $F.GetMethod('ShowPage', $flags).Invoke($form, [object[]]@('pending')) | Out-Null
    $F.GetMethod('ApplySnapshot', $flags).Invoke($form, [object[]]@($dashboard)) | Out-Null
    $list = $F.GetField('pendingList', $flags).GetValue($form)
    $null = $list.Handle
    $out.rows = [int]$list.Items.Count
    $list.Items[0].Selected = $true
    $F.GetMethod('UpdatePendingButtons', $flags).Invoke($form, $null) | Out-Null
    $button = $F.GetField('retryButton', $flags).GetValue($form)
    $out.enabled = [bool]$button.Enabled
    # The window's own handler, as the button's click runs it.
    $F.GetMethod('RetryNow', $flags).Invoke($form, $null) | Out-Null
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    while ([DateTime]::UtcNow -lt $deadline) {
        [Windows.Forms.Application]::DoEvents()
        $done = @([Recorder]::Seen() | Where-Object { $_.StartsWith("retry-now`n") }).Count -gt 0
        if ($done -and [int]$F.GetField('busy', $flags).GetValue($form) -eq 0) { break }
        Start-Sleep -Milliseconds 20
    }
    $out.calls = @([Recorder]::Seen())
    $out.note = [string]$F.GetField('pendingNoteText', $flags).GetValue($form)
    $form.Dispose()
} catch {
    [Console]::Error.WriteLine($_.Exception.ToString())
    exit 3
}
$out | ConvertTo-Json -Depth 5 -Compress
"""


class Scene:
    """One usage-limited conversation waiting for a reset an hour ahead, on test_engine's harness, in a home of its own."""

    def __init__(self, folder: Path):
        self.paths = config.Paths(folder / "home")
        self.paths.ensure()
        self.h = Harness(self.paths.state_dir)
        self.h.enable()
        self.reads = 0
        usage = self.h.backend.usage

        def counted():
            self.reads += 1
            return usage()
        self.h.backend.usage = counted
        self.h.home.fail_usage(T1, TURN_A)
        self.h.backend.loaded_map[T1] = "loaded"
        self.h.tick()
        self.key = self.h.record()["interruption_id"]
        assert self.h.record()["state"] == "waiting_reset" and self.h.record()["reset_at"] > self.h.now

    def control(self):
        return control.Control(self.paths)

    def ask(self, command, payload):
        """The bridge's own dispatch, as the window's call reaches it, on the harness's clock with a watcher to wake."""
        with mock.patch.object(control_actions.WakeEvent, "signal", lambda _self: True), \
                mock.patch("time.time", lambda: self.h.now):
            return controlcli.dispatch(self.control(), command, payload)

    def row(self):
        with mock.patch("time.time", lambda: self.h.now):
            (row,) = [row for row in self.control().list_pending() if row["thread_id"] == T1]
        return row

    def close(self):
        self.h.close()


def _cases(folder: Path) -> dict:
    """name -> (scene, the row as the control lists it, what a Dashboard Retry now answers for usage)."""
    found = {}
    for name in ("plain", "paused", "off", "held", "postponed", "observe"):
        scene = Scene(folder / name)
        store = scene.h.store
        if name == "paused":
            store.set_enabled(False, scene.h.now)
        elif name == "off":
            store.set_thread_enabled(T1, False, actor="gui")
        elif name == "held":
            store.hold_waiting([scene.key], "ask", scene.h.now)
        elif name == "postponed":
            store.postpone(scene.key, T1, scene.h.now + 7200, scene.h.now)
        elif name == "observe":
            store.set_observe_only(True)
        row = scene.row()
        answer = scene.ask("retry-now", {"interruption_id": scene.key})
        found[name] = (scene, row, answer)
    return found


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class CheckOneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        work = Path(cls.folder.name)
        cls.cases = _cases(work / "cases")
        # The click's scene: a fresh one, untouched by a Retry now.
        cls.scene = Scene(work / "click")
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll",
                        "/reference:System.Windows.Forms.dll", *[str(path) for path in guiscan.sources()]],
                       check=True, capture_output=True, timeout=300,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        write = lambda name, value: (work / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        write("strings.json", {"strings": l10n.catalog("en")})
        write("rows.json", {name: row for name, (_scene, row, _answer) in cls.cases.items()})
        write("dashboard.json", cls.scene.ask("dashboard", {}))
        write("retry.json", {"ok": True, "result": {"interruption_id": cls.scene.key, "usage_check": "asked",
                                                    "eligible_at": cls.scene.h.now, "woke": True}})
        probe = work / "probe.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        cls.result = subprocess.run(
            [str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=dict(os.environ, CAR_EXE=str(exe), CAR_WORK=str(work), CAR_NOW=repr(cls.scene.h.now)))
        cls.answer = json.loads(cls.result.stdout) if cls.result.returncode == 0 and cls.result.stdout.strip() else {}

    @classmethod
    def tearDownClass(cls):
        for scene, _row, _answer in cls.cases.values():
            scene.close()
        cls.scene.close()
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-3000:])

    def test_it_is_offered_on_a_usage_reset_ahead_and_the_click_asks_for_a_reading(self):
        """Fails with CanRetryNow's old rule: every reset ahead greyed the button beta.2's reading is behind."""
        self.assertTrue(self.answer["retry"]["plain"])
        self.assertEqual(self.cases["plain"][2]["result"]["usage_check"], "asked")

    def test_it_is_not_offered_where_the_reason_is_in_view_and_the_control_asks_nothing_there(self):
        for name, expected in (("paused", "paused"), ("off", "conversation_off"), ("held", None), ("postponed", None)):
            with self.subTest(name):
                self.assertFalse(self.answer["retry"][name])
                self.assertEqual(self.cases[name][2]["result"]["usage_check"], expected)
                self.assertEqual(self.cases[name][0].h.store.usage_checks_asked(self.cases[name][0].h.now), {})

    def test_under_observe_only_it_is_offered_and_the_answer_says_why_nothing_was_read(self):
        self.assertTrue(self.answer["retry"]["observe"])
        self.assertEqual(self.cases["observe"][2]["result"]["usage_check"], "observe_only")

    def test_the_windows_own_click_reaches_the_engines_usage_read(self):
        """The button enabled by the window's rule, its handler's request, the bridge's dispatch, one read, sent."""
        self.assertEqual(self.answer["rows"], 1)
        self.assertTrue(self.answer["enabled"], "the window's own UpdatePendingButtons greyed it")
        calls = [call.split("\n", 1) for call in self.answer["calls"] if call.startswith("retry-now\n")]
        self.assertEqual(len(calls), 1, self.answer["calls"])
        payload = json.loads(calls[0][1])
        self.assertEqual(payload, {"interruption_id": self.scene.key})
        self.assertIn("Checking usage now", self.answer["note"])
        reply = self.scene.ask(calls[0][0], payload)
        self.assertEqual(reply["result"]["usage_check"], "asked")
        before = self.scene.reads
        self.scene.h.tick(advance=1)
        self.assertEqual(self.scene.reads - before, 1, "read once, at the look the click asked for")
        self.assertEqual(len(self.scene.h.backend.send_calls), 1, "Codex said the limit lifted: it went on")


if __name__ == "__main__":
    unittest.main()
