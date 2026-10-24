r"""v0.6.16-beta.3, issue #31: Settings' "Run at Windows sign-in" shows what Windows holds.

The switch was set from the page's own status read alone (RefreshStatusAsync), built off and left off
until that read came back - so it showed off while the read was on its way, and for good after one that
failed, though the Run value was there and the status said startup_enabled true. Save then wrote what it
showed, whatever was saved: a switch never read removed the entry the person had kept, and one read before
the entry was removed elsewhere put it back.

Now any status read that says it - the Dashboard's snapshot too - sets what an edit of the switch is measured
from, and the switch shows it unless the person has moved it: a move, before any read or since the last, is
never taken back while it is unsaved, by a snapshot or by the page's own read (review findings 1 and 2). Save
writes the entry only where the person moved the switch from what Windows holds; a move made before any read
worked is read for first, and where that read fails too the entry is left alone, the move stays unsaved, and
the save says so instead of "Saved".

The source half reads the window with guiscan. The built half compiles the real window: one never shown and
asking no bridge (it is audited), driven through status answers; and one shown off-screen whose bridge is a
stand-in program answering as the test says, so Save itself runs and what it asks the bridge is recorded.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import guiscan
from codex_auto_resume import l10n, settings
from test_gui_v0611_access import CSC, NO_WINDOW, POWERSHELL, compile_window, reply, run_probe


def body(member: str) -> str:
    return guiscan.member_body("SettingsForm", member)


class SourceTests(unittest.TestCase):
    def test_save_writes_the_entry_only_where_the_person_moved_the_switch_from_what_was_read(self):
        save = body("Save")
        self.assertIn("if (startup != null && startupKnown && startAtSignIn != startupBaseline)", save)
        self.assertIn("else registeredThen(null);", save)
        # A move made before any read worked is read for first, and a read that fails too is said.
        self.assertIn('CallAsync("status", null,', save)
        self.assertIn('S("settings.startup_unchecked",', save)

    def test_a_build_forgets_what_was_read(self):
        self.assertIn("startupKnown = false;", body("BuildEditors"))

    def test_every_status_read_reaches_the_switch_through_one_place(self):
        self.assertIn("KnowStartup(status, startup);", body("ApplyStatus"))
        know = body("KnowStartup")
        self.assertIn('editors.ContainsKey("__startup")', know)
        self.assertIn("if (!moved) startup.Checked = startupBaseline;", know)

    def test_the_sentence_is_in_every_language(self):
        english = l10n._read("en")["settings.startup_unchecked"]
        self.assertIn('"settings.startup_unchecked", "%s"' % english, body("Save"))
        for locale in l10n.LOCALES:
            with self.subTest(locale):
                self.assertTrue(l10n._read(locale).get("settings.startup_unchecked"))


# A stand-in for the installation's python.exe: the bridge runs `python.exe [-X OPTION ...] -c CODE APP_SRC serve` (one request a
# line) or `python.exe -c CODE APP_SRC COMMAND [-]`. It answers status as CAR_FAKE_STATUS says (fail, true or
# false; after a startup write, what was written), update and startup with ok, and writes each command - startup
# with its argument - to CAR_FAKE_LOG.
FAKE = r"""
using System;
using System.IO;
using System.Text.RegularExpressions;
static class Fake {
    static string Answer(string command, string argument) {
        string log = Environment.GetEnvironmentVariable("CAR_FAKE_LOG");
        File.AppendAllText(log, command + (command == "startup" ? " " + argument : "") + "\n");
        string state = Environment.GetEnvironmentVariable("CAR_FAKE_STATUS") ?? "fail";
        string held = log + ".registered";
        if (state != "fail" && File.Exists(held)) state = File.ReadAllText(held);
        if (command == "startup") File.WriteAllText(held, argument.Contains("true") ? "true" : "false");
        if (command == "status")
            return state == "fail" ? "{\"ok\":false,\"error\":\"unread\"}"
                 : "{\"ok\":true,\"status\":{\"watcher_running\":false,\"startup_enabled\":" + state + "}}";
        if (command == "update") return "{\"ok\":true}";
        if (command == "startup") return "{\"ok\":true,\"startup_enabled\":" + (argument.Contains("true") ? "true" : "false") + "}";
        return "{\"ok\":false,\"error\":\"unknown\"}";
    }
    static int Main(string[] args) {
        // The interpreter's own options come first (-X disable-remote-debug, v0.6.19-beta.3), as python.exe reads them.
        int options = 0;
        while (options + 1 < args.Length && args[options] == "-X") options += 2;
        if (options > 0) { var rest = new string[args.Length - options]; System.Array.Copy(args, options, rest, 0, rest.Length); args = rest; }
        string command = args.Length > 3 ? args[3] : "";
        if (command != "serve") {
            string argument = args.Length > 4 && args[4] == "-" ? Console.In.ReadToEnd() : "";
            Console.Out.Write(Answer(command, argument));
            return 0;
        }
        string line;
        while ((line = Console.In.ReadLine()) != null) {
            string id = Regex.Match(line, "\"id\":(\\d+)").Groups[1].Value;
            string name = Regex.Match(line, "\"command\":\"([a-z_-]+)\"").Groups[1].Value;
            Match given = Regex.Match(line, "\"argument\":(\\{[^}]*\\})");
            Console.Out.Write("{\"id\":" + id + ",\"reply\":" + Answer(name, given.Success ? given.Groups[1].Value : "") + "}\n");
            Console.Out.Flush();
        }
        return 0;
    }
}
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box C# compiler and Windows PowerShell")
class BuiltSwitchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = compile_window(work)
        home = work / "home"
        (home / "runtime").mkdir(parents=True)
        (home / "app" / "src").mkdir(parents=True)
        source = work / "fake.cs"
        source.write_text(FAKE, encoding="utf-8")
        subprocess.run([str(CSC), "/nologo", "/target:exe", "/out:" + str(home / "runtime" / "python.exe"), str(source)],
                       check=True, capture_output=True, timeout=300, creationflags=NO_WINDOW)
        (work / "schema.json").write_text(json.dumps(settings.describe(), ensure_ascii=False), encoding="utf-8")
        (work / "settings.json").write_text(json.dumps(settings.defaults(), ensure_ascii=False), encoding="utf-8")
        (work / "strings-en.json").write_text(json.dumps(reply("en"), ensure_ascii=False), encoding="utf-8")
        cls.answer = run_probe(PROBE, work, 600, CAR_EXE=str(exe), CAR_HOME=str(home))
        cls.english = l10n._read("en")

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_before_any_read_nothing_is_known(self):
        self.assertEqual(self.answer["unread"], {"on": False, "known": False, "dirty": False})

    def test_a_status_without_the_answer_changes_nothing(self):
        self.assertEqual(self.answer["silent"], {"on": False, "known": False, "dirty": False})

    def test_a_snapshot_that_says_it_is_registered_turns_it_on(self):
        self.assertEqual(self.answer["snapshot"], {"on": True, "known": True, "dirty": False})

    def test_a_snapshot_never_takes_back_a_change_not_yet_saved(self):
        self.assertEqual(self.answer["edited"], {"on": False, "known": True, "dirty": True})

    def test_nor_does_the_page_s_own_read(self):
        """Review finding 2: Start watcher's refresh used to put an unsaved move back."""
        self.assertEqual(self.answer["own"], {"on": False, "known": True, "dirty": True})

    def test_once_windows_holds_what_the_switch_shows_nothing_is_unsaved(self):
        self.assertEqual(self.answer["agreed"], {"on": False, "known": True, "dirty": False})

    def test_a_move_before_any_read_survives_the_first_snapshot(self):
        """Review finding 1: the snapshot's first read used to overwrite it."""
        self.assertEqual(self.answer["early"], {"on": True, "known": True, "dirty": True})

    def test_save_with_nothing_readable_leaves_the_entry_keeps_the_move_and_says_so(self):
        save = self.answer["saves"]["unreadable"]
        self.assertEqual(save["asked"][:2], ["update", "status"])
        self.assertFalse([call for call in save["asked"] if call.startswith("startup")], save["asked"])
        self.assertEqual(save["after"], {"on": True, "known": False, "dirty": True})
        self.assertEqual(save["said"], self.english["settings.startup_unchecked"])

    def test_save_reads_first_and_then_writes_the_move(self):
        save = self.answer["saves"]["read first"]
        self.assertEqual(save["asked"][:3], ["update", "status", 'startup {"enabled":true}'])
        self.assertEqual(save["after"], {"on": True, "known": True, "dirty": False})
        self.assertEqual(save["said"], self.english["settings.saved"])

    def test_a_move_windows_already_holds_writes_nothing(self):
        save = self.answer["saves"]["already held"]
        self.assertFalse([call for call in save["asked"] if call.startswith("startup")], save["asked"])
        self.assertEqual(save["after"], {"on": True, "known": True, "dirty": False})

    def test_a_save_of_something_else_never_writes_the_entry(self):
        save = self.answer["saves"]["untouched"]
        self.assertEqual(save["asked"][0], "update")
        self.assertFalse([call for call in save["asked"] if call.startswith("startup")], save["asked"])
        self.assertEqual(save["said"], self.english["settings.saved"])


PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$flags = [Reflection.BindingFlags]'Instance,Static,NonPublic,Public'
$F = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$PB = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
$BT = $assembly.GetType('CodexAutoResume.Bridge', $true)
$J = $assembly.GetType('CodexAutoResume.Json', $true)
$utf8 = New-Object Text.UTF8Encoding $false
function Read($name) { return [IO.File]::ReadAllText((Join-Path $env:CAR_WORK $name), $utf8) }
function Parse([string]$text) { return ,$J.GetMethod('Parse', $flags).Invoke($null, [object[]]@($text)) }
function Call($name, $arguments) {
  $given = New-Object 'object[]' $arguments.Count
  for ($i = 0; $i -lt $arguments.Count; $i++) {
    $value = $arguments[$i]
    if ($null -ne $value -and $value -is [psobject]) { $value = $value.PSObject.BaseObject }
    $given[$i] = $value
  }
  return $F.GetMethod($name, $flags).Invoke($form, $given)
}
function Field($name) { return $F.GetField($name, $flags).GetValue($form) }
$make = $F.GetConstructor($flags, $null, [type[]]@($PB, [Collections.Generic.Dictionary[string,object]], [Drawing.Font]), $null)
function NewWindow([string]$root) {
  $bridge = $BT.GetConstructor($flags, $null, [type[]]@([string]), $null).Invoke([object[]]@($root))
  $persistent = $PB.GetConstructor($flags, $null, [type[]]@([string], $BT), $null).Invoke([object[]]@($root, $bridge))
  $window = $make.Invoke([object[]]@($persistent.PSObject.BaseObject, (Parse (Read 'strings-en.json')), [Drawing.SystemFonts]::MessageBoxFont))
  $F.GetField('auditing', $flags).SetValue($window, $true)
  return $window
}
function InFlight() { return [int]$PB.GetProperty('InFlight', $flags).GetValue((Field 'bridge'), $null) }
function Switch() { return (Field 'editors')['__startup'] }
function Now() { return @{ on = [bool](Switch).Checked; known = [bool](Field 'startupKnown'); dirty = [bool](Call 'Dirty' @()) } }
$registered = '{"watcher_running": false, "startup_enabled": true}'
$unregistered = '{"watcher_running": false, "startup_enabled": false}'
$out = @{}

# Driven through status answers, in a window never shown that asks no bridge.
$form = NewWindow (Join-Path $env:CAR_WORK 'nowhere')
$form.TopLevel = $false
$form.ClientSize = New-Object Drawing.Size 1000, 664
Call 'BuildEditors' @((Parse (Read 'schema.json')), (Parse (Read 'settings.json'))) | Out-Null
$out.unread = Now
# A status that does not say it (an older bridge's) leaves the switch as it was.
Call 'ApplyStatus' @((Parse '{"watcher_running": false}'), $null) | Out-Null
$out.silent = Now
# The Dashboard's snapshot: ApplyStatus is handed no switch.
Call 'ApplyStatus' @((Parse $registered), $null) | Out-Null
$out.snapshot = Now
# The person turns it off and has not saved: the next snapshot leaves that alone ...
(Switch).Checked = $false
Call 'ApplyStatus' @((Parse $registered), $null) | Out-Null
$out.edited = Now
# ... and so does the page's own read, after a start (finding 2).
Call 'ApplyStatus' @((Parse $registered), (Switch)) | Out-Null
$out.own = Now
# Windows comes to hold what the switch shows: nothing is left unsaved.
Call 'ApplyStatus' @((Parse $unregistered), $null) | Out-Null
$out.agreed = Now
$form.Dispose()
# A move before any read, then the first snapshot (finding 1).
$form = NewWindow (Join-Path $env:CAR_WORK 'nowhere')
$form.TopLevel = $false
Call 'BuildEditors' @((Parse (Read 'schema.json')), (Parse (Read 'settings.json'))) | Out-Null
(Switch).Checked = $true
Call 'ApplyStatus' @((Parse $unregistered), $null) | Out-Null
$out.early = Now
$form.Dispose()

# Save itself, in a window shown off-screen whose bridge is the stand-in.
$log = Join-Path $env:CAR_WORK 'asked.txt'
$env:CAR_FAKE_LOG = $log
function Settle() {
  $clock = [Diagnostics.Stopwatch]::StartNew()
  do { [Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 10 }
  while (([int](Field 'busy') -gt 0 -or (InFlight) -gt 0) -and $clock.ElapsedMilliseconds -lt 60000)
  $clock.Restart()
  do { [Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 10 } while ($clock.ElapsedMilliseconds -lt 500)
  do { [Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 10 }
  while (([int](Field 'busy') -gt 0 -or (InFlight) -gt 0) -and $clock.ElapsedMilliseconds -lt 60000)
}
function SaveCase([string]$status, [string]$known, [bool]$move) {
  $env:CAR_FAKE_STATUS = $status
  if (Test-Path $log) { Remove-Item $log }
  if (Test-Path ($log + '.registered')) { Remove-Item ($log + '.registered') }
  $script:form = NewWindow $env:CAR_HOME
  $form.StartPosition = 'Manual'
  $form.Location = New-Object Drawing.Point -4000, -4000
  $form.ShowInTaskbar = $false
  $form.Show()
  [Windows.Forms.Application]::DoEvents()
  Call 'BuildEditors' @((Parse (Read 'schema.json')), (Parse (Read 'settings.json'))) | Out-Null
  if ($known) { Call 'ApplyStatus' @((Parse $known), $null) | Out-Null }
  if ($move) { (Switch).Checked = $true }
  if (Test-Path $log) { Remove-Item $log }
  Call 'Save' @() | Out-Null
  Settle
  $asked = @()
  if (Test-Path $log) { $asked = @([IO.File]::ReadAllLines($log) | Where-Object { $_ -ne '' }) }
  $result = @{ asked = $asked; after = (Now); said = [string](Field 'detail').Text }
  $PB.GetMethod('Stop', $flags).Invoke((Field 'bridge'), [object[]]@()) | Out-Null
  $form.Close()
  $form.Dispose()
  return $result
}
$out.saves = @{}
$out.saves['unreadable'] = SaveCase 'fail' $null $true
$out.saves['read first'] = SaveCase 'false' $null $true
$out.saves['already held'] = SaveCase 'true' $null $true
$out.saves['untouched'] = SaveCase 'true' $registered $false
[IO.File]::WriteAllText((Join-Path $env:CAR_WORK 'result.json'), ($out | ConvertTo-Json -Depth 6 -Compress), $utf8)
"""


if __name__ == "__main__":
    unittest.main()
