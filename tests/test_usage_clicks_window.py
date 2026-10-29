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
from test_engine import T1, T2, TURN_A, TURN_B, Harness  # noqa: E402
from codex_auto_resume import config, control, controlcli, l10n  # noqa: E402
from codex_auto_resume.control import actions as control_actions  # noqa: E402
from codex_auto_resume.store.actions import RECHECKED  # noqa: E402

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
function Wait-For([string]$command, [int]$count) {
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    while ([DateTime]::UtcNow -lt $deadline) {
        [Windows.Forms.Application]::DoEvents()
        $seen = @([Recorder]::Seen() | Where-Object { $_.StartsWith($command + "`n") }).Count
        if ($seen -ge $count -and [int]$F.GetField('busy', $flags).GetValue($script:form) -eq 0) { return }
        Start-Sleep -Milliseconds 20
    }
    throw ('the window made no ' + $command + ' call')
}
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
    # No seam, no click that asks: the window's own dialog must never open on anyone's desktop.
    if (-not $dialogs) { throw 'the window has no DialogAnswers: a click that asks would show a dialog' }
    $dialogs.SetValue($null, [Delegate]::CreateDelegate($dialogs.FieldType, [Recorder].GetMethod('Yes')))
    $dashboard = Parse 'dashboard.json'
    [Recorder]::Replies['dashboard'] = $dashboard
    [Recorder]::Replies['retry-now'] = (Parse 'retry.json')
    [string]$nowhere = Join-Path $env:CAR_WORK 'nowhere'
    $bridge = $BT.GetConstructor($flags, $null, [type[]]@([string]), $null).Invoke([object[]]@($nowhere))
    $persistent = $PB.GetConstructor($flags, $null, [type[]]@([string], $BT), $null).Invoke([object[]]@($nowhere, $bridge))
    $catalog = Parse 'strings.json'
    $make = $F.GetConstructor($flags, $null, [type[]]@($PB, [Collections.Generic.Dictionary[string,object]], [Drawing.Font]), $null)
    $script:form = $make.Invoke([object[]]@($persistent, $catalog, [Drawing.SystemFonts]::MessageBoxFont))
    $F.GetField('auditing', $flags).SetValue($form, $true)
    $form.TopLevel = $false
    $form.ClientSize = New-Object Drawing.Size 1100, 760
    $form = $script:form
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
    Wait-For 'retry-now' 1
    $out.note = [string]$F.GetField('pendingNoteText', $flags).GetValue($form)
    # Rescan, "check all": the second scene's two usage-waiting rows, the button, its question, its call and its note.
    $rescanned = Parse 'dashboard-rescan.json'
    [Recorder]::Replies['dashboard'] = $rescanned
    [Recorder]::Replies['rescan'] = (Parse 'rescan-asked.json')
    $F.GetMethod('ApplySnapshot', $flags).Invoke($form, [object[]]@($rescanned)) | Out-Null
    $list.Items[0].Selected = $true
    $F.GetMethod('UpdatePendingButtons', $flags).Invoke($form, $null) | Out-Null
    $out.rescanEnabled = [bool]$F.GetField('rescanButton', $flags).GetValue($form).Enabled
    $out.rescanText = [string]$F.GetField('rescanButton', $flags).GetValue($form).Text
    $F.GetMethod('Rescan', $flags).Invoke($form, $null) | Out-Null
    Wait-For 'rescan' 1
    $out.rescanNote = [string]$F.GetField('pendingNote', $flags).GetValue($form).Text
    # And under a Pause: the reply says why no usage was read, and the note says it in words.
    [Recorder]::Replies['rescan'] = (Parse 'rescan-paused.json')
    $F.GetMethod('Rescan', $flags).Invoke($form, $null) | Out-Null
    Wait-For 'rescan' 2
    $out.pausedNote = [string]$F.GetField('pendingNote', $flags).GetValue($form).Text
    # Why it is waiting: each row's reading, led by the button that asked it; the note under the buttons says none of it.
    $readings = Parse 'dashboard-readings.json'
    [Recorder]::Replies['dashboard'] = $readings
    $F.GetField('pendingNoteFor', $flags).SetValue($form, $null)
    $F.GetMethod('ApplySnapshot', $flags).Invoke($form, [object[]]@($readings)) | Out-Null
    $explain = $F.GetField('explainList', $flags).GetValue($form)
    $out.explain = @()
    $out.notes = @()
    foreach ($index in 0, 1) {
        $list.SelectedIndices.Clear()
        $list.Items[$index].Selected = $true
        $F.GetMethod('ShowExplain', $flags).Invoke($form, $null) | Out-Null
        $F.GetMethod('ShowPendingNote', $flags).Invoke($form, $null) | Out-Null
        $out.explain += [string]$explain.GetType().GetProperty('Note', $flags).GetValue($explain, $null)
        $out.notes += [string]$F.GetField('pendingNote', $flags).GetValue($form).Text
    }
    $out.order = @(foreach ($item in $list.Items) { [string]$item.Tag['interruption_id'] })
    $out.calls = @([Recorder]::Seen())
    $form.Dispose()
} catch {
    [Console]::Error.WriteLine($_.Exception.ToString())
    exit 3
}
$out | ConvertTo-Json -Depth 5 -Compress
"""


class Scene:
    """One usage-limited conversation waiting for a reset an hour ahead, on test_engine's harness, in a home of its own."""

    def __init__(self, folder: Path, threads=((T1, TURN_A),)):
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
        for thread, turn in threads:
            self.h.home.fail_usage(thread, turn)
            self.h.backend.loaded_map[thread] = "loaded"
        self.h.tick()
        self.threads = [thread for thread, _turn in threads]
        self.key = self.h.record()["interruption_id"]
        for thread in self.threads:
            assert self.h.record(thread)["state"] == "waiting_reset" and self.h.record(thread)["reset_at"] > self.h.now

    def control(self):
        return control.Control(self.paths)

    def ask(self, command, payload):
        """The bridge's own dispatch, as the window's call reaches it, on the harness's clock with a watcher to wake."""
        with mock.patch.object(control_actions.WakeEvent, "signal", lambda _self: True), \
                mock.patch("time.time", lambda: self.h.now), \
                mock.patch("codex_auto_resume.rescan.judge_for", lambda _control: lambda _row, _kin: (RECHECKED, None)):
            # The rescan's judge stands in for the one that reads a Codex home: nothing here reads this machine's Codex.
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
        cls.rescan_scene = Scene(work / "rescan", ((T1, TURN_A), (T2, TURN_B)))
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll",
                        "/reference:System.Windows.Forms.dll", *[str(path) for path in guiscan.sources()]],
                       check=True, capture_output=True, timeout=300,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        write = lambda name, value: (work / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        write("strings.json", {"ok": True, "language": "en", "strings": l10n.catalog("en")})
        write("rows.json", {name: row for name, (_scene, row, _answer) in cls.cases.items()})
        write("dashboard.json", cls.scene.ask("dashboard", {}))
        write("retry.json", {"ok": True, "result": {"interruption_id": cls.scene.key, "usage_check": "asked",
                                                    "eligible_at": cls.scene.h.now, "woke": True}})
        write("dashboard-rescan.json", cls.rescan_scene.ask("dashboard", {}))
        counts = {"scanned": 2, "not_waiting": 0, "retired": 0, "rechecked": 2, "unresolved": 0, "changed": 0,
                  "records": [], "woke": True}
        write("rescan-asked.json", {"ok": True, "result": dict(counts, usage_check="asked", usage_asked=2)})
        write("rescan-paused.json", {"ok": True, "result": dict(counts, usage_check="paused", usage_asked=0)})
        readings = cls.rescan_scene.ask("dashboard", {})
        cls.readings = {}
        for row, source in zip(readings["pending"], ("rescan", "retry_now")):
            row["usage_check"] = {"at": cls.rescan_scene.h.now - 30, "read": "still_limited", "lifted": False,
                                  "why": None, "continued": False, "source": source}
            cls.readings[row["interruption_id"]] = source
            # As the watcher records a look: the panel says its sentences under the checks it lists.
            row["gates"] = row.get("gates") or {"schedule": ["WAIT", "waiting_reset"]}
            row["gates_at"] = row.get("gates_at") or cls.rescan_scene.h.now - 40
        write("dashboard-readings.json", readings)
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
        cls.rescan_scene.close()
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

    def test_rescan_is_offered_asks_first_and_says_it_reads_usage_once(self):
        english = l10n.catalog("en")
        self.assertEqual(self.answer["rescanText"], english["action.rescan"])
        self.assertEqual(english["action.rescan"], "Rescan")
        self.assertTrue(self.answer["rescanEnabled"])
        dialogs = [call for call in self.answer["calls"] if call.startswith("dialog\n")]
        self.assertTrue(dialogs and "read Codex's usage once" in dialogs[0], dialogs)
        calls = [call for call in self.answer["calls"] if call.startswith("rescan\n")]
        self.assertEqual(calls, ["rescan\n", "rescan\n"], "the bridge's no-argument rescan, once a click")
        self.assertIn("Rechecked: 2", self.answer["rescanNote"])
        self.assertIn(english["rescan.usage_asked"].replace("{n}", "2"), self.answer["rescanNote"])

    def test_rescan_says_why_no_usage_was_read_under_a_pause(self):
        """Retry now is not offered under a Pause; Rescan is how the click says why nothing was read."""
        self.assertIn(l10n.catalog("en")["retry.not_checked.paused"], self.answer["pausedNote"])

    def test_the_windows_rescan_reaches_one_usage_read_for_every_waiting_recovery(self):
        calls = [call.split("\n", 1) for call in self.answer["calls"] if call.startswith("rescan\n")]
        reply = self.rescan_scene.ask(calls[0][0], {})
        self.assertEqual((reply["result"]["usage_check"], reply["result"]["usage_asked"]), ("asked", 2))
        before = self.rescan_scene.reads
        self.rescan_scene.h.tick(advance=1)
        self.assertEqual(self.rescan_scene.reads - before, 1, "one reading for both")
        for thread in self.rescan_scene.threads:
            self.assertLess(self.rescan_scene.h.record(thread)["reset_at"], self.rescan_scene.h.now + 1)

    def test_why_it_is_waiting_says_each_reading_and_who_asked_it(self):
        """Fails with the reading said under the buttons instead (beta.2): the panel names no reading of a click."""
        english = l10n.catalog("en")
        limited = english["retry.checked_limited"].split("{time}")[0]
        for index, key in enumerate(self.answer["order"][:2]):
            with self.subTest(index):
                by = english["action.rescan"] if self.readings[key] == "rescan" else english["action.retry_now"]
                lines = [line for line in self.answer["explain"][index].split("\n") if limited in line]
                self.assertEqual(len(lines), 1, self.answer["explain"][index])
                self.assertTrue(lines[0].startswith(by + " · "), lines[0])
                self.assertNotIn(limited, self.answer["notes"][index], "the note under the buttons says only what a click did")


if __name__ == "__main__":
    unittest.main()
