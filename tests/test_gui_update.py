r"""What the window makes of the update check's answer.

The window runs `scripts/bootstrap.ps1` and reads one line of its output. Two things can
go wrong there and neither is visible by reading the C#: the line could be parsed loosely
enough that a different script satisfies it, and the exit code could be trusted on its
own. Both matter, because the answer decides whether a person is shown "up to date" - the
one sentence this feature must never say wrongly.

So the real method is called, through reflection on the real compiled window, against real
child processes: small scripts that print a chosen line and exit with a chosen code. What
is exercised is the shipped parser, including its rule that the code and the line have to
agree before either is believed.
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

# name -> (what the fake bootstrap prints, what it exits with, what the window must decide)
CASES = {
    "current":            ("update: current 0.6.0", 0, "current"),
    "available":          ("update: available 0.5.7 0.6.0", 10, "available"),
    "newer_local":        ("update: newer-local 0.7.0 0.6.0", 11, "newer-local"),
    "unavailable":        ("update: unavailable", 12, "unavailable"),
    # -Update runs on past the line into the installer and exits with its code.
    "installed":          ("update: available 0.5.7 0.6.0", 0, "installed"),
    # A code and a line that disagree are not an answer. Either could be an older script,
    # a crash after printing, or a code Windows supplied; believing one of them is how
    # "up to date" gets said to a machine that never asked anything.
    "current_but_failed": ("update: current 0.6.0", 12, "failed"),
    "available_but_local": ("update: available 0.5.7 0.6.0", 11, "failed"),
    "unavailable_but_zero": ("update: unavailable", 0, "failed"),
    "silent_success":     ("", 0, "failed"),
    "silent_failure":     ("something went wrong", 1, "failed"),
    "wrong_word":         ("update: fine 0.6.0", 0, "failed"),
    # Noise around the line is ordinary: the script prints sentences for a person too.
    "line_among_others":  ("  Asking github.com\nupdate: current 0.6.0\n  [ok] done", 0, "current"),
    # Two lines, and the last one wins - which is the one the script prints last.
    "last_line_wins":     ("update: unavailable\nupdate: current 0.6.0", 0, "current"),
}

PROBE = r"""
$ErrorActionPreference = 'Stop'
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$run = $form.GetMethod('RunBootstrap', [Reflection.BindingFlags]'Static,NonPublic,Public')
if (-not $run) { throw 'SettingsForm has no RunBootstrap' }

$out = @{}
# Cast, every time. A value a cmdlet produced is a PSObject wrapping a string, and
# reflection hands it to a `string` parameter as the wrapper, which is an ArgumentException
# rather than anything to do with what is being tested.
$work = [string]$env:CAR_WORK
foreach ($case in (ConvertFrom-Json $env:CAR_CASES).PSObject.Properties) {
    $script = [string](Join-Path $work ($case.Name + '.ps1'))
    $body = @()
    foreach ($line in ($case.Value[0] -split "`n")) { $body += ("Write-Host " + ($line | ConvertTo-Json)) }
    $body += ('exit ' + $case.Value[1])
    [IO.File]::WriteAllText($script, ($body -join "`r`n"), (New-Object Text.UTF8Encoding $false))
    # out parameters come back through the array .NET was handed.
    $arguments = [object[]]@($work, $script, '-CheckOnly', 60000, $null, $null, $null, $null)
    $null = $run.Invoke($null, $arguments)
    $out[$case.Name] = @{
        answer  = $arguments[4]
        current = $arguments[5]
        latest  = $arguments[6]
    }
}

# A child that does not finish is not killed: it may be part way through an installation.
$slow = [string](Join-Path $work 'slow.ps1')
[IO.File]::WriteAllText($slow, "Start-Sleep -Seconds 30`r`nexit 0", (New-Object Text.UTF8Encoding $false))
$arguments = [object[]]@($work, $slow, '-CheckOnly', 1500, $null, $null, $null, $null)
$null = $run.Invoke($null, $arguments)
$out['slow'] = @{ answer = $arguments[4]; current = $arguments[5]; latest = $arguments[6] }

# A script that is not there at all.
$arguments = [object[]]@($work, [string](Join-Path $work 'absent.ps1'), '-CheckOnly',
                         60000, $null, $null, $null, $null)
$null = $run.Invoke($null, $arguments)
$out['absent'] = @{ answer = $arguments[4]; current = $arguments[5]; latest = $arguments[6] }

$out | ConvertTo-Json -Depth 5 -Compress
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(),
                     "needs the in-box compiler and PowerShell")
class BootstrapReadingTests(unittest.TestCase):
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
        # Written to a file rather than passed with -Command: a command line this long is
        # refused outright on some machines, and the refusal arrives as "access is denied"
        # from CreateProcess, which reads like a permissions problem and is not one.
        probe = work / "probe.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        result = subprocess.run(
            [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
            env=dict(os.environ, CAR_EXE=str(exe), CAR_WORK=str(work),
                     CAR_CASES=json.dumps({name: [printed, code]
                                           for name, (printed, code, _) in CASES.items()})))
        cls.result = result
        cls.answer = json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else {}

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-2000:])

    def test_each_answer_is_read_as_itself(self):
        for name, (_, _, expected) in sorted(CASES.items()):
            with self.subTest(name):
                self.assertEqual(self.answer[name]["answer"], expected)

    def test_the_versions_come_out_of_the_line(self):
        self.assertEqual(self.answer["available"]["current"], "0.5.7")
        self.assertEqual(self.answer["available"]["latest"], "0.6.0")
        self.assertEqual(self.answer["current"]["current"], "0.6.0")
        self.assertIsNone(self.answer["unavailable"]["current"])

    def test_a_child_that_has_not_finished_is_left_alone(self):
        """Killing it halfway is how an installation ends up half written."""
        self.assertEqual(self.answer["slow"]["answer"], "running")

    def test_a_missing_script_is_not_a_failed_check(self):
        """Nothing to run is a broken installation, not an answer about updates."""
        self.assertEqual(self.answer["absent"]["answer"], "failed")


class ButtonTests(unittest.TestCase):
    """The window offers the action, and offers it apart from Repair.

    They are one word apart in a support conversation and do completely different things:
    one runs setup over the files that are here, the other fetches different ones.
    """

    def setUp(self):
        self.source = (ROOT / "gui" / "Dashboard.cs").read_text(encoding="utf-8")

    def test_diagnostics_offers_the_check(self):
        self.assertIn('S("action.check_updates", "Check for updates...")', self.source)
        self.assertIn("delegate { CheckForUpdates(); }", self.source)

    def test_it_is_disabled_while_something_else_is_in_flight(self):
        self.assertIn("if (updateButton != null) updateButton.Enabled = busy == 0;", self.source)

    def test_nothing_asks_without_being_asked(self):
        """No timer, no first-open check: the only caller is the button."""
        calls = self.source.count("CheckForUpdates()")
        self.assertEqual(calls, 2, "CheckForUpdates is reached from somewhere other than "
                                   "its own definition and the button")
        clock = self.source[self.source.index("private void StartClock()"):]
        self.assertNotIn("CheckForUpdates", clock[:clock.index("\n        }")])

    def test_the_watcher_identity_is_the_start_time_not_the_version(self):
        """An old watcher reads its version out of the files under it, so a changed
        version proves nothing after an update. A start time that moved does."""
        identity = self.source[self.source.index("private string WatcherIdentity()"):]
        identity = identity[:identity.index("\n        }")]
        self.assertIn('Get(watcher, "started_at")', identity)
        self.assertIn('Get(watcher, "pid")', identity)
        self.assertNotIn("code_version", identity)

    def test_powershell_is_found_by_full_path(self):
        """A `powershell.exe` earlier on PATH is the whole of v0.5.7's system-executable
        fix, and this is a new caller of one."""
        run = self.source[self.source.index("private static void RunBootstrap"):]
        run = run[:run.index("\n        /// The one-line fact")]
        self.assertIn("Environment.GetFolderPath(Environment.SpecialFolder.System)", run)
        self.assertNotIn('ProcessStartInfo("powershell', run)
        self.assertIn('info.EnvironmentVariables["CODEX_AUTO_RESUME_PLUGIN_HOME"] = root;', run)


if __name__ == "__main__":
    unittest.main()
