r"""The Dashboard opens a Pending row's own dialog when the popup's row menu asks (v0.6.23; the owner, 2026-11-11:
"대시보드 창 띄우기").

The popup's Message for this conversation... and Add (or Change) words for this time... open the Dashboard on Pending
with that row and the Dashboard's own dialog for it - one dialog, no copy in the popup. The window is asked in one of
two ways, as any open from the watcher is (win/handover.py, ui/tray/dashboard.py):

* started with `--dialog=<dialog>:<interruption id>:<thread id>` (ParseArguments, RowDialogRequest), which also opens
  Pending - and a start a person made with it hands over to a window that is open, as `--page=` does (HandsOverOnStart,
  HandOverPage);
* handed to a window that is open: an open request whose text is "pending" and, on a second line, that same value
  (OpenRequestPage, OpenRequestRow, ComeForwardOn -> AskRowDialog).

Either way the value is checked strictly - a dialog of two, 64 lowercase hex digits, a canonical UUID - and the row is
checked against the rows read next, as every row action's identities are (RowForDialog, TakeRowAsked): the same
interruption and conversation, by the rules the row menu offers the item with. A row no longer waiting opens Pending
and nothing more.

The window is built and never shown (its own `auditing`, a bridge rooted where nothing is): a window nobody sees opens
no dialog, and says what it would have opened (`rowDialogOpened`) - so no dialog ever reaches the screen.

GUI test module: compiles the window, so it runs on its own (gui_lock.sh).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

import guiscan
from codex_auto_resume import l10n
from test_gui_layout import fullest_snapshot

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# The rows of fullest_snapshot: 1 waits for a reset, 2 is scheduled, 3 is a turn running in Codex (not waiting).
ROW = {index: (("%x" % index) * 64, "%08d-0000-7000-8000-000000000000" % index) for index in (1, 2, 3)}


def asked(dialog, index, thread=None):
    key, own = ROW[index]
    return "%s:%s:%s" % (dialog, key, thread or own)


GOOD = asked("once_words", 1)
MALFORMED = [
    "", "once_words", "once_words:" + ROW[1][0], "settings:%s:%s" % ROW[1], "Once_words:%s:%s" % ROW[1],
    "once_words:%s:%s" % ("AB" * 32, ROW[1][1]), "once_words:%s:%s" % (ROW[1][0][:-1], ROW[1][1]),
    "once_words:%s0:%s" % ROW[1], "once_words:%s:%s" % (ROW[1][0], "aaaaaaaa-0000-7000-8000-00000000000b"),
    "once_words:%s:{%s}" % ROW[1], "once_words:%s:%s:x" % ROW[1], "once_words:%s:%s " % ROW[1],
    "once_words:%s:%s" % (ROW[1][0], ROW[1][1].replace("-", "")), "message:%s:%s\n--page=x" % ROW[1],
]

PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
# A probe never shows a dialog: an exception is thrown here, never put in a window on the screen.
[Windows.Forms.Application]::SetUnhandledExceptionMode([Windows.Forms.UnhandledExceptionMode]::ThrowException)
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$script:F = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$R = $assembly.GetType('CodexAutoResume.OpenRequest', $true)
$PB = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
$BT = $assembly.GetType('CodexAutoResume.Bridge', $true)
$J = $assembly.GetType('CodexAutoResume.Json', $true)
$script:flags = [Reflection.BindingFlags]'Instance,Static,NonPublic,Public'
$utf8 = New-Object Text.UTF8Encoding $false
function Read($name) { return [IO.File]::ReadAllText((Join-Path $env:CAR_WORK $name), $utf8) }
function Parse($name) { return ,$J.GetMethod('Parse', $script:flags).Invoke($null, [object[]]@((Read $name))) }
function Call($name, $target, $arguments) {
  $m = $script:F.GetMethod($name, $script:flags)
  if (-not $m) { throw ('no ' + $name) }
  $given = New-Object 'object[]' $arguments.Count
  for ($i = 0; $i -lt $arguments.Count; $i++) {
    $value = $arguments[$i]
    if ($null -ne $value -and $value -is [psobject]) { $value = $value.PSObject.BaseObject }
    $given[$i] = $value
  }
  return $m.Invoke($target, $given)
}
function Field($name) { return $script:F.GetField($name, $script:flags).GetValue($script:form) }
function SetField($name, $value) { $script:F.GetField($name, $script:flags).SetValue($script:form, $value) }
function Text($value) { if ($null -eq $value) { return '<null>' } return [string]$value }
function Chosen() {
  $list = Field 'pendingList'
  $found = New-Object 'System.Collections.Generic.List[object]'
  for ($i = 0; $i -lt $list.Items.Count; $i++) {
    if ($list.Items[$i].Selected) { $found.Add([string]$list.Items[$i].Tag['interruption_id']) }
  }
  return ,$found
}
try {
  $cases = ConvertFrom-Json (Read 'cases.json')
  $out = @{}

  # The command line and the open request, checked: pure, no window.
  $parsed = New-Object System.Collections.ArrayList
  foreach ($argv in $cases.argv) {
    $request = Call 'ParseArguments' $null @(,[string[]]@($argv | ForEach-Object { [string]$_ }))
    $two = [object[]]::new(2); $two[0] = [string[]]@($argv | ForEach-Object { [string]$_ }); $two[1] = $false
    [void]$parsed.Add(@((Text $R.GetField('RowDialog', $script:flags).GetValue($request)),
                        (Text $R.GetField('Page', $script:flags).GetValue($request)),
                        [bool]$script:F.GetMethod('HandsOverOnStart', $script:flags).Invoke($null, $two),
                        (Text (Call 'HandOverPage' $null @(,[string[]]@($argv | ForEach-Object { [string]$_ }))))))
  }
  $out.parsed = $parsed
  $requests = New-Object System.Collections.ArrayList
  foreach ($text in $cases.requests) {
    [void]$requests.Add(@((Text (Call 'OpenRequestPage' $null @([string]$text))), (Text (Call 'OpenRequestRow' $null @([string]$text)))))
  }
  $out.requests = $requests

  # The window, built and never shown.
  [string]$nowhere = Join-Path $env:CAR_WORK 'nowhere'
  $bridge = $BT.GetConstructor($script:flags, $null, [type[]]@([string]), $null).Invoke([object[]]@($nowhere))
  $persistent = $PB.GetConstructor($script:flags, $null, [type[]]@([string], $BT), $null).Invoke([object[]]@($nowhere, $bridge))
  $catalog = (Parse 'strings.json')['strings']
  $make = $script:F.GetConstructor($script:flags, $null, [type[]]@($PB, [Collections.Generic.Dictionary[string,object]], [Drawing.Font]), $null)
  $script:form = $make.Invoke([object[]]@($persistent, $catalog, [Drawing.SystemFonts]::MessageBoxFont))
  SetField 'auditing' $true
  $script:form.TopLevel = $false
  Call 'Materialise' $null @($script:form) | Out-Null
  Call 'ShowPage' $script:form @('pending') | Out-Null
  $snapshot = Parse 'snapshot.json'
  Call 'ApplySnapshot' $script:form @($snapshot) | Out-Null
  # A read already on its way: AskRowDialog's read again waits for it, and nothing is asked of the bridge.
  SetField 'refreshing' $true

  $asked = New-Object System.Collections.ArrayList
  foreach ($row in $cases.asked) {
    SetField 'rowDialogOpened' $null
    Call 'AskRowDialog' $script:form @([string]$row) | Out-Null
    $waiting = Text (Field 'rowAsked')
    Call 'ApplySnapshot' $script:form @($snapshot) | Out-Null
    [void]$asked.Add(@($waiting, (Text (Field 'rowDialogOpened')), (Text (Field 'rowAsked')), (Chosen)))
  }
  $out.asked = $asked

  # The row gone from the next read: the request is spent and nothing opens.
  SetField 'rowDialogOpened' $null
  Call 'AskRowDialog' $script:form @([string]$cases.good) | Out-Null
  Call 'ApplySnapshot' $script:form @((Parse 'without.json')) | Out-Null
  $out.gone = @((Text (Field 'rowDialogOpened')), (Text (Field 'rowAsked')))

  # An action on its way: the request waits for the read after it.
  Call 'ApplySnapshot' $script:form @($snapshot) | Out-Null
  SetField 'rowDialogOpened' $null
  SetField 'busy' ([int]1)
  Call 'AskRowDialog' $script:form @([string]$cases.good) | Out-Null
  Call 'ApplySnapshot' $script:form @($snapshot) | Out-Null
  $held = @((Text (Field 'rowDialogOpened')), (Text (Field 'rowAsked')))
  SetField 'busy' ([int]0)
  Call 'ApplySnapshot' $script:form @($snapshot) | Out-Null
  $out.busy = @($held[0], $held[1], (Text (Field 'rowDialogOpened')), (Text (Field 'rowAsked')))

  $out | ConvertTo-Json -Depth 8 -Compress
} catch {
  $thrown = $_.Exception
  while ($thrown.InnerException) { $thrown = $thrown.InnerException }
  [Console]::Error.WriteLine($thrown.ToString())
  exit 3
}
"""

ARGV = [
    ["--dialog=" + GOOD],
    ["--page=history", "--dialog=" + GOOD],
    ["--outside", "--dialog=" + asked("message", 3)],
    ["--page=pending"],
] + [["--dialog=" + bad] for bad in MALFORMED]
REQUESTS = ["pending", "", "pending\n" + GOOD, "pending\n" + asked("message", 2), "history\n" + GOOD,
            "pending\n" + MALFORMED[3], "pending\n", "\n" + GOOD, "pending\n" + GOOD + "\n"]
ASKED = [GOOD, asked("once_words", 2), asked("message", 3), asked("once_words", 3), asked("once_words", 1, ROW[2][1]),
         "once_words:%s:%s" % ("f" * 64, ROW[1][1]), MALFORMED[6]]


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class RowDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll",
                        "/reference:System.Windows.Forms.dll", *[str(path) for path in guiscan.sources()]],
                       check=True, capture_output=True, timeout=300, creationflags=NO_WINDOW)
        (work / "strings.json").write_text(json.dumps({"strings": l10n.catalog("en")}, ensure_ascii=False),
                                           encoding="utf-8")
        snapshot = fullest_snapshot(time.time())
        (work / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        without = dict(snapshot, pending=[row for row in snapshot["pending"] if row["interruption_id"] != ROW[1][0]])
        (work / "without.json").write_text(json.dumps(without, ensure_ascii=False), encoding="utf-8")
        (work / "cases.json").write_text(json.dumps({"argv": ARGV, "requests": REQUESTS, "asked": ASKED,
                                                     "good": GOOD}), encoding="utf-8")
        probe = work / "probe.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        result = subprocess.run(
            [str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600, creationflags=NO_WINDOW,
            env=dict(os.environ, CAR_EXE=str(exe), CAR_WORK=str(work)))
        cls.result = result
        cls.answer = json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else {}

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-2000:])

    def test_the_start_argument_is_parsed_strictly_and_opens_pending(self):
        """Fails with the argument reverted: `--dialog=` is ignored and the window opens where it always did."""
        parsed = self.answer["parsed"]
        self.assertEqual(parsed[0][:2], [GOOD, "pending"])
        self.assertEqual(parsed[1][:2], [GOOD, "pending"], "a row's dialog is on Pending, whatever page is named")
        self.assertEqual(parsed[2][:2], [asked("message", 3), "pending"])
        self.assertEqual(parsed[3][:2], ["<null>", "pending"])
        for bad, (row, page, _, _) in zip(MALFORMED, parsed[4:]):
            with self.subTest(bad=bad):
                self.assertEqual((row, page), ("<null>", "<null>"))

    def test_a_start_with_it_hands_over_to_an_open_window_with_the_row(self):
        parsed = self.answer["parsed"]
        self.assertEqual(parsed[0][2:], [True, "pending\n" + GOOD])
        self.assertEqual(parsed[2][2:], [True, "pending\n" + asked("message", 3)])
        self.assertEqual(parsed[3][2:], [True, "pending"])
        for bad, (_, _, asks, _) in zip(MALFORMED, parsed[4:]):
            with self.subTest(bad=bad):
                self.assertFalse(asks, "a start with an argument it does not take starts as it always did")

    def test_an_open_window_takes_a_request_with_a_rows_dialog_and_nothing_else(self):
        requests = dict(zip(REQUESTS, self.answer["requests"]))
        self.assertEqual(requests["pending"], ["pending", "<null>"])
        self.assertEqual(requests[""], ["", "<null>"])
        self.assertEqual(requests["pending\n" + GOOD], ["pending", GOOD])
        self.assertEqual(requests["pending\n" + asked("message", 2)], ["pending", asked("message", 2)])
        for refused in REQUESTS[4:]:
            with self.subTest(text=refused):
                self.assertEqual(requests[refused], ["<null>", "<null>"])

    def test_the_dialog_opens_for_the_row_named_and_chooses_it(self):
        """Fails with the request reverted: nothing is asked, and nothing would open."""
        waiting, opened, left, chosen = self.answer["asked"][0]
        self.assertEqual((waiting, opened, left), (GOOD, "once_words:" + ROW[1][0], "<null>"))
        self.assertEqual(chosen, [ROW[1][0]])
        _, opened, _, chosen = self.answer["asked"][1]
        self.assertEqual((opened, chosen), ("once_words:" + ROW[2][0], [ROW[2][0]]))

    def test_by_the_rules_the_row_menu_offers_it_with(self):
        # Message for this conversation... on any row of Pending; words for this time only while it waits.
        self.assertEqual(self.answer["asked"][2][1], "message:" + ROW[3][0])
        self.assertEqual(self.answer["asked"][3][1:3], ["<null>", "<null>"], "a turn already in Codex: nothing opens")

    def test_a_row_of_another_conversation_or_not_there_opens_nothing(self):
        self.assertEqual(self.answer["asked"][4][1:3], ["<null>", "<null>"])
        self.assertEqual(self.answer["asked"][5][1:3], ["<null>", "<null>"])
        self.assertEqual(self.answer["gone"], ["<null>", "<null>"], "a row gone from Pending: Pending and nothing more")

    def test_a_malformed_request_is_not_even_waited_for(self):
        self.assertEqual(self.answer["asked"][6][:3], ["<null>", "<null>", "<null>"])

    def test_an_action_on_its_way_holds_it_for_the_next_read(self):
        self.assertEqual(self.answer["busy"], ["<null>", GOOD, "once_words:" + ROW[1][0], "<null>"])


class SourceTests(unittest.TestCase):
    def test_the_start_and_the_open_request_reach_the_same_request(self):
        build = guiscan.member_body("SettingsForm", "BuildDashboard")
        self.assertIn("if (request.RowDialog != null) rowAsked = request.RowDialog;", build)
        forward = guiscan.member_body("SettingsForm", "ComeForwardOn")
        self.assertIn("if (row != null && IsWindowEnabled(Handle)) AskRowDialog(row);", forward)
        take = guiscan.member_body("SettingsForm", "TakeOpenRequest")
        self.assertIn("ComeForwardOn(page, row)", take)
        self.assertIn("copy.Size <= OpenRequestBytes", take)

    def test_the_window_opens_its_own_dialogs_and_none_in_a_window_nobody_sees(self):
        take = guiscan.member_body("SettingsForm", "TakeRowAsked")
        self.assertIn("if (auditing || !IsHandleCreated) return;", take)
        self.assertLess(take.index("if (auditing || !IsHandleCreated) return;"), take.index("BeginInvoke("))
        self.assertIn('if (dialog == "once_words") EditOnceWords(row);', take)
        self.assertIn("else EditConversationMessage(row);", take)
        self.assertIn("TakeRowAsked();", guiscan.member_body("SettingsForm", "ApplySnapshot"))


if __name__ == "__main__":
    unittest.main()
