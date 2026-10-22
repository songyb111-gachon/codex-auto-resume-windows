"""Install another version... runs in the installer window, as the Dashboard's update does (v0.6.18 acceptance).

The owner, 2026-10-21: moving to another version should show the setup window too. Before, the pick ran the installed
bootstrap's -Pick with no window: the Dashboard said "installing...", and nobody saw the download, the steps, the finish
or a log, and the streamed download's bytes reached no bar. Now the pick starts the InstallerWindow with the progress
lines asked for (StartBootstrap sets InstallerProgress.Variable where a window listens), headed as an install of
another version (InstallerFlow.Another) - never as an update - with the bar's steps, the finished page with the exit
code (PickCode) and the log; and what the bootstrap printed still reaches PickLine whole, the -Force rule is as it was,
and AfterPick and ReportPick say what they said. Where it installed and the window opens the new Dashboard, this one
closes, as after an update.

Read from the window's sources (guiscan), and compiled with the in-box compiler and called through reflection, so what
is tested is what ships. Nothing is shown and nothing is installed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import guiscan  # noqa: E402
from codex_auto_resume import l10n  # noqa: E402

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
ENGLISH = l10n.catalog("en")


def body(member: str) -> str:
    return guiscan.member_body("SettingsForm", member)


class SourceTests(unittest.TestCase):
    def test_the_pick_runs_in_the_installer_window_as_an_install_of_another_version(self):
        pick = body("InstallPick")
        self.assertIn("var flow = new InstallerFlow(InstallerFlow.Update, root, edition,", pick)
        self.assertIn("flow.Another = true;", pick)
        self.assertIn("var window = new InstallerWindow(flow, new InstallerWords(strings, openedLanguage), null,", pick)
        self.assertIn("window.ShowDialog(this);", pick)
        self.assertLess(pick.index("new InstallerWindow("), pick.index("window.ShowDialog(this);"))
        self.assertNotIn("QueueUserWorkItem", pick, "the window runs it on its worker, as it runs an update")

    def test_the_window_hears_each_line_with_the_progress_lines_asked_for(self):
        pick = body("InstallPick")
        heard = pick.index("Heard = line;")
        started = pick.index("StartBootstrap(root, script, flag, UpdateMilliseconds, out printed, out errors, out code);")
        self.assertLess(heard, started, "set before the bootstrap starts")
        self.assertGreater(pick.index("finally { Heard = null; }"), started, "and cleared once it has ended")
        self.assertNotIn("-AskFirst", pick, "a pick prints no notes and asks nothing")
        self.assertNotIn("Asked =", pick)
        started = body("StartBootstrap")
        self.assertIn("if (Heard != null) info.EnvironmentVariables[InstallerProgress.Variable] = \"1\";", started)
        self.assertIn("else info.EnvironmentVariables.Remove(InstallerProgress.Variable);", started)
        self.assertEqual(guiscan.read("gui/InstallerFlow.cs").count('internal const string Variable = '
                                                                    '"CODEX_AUTO_RESUME_PROGRESS_LINES";'), 1)

    def test_pick_line_still_gets_the_whole_printed_text(self):
        pick = body("InstallPick")
        self.assertIn("outcome = PickLine(printed, code, out reason, out converted, out installed);", pick)
        self.assertIn("releases = ran == \"done\" ? ReleasesLine(printed) : null;", pick)
        self.assertIn('if (outcome == "installed" && installed != version + " " + edition) outcome = "failed";', pick)
        self.assertIn('detail = Tail(printed + "\\n" + errors);', pick)
        # Heard or not, StartBootstrap keeps every line but the window's own progress lines.
        started = body("StartBootstrap")
        self.assertIn("if (!InstallerProgress.IsProgress(line)) lines.Append(line).Append('\\n');", started)
        self.assertIn("heard(line);", started)

    def test_the_force_rule_and_the_command_line_are_as_they_were(self):
        pick = body("InstallPick")
        self.assertIn('bool force = words.Contains("older") || words.Contains("edition");', pick)
        self.assertIn('string flag = "-Pick " + row[0] + " -Edition " + (row[1] == "advanced" ? "Advanced" : "Standard") +\n'
                      '                          (force ? " -Force" : "");', pick)
        self.assertLess(pick.index("VersionRule.IsMatch(row[0])"), pick.index('"-Pick "'))

    def test_after_the_window_the_words_are_the_ones_the_pick_always_said(self):
        pick = body("InstallPick")
        shown = pick.index("window.ShowDialog(this);")
        self.assertLess(shown, pick.index("if (outcome == \"installed\") AfterPick(before, version, converted);"))
        self.assertLess(shown, pick.index("ReportPick(outcome, reason, converted, detail, releases);"))
        self.assertLess(shown, pick.index("updatingHere = false;"))
        said = set(re.findall(r'S\("([a-z_.]+)"', body("AfterPick") + body("ReportPick")))
        self.assertEqual(said, {
            "diag.update_installed", "diag.update_done", "pick.watcher_restarted", "pick.watcher_same",
            "diag.update_watcher_unknown", "pick.done_converted", "pick.reopen", "diag.repair_busy",
            "pick.refused.watcher_running", "pick.refused.state", "diag.update_incomplete", "pick.refused.changed",
            "diag.update_running", "pick.failed", "pick.failed_converted"})
        self.assertIn("Tell(PickUnavailableWords(releases));", body("ReportPick"))

    def test_an_installed_pick_closes_this_dashboard_as_an_update_does(self):
        """The acceptance saw the Dashboard that ran the pick stay open from its renamed .old file. As after an update
        (InstallUpdate), the window's Open the Dashboard opens the version now installed and this one closes."""
        pick = body("InstallPick")
        closing = pick[pick.index('if (outcome == "installed" && window.OpenDashboard &&'):]
        self.assertLess(closing.index("if (OpenNewDashboard(root))"), closing.index("Close();"))
        self.assertLess(closing.index("Close();"), closing.index("AfterPick("))
        # The conversion is said before it closes, in the words AfterPick says it with.
        self.assertLess(closing.index('S("pick.done_converted"'), closing.index("OpenNewDashboard(root)"))
        self.assertLess(closing.index("AppendConverted(told, converted);"), closing.index("Close();"))
        update = body("InstallUpdate")
        self.assertIn('if (answer == "installed" && window.OpenDashboard && OpenNewDashboard(root))', update)

    def test_the_window_names_it_an_install_of_another_version(self):
        window = guiscan.read("gui/InstallerWindow.cs")
        self.assertIn(': flow.Another ? words.Say("installer.progress.another", "Installing another version")', window)
        self.assertIn('? words.Say("installer.done.installed_version", "Installed v{version}", "version", flow.Version)',
                      window)
        self.assertEqual(ENGLISH["installer.progress.another"], "Installing another version")
        self.assertEqual(ENGLISH["installer.done.installed_version"], "Installed v{version}")
        for locale in l10n.LOCALES:
            catalog = l10n.catalog(locale)
            with self.subTest(locale):
                self.assertTrue(catalog.get("installer.progress.another", "").strip())
                self.assertIn("{version}", catalog.get("installer.done.installed_version", ""))
                self.assertNotEqual(catalog["installer.progress.another"], catalog["installer.progress.updating"])
                self.assertNotEqual(catalog["installer.done.installed_version"], catalog["installer.done.updated_to"])

    def test_the_bar_reads_the_picks_own_ask_line(self):
        flow = guiscan.read("gui/InstallerFlow.cs")
        self.assertIn('new Milestone("Asking api.github.com for this repository\'s whole list of releases", 0.05, "ask"),',
                      flow)
        bootstrap = (ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")
        self.assertIn("Step 'Asking api.github.com for this repository''s whole list of releases again", bootstrap)
        self.assertIn("Get-Remote -Uri ($base + $name) -OutFile $zip -What 'The archive' -Count:$progressLines",
                      bootstrap)


PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$asm = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$any = [Reflection.BindingFlags]'Static,Instance,NonPublic,Public'
$form = $asm.GetType('CodexAutoResume.SettingsForm', $true)
$code = $form.GetMethod('PickCode', $any)
$codes = @{}
foreach ($case in @(@('done', 'installed', 0), @('done', 'refused', 15), @('done', 'unavailable', 12),
                    @('done', 'failed', 0), @('done', 'failed', 3), @('running', 'running', -1),
                    @('incomplete', 'incomplete', -1), @('failed', 'failed', -1))) {
    $codes[$case[0] + '/' + $case[1] + '/' + $case[2]] = $code.Invoke($null, [object[]]@($case[0], $case[1], [int]$case[2]))
}
$flowType = $asm.GetType('CodexAutoResume.InstallerFlow', $true)
$flow = [Activator]::CreateInstance($flowType, $any, $null,
                                    [object[]]@('update', 'C:\Users\ExampleUser\.codex-auto-resume', 'advanced', 'standard', '0.6.11-beta.2'), $null)
$flowType.GetField('Another', $any).SetValue($flow, $true)
$pages = @($flowType.GetMethod('Pages', $any).Invoke($flow, @()))
$update = [Activator]::CreateInstance($flowType, $any, $null,
                                      [object[]]@('update', 'C:\Users\ExampleUser\.codex-auto-resume', 'standard', 'standard', '0.6.19'), $null)
$updatePages = @($flowType.GetMethod('Pages', $any).Invoke($update, @()))
$wordsType = $asm.GetType('CodexAutoResume.InstallerWords', $true)
$jsonType = $asm.GetType('CodexAutoResume.Json', $true)
$catalog = $jsonType.GetMethod('Parse', $any).Invoke($null, [object[]]@([IO.File]::ReadAllText($env:CAR_CATALOG)))
$words = [Activator]::CreateInstance($wordsType, $any, $null, [object[]]@($catalog, 'en'), $null)
$windowType = $asm.GetType('CodexAutoResume.InstallerWindow', $true)
function Texts($control) {
    $found = @()
    foreach ($child in $control.Controls) { if ($child.Text) { $found += [string]$child.Text }; $found += Texts $child }
    return $found
}
$seen = @{}
foreach ($one in @(@('pick', $flow), @('update', $update))) {
    $window = [Activator]::CreateInstance($windowType, $any, $null,
                                          [object[]]@($one[1], $words, $null, $null, $null, $null), $null)
    $windowType.GetMethod('ShowPage', $any).Invoke($window, [object[]]@('progress'))
    $progress = @(Texts $window)
    $windowType.GetMethod('Finished', $any).Invoke($window, [object[]]@([int]0, ''))
    $finish = @(Texts $window)
    $windowType.GetMethod('Finished', $any) | Out-Null
    $seen[$one[0]] = @{ progress = $progress; finish = $finish; open = [bool]$windowType.GetProperty('OpenDashboard', $any).GetValue($window) }
    $window.Dispose()
}
@{ codes = $codes; pages = $pages; update_pages = $updatePages; seen = $seen } | ConvertTo-Json -Depth 5 -Compress
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class CompiledTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        exe = Path(cls.folder.name) / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll",
                        "/reference:System.Windows.Forms.dll",
                        *[str(path) for path in guiscan.sources()]],
                       check=True, capture_output=True, timeout=300, creationflags=NO_WINDOW)
        probe = Path(cls.folder.name) / "probe.ps1"
        probe.write_text(PROBE, encoding="utf-8-sig")
        env = dict(os.environ, CAR_EXE=str(exe), CAR_CATALOG=str(l10n.DIRECTORY / "en.json"))
        result = subprocess.run([str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                 "-File", str(probe)], capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=300, env=env, creationflags=NO_WINDOW)
        cls.result = result
        cls.answer = json.loads(result.stdout.strip().splitlines()[-1]) if result.returncode == 0 and result.stdout.strip() else {}

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-3000:])

    def test_the_window_gets_the_picks_code(self):
        self.assertEqual(self.answer["codes"], {
            "done/installed/0": 0, "done/refused/15": 15, "done/unavailable/12": 12, "done/failed/0": 1,
            "done/failed/3": 3, "running/running/-1": -2, "incomplete/incomplete/-1": -1, "failed/failed/-1": -1})

    def test_a_pick_has_no_notes_page_and_an_update_keeps_its_own(self):
        self.assertEqual(self.answer["pages"], ["progress", "finish"])
        self.assertEqual(self.answer["update_pages"], ["progress", "notes", "finish"])

    def test_it_is_headed_as_an_install_of_another_version_never_an_update(self):
        pick, update = self.answer["seen"]["pick"], self.answer["seen"]["update"]
        self.assertIn("Installing another version", pick["progress"])
        self.assertNotIn("Updating", pick["progress"])
        self.assertIn("Installed v0.6.11-beta.2", pick["finish"])
        self.assertNotIn("Updated to v0.6.11-beta.2", pick["finish"])
        self.assertIn("Exit code: 0", pick["finish"])
        self.assertIn("Updating", update["progress"])
        self.assertIn("Updated to v0.6.19", update["finish"])
        self.assertTrue(pick["open"], "an installed pick opens the version installed, as an update does")


if __name__ == "__main__":
    unittest.main()
