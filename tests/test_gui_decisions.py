r"""The decisions the window makes about a record, and about a repair.

Both were rows in `docs/FEATURE_MATRIX.md` whose evidence was that somebody had read the
C#. They are decisions rather than drawing: which buttons a record is offered, and which of
five things a repair did. Nothing executed either, so a rule inverted in an edit would have
produced a window that silently never offers Retry now - which a person reads as the
product being stuck, not as a bug - or a repair that reports success for a setup that
rejected its arguments.

The real compiled window is loaded and its real methods are called through reflection,
with synthetic records and, for the repair, real child processes standing in for setup.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")

# `now` for every case, so "the reset is ahead" and "the reset has passed" are decidable.
NOW = 1000000.0

# name -> (record, whether Retry now is offered, whether attempts can be given back)
RECORDS = {
    # Waiting on a usage reset that has already passed: the case Retry now is for.
    "reset_passed":      ({"code": "waiting_reset", "reset_at": NOW - 60}, True, False),
    # Still ahead. Retry now would not move it, and a button that does nothing is worse
    # than no button.
    "reset_ahead":       ({"code": "waiting_reset", "reset_at": NOW + 600}, False, False),
    "reset_unknown":     ({"code": "waiting_usage"}, True, False),
    "waiting_thread":    ({"code": "waiting_thread"}, True, False),
    "scheduled":         ({"code": "scheduled"}, True, False),
    "failed_retryable":  ({"code": "failed_retryable"}, True, False),
    # Consent, in both its forms. Retry now is a request to re-evaluate, never a way past
    # a pause or a conversation somebody switched off.
    "paused":            ({"code": "scheduled", "overlays": ["paused"]}, False, False),
    "thread_off":        ({"code": "scheduled", "overlays": ["thread_disabled"]}, False, False),
    "paused_and_off":    ({"code": "scheduled", "overlays": ["paused", "thread_disabled"]}, False, False),
    # A cancellation is authoritative; nothing is offered that would undo it.
    "cancelled":         ({"code": "scheduled", "cancel_requested": True}, False, False),
    "cancelled_exhausted": ({"code": "exhausted", "cancel_requested": True,
                             "budget_resets_left": 3}, False, False),
    # Not waiting on anything.
    "running":           ({"code": "running"}, False, False),
    "recovered":         ({"code": "recovered"}, False, False),
    "sent_unverified":   ({"code": "sent_unverified"}, False, False),
    # Out of attempts, with resets left and without.
    "exhausted":         ({"code": "exhausted", "budget_resets_left": 2}, False, True),
    "exhausted_spent":   ({"code": "exhausted", "budget_resets_left": 0}, False, False),
    # A code nothing knows. Fail closed: offer nothing.
    "unknown_code":      ({"code": "something_new"}, False, False),
    "empty":             ({}, False, False),
}

# name -> (what the fake setup prints, its exit code, what Repair must call it)
REPAIRS = {
    "done":              ("state: ok", 0, "done"),
    # 2 is "everything done, the watcher was not seen running yet" - but it is also what
    # setup exits with when it rejects an argument it does not know, such as --keep-state
    # on a copy older than this window. So a 2 counts only with the line setup prints when
    # it has finished its work.
    "done_not_yet_seen": ("state: starting", 2, "done"),
    "argument_rejected": ("unrecognized arguments: --keep-state", 2, "failed"),
    "failed":            ("something went wrong", 1, "failed"),
    "silent_failure":    ("", 1, "failed"),
}

PROBE = r"""
$ErrorActionPreference = 'Stop'
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$flags = [Reflection.BindingFlags]'Static,NonPublic,Public'
$retry = $form.GetMethod('CanRetryNow', $flags)
$give = $form.GetMethod('CanGiveAttemptsBack', $flags)
$repair = $form.GetMethod('RunRepair', $flags)
foreach ($pair in @(@('CanRetryNow', $retry), @('CanGiveAttemptsBack', $give), @('RunRepair', $repair))) {
    if (-not $pair[1]) { throw ('SettingsForm has no ' + $pair[0]) }
}
$work = [string]$env:CAR_WORK
$out = @{ retry = @{}; give = @{}; busy = @{}; repair = @{} }

# The window's own dictionary shape: string keys, object values.
function To-Row {
    param($source)
    $row = New-Object 'System.Collections.Generic.Dictionary[string,object]'
    foreach ($field in $source.PSObject.Properties) {
        $value = $field.Value
        # Cast every one: PowerShell hands back PSObject wrappers, and the window reads its
        # values with `is double` and `as List<object>`, both of which a wrapper fails. A
        # row of wrappers would answer "no" to every question and look like agreement.
        # Added through the method rather than the indexer: assigning through the indexer
        # can store PowerShell's PSObject wrapper, and the window reads its values with
        # `is double` and `as List<object>`, which a wrapper fails. A row of wrappers
        # answers "no" to every question, which looks like agreement and is not.
        if ($value -is [Array]) {
            $list = New-Object 'System.Collections.Generic.List[object]'
            foreach ($item in $value) { $list.Add([string]$item) }
            $row.Add([string]$field.Name, $list)
        } elseif ($value -is [bool]) {
            $row.Add([string]$field.Name, [bool]$value)
        } elseif ($value -is [string]) {
            $row.Add([string]$field.Name, [string]$value)
        } else {
            # Numbers arrive as the window's bridge delivers them: JSON numbers, doubles.
            $row.Add([string]$field.Name, [double]$value)
        }
    }
    return $row
}

foreach ($case in (ConvertFrom-Json $env:CAR_RECORDS).PSObject.Properties) {
    # Cast at the call: a function's return value is a PSObject wrapping the dictionary,
    # and reflection hands the wrapper to a Dictionary parameter.
    $row = [Collections.Generic.Dictionary[string,object]](To-Row $case.Value)
    $out.retry[$case.Name] = [bool]$retry.Invoke($null, [object[]]@($row, $true, [double]$env:CAR_NOW))
    $out.give[$case.Name] = [bool]$give.Invoke($null, [object[]]@($row, $true))
    # And with the window busy, which is what stops a second click acting on a row the
    # first click already changed.
    $out.busy[$case.Name] = [bool]$retry.Invoke($null, [object[]]@($row, $false, [double]$env:CAR_NOW)) -or
                            [bool]$give.Invoke($null, [object[]]@($row, $false))
}
# No record selected at all.
$out.retry['null'] = [bool]$retry.Invoke($null, [object[]]@($null, $true, [double]$env:CAR_NOW))
$out.give['null'] = [bool]$give.Invoke($null, [object[]]@($null, $true))

# Repair, against real child processes. python is a script that prints and exits; setup is
# the argument it is handed, which this window quotes and passes through.
$python = [string](Join-Path $work 'fake-python.cmd')
foreach ($case in (ConvertFrom-Json $env:CAR_REPAIRS).PSObject.Properties) {
    $lines = @('@echo off')
    foreach ($line in ($case.Value[0] -split "`n")) {
        if ($line.Length) { $lines += ('echo ' + $line) }
    }
    $lines += ('exit /b ' + $case.Value[1])
    [IO.File]::WriteAllText($python, ($lines -join "`r`n"), (New-Object Text.ASCIIEncoding))
    $setup = [string](Join-Path $work 'plugin_setup.py')
    [IO.File]::WriteAllText($setup, '# stands in for setup', (New-Object Text.ASCIIEncoding))
    $arguments = [object[]]@($work, $python, $setup, $null, $null)
    $null = $repair.Invoke($null, $arguments)
    $out.repair[$case.Name] = $arguments[3]
}

# Nothing to run: this installation is missing the files setup is made of.
$arguments = [object[]]@($work, [string](Join-Path $work 'absent.exe'),
                         [string](Join-Path $work 'plugin_setup.py'), $null, $null)
$null = $repair.Invoke($null, $arguments)
$out.repair['incomplete'] = $arguments[3]

# The installer's own lock is already held by somebody else.
#
# By another process, which is what an installer is. A named mutex is reentrant for the
# thread that owns it, so taking it here and then calling into the window on this same
# thread would be granted again and the case would quietly not be tested.
$holder = Start-Process -PassThru -WindowStyle Hidden -FilePath 'powershell.exe' -ArgumentList @(
    '-NoProfile', '-NonInteractive', '-Command',
    "`$m = New-Object System.Threading.Mutex(`$false, 'Local\CodexAutoResume.Install'); " +
    "[void]`$m.WaitOne(0); Start-Sleep -Seconds 30")
try {
    # Ready when this thread can no longer take it.
    $ready = $false
    for ($i = 0; $i -lt 100 -and -not $ready; $i++) {
        Start-Sleep -Milliseconds 100
        $probeGate = New-Object System.Threading.Mutex($false, 'Local\CodexAutoResume.Install')
        $got = $false
        try { $got = $probeGate.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $got = $true }
        if ($got) { $probeGate.ReleaseMutex() } else { $ready = $true }
        $probeGate.Dispose()
    }
    if (-not $ready) { throw 'the holder process never took the installer lock' }
    $lines = @('@echo off', 'echo state: ok', 'exit /b 0')
    [IO.File]::WriteAllText($python, ($lines -join "`r`n"), (New-Object Text.ASCIIEncoding))
    $arguments = [object[]]@($work, $python, [string](Join-Path $work 'plugin_setup.py'), $null, $null)
    $null = $repair.Invoke($null, $arguments)
    $out.repair['busy'] = $arguments[3]
} finally { $holder | Stop-Process -Force -ErrorAction SilentlyContinue }

# A part of the snapshot that came back as an error, and the two labels that result.
$unreadable = $form.GetMethod('Unreadable', $flags)
$show = $form.GetMethod('ShowUnreadable', $flags)
if (-not $unreadable -or -not $show) { throw 'SettingsForm has no Unreadable/ShowUnreadable' }
$out.parts = @{}
foreach ($case in @(
        @('nothing_failed', @()),
        @('pending_failed', @('pending_error')),
        @('history_failed', @('history_error')),
        @('both_failed', @('pending_error', 'history_error')))) {
    [Collections.Generic.Dictionary[string,object]]$reply =
        New-Object 'System.Collections.Generic.Dictionary[string,object]'
    $reply.Add('ok', $true)
    foreach ($key in $case[1]) { $reply.Add([string]$key, 'store is unreadable') }
    $out.parts[$case[0]] = @{
        pending = [bool]$unreadable.Invoke($null, [object[]]@($reply, 'pending'))
        history = [bool]$unreadable.Invoke($null, [object[]]@($reply, 'history'))
    }
}
$out.parts['no_reply'] = @{
    pending = [bool]$unreadable.Invoke($null, [object[]]@($null, 'pending'))
    history = [bool]$unreadable.Invoke($null, [object[]]@($null, 'history'))
}

# And what it actually puts on screen. Real controls, not a form: what matters is the
# text, and that the list is emptied rather than left showing rows nothing is refreshing.
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.ListView]$list = New-Object System.Windows.Forms.ListView
$item = New-Object System.Windows.Forms.ListViewItem('a row from before')
[void]$list.Items.Add($item)
[System.Windows.Forms.Label]$label = New-Object System.Windows.Forms.Label
$label.Text = 'Nothing is waiting'
$label.Visible = $false
$null = $show.Invoke($null, [object[]]@($list, $label, 'This cannot be read right now'))
$out.shown = @{
    rows = $list.Items.Count
    text = $label.Text
    visible = [bool]$label.Visible
}
$list.Dispose()
$label.Dispose()

$out | ConvertTo-Json -Depth 5 -Compress
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(),
                     "needs the in-box compiler and PowerShell")
class DecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64",
                        "/out:" + str(exe), "/reference:System.dll",
                        "/reference:System.Drawing.dll", "/reference:System.Windows.Forms.dll",
                        *[str(ROOT / "gui" / name)
                          for name in ("SettingsApp.cs", "Dashboard.cs", "Brand.cs")]],
                       check=True, capture_output=True, timeout=300)
        probe = work / "probe.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        result = subprocess.run(
            [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
            env=dict(os.environ, CAR_EXE=str(exe), CAR_WORK=str(work), CAR_NOW=str(NOW),
                     CAR_RECORDS=json.dumps({name: record
                                             for name, (record, _, _) in RECORDS.items()}),
                     CAR_REPAIRS=json.dumps({name: [printed, code]
                                             for name, (printed, code, _) in REPAIRS.items()})))
        cls.result = result
        cls.answer = json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else {}

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-2000:])

    def test_retry_now_is_offered_where_it_would_do_something(self):
        for name, (_, retry, _) in sorted(RECORDS.items()):
            with self.subTest(name):
                self.assertEqual(self.answer["retry"][name], retry)

    def test_attempts_can_be_given_back_only_where_that_could_succeed(self):
        for name, (_, _, give) in sorted(RECORDS.items()):
            with self.subTest(name):
                self.assertEqual(self.answer["give"][name], give)

    def test_nothing_is_offered_while_the_window_is_busy(self):
        """A second click on a button whose first click has not been answered is how a
        person acts twice, or on the row that happened to be selected by then."""
        for name in sorted(RECORDS):
            with self.subTest(name):
                self.assertFalse(self.answer["busy"][name])

    def test_nothing_is_offered_with_no_record_selected(self):
        self.assertFalse(self.answer["retry"]["null"])
        self.assertFalse(self.answer["give"]["null"])

    def test_repair_says_which_of_the_five_things_happened(self):
        for name, (_, _, outcome) in sorted(REPAIRS.items()):
            with self.subTest(name):
                self.assertEqual(self.answer["repair"][name], outcome)

    def test_a_missing_setup_is_an_incomplete_installation_not_a_failure(self):
        """"Setup did not finish" describes the wrong problem: there was nothing to run."""
        self.assertEqual(self.answer["repair"]["incomplete"], "incomplete")

    def test_an_installer_already_running_is_its_own_answer(self):
        """Two processes rewriting the same registrations at once is the one case the
        installer's lock exists for, and "try again shortly" is a different sentence from
        "it failed"."""
        self.assertEqual(self.answer["repair"]["busy"], "busy")


    def test_a_part_that_failed_is_the_only_part_marked_unreadable(self):
        """Each part of the Overview is read on its own, so one failing must not cost the
        others - and must not be reported as the others being empty."""
        self.assertEqual(self.answer["parts"]["nothing_failed"], {"pending": False, "history": False})
        self.assertEqual(self.answer["parts"]["pending_failed"], {"pending": True, "history": False})
        self.assertEqual(self.answer["parts"]["history_failed"], {"pending": False, "history": True})
        self.assertEqual(self.answer["parts"]["both_failed"], {"pending": True, "history": True})

    def test_no_reply_at_all_is_not_a_part_that_failed(self):
        """No snapshot is the whole window's problem, handled by `MarkUnavailable`, and
        not a report that two particular parts came back as errors."""
        self.assertEqual(self.answer["parts"]["no_reply"], {"pending": False, "history": False})

    def test_an_unreadable_list_says_so_and_shows_no_stale_rows(self):
        """The wrong answer here is "Nothing is waiting" over a list nobody could read:
        recoveries may well be waiting, and an older watcher may still be sending them."""
        shown = self.answer["shown"]
        self.assertEqual(shown["rows"], 0, "rows nothing is refreshing were left on screen")
        self.assertEqual(shown["text"], "This cannot be read right now")
        self.assertNotIn("Nothing", shown["text"])
        self.assertTrue(shown["visible"])

if __name__ == "__main__":
    unittest.main()
