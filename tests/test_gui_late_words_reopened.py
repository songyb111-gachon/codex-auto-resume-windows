r"""A window opened again by the setup program after an update ends in its own language (v0.6.23, the final's live acceptance).

Seen on a Korean Windows, Interface language System: an update with the watcher stopped reopened the Dashboard from the old
window's record (config/reopen-after-update-<pid>.txt, written by CloseForUpdate) as `<record> --after-update`. The first
bridge start after the update took about 11 s, past StringsWaitMilliseconds, so the window opened in English and its words
came late - and TakeLateWords returned at `request.Generation != 0`: the record carries `--reopened=1`, so the window
counted as a reopened one and never opened again in its words. It stayed English for good, but for the advanced edition's
own words, which it asked in the stored language (AdvancedPage.LocaleArgument).

The guard was there so a bridge always slower than the wait cannot reopen the window over and over. It is kept, aimed at
what it is for: a window opens again for late words with `--late-words` (MarkLateWords), and only such a window takes no
late words of its own. Any other reopen - an update's, a language's, a theme's, a monitor's - takes them as a window a
person opened does, and decides as a first window does (DecidingGeneration), so even a second reopen in a row for its theme
does not keep English (AdoptWhatWasRead).

The built half compiles the real window and runs it against tests/test_gui_v0620_audit.py's stand-in python.exe in its
`slow` mode (the strings, in Korean, after 3 s; the window waits 1.5). Each window's command line is set as ParseArguments
makes it of `--reopened=1 --after-update`, `--reopened=1`, `--reopened=2` and `--reopened=1 --late-words`. Nothing of the
real installation is read, no window is shown, and no reopen is started: what CheckReopen would decide and what Reopen would
pass on are asked of the window (DecidingGeneration, MarkLateWords).

    PYTHONPATH="src;tests" python -m unittest test_gui_late_words_reopened      (a GUI module: gui_lock.sh)
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import guiscan
from test_gui_v0611_access import CSC, NO_WINDOW, POWERSHELL, compile_window, run_probe
from test_gui_v0620_audit import FAKE

PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
[Windows.Forms.Application]::SetUnhandledExceptionMode([Windows.Forms.UnhandledExceptionMode]::ThrowException)
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$flags = [Reflection.BindingFlags]'Instance,Static,NonPublic,Public'
$F = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$BT = $assembly.GetType('CodexAutoResume.Bridge', $true)
$PB = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
$work = [string]$env:CAR_WORK
$home_ = [string]$env:CAR_HOME
$utf8 = New-Object Text.UTF8Encoding $false
$out = @{}

$F.GetField('StringsWaitMilliseconds', $flags).SetValue($null, [int]1500)
$PB.GetField('RetryMilliseconds', $flags).SetValue($null, [int]600000)
$env:CAR_FAKE_MODE = 'slow'
$parse = $F.GetMethod('ParseArguments', $flags)
$decide = $F.GetMethod('ReopenDecision', $flags)
$codes = @{ keep = [int]$F.GetField('KeepWindow', $flags).GetValue($null); reopen = [int]$F.GetField('ReopenWindow', $flags).GetValue($null)
            adopt = [int]$F.GetField('AdoptWhatWasRead', $flags).GetValue($null) }
$out.codes = $codes
$out.marker = [string]$F.GetField('LateLanguage', $flags).GetValue($null)
$out.flag = [string]$F.GetField('ReopenedForLateWords', $flags).GetValue($null)

function Request([string[]]$arguments) {
    return $parse.Invoke($null, [object[]]@(,$arguments))
}

# A window started with `arguments`, its words asked of a bridge that answers them after the window has opened in English.
function Late-Window([string[]]$arguments) {
    $oneShot = $BT.GetConstructors($flags)[0].Invoke([object[]]@($home_))
    $bridge = $PB.GetConstructors($flags)[0].Invoke([object[]]@($home_, $oneShot))
    # Given up already, so the words are asked of the one-shot bridge at once.
    $PB.GetField('failures', $flags).SetValue($bridge, [int]3)
    $PB.GetField('givenUp', $flags).GetValue($bridge).Start()
    $one = @($F.GetConstructors($flags) | Where-Object { $_.GetParameters().Count -eq 1 })[0]
    $window = $one.Invoke([object[]]@($bridge))
    # The command line the window was started with: this probe's own is PowerShell's.
    $request = Request $arguments
    $F.GetField('request', $flags).SetValue($window, $request)
    $result = @{ late = [bool]$F.GetField('lateWords', $flags).GetValue($window)
                 openedLate = [bool]$F.GetField('openedLate', $flags).GetValue($window)
                 generation = [int]$request.GetType().GetField('Generation', $flags).GetValue($request)
                 forLateWords = [bool]$request.GetType().GetField('ForLateWords', $flags).GetValue($request) }
    $null = $window.Handle
    $clock = [Diagnostics.Stopwatch]::StartNew()
    while ($clock.ElapsedMilliseconds -lt 15000 -and [bool]$F.GetField('lateWords', $flags).GetValue($window)) {
        [Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 50
    }
    $opened = $F.GetField('openedLanguage', $flags).GetValue($window)
    $result.taken = -not [bool]$F.GetField('lateWords', $flags).GetValue($window)
    $result.opened = [string]$opened
    # What CheckReopen decides once the settings say the stored language - System, as on the PC it was seen on - in the
    # first read and in a later one; the theme and design not known, so the language alone decides.
    $generation = [int]$F.GetMethod('DecidingGeneration', $flags).Invoke($window, @())
    $result.deciding = $generation
    $result.first = [int]$decide.Invoke($null, [object[]]@($opened, $null, $null, 'system', $null, $null, $false, $true, $generation))
    $result.later = [int]$decide.Invoke($null, [object[]]@($opened, $null, $null, 'system', $null, $null, $false, $false, $generation))
    # What Reopen passes on, and what the window it starts makes of it.
    $line = [string]$F.GetMethod('MarkLateWords', $flags).Invoke($window, [object[]]@('--page=pending --reopened=1'))
    $result.line = $line
    $next = Request ($line.Split(' '))
    $result.nextForLateWords = [bool]$next.GetType().GetField('ForLateWords', $flags).GetValue($next)
    $null = $PB.GetMethod('Stop', $flags).Invoke($bridge, @())
    $window.Dispose()
    Get-Process -Name python, pythonw -ErrorAction SilentlyContinue | Where-Object {
        $_.Path -and $_.Path.StartsWith($home_, [StringComparison]::OrdinalIgnoreCase) } | Stop-Process -Force
    Start-Sleep -Milliseconds 300
    return $result
}

$out.afterUpdate = Late-Window @('--page=pending', '--bounds=10,20,1000,700', '--theme=system', '--design=soft', '--reopened=1',
                                 '--focus=page.pending', '--after-update')
$out.reopened = Late-Window @('--page=settings', '--reopened=1')
$out.twice = Late-Window @('--reopened=2')
$out.person = Late-Window @()
$out.forLate = Late-Window @('--page=pending', '--reopened=1', '--late-words')

[IO.File]::WriteAllText((Join-Path $work 'result.json'), (ConvertTo-Json $out -Compress -Depth 6), $utf8)
"""


def body(type_name: str, member: str) -> str:
    return guiscan.member_body(type_name, member)


class SourceTests(unittest.TestCase):
    def test_late_words_are_held_back_only_in_a_window_reopened_for_them(self):
        take = body("SettingsForm", "TakeLateWords")
        self.assertIn("if (request.ForLateWords) return;", take)
        self.assertNotIn("request.Generation", take, "a reopen for an update or a theme is no reason to keep English")

    def test_check_reopen_and_reopen_use_the_late_words_rules(self):
        self.assertIn("Dirty(), firstRead, DecidingGeneration());", body("SettingsForm", "CheckReopen"))
        reopen = body("SettingsForm", "Reopen")
        self.assertIn("arguments = MarkLateWords(arguments);", reopen)
        self.assertLess(reopen.index("arguments = MarkLateWords(arguments);"), reopen.index("new ProcessStartInfo("))

    def test_the_update_s_record_never_carries_the_marker(self):
        """The old window's record is written by CloseForUpdate: a new version, with a new bridge, takes its words."""
        self.assertNotIn("MarkLateWords", body("SettingsForm", "CloseForUpdate"))


@unittest.skipUnless(os.name == "nt" and CSC.is_file() and POWERSHELL.is_file(),
                     "needs the in-box C# compiler and Windows PowerShell")
class BuiltTests(unittest.TestCase):
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
        try:
            cls.answer = run_probe(PROBE, work, 300, CAR_EXE=str(exe), CAR_HOME=str(cls.home),
                                   CAR_FAKE_PIDS=str(work / "pids.txt"))
        finally:
            cls.end_ours()

    @classmethod
    def end_ours(cls):
        """Whatever the stand-in started and still runs, by its path inside this test's folder."""
        script = ("Get-Process -Name python,pythonw -ErrorAction SilentlyContinue | Where-Object { $_.Path -and "
                  "$_.Path.StartsWith($env:CAR_HOME, [StringComparison]::OrdinalIgnoreCase) } | Stop-Process -Force")
        subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                       timeout=120, creationflags=NO_WINDOW, env=dict(os.environ, CAR_HOME=str(cls.home)))

    @classmethod
    def tearDownClass(cls):
        cls.end_ours()
        cls.folder.cleanup()

    def ends_in_its_language(self, name, generation):
        window = self.answer[name]
        self.assertTrue(window["late"] and window["openedLate"], "the words were meant to come after the window opened")
        self.assertEqual(window["generation"], generation)
        self.assertFalse(window["forLateWords"])
        self.assertTrue(window["taken"], "the late words never came")
        self.assertEqual(window["opened"], self.answer["marker"],
                         "Korean words came after the window opened in English: it must open again in them")
        self.assertEqual(window["deciding"], 0)
        self.assertEqual((window["first"], window["later"]), (self.answer["codes"]["reopen"],) * 2,
                         "once the settings are read, the window opens again in its language")
        self.assertEqual(window["line"], "--page=pending --reopened=1 " + self.answer["flag"])
        self.assertTrue(window["nextForLateWords"], "the window it opens reopens for late words no more")

    def test_the_window_an_update_reopens_ends_in_its_language(self):
        self.ends_in_its_language("afterUpdate", 1)

    def test_a_window_reopened_for_anything_else_ends_in_its_language(self):
        self.ends_in_its_language("reopened", 1)

    def test_a_window_reopened_twice_for_its_theme_does_not_keep_english(self):
        self.ends_in_its_language("twice", 2)

    def test_a_window_a_person_opened_ends_in_its_language_as_before(self):
        self.ends_in_its_language("person", 0)

    def test_a_window_reopened_for_late_words_does_not_reopen_again(self):
        window = self.answer["forLate"]
        self.assertTrue(window["late"] and window["forLateWords"])
        self.assertTrue(window["taken"])
        self.assertEqual(window["opened"], "", "it keeps what it opened in: a bridge always slower cannot loop it")
        self.assertEqual((window["first"], window["later"]), (self.answer["codes"]["keep"],) * 2)
        self.assertEqual(window["line"], "--page=pending --reopened=1", "and passes on no marker of its own")
        self.assertFalse(window["nextForLateWords"])


if __name__ == "__main__":
    unittest.main()
