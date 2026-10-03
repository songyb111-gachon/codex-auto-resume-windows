r"""Install another version... (v0.6.12): the Diagnostics button, its dialog, and what the window makes of
the bootstrap's -Versions and -Pick answers.

The window fetches nothing. It starts the installed scripts/bootstrap.ps1 when a person presses the button
(the list) and when they confirm a row (the install), and reads its closed lines back. So what is held here:

* the button is last in the Tools card, waits while an action runs and is greyed by DisableUpdateCheck, and
  the header's Start watcher waits too - an install that has stopped the watcher must not be undone by it;
* only the button's handler starts the listing: the dialog is built starting nothing, so the window audit,
  which builds and fills it, never asks GitHub for anything (C4);
* the confirmation is the careful one, -Force goes with exactly an older row or one of the other edition, and
  the version reaches the command line only through the version rule;
* the parsers, compiled and called through reflection as tests/test_gui_update.py calls RunBootstrap, refuse
  the whole answer on any word outside their closed sets, and read the conversion's counts as integers only;
* every English word is the catalog's (the 17 other catalogs follow with the translation).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import guiscan

ROOT = Path(__file__).resolve().parents[1]
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
ENGLISH = ROOT / "src" / "codex_auto_resume" / "locales" / "en.json"

LISTED = "versions: listed 0.6.12-beta standard 0.6.13 v0.6.2 v0.6.11-alpha"
ROWS = [
    "version: 0.6.13 standard offered newer,release,kept,latest",
    "version: 0.6.13 advanced offered newer,release,kept,latest,edition",
    "version: 0.6.12-beta.2 standard refused not-offered",
    "version: 0.6.12-beta standard installed -",
    "version: 0.6.12-beta advanced offered same,prerelease,kept,edition",
    "version: 0.6.11 standard offered older,release,kept",
    "version: 0.6.11-alpha advanced offered older,prerelease,convert3,edition,advanced-off",
    "version: 0.6.10 standard offered older,release,convert3",
    "version: 0.6.6-alpha standard refused no-archive",
    "version: 0.6.5 standard refused no-checksum",
    "version: 0.6.4 standard refused managed-policy",
    "version: 0.6.3 advanced refused edition-first",
    "version: 0.6.3 standard refused older-prerelease",
]
GOOD = "\n".join(["  Asking api.github.com for this repository's whole list of releases, page by page."] + ROWS + [LISTED])


def rows_with(*replaced: str) -> str:
    """GOOD with its first row replaced by each of `replaced`."""
    return "\n".join(list(replaced) + ROWS[1:] + [LISTED])


# name -> (what -Versions prints, its exit code, the state read, the rows read, the listed line read)
VERSIONS = {
    "listed": (GOOD, 0, "listed", [row[len("version: "):] for row in ROWS],
               "0.6.12-beta standard 0.6.13 0.6.2 0.6.11-alpha"),
    "no_rows": ("versions: listed 0.6.12 advanced - v0.6.2 v0.6.11-alpha", 0, "listed", [],
                "0.6.12 advanced - 0.6.2 0.6.11-alpha"),
    "unavailable": ("  [!] The list of releases could not be read (timeout).\nversions: unavailable", 12,
                    "unavailable", [], None),
    # The line and the code have to agree, and "could not ask" carries no row.
    "unavailable_but_zero": ("versions: unavailable", 0, "unreadable", [], None),
    "unavailable_with_a_row": (ROWS[0] + "\nversions: unavailable", 12, "unreadable", [], None),
    "listed_but_twelve": (GOOD, 12, "unreadable", [], None),
    "listed_but_one": (GOOD, 1, "unreadable", [], None),
    "silent": ("", 0, "unreadable", [], None),
    "no_last_line": ("\n".join(ROWS), 0, "unreadable", [], None),
    "two_last_lines": (GOOD + "\n" + LISTED, 0, "unreadable", [], None),
    "a_row_after_the_last_line": (GOOD + "\n" + ROWS[0], 0, "unreadable", [], None),
    "an_unknown_last_line": ("\n".join(ROWS + ["versions: fine"]), 0, "unreadable", [], None),
    # A word outside the closed sets refuses the whole answer, never the row alone.
    "unknown_word": (rows_with("version: 0.6.13 standard offered newer,release,kept,shiny"), 0, "unreadable", [], None),
    "unknown_reason": (rows_with("version: 0.6.13 standard refused tired"), 0, "unreadable", [], None),
    "unknown_answer": (rows_with("version: 0.6.13 standard maybe -"), 0, "unreadable", [], None),
    "no_words": (rows_with("version: 0.6.13 standard offered "), 0, "unreadable", [], None),
    "a_fifth_field": (rows_with("version: 0.6.13 standard offered newer,release,kept -Force"), 0, "unreadable", [], None),
    "a_leading_zero": (rows_with("version: 0.6.013 standard offered newer,release,kept"), 0, "unreadable", [], None),
    "a_command_in_the_version": (rows_with("version: 0.6.13;calc standard offered newer,release,kept"), 0,
                                 "unreadable", [], None),
    "an_edition_in_capitals": (rows_with("version: 0.6.13 Standard offered newer,release,kept"), 0,
                               "unreadable", [], None),
    "two_orders": (rows_with("version: 0.6.13 standard offered newer,older,release,kept"), 0, "unreadable", [], None),
    "no_schema_word": (rows_with("version: 0.6.13 standard offered newer,release"), 0, "unreadable", [], None),
    "a_word_twice": (rows_with("version: 0.6.13 standard offered newer,release,kept,kept"), 0, "unreadable", [], None),
    # The words agree with the row they are on.
    "prerelease_word_on_a_release": (rows_with("version: 0.6.13 standard offered newer,prerelease,kept"), 0,
                                     "unreadable", [], None),
    "release_word_on_a_prerelease": (rows_with("version: 0.6.13-beta standard offered newer,release,kept"), 0,
                                     "unreadable", [], None),
    "latest_on_a_prerelease": (rows_with("version: 0.6.13-beta standard offered newer,prerelease,kept,latest"), 0,
                               "unreadable", [], None),
    "the_other_edition_without_its_word": (rows_with("version: 0.6.13 advanced offered newer,release,kept"), 0,
                                           "unreadable", [], None),
    "this_edition_with_the_word": (rows_with("version: 0.6.13 standard offered newer,release,kept,edition"), 0,
                                   "unreadable", [], None),
    "same_in_this_edition": (rows_with("version: 0.6.13 standard offered same,release,kept"), 0, "unreadable", [], None),
    "advanced_off_in_standard": (rows_with("version: 0.6.13 standard offered newer,release,kept,advanced-off"), 0,
                                 "unreadable", [], None),
    "installed_is_another_version": (rows_with("version: 0.6.13 standard installed -"), 0, "unreadable", [], None),
    "installed_with_words": (rows_with("version: 0.6.12-beta standard installed newer"), 0, "unreadable", [], None),
    "a_row_twice": (rows_with(ROWS[1]), 0, "unreadable", [], None),
    "the_floor_without_its_v": ("\n".join(ROWS + ["versions: listed 0.6.12-beta standard 0.6.13 0.6.2 v0.6.11-alpha"]),
                                0, "unreadable", [], None),
    "a_newest_that_is_no_version": ("\n".join(ROWS + ["versions: listed 0.6.12-beta standard latest v0.6.2 v0.6.11-alpha"]),
                                    0, "unreadable", [], None),
}

CONVERTED = "pick: state converted 12 1 2 3 1"
# name -> (what -Pick prints, its exit code, the outcome, the reason, the counts, the installed line)
PICKS = {
    "installed": ("pick: offered newer,release,kept,latest\n  Installing\n  [ok] done\npick: installed 0.6.13 standard", 0,
                  "installed", None, None, "0.6.13 standard"),
    "installed_after_the_conversion": ("pick: offered older,release,convert3\n" + CONVERTED +
                                       "\npick: installed 0.6.10 standard", 0,
                                       "installed", None, [12, 1, 2, 3, 1], "0.6.10 standard"),
    "installed_but_not_zero": ("pick: offered newer,release,kept\npick: installed 0.6.13 standard", 1,
                               "failed", None, None, None),
    "installed_without_its_offer": ("pick: installed 0.6.13 standard", 0, "failed", None, None, None),
    "installed_a_version_that_is_none": ("pick: offered newer,release,kept\npick: installed 0.6.13x standard", 0,
                                         "failed", None, None, None),
    # The installer's own failure: its code and no installed line. The conversion before it is still said.
    "the_installer_failed": ("pick: offered older,release,convert3\n" + CONVERTED + "\n  [!] Codex is not installed", 1,
                             "failed", None, [12, 1, 2, 3, 1], None),
    "unavailable": ("  [!] The list of releases could not be read.\npick: unavailable", 12, "unavailable", None, None, None),
    "unavailable_but_zero": ("pick: unavailable", 0, "failed", None, None, None),
    "refused_but_one": ("pick: refused busy", 1, "failed", None, None, None),
    "refused_for_no_known_reason": ("pick: refused tired", 15, "failed", None, None, None),
    "an_unknown_line": ("pick: offered newer,release,kept\npick: maybe", 0, "failed", None, None, None),
    "an_unknown_offered_word": ("pick: offered newer,shiny\npick: installed 0.6.13 standard", 0, "failed", None, None, None),
    "two_answers": ("pick: refused busy\npick: installed 0.6.13 standard", 15, "failed", None, None, None),
    "silent": ("", 0, "failed", None, None, None),
    # The counts are whole numbers and the flag 0 or 1, or the line is not read at all.
    "a_count_that_is_text": ("pick: offered older,release,convert3\npick: state converted 12 x 2 3 1\n"
                             "pick: installed 0.6.10 standard", 0, "failed", None, None, None),
    "a_negative_count": ("pick: offered older,release,convert3\npick: state converted 12 -1 2 3 1\n"
                         "pick: installed 0.6.10 standard", 0, "failed", None, None, None),
    "a_flag_of_two": ("pick: offered older,release,convert3\npick: state converted 12 1 2 3 2\n"
                      "pick: installed 0.6.10 standard", 0, "failed", None, None, None),
    "a_count_too_long": ("pick: offered older,release,convert3\npick: state converted 1234567890 1 2 3 1\n"
                         "pick: installed 0.6.10 standard", 0, "failed", None, None, None),
    "six_counts": ("pick: offered older,release,convert3\npick: state converted 12 1 2 3 1 0\n"
                   "pick: installed 0.6.10 standard", 0, "failed", None, None, None),
    "a_conversion_before_the_offer": (CONVERTED + "\npick: offered older,release,convert3\npick: installed 0.6.10 standard",
                                      0, "failed", None, [12, 1, 2, 3, 1], None),
}
for _reason in ("installed", "unreadable", "needs-force", "force-not-needed", "changed", "busy", "watcher-running",
                "state"):
    PICKS["refused_" + _reason] = ("  [!] no\npick: refused " + _reason, 15, "refused", _reason, None, None)

# name -> (the picked row, the version installed, whether the confirmation says Check for updates in that version
# brings you back). Its check stays in its edition and offers a release from v0.6.2 on, a pre-release only from
# v0.6.11-beta.2, the first bootstrap with Get-NewerPrerelease; v0.6.2 to v0.6.11-beta read releases/latest alone.
WAY_BACK = {
    "a_release_from_a_prerelease_that_offers_them": ("0.6.11 standard offered older,release,kept", "0.6.12-beta", True),
    "the_first_that_offers_prereleases": ("0.6.11-beta.2 standard offered older,prerelease,kept", "0.6.12-beta", True),
    "an_older_prerelease_of_this_line": ("0.6.12-alpha.2 standard offered older,prerelease,kept", "0.6.12-beta", True),
    "one_that_reads_latest_alone": ("0.6.11-beta standard offered older,prerelease,kept", "0.6.12-beta", False),
    "a_release_that_reads_latest_alone": ("0.6.10 standard offered older,release,convert3", "0.6.12-beta", False),
    "the_floor_from_a_prerelease": ("0.6.2 standard offered older,release,convert3", "0.6.12-beta", False),
    "the_floor_from_a_release": ("0.6.2 standard offered older,release,convert3", "0.6.12", True),
    "an_advanced_release_from_a_prerelease": ("0.6.11 advanced offered older,release,kept", "0.6.12-beta", True),
    "an_advanced_one_that_reads_latest_alone": ("0.6.11-alpha advanced offered older,prerelease,convert3,advanced-off",
                                                "0.6.12-beta", False),
    "another_edition_from_a_release": ("0.6.11 advanced offered older,release,kept,edition", "0.6.12", False),
    "the_standard_edition_from_the_advanced": ("0.6.10 standard offered older,release,convert3,edition", "0.6.12", False),
    "a_newer_one": ("0.6.13 standard offered newer,release,kept,latest", "0.6.12", False),
}

# SettingsForm.HeldColumns: name -> (the columns' widths, the list's width, the least What it means keeps before the
# others give way, the widths held). No form is larger than the screen allows, so on GitHub's 1024 by 768 runners the
# dialog at 200% and the largest text size (4.5 times) had a list 856 wide for four columns at their least, 864.
HELD = {
    "the_runners_screen": ([216, 216, 216, 216], 856, 108, [216, 216, 216, 208]),
    "a_list_they_fit_at_100": ([105, 116, 80, 397], 698, 24, [105, 116, 80, 397]),
    "a_list_they_fill_at_450": ([274, 473, 335, 1293], 2375, 108, [274, 473, 335, 1293]),
    "what_it_means_down_to_its_ellipsis": ([576, 576, 576, 576], 2000, 144, [576, 576, 576, 272]),
    "then_every_column_in_proportion": ([624, 624, 624, 624], 1800, 144, [557, 557, 557, 129]),
    "no_room_at_all": ([216, 216, 216, 216], 0, 108, [0, 0, 0, 0]),
}

PROBE = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$flags = [Reflection.BindingFlags]'Static,NonPublic,Public'
$versions = $form.GetMethod('VersionsLines', $flags)
$pick = $form.GetMethod('PickLine', $flags)
$rule = $form.GetField('VersionRule', $flags).GetValue($null)
$wayBack = $form.GetMethod('WayBack', $flags)
$held = $form.GetMethod('HeldColumns', $flags)
if (-not $versions -or -not $pick -or -not $rule -or -not $wayBack -or -not $held) { throw 'SettingsForm lacks a parser' }
$out = @{ versions = @{}; picks = @{}; rule = @(); way_back = @{}; held = @{} }
foreach ($case in (ConvertFrom-Json $env:CAR_HELD).PSObject.Properties) {
    $arguments = [object[]]@([int[]]$case.Value[0], [int]$case.Value[1], [int]$case.Value[2])
    $out.held[$case.Name] = @([int[]]$held.Invoke($null, $arguments))
}
foreach ($case in (ConvertFrom-Json $env:CAR_WAY_BACK).PSObject.Properties) {
    $arguments = New-Object 'object[]' 2
    $arguments[0] = [string[]]([string]$case.Value[0]).Split(' ')
    $arguments[1] = [string]$case.Value[1]
    $out.way_back[$case.Name] = [bool]$wayBack.Invoke($null, $arguments)
}
foreach ($case in (ConvertFrom-Json $env:CAR_VERSIONS).PSObject.Properties) {
    $arguments = [object[]]@([string]$case.Value[0], [int]$case.Value[1], $null, $null)
    $state = $versions.Invoke($null, $arguments)
    $rows = @()
    foreach ($row in $arguments[2]) { $rows += ([string[]]$row -join ' ') }
    $listed = $null
    if ($null -ne $arguments[3]) { $listed = ([string[]]$arguments[3] -join ' ') }
    $out.versions[$case.Name] = @{ state = $state; rows = $rows; listed = $listed }
}
foreach ($case in (ConvertFrom-Json $env:CAR_PICKS).PSObject.Properties) {
    $arguments = [object[]]@([string]$case.Value[0], [int]$case.Value[1], $null, $null, $null)
    $outcome = $pick.Invoke($null, $arguments)
    $counts = $null
    if ($null -ne $arguments[3]) { $counts = @([int[]]$arguments[3]) }
    $out.picks[$case.Name] = @{ outcome = $outcome; reason = $arguments[2]; counts = $counts; installed = $arguments[4] }
}
foreach ($text in (ConvertFrom-Json $env:CAR_RULE)) {
    $out.rule += ,@([string]$text, $rule.IsMatch([string]$text))
}
$out | ConvertTo-Json -Depth 6 -Compress
"""


def rule_cases() -> list:
    """Every version of the version rule's table that is one line, and what a command line reads as more."""
    import test_version_rule
    cases = [(version, accepted) for version, accepted in test_version_rule.CASES
             if "\n" not in version and "\r" not in version]
    return cases + [("0.6.12-alpha -Force", False), ("0.6.12 -Edition Advanced", False), ("v0.6.12", False),
                    ("0.6.12\"", False), ("", False)]


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class ParserTests(unittest.TestCase):
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
        probe = work / "probe.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        result = subprocess.run(
            [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
            env=dict(os.environ, CAR_EXE=str(exe),
                     CAR_VERSIONS=json.dumps({name: [case[0], case[1]] for name, case in VERSIONS.items()}),
                     CAR_PICKS=json.dumps({name: [case[0], case[1]] for name, case in PICKS.items()}),
                     CAR_RULE=json.dumps([text for text, _ in rule_cases()]),
                     CAR_WAY_BACK=json.dumps({name: [case[0], case[1]] for name, case in WAY_BACK.items()}),
                     CAR_HELD=json.dumps({name: list(case[:3]) for name, case in HELD.items()})))
        cls.result = result
        cls.answer = json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else {}

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-2000:])

    def test_each_listing_is_read_as_itself_or_not_at_all(self):
        for name, (_, _, state, rows, listed) in sorted(VERSIONS.items()):
            with self.subTest(name):
                read = self.answer["versions"][name]
                self.assertEqual(read["state"], state)
                self.assertEqual(list(read["rows"] or []), rows, "no row of an answer that is not read")
                self.assertEqual(read["listed"], listed)

    def test_each_pick_answer_is_read_as_itself(self):
        for name, (_, _, outcome, reason, counts, installed) in sorted(PICKS.items()):
            with self.subTest(name):
                read = self.answer["picks"][name]
                self.assertEqual(read["outcome"], outcome)
                self.assertEqual(read["reason"], reason)
                self.assertEqual(read["counts"], counts)
                self.assertEqual(read["installed"], installed)

    def test_only_a_version_by_the_rule_reaches_the_command_line(self):
        read = {text: matched for text, matched in self.answer["rule"]}
        for text, accepted in rule_cases():
            with self.subTest(ascii(text)):
                self.assertEqual(read[text], accepted)

    def test_the_way_back_is_said_only_where_that_versions_check_for_updates_brings_you_back(self):
        """Check for updates in v0.6.2 to v0.6.11-beta reads releases/latest alone, so from a pre-release it can
        never offer the one you came from, and no version's check changes the edition."""
        for name, (_, _, said) in sorted(WAY_BACK.items()):
            with self.subTest(name):
                self.assertIs(self.answer["way_back"][name], said)

    def test_the_columns_are_held_to_the_list_however_narrow_windows_makes_the_dialog(self):
        """As they are wherever they fit; else What it means - said whole for the chosen row under the list - gives
        way first, down to an ellipsis, then every column in proportion, and never are they wider than the list."""
        for name, (widths, room, ellipsis, held) in sorted(HELD.items()):
            with self.subTest(name):
                read = list(self.answer["held"][name])
                self.assertEqual(read, held)
                self.assertLessEqual(sum(read), max(room, 0))


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.window = guiscan.whole()
        self.dashboard = guiscan.dashboard()

    def body(self, name: str) -> str:
        return guiscan.member_body("SettingsForm", name)

    def test_the_dialog_is_a_window_source_of_the_dashboard(self):
        self.assertIn("gui/DashboardVersions.cs", guiscan.group("dashboard"))

    def test_the_button_is_last_in_the_tools_card_and_has_one_handler(self):
        page = self.body("BuildDiagnostics")
        self.assertIn('versionsButton = MakeButton(S("action.pick_version", "Install another version..."), false, '
                      'delegate { OpenVersions(); });', page)
        tools = page[page.index("foreach (Button button in new[] {"):]
        self.assertIn("demoButton,\n                versionsButton })", tools.replace("\r\n", "\n"),
                      "after Show me what happens, so no button before it moves")
        self.assertEqual(self.window.count("OpenVersions()"), 2, "defined once, and the button's handler")

    def test_it_waits_while_an_action_runs_and_an_administrator_greys_it(self):
        line = "if (versionsButton != null) versionsButton.Enabled = busy == 0 && !updatesManaged;"
        self.assertIn(line, self.body("SetBusy"))
        self.assertEqual(self.dashboard.count(line), 2, "in SetBusy and where the status says what is managed")
        opened = self.body("OpenVersions")
        self.assertLess(opened.index("if (updatesManaged) return;"), opened.index("BuildVersions()"))

    def test_start_watcher_waits_while_an_action_runs(self):
        """An install that stopped the watcher - a conversion for an older version - must not have the current watcher
        started under it from this window's header before the installer has run."""
        rule = "startButton.Enabled = busy == 0 && !starting;"
        self.assertIn("if (startButton != null) " + rule, self.body("SetBusy"))
        start = self.body("StartWatcher")
        self.assertLess(start.index("starting = true;"), start.index("QueueUserWorkItem("))
        finished = self.body("StartWatcherFinished")
        self.assertLess(finished.index("starting = false;"), finished.index(rule))
        self.assertNotIn("startButton.Enabled = true", self.window)

    def test_only_the_buttons_handler_starts_the_listing(self):
        opened = self.body("OpenVersions")
        order = [opened.index(text) for text in ("BuildVersions()", "StartVersionsListing(dialog, root, script);",
                                                 "dialog.ShowDialog(this)", "ConfirmPick(", "InstallPick(")]
        self.assertEqual(order, sorted(order))
        self.assertEqual(self.window.count("StartVersionsListing("), 2, "defined once, and called by OpenVersions")
        self.assertEqual(self.window.count('"-Versions"'), 1)
        self.assertIn('StartBootstrap(root, script, "-Versions", ListMilliseconds,', self.body("StartVersionsListing"))
        self.assertEqual(self.window.count("StartBootstrap("), 4,
                         "defined once; the update check's RunBootstrap, the listing and the pick")
        self.assertIn("StartBootstrap(root, script, flag, UpdateMilliseconds,", self.body("InstallPick"))

    def test_building_the_dialog_starts_nothing(self):
        built = self.body("BuildVersions")
        for started in ("StartBootstrap", "StartVersionsListing", "Process", "Timer", "QueueUserWorkItem", "Shown +=",
                        "bridge."):
            with self.subTest(started):
                self.assertNotIn(started, built)
        self.assertIn('S("pick.asking", "Asking GitHub for the list of releases...")', built)
        self.assertIn("install.Enabled = false;", built)
        self.assertIn("dialog.CancelButton = close;", built)
        self.assertNotIn("dialog.AcceptButton", built, "Enter installs nothing")

    def test_the_audit_builds_and_fills_the_dialog_without_asking(self):
        audit = self.body("AuditVersions")
        self.assertIn("VersionsLines(AuditedVersions, 0, out rows, out listed)", audit)
        self.assertLess(audit.index("BuildVersions()"), audit.index("ShowVersionRows(state, rows, listed);"))
        for started in ("StartBootstrap", "StartVersionsListing", "Process", "QueueUserWorkItem", "OpenVersions"):
            with self.subTest(started):
                self.assertNotIn(started, audit)
        self.assertIn('AuditList("versions/"', audit)
        self.assertIn('AuditSpoken("versions", dialog, findings);', audit)
        self.assertIn("form.AuditVersions(findings);", self.body("LayoutAuditAt"))

    def test_a_closed_dialog_drops_the_answer_and_still_ends_the_wait(self):
        listing = self.body("StartVersionsListing")
        self.assertLess(listing.index("SetBusy(true);"), listing.index("QueueUserWorkItem("))
        apply = listing[listing.index("MethodInvoker apply"):]
        self.assertLess(apply.index("SetBusy(false);"), apply.index("if (mine != versionsToken || dialog.IsDisposed) return;"))
        self.assertNotIn("Kill", listing)

    def test_the_list_never_scrolls_sideways_however_narrow_windows_makes_the_dialog(self):
        """No form is larger than the screen allows, so where the screen is too small for the dialog its list is
        narrower than its columns' least; after FitColumns they are held to it, as the list's width changes and as its
        rows are measured, and FitColumns is not asked while they are set."""
        built = self.body("BuildVersions")
        self.assertIn("view.ClientSizeChanged += delegate { HoldVersionColumns(view); };", built)
        self.assertLess(built.index("var view = List("), built.index("HoldVersionColumns(view)"),
                        "after FitColumns, which List asks first")
        shown = self.body("ShowVersionRows")
        self.assertLess(shown.index("MeasureCells(versionsList);"), shown.index("HoldVersionColumns(versionsList);"))
        hold = self.body("HoldVersionColumns")
        self.assertIn("HeldColumns(widths, list.ClientSize.Width, Px(24))", hold)
        self.assertLess(hold.index("columnWeights.Remove(list);"), hold.index("list.Columns[i].Width = held[i];"))

    def test_the_confirmation_is_the_careful_one(self):
        confirm = self.body("ConfirmPick")
        self.assertIn('S("action.install", "Install"), S("action.not_now", "Not now"));', confirm)
        self.assertIn("return Dialog(", confirm)
        self.assertNotIn("Confirm(", confirm)
        opened = self.body("OpenVersions")
        self.assertIn("if (!ConfirmPick(picked, listed)) return;", opened)
        self.assertIn('picked[2] != "offered"', opened, "only an offered row is ever asked about")

    def test_the_way_back_is_said_only_where_it_holds(self):
        """For an older row the confirmation said "To come back, use Check for updates in that version." whatever the
        row: false from a pre-release for v0.6.2 to v0.6.11-beta, and after any change of edition (WayBack)."""
        confirm = self.body("ConfirmPick")
        self.assertIn('if (WayBack(row, listed[0]))\n                text.Add(S("pick.confirm.way_back"', confirm)
        self.assertEqual(confirm.count('"pick.confirm.way_back"'), 1)
        way_back = self.body("WayBack")
        self.assertIn('!HasWord(row, "older") || HasWord(row, "edition")', way_back)
        self.assertIn("CompareVersions(row[0], PrereleaseOffersSince) >= 0", way_back)

    def test_force_goes_with_an_older_row_or_the_other_edition_alone(self):
        install = self.body("InstallPick")
        self.assertIn('bool force = words.Contains("older") || words.Contains("edition");', install)
        self.assertIn('(force ? " -Force" : "")', install)
        self.assertEqual(self.window.count('" -Force"'), 1)
        self.assertLess(install.index("VersionRule.IsMatch(row[0])"), install.index('"-Pick "'),
                        "the version is held to the rule before it reaches the command line")
        self.assertIn('(row[1] == "advanced" ? "Advanced" : "Standard")', install)
        self.assertIn("SetBusy(true);", install[:install.index("QueueUserWorkItem(")])

    def test_a_refused_row_stays_in_the_list_quietly_and_each_chip_has_its_tone(self):
        cell = self.body("DrawCell")
        self.assertIn("Color ink = Palette.Contrast && selected ? SystemColors.HighlightText : "
                      "PickRefusedRow(row) ? Secondary : Ink;", cell)
        tone = self.body("ToneFor")
        for code, tint in (("PickRelease", "Success"), ("PickPrerelease", "Warning"), ("PickInstalled", "Accent"),
                           ("PickUnavailable", "Paused")):
            with self.subTest(code):
                self.assertIn("if (code == %s) return Palette.%s;" % (code, tint), tone)
        self.assertIn('Str(row, "code") == PickUnavailable', self.body("PickRefusedRow"))

    def test_the_window_reaches_no_network(self):
        for name in guiscan.window_sources():
            text = guiscan.read(name)
            for word in ("System.Net", "WebClient", "HttpClient", "WebRequest", "TcpClient", "Socket"):
                with self.subTest(source=name, word=word):
                    self.assertNotIn(word, text)

    def test_every_english_word_is_the_catalogs(self):
        """Each fallback is the English catalog's sentence, every Install another version... key the catalog has is
        one the window says, and none is built at run time."""
        english = json.loads(ENGLISH.read_text(encoding="utf-8"))
        literal = r'"((?:[^"\\]|\\.)*)"'
        found = {}
        for key, said in re.findall(r'S\("(pick\.[a-z_.]+|action\.pick_version)",\s*' + literal, self.window):
            found.setdefault(key, set()).add(json.loads('"%s"' % said))
        self.assertNotRegex(self.window, r'S\("pick\.[a-z_.]*"\s*\+', "a key built at run time")
        wanted = {key for key in english if key.startswith("pick.")} | {"action.pick_version"}
        self.assertEqual(set(found), wanted)
        for key, fallbacks in sorted(found.items()):
            with self.subTest(key):
                self.assertEqual(fallbacks, {english[key]})
        for key, said in (("diag.update_watcher_unknown", "Whether the watcher restarted could not be confirmed."),
                          ("edition.standard", "Standard"), ("edition.advanced", "Advanced")):
            with self.subTest(key):
                self.assertEqual(english[key], said)
                self.assertIn('S("%s", "%s")' % (key, said), guiscan.read("gui/DashboardVersions.cs"))


if __name__ == "__main__":
    unittest.main()
