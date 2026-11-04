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

import datetime
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import guiscan

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
    # v0.6.5: the check's second request, the Codex compatibility data, answers on its own line before the
    # update's. It never changes the update's answer, whatever it says.
    "with_refresh":       ("compatibility: refreshed 12\nupdate: current 0.6.0", 0, "current"),
    "with_refusal":       ("compatibility: refused from_the_future\nupdate: available 0.5.7 0.6.0", 10, "available"),
    "with_no_refresh":    ("compatibility: unavailable\nupdate: current 0.6.0", 0, "current"),
    # v0.6.11: the check's question about pre-releases answers on a line of its own, and never
    # changes the update's answer either.
    "with_prerelease":    ("prerelease: v0.6.1-beta\nupdate: current 0.6.0", 0, "current"),
    "prerelease_and_newer_local": ("prerelease: v0.7.1-alpha.2\nupdate: newer-local 0.7.0 0.6.0", 11, "newer-local"),
    "prerelease_alone":   ("prerelease: v0.6.1-beta", 0, "failed"),
    # v0.6.17 (GitHub #41): where the list could not be read, a `releases:` line says so and why, and changes no answer.
    "rate_limited":       ("releases: rate-limited 1760000000\nupdate: newer-local 0.7.0 0.6.0", 11, "newer-local"),
    "rate_limited_unknown": ("releases: rate-limited unknown\nupdate: current 0.6.0", 0, "current"),
    "list_unread":        ("releases: unread\nupdate: current 0.6.0", 0, "current"),
    "releases_malformed": ("releases: rate-limited soon\nupdate: current 0.6.0", 0, "current"),
    "releases_too_long":  ("releases: rate-limited 176000000000000\nupdate: current 0.6.0", 0, "current"),
    "releases_last_wins": ("releases: unread\nreleases: rate-limited 1760000000\nupdate: current 0.6.0", 0, "current"),
}

# What the window reads from each case's `releases:` line (ReleasesLine): its words, or null.
RELEASES = {"rate_limited": "rate-limited 1760000000", "rate_limited_unknown": "rate-limited unknown",
            "list_unread": "unread", "releases_last_wins": "rate-limited 1760000000"}

# What the window reads from each case's `compatibility:` line (CompatibilityLine): the words, or null.
COMPATIBILITY = {"with_refresh": "refreshed 12", "with_refusal": "refused from_the_future",
                 "with_no_refresh": "unavailable"}

# What the window reads from each case's `prerelease:` line (PrereleaseLine): the version, or null.
PRERELEASE = {"with_prerelease": "0.6.1-beta", "prerelease_and_newer_local": "0.7.1-alpha.2",
              "prerelease_alone": "0.6.1-beta"}

# The `prerelease:` line alone, as PrereleaseLine reads it: what the window would put on the
# bootstrap's command line after a yes, or None. Every version of the version rule's table is
# added below, as `prerelease: v<version>`; these are the ways the line itself can be wrong.
PRERELEASE_LINES = {
    "prerelease: v0.6.12-alpha": "0.6.12-alpha",
    "  prerelease: v0.6.12-beta.2  ": "0.6.12-beta.2",
    "prerelease: 0.6.12-alpha": None,                       # no v
    "prerelease: V0.6.12-alpha": None,
    "prerelease: v0.6.12": None,                            # a release is not a pre-release
    "prerelease: v0.06.12-alpha": None,                     # a leading zero names another tag
    "prerelease: v00.6.12-alpha": None,
    "prerelease: v0.6.12-alpha -Force": None,               # nothing more on the command line
    "prerelease: v0.6.12-alpha;calc": None,
    "prerelease: v0.6.12-alpha\"": None,
    "prerelease: v1234567.0.0-alpha": None,
    "prerelease:v0.6.12-alpha": None,
    "prerelease: ": None,
    "update: current 0.6.0": None,
    # The last line counts, as the `update:` line's does.
    "prerelease: v0.6.12-alpha\nprerelease: nonsense": None,
    "prerelease: nonsense\nprerelease: v0.6.12-beta": "0.6.12-beta",
}

PROBE = r"""
$ErrorActionPreference = 'Stop'
# The lines below carry other scripts' digits, and the answer is read as UTF-8: left to the
# console, it would be written in whatever code page the parent console has.
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
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
    $arguments = [object[]]@($work, $script, '-CheckOnly', 60000, $null, $null, $null, $null, $null, $null, $null)
    $null = $run.Invoke($null, $arguments)
    $out[$case.Name] = @{
        answer  = $arguments[4]
        current = $arguments[5]
        latest  = $arguments[6]
        compatibility = $arguments[8]
        prerelease = $arguments[9]
        releases = $arguments[10]
    }
}

# The `prerelease:` line on its own, through the window's own reader.
$line = $form.GetMethod('PrereleaseLine', [Reflection.BindingFlags]'Static,NonPublic,Public')
if (-not $line) { throw 'SettingsForm has no PrereleaseLine' }
$out['lines'] = @()
foreach ($text in (ConvertFrom-Json $env:CAR_LINES)) {
    $out['lines'] += ,@([string]$text, $line.Invoke($null, [object[]]@([string]$text)))
}

# A child that does not finish is not killed: it may be part way through an installation.
$slow = [string](Join-Path $work 'slow.ps1')
[IO.File]::WriteAllText($slow, "Start-Sleep -Seconds 30`r`nexit 0", (New-Object Text.UTF8Encoding $false))
$arguments = [object[]]@($work, $slow, '-CheckOnly', 1500, $null, $null, $null, $null, $null, $null, $null)
$null = $run.Invoke($null, $arguments)
$out['slow'] = @{ answer = $arguments[4]; current = $arguments[5]; latest = $arguments[6] }

# A script that is not there at all.
$arguments = [object[]]@($work, [string](Join-Path $work 'absent.ps1'), '-CheckOnly',
                         60000, $null, $null, $null, $null, $null, $null, $null)
$null = $run.Invoke($null, $arguments)
$out['absent'] = @{ answer = $arguments[4]; current = $arguments[5]; latest = $arguments[6] }

# GitHub #41: what the window says, in English (a form whose constructor never ran, with no catalog), for an answer and
# the check's `releases:` line, and for Install another version...'s listing and pick where GitHub could not be asked.
$instance = [Reflection.BindingFlags]'Instance,NonPublic,Public'
$updateWords = $form.GetMethod('UpdateWords', $instance)
$listWords = $form.GetMethod('ListUnavailableWords', $instance)
$pickWords = $form.GetMethod('PickUnavailableWords', $instance)
$out['words'] = $null
if ($updateWords -and $listWords -and $pickWords) {
    $blank = [Runtime.Serialization.FormatterServices]::GetUninitializedObject($form)
    $form.GetField('strings', $instance).SetValue($blank, (New-Object 'System.Collections.Generic.Dictionary[string,object]'))
    $out['words'] = @{}
    foreach ($case in (ConvertFrom-Json $env:CAR_WORDS).PSObject.Properties) {
        $v = @($case.Value)
        $releases = $null
        if ($null -ne $v[4]) { $releases = [string]$v[4] }
        if ($v[0] -eq 'update') {
            $said = $updateWords.Invoke($blank, [object[]]@([string]$v[1], [string]$v[2], [string]$v[3], '', $releases))
        } elseif ($v[0] -eq 'list') { $said = $listWords.Invoke($blank, [object[]]@($releases)) }
        else { $said = $pickWords.Invoke($blank, [object[]]@($releases)) }
        $out['words'][$case.Name] = [string]$said
    }
}

# GitHub #43: whether a finished Repair has to say that it wrote no entry in Settings > Apps.
$entry = $form.GetMethod('EntryCannotBeWritten', [Reflection.BindingFlags]'Static,NonPublic,Public')
$out['entry'] = $null
if ($entry) {
    $out['entry'] = @{}
    foreach ($case in (ConvertFrom-Json $env:CAR_ENTRY).PSObject.Properties) {
        $out['entry'][$case.Name] = $entry.Invoke($null, [object[]]@([string]$case.Value[0], [string]$case.Value[1]))
    }
}

$out | ConvertTo-Json -Depth 5 -Compress
"""


def clock(seconds: int) -> str:
    """A moment as the window's ClockTime writes it: this PC's time, the hour alone today and the date too otherwise."""
    moment = datetime.datetime.fromtimestamp(seconds)
    return moment.strftime("%H:%M" if moment.date() == datetime.date.today() else "%Y-%m-%d %H:%M")


LIMIT = ("GitHub refused because this network has used up its limit of requests to GitHub for now (a VPN or a shared "
         "connection often does). ")
NEWER_UNCHECKED = ("This build is newer than the latest release, v0.6.0, but pre-releases could not be checked, so a "
                   "newer pre-release may have been published.")
CURRENT_UNCHECKED = ("Version 0.6.0 is the newest published release, but pre-releases could not be checked, so a newer "
                     "pre-release may have been published.")
COULD_NOT_LIST = "GitHub could not be asked for the list of releases just now. Nothing was changed."
COULD_NOT_ASK = "GitHub could not be asked just now, so nothing was installed and nothing was changed."


def limited_today() -> dict:
    """The one case of WORDS that depends on the day, so it is made right before the window answers it. Made when this
    module was read, a run crossing midnight expected a date where the window writes the hour alone (every lane of a dev
    run pushed at 23:59 UTC, 2026-11-04)."""
    soon = int(time.time()) + 1800
    return {"ahead_and_limited_today": (("update", "newer-local", "0.7.0", "0.6.0", "rate-limited %d" % soon),
                                        NEWER_UNCHECKED + "\n\n" + LIMIT + "The limit resets at %s; try again after that." % clock(soon))}


# name -> ((what is asked: update, list or pick; answer; current; latest; the `releases:` words), what the window says)
WORDS = {
    "ahead_and_limited": (("update", "newer-local", "0.7.0", "0.6.0", "rate-limited 1760000000"),
                          NEWER_UNCHECKED + "\n\n" + LIMIT + "The limit resets at %s; try again after that." % clock(1760000000)),
    "ahead_and_limited_unknown": (("update", "newer-local", "0.7.0", "0.6.0", "rate-limited unknown"),
                                  NEWER_UNCHECKED + "\n\n" + LIMIT + "The limit resets within an hour; try again after that."),
    "ahead_and_unread": (("update", "newer-local", "0.7.0", "0.6.0", "unread"), NEWER_UNCHECKED + "\n\nTry again later."),
    "current_and_unread": (("update", "current", "0.6.0", "0.6.0", "unread"), CURRENT_UNCHECKED + "\n\nTry again later."),
    # A list that was read leaves the words as they were.
    "ahead_and_read": (("update", "newer-local", "0.7.0", "0.6.0", None),
                       "This build is ahead of the newest published release, so there is nothing to install."),
    "current_and_read": (("update", "current", "0.6.0", "0.6.0", None), "Version 0.6.0 is the newest published release."),
    "available_and_unread": (("update", "available", "0.5.0", "0.6.0", "unread"), "Version 0.6.0 has been published."),
    "list_limited": (("list", None, None, None, "rate-limited 1760000000"),
                     COULD_NOT_LIST + "\n" + LIMIT + "The limit resets at %s; try again after that." % clock(1760000000)),
    "list_unread": (("list", None, None, None, "unread"), COULD_NOT_LIST + "\nTry again later."),
    "list_as_before": (("list", None, None, None, None), COULD_NOT_LIST),
    "pick_limited": (("pick", None, None, None, "rate-limited unknown"),
                     COULD_NOT_ASK + "\n\n" + LIMIT + "The limit resets within an hour; try again after that."),
    "pick_as_before": (("pick", None, None, None, None), COULD_NOT_ASK),
}


def entry_cases(work: Path) -> dict:
    """name -> ((root, profile), whether Repair must say it wrote no entry): scratch homes in `work`, made here."""
    profile = work / "Profile Of ExampleUser"
    ordinary = profile / ".codex-auto-resume"
    elsewhere = work / "Elsewhere" / ".codex-auto-resume"
    for folder in (ordinary / "app", elsewhere / "app"):
        folder.mkdir(parents=True, exist_ok=True)
    kept_home = work / "Kept Profile"
    (kept_home / ".codex-auto-resume" / "uninstall").mkdir(parents=True)
    (kept_home / ".codex-auto-resume" / "uninstall" / "install.ps1").write_text("# kept", encoding="utf-8")
    folder_only = work / "Folder Only"
    (folder_only / ".codex-auto-resume" / "uninstall").mkdir(parents=True)
    return {
        "ordinary_without_it": ((str(ordinary), str(profile)), True),
        "ordinary_spelled_otherwise": ((str(ordinary).upper() + "\\", str(profile)), True),
        "ordinary_with_an_empty_folder": ((str(folder_only / ".codex-auto-resume"), str(folder_only)), True),
        "ordinary_with_it": ((str(kept_home / ".codex-auto-resume"), str(kept_home)), False),
        "placed_elsewhere": ((str(elsewhere), str(profile)), False),
        "no_profile": ((str(ordinary), ""), False),
    }


def prerelease_lines() -> dict:
    """PRERELEASE_LINES, and every version of the version rule's table as a `prerelease:` line:
    the window takes exactly the rule's pre-releases, as the bootstrap does."""
    import test_version_rule
    rule = {version for version, accepted in test_version_rule.CASES if accepted and "-" in version}
    lines = dict(PRERELEASE_LINES)
    for version, _ in test_version_rule.CASES:
        if "\n" in version or "\r" in version:
            continue                    # a line break ends the line; the cases above cover that
        # The window trims the line it reads, as it does the `update:` line, so what follows the
        # `v` is the version when the trimmed line's version is one by the rule.
        text = "prerelease: v" + version
        said = text.strip()[len("prerelease: v"):]
        lines[text] = said if said in rule else None
    return lines


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
                        *[str(path) for path in guiscan.sources()]],
                       check=True, capture_output=True, timeout=300)
        # Written to a file rather than passed with -Command: a command line this long is
        # refused outright on some machines, and the refusal arrives as "access is denied"
        # from CreateProcess, which reads like a permissions problem and is not one.
        probe = work / "probe.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        cls.entry = entry_cases(work / "homes")
        for _ in range(2):  # Once more if midnight passed while the window answered: its "today" may be either day.
            day = datetime.date.today()
            cls.words = dict(WORDS, **limited_today())
            result = subprocess.run(
                [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-File", str(probe)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
                env=dict(os.environ, CAR_EXE=str(exe), CAR_WORK=str(work),
                         CAR_CASES=json.dumps({name: [printed, code]
                                               for name, (printed, code, _) in CASES.items()}),
                         CAR_LINES=json.dumps(list(prerelease_lines())),
                         CAR_ENTRY=json.dumps({name: list(pair) for name, (pair, _) in cls.entry.items()}),
                         CAR_WORDS=json.dumps({name: list(asked) for name, (asked, _) in cls.words.items()})))
            if datetime.date.today() == day:
                break
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

    def test_the_compatibility_line_is_read_beside_the_update_line(self):
        """v0.6.5: an update check also refreshes the Codex compatibility data once github.com has answered,
        and says how that went on a line of its own. The window reads it so the person is told (the
        Diagnostics card says it in the refresh's own words); every case without the line reads as none."""
        for name in CASES:
            with self.subTest(name):
                self.assertEqual(self.answer[name].get("compatibility"), COMPATIBILITY.get(name))

    def test_the_prerelease_line_is_read_beside_the_update_line(self):
        """v0.6.11: the check's question about pre-releases answers on its own line, and the window
        reads it without letting it change the update's answer."""
        for name in CASES:
            with self.subTest(name):
                self.assertEqual(self.answer[name].get("prerelease"), PRERELEASE.get(name))

    def test_only_a_pre_release_by_the_rule_reaches_the_command_line(self):
        """What PrereleaseLine gives back is put on the bootstrap's command line after a yes, so it
        is the pre-release rule's and nothing else - no release, no leading zero, no second word."""
        expected = prerelease_lines()
        read = {text: version for text, version in self.answer["lines"]}
        self.assertEqual(set(read), set(expected))
        for text, version in sorted(expected.items()):
            with self.subTest(ascii(text)):
                self.assertEqual(read[text], version)

    def test_the_releases_line_is_read_beside_the_update_line(self):
        """GitHub #41: where GitHub's list could not be read the bootstrap says so on a `releases:` line, and why; the
        window reads its words without letting them change the answer, and nothing malformed is read."""
        for name in CASES:
            with self.subTest(name):
                self.assertEqual(self.answer[name].get("releases"), RELEASES.get(name))

    def test_a_check_that_could_not_read_the_list_says_pre_releases_were_not_checked(self):
        """GitHub #41: "ahead of the newest published release" was all a VPN's spent rate limit was told. Where the list
        was not read the answer says the pre-releases were not checked, names the rate limit with when it resets in this
        PC's time, or says to try again later; a list that was read, or a release to offer, leaves the words as they
        were. Install another version... says the same after its own sentence."""
        self.assertIsNotNone(self.answer["words"],
                             "SettingsForm has no UpdateWords, ListUnavailableWords or PickUnavailableWords")
        for name, (_, expected) in sorted(self.words.items()):
            with self.subTest(name):
                self.assertEqual(self.answer["words"][name].replace("\r\n", "\n"), expected)

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

    def test_a_repair_says_when_it_could_write_no_entry_in_settings_apps(self):
        """GitHub #43: the ordinary home without its kept uninstaller gets no entry in Settings > Apps from setup, and the
        installation holds no other copy of install.ps1 to put back, so Repair says so instead of saying only "Setup
        finished". A home with it, a home placed elsewhere (which never has one, as documented) and a profile that
        cannot be read say nothing more."""
        self.assertIsNotNone(self.answer["entry"], "SettingsForm has no EntryCannotBeWritten")
        for name, (_, expected) in sorted(self.entry.items()):
            with self.subTest(name):
                self.assertIs(self.answer["entry"][name], expected)


class RepairEntryTests(unittest.TestCase):
    """GitHub #43: Repair asks EntryCannotBeWritten only once setup has finished, and then says the sentence."""

    def test_a_finished_repair_says_it_wrote_no_entry(self):
        repair = guiscan.member_body("SettingsForm", "Repair")
        self.assertIn('bool noEntry = outcome == "done" &&\n'
                      '                               EntryCannotBeWritten(root, Environment.GetEnvironmentVariable("USERPROFILE"));',
                      repair)
        self.assertIn("ReportRepair(outcome, detail, noEntry);", repair)
        report = guiscan.member_body("SettingsForm", "ReportRepair")
        self.assertIn('if (noEntry)', report)
        self.assertIn('S("diag.repair_no_entry", ', report)
        self.assertLess(report.index('if (noEntry)'), report.index("Tell(text);"))


class ButtonTests(unittest.TestCase):
    """The window offers the action, and offers it apart from Repair.

    They are one word apart in a support conversation and do completely different things:
    one runs setup over the files that are here, the other fetches different ones.
    """

    def setUp(self):
        self.source = guiscan.dashboard()

    def test_diagnostics_offers_the_check(self):
        self.assertIn('S("action.check_updates", "Check for updates...")', self.source)
        self.assertIn("delegate { CheckForUpdates(); }", self.source)

    def test_it_is_disabled_while_something_else_is_in_flight(self):
        # v0.6.11: and while an administrator's DisableUpdateCheck is in force (managed.py).
        self.assertIn("if (updateButton != null) updateButton.Enabled = busy == 0 && !updatesManaged;", self.source)

    def test_an_administrators_key_turns_it_off_and_nothing_is_asked(self):
        """v0.6.11: DisableUpdateCheck, read from the status's `managed`, greys the button, says so on
        the page, and stops the check before anything is started however it is reached."""
        self.assertIn('updatesManaged = managed.Contains("DisableUpdateCheck");', self.source)
        check = self.source[self.source.index("private void CheckForUpdates()"):]
        self.assertLess(check.index("if (updatesManaged) return;"), check.index("RunBootstrap("))
        self.assertIn('S("diag.update_managed", "turned off by your administrator")', self.source)

    def test_nothing_asks_without_being_asked(self):
        """No timer, no first-open check: the only caller is the button."""
        calls = self.source.count("CheckForUpdates()")
        self.assertEqual(calls, 2, "CheckForUpdates is reached from somewhere other than "
                                   "its own definition and the button")
        clock = self.source[self.source.index("private void StartClock()"):]
        self.assertNotIn("CheckForUpdates", clock[:clock.index("\n        }")])

    def test_a_pre_release_is_offered_only_when_there_is_no_release_to_offer(self):
        """v0.6.11: the check's pre-release is offered where the answer is "current" or "newer-local"
        and a `prerelease:` line was read; a release that can be installed is offered first."""
        check = self.source[self.source.index("private void CheckForUpdates()"):]
        check = check[:check.index("\n        }\n")]
        self.assertLess(check.index('if (answer == "available") OfferUpdate('),
                        check.index("OfferPrerelease("))
        self.assertIn('else if ((answer == "current" || answer == "newer-local") && prerelease != null)\n'
                      "                        OfferPrerelease(root, script, prerelease);", check)
        self.assertEqual(self.source.count("OfferPrerelease("), 2, "defined once, called by the check alone")

    def test_the_offer_says_what_it_is_and_not_now_is_the_default(self):
        offer = self.source[self.source.index("private void OfferPrerelease("):]
        offer = offer[:offer.index("\n        }\n")]
        self.assertIn('S("confirm.prerelease",', offer)
        self.assertIn('S("action.install_prerelease", "Install pre-release"), S("action.not_now", "Not now")', offer)
        self.assertIn("if (!Dialog(", offer, "the question whose safe answer is the default")
        # A yes installs exactly the version the check printed, through -Version.
        self.assertIn('InstallUpdate(root, script, "-Version " + prerelease, prerelease);', offer)

    def test_only_the_offer_installs_a_pre_release(self):
        """The one -Version in the window is the offer's yes; nothing else passes it."""
        self.assertEqual(self.source.count('"-Version "'), 1)

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
        fix, and this is a new caller of one.

        v0.6.12: the start is StartBootstrap's, which every caller of the bootstrap goes through - the
        update check's RunBootstrap, and Install another version...'s listing and pick."""
        start = guiscan.member_body("SettingsForm", "StartBootstrap")
        self.assertIn("Environment.GetFolderPath(Environment.SpecialFolder.System)", start)
        self.assertNotIn('ProcessStartInfo("powershell', start)
        self.assertIn('info.EnvironmentVariables["CODEX_AUTO_RESUME_PLUGIN_HOME"] = root;', start)
        run = guiscan.member_body("SettingsForm", "RunBootstrap")
        self.assertIn("StartBootstrap(root, script, flag, milliseconds, out printed, out errors, out code);", run)
        self.assertNotIn("ProcessStartInfo", run, "the one start of the bootstrap is StartBootstrap's")
        self.assertEqual(self.source.count("new ProcessStartInfo(powershell,"), 1)


if __name__ == "__main__":
    unittest.main()
