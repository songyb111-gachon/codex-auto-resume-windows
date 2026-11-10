"""The setup window's bar moves only as far as the work really is (the owner, 2026-10-21).

It used to jump to a step's place when the step began and then sit there. Now the steps that count what they do say
so on a progress line of their own - `progress: <step> <done>/<total>` - and the bar takes that share of the way to the
next milestone; nothing moves it with time. What it draws glides up to that place and never past it.

* ProgressTests - gui/InstallerFlow.cs InstallerProgress and gui/InstallerWindow.cs, compiled into a setup program around
  a TEST archive (never the real installer) and called through reflection, with no window shown: a line read, its
  share mapped onto the gap to the next milestone, forward only, never past that milestone nor to the whole bar, a
  line of another step ignored, no line at all exactly as before; the glide, which never overshoots or goes back; no
  motion under a capture; the window keeping the lines out of the log it shows.
* ScriptTests - install.ps1's own pieces, lifted into scratch folders as tests/test_installer.py lifts them (never the
  real installer, never a real home): no progress line without CODEX_AUTO_RESUME_PROGRESS_LINES and real counts with
  it, at most one a percent; the copy and the removal counting what they do; the variable kept from what lives on.
* PythonTests - setup's steps and the health check's checks, counted only when asked.
* RouteTests - every way the window starts an installer asks for the lines, and only that way.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "build"), str(ROOT / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from test_installer_window import CSC, INSTALLING, NO_WINDOW, POWERSHELL, REMOVING, UPDATING, _build, _powershell  # noqa: E402

FLOW = (ROOT / "gui" / "InstallerFlow.cs").read_text(encoding="utf-8")
INSTALL_PS1 = (ROOT / "build" / "install" / "install.ps1").read_text(encoding="utf-8")
BOOTSTRAP = (ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")
VARIABLE = "CODEX_AUTO_RESUME_PROGRESS_LINES"

PARSE = ["progress: files 3/10", "    progress: setup 1/7", "progress: remove_files 0/4", "progress: check 8/8",
         "progress: files 11/10", "progress: files 3/0", "progress: files -1/10", "progress: Files 3/10",
         "progress: files 3/10 more", "progress:files 3/10", "progress: files 3-10", "progress: files 3/x",
         "  Copying the program files into place", "", "progress: 3/10"]

# (mode, milestone place, step, the bar's place, lines): a step under way, and what it hears.
PROGRESSED = [
    ["install", 0.50, "files", 0.50, ["progress: files 1/10", "progress: files 5/10", "progress: files 3/10",
                                      "progress: plugin 2/3", "  Setting up the watcher", "progress: files 10/10"]],
    ["install", 0.92, "check", 0.92, ["progress: check 4/8", "progress: check 8/8"]],
    ["uninstall", 0.70, "remove_files", 0.70, ["progress: remove_files 1/2", "progress: remove_files 2/2"]],
]

# A first installation with progress lines between its steps, as install.ps1 and setup print them for the window.
COUNTED = ["Codex Auto Resume", "edition: standard", "  [ok] Found Codex", "  Installing program files",
           "  Copying the program files into place", "  progress: files 1/4", "  progress: files 2/4",
           "  progress: setup 1/7", "  progress: files 4/4", "  [ok] Bundled Python 3.13 (no system Python needed)",
           "  Registering the Codex plugin", "  progress: plugin 1/3", "  progress: plugin 2/3", "  progress: plugin 3/3",
           "  [ok] Codex plugin installed", "  Setting up the watcher", "    progress: setup 3/7",
           "    progress: setup 7/7", "  Checking the installation", "    progress: check 8/8", "Installed and running."]

PROBE = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
Add-Type -AssemblyName System.Drawing, System.Windows.Forms
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$any = [Reflection.BindingFlags]'Static,Instance,NonPublic,Public'
function T($name) { $assembly.GetType('CodexAutoResume.' + $name, $true) }
function Call($type, $name, $arguments) { (T $type).GetMethod($name, $any).Invoke($null, [object[]]$arguments) }
function Of($object, $name) { $object.GetType().GetProperty($name, $any).GetValue($object, $null) }
function Field($object, $name) { $object.GetType().GetField($name, $any).GetValue($object) }
function CallOn($object, $name, $arguments) { $object.GetType().GetMethod($name, $any).Invoke($object, [object[]]$arguments) }
$P = T 'InstallerProgress'
$input_ = ConvertFrom-Json ([IO.File]::ReadAllText($env:CAR_INPUT, [Text.Encoding]::UTF8))
$out = @{}
$out.variable = [string]$P.GetField('Variable', $any).GetValue($null)
$out.ceiling = [double]$P.GetField('Ceiling', $any).GetValue($null)
$out.finish_seconds = [double]$P.GetField('FinishSeconds', $any).GetValue($null)

$parse = $P.GetMethod('ParseProgress', $any)
$out.parsed = @()
foreach ($line in $input_.parse) {
    $a = [object[]]@([string]$line, $null, [int]0, [int]0)
    $ok = $parse.Invoke($null, $a)
    $out.parsed += ,@([string]$line, [bool]$ok, [string]$a[1], [int]$a[2], [int]$a[3],
                      [bool](Call 'InstallerProgress' 'IsProgress' @([string]$line)))
}

$out.within = @{}
foreach ($mode in @('install', 'update', 'uninstall')) {
    $rows = @()
    foreach ($m in @(Call 'InstallerProgress' 'Of' @($mode))) {
        $a = [double]$m.GetType().GetField('At', $any).GetValue($m)
        $next = [double](Call 'InstallerProgress' 'NextPlace' @($mode, $a))
        $shares = @(foreach ($k in 0..7) { [double](Call 'InstallerProgress' 'Within' @($mode, $a, [int]$k, [int]7)) })
        $rows += ,@($a, $next, $shares)
    }
    $out.within[$mode] = $rows
}

$progressed = $P.GetMethod('Progressed', $any)
$out.progressed = @()
foreach ($case in $input_.progressed) {
    $at = [double]$case[3]
    $seen = @()
    foreach ($line in $case[4]) {
        $a = [object[]]@([string]$case[0], [string]$line, [double]$case[1], [string]$case[2], $at)
        $moved = $progressed.Invoke($null, $a)
        $at = [double]$a[4]
        $seen += ,@([bool]$moved, $at)
    }
    $out.progressed += ,$seen
}

# The glide: one frame of 1/60 s after another, from each start to each target, until it arrives or 120 frames pass.
$out.glide = @()
foreach ($case in $input_.glides) {
    $shown = [double]$case[0]; $target = [double]$case[1]; $path = @()
    for ($frame = 0; $frame -lt 120 -and $shown -lt $target; $frame++) {
        $shown = [double](Call 'InstallerProgress' 'Glide' @($shown, $target, [double](1.0 / 60)))
        $path += $shown
    }
    $out.glide += ,@($case[0], $case[1], $path)
}
$out.glide_back = [double](Call 'InstallerProgress' 'Glide' @([double]0.5, [double]0.3, [double]0.5))
$out.glide_still = [double](Call 'InstallerProgress' 'Glide' @([double]0.5, [double]0.7, [double]0))

$Bar = T 'InstallerBar'
$out.motion = @{}
foreach ($capture in @($false, $true)) { foreach ($seen in @($false, $true)) { foreach ($reduced in @($false, $true)) {
    $out.motion[('{0}/{1}/{2}' -f $capture, $seen, $reduced)] = [string]$Bar.GetMethod('MotionFor', $any).Invoke($null, [object[]]@($capture, $seen, $reduced))
} } }

# The window, built and never shown: what each line leaves the bar at, and the log it keeps.
$FlowType = T 'InstallerFlow'
function NewFlow($mode) {
    $FlowType.GetConstructors($any)[0].Invoke([object[]]@([string]$mode, 'C:\Users\ExampleUser\.codex-auto-resume',
                                                      'standard', $null, '9.9.9'))
}
$WordsType = T 'InstallerWords'
$english = $WordsType.GetConstructors($any)[0].Invoke([object[]]@($null, 'en'))
$WindowType = T 'InstallerWindow'
$font = [System.Drawing.SystemFonts]::MessageBoxFont
$advance = $P.GetMethod('Advance', $any)
$out.windows = @{}
foreach ($run in $input_.windows.PSObject.Properties) {
    $mode = [string]$run.Value[0]
    $window = $WindowType.GetConstructors($any)[0].Invoke([object[]]@((NewFlow $mode), $english, $null, $null, $null, $font))
    $bar = Field $window 'bar'
    $seen = @()
    $at = [double]0; $step = 'starting'
    foreach ($line in $run.Value[1]) {
        $null = CallOn $window 'Heard' @([string]$line)
        # InstallerProgress.Advance alone, as the window read the lines before progress lines.
        $a = [object[]]@($mode, [string]$line, $at, $step)
        $null = $advance.Invoke($null, $a)
        $at = [double]$a[2]; $step = [string]$a[3]
        $seen += ,@([double](Field $window 'at'), [string](Field $window 'step'), [double](Of $bar 'Value'),
                    [double](Of $bar 'Shown'), [string]$bar.AccessibleDescription, $at, $step)
    }
    $null = CallOn $window 'Finished' @(0, '')
    $out.windows[$run.Name] = @{ seen = $seen; log = [string](Of $window 'Log'); page = [string](Of $window 'Page')
                                 shown = [double](Of $bar 'Shown'); moving = [bool](Of $bar 'Moving') }
}
$out | ConvertTo-Json -Depth 8 -Compress
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class ProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="installer-progress-"))
        exe = _build(cls.work)
        source = cls.work / "input.json"
        glides = [[0.0, 0.25], [0.27, 0.30], [0.5, 0.6], [0.62, 0.78], [0.3, 0.92], [0.92, 1.0], [0.995, 1.0]]
        windows = {"install_plain": ["install", INSTALLING], "update_plain": ["update", UPDATING],
                   "uninstall_plain": ["uninstall", REMOVING], "install_counted": ["install", COUNTED]}
        source.write_text(json.dumps({"parse": PARSE, "progressed": PROGRESSED, "glides": glides, "windows": windows}),
                          encoding="utf-8")
        result = _powershell(PROBE, cls.work, 600, CAR_EXE=str(exe), CAR_INPUT=str(source))
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.answer = json.loads(result.stdout.strip().splitlines()[-1])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_the_variable_is_one_name_everywhere(self):
        self.assertEqual(self.answer["variable"], VARIABLE)
        from codex_auto_resume.commands import base
        self.assertEqual(base.PROGRESS_LINES, VARIABLE)
        self.assertIn("$env:%s -ceq '1'" % VARIABLE, INSTALL_PS1)
        self.assertIn("$env:%s -ceq '1'" % VARIABLE, BOOTSTRAP)

    def test_a_progress_line_is_read_and_nothing_else_is(self):
        parsed = {line: rest for line, *rest in self.answer["parsed"]}
        self.assertEqual(parsed["progress: files 3/10"], [True, "files", 3, 10, True])
        self.assertEqual(parsed["    progress: setup 1/7"], [True, "setup", 1, 7, True], "setup's lines come indented")
        self.assertEqual(parsed["progress: remove_files 0/4"], [True, "remove_files", 0, 4, True])
        self.assertEqual(parsed["progress: check 8/8"], [True, "check", 8, 8, True])
        for line in PARSE[4:]:
            with self.subTest(line):
                self.assertFalse(parsed[line][0])
                self.assertFalse(parsed[line][4])

    def test_a_share_fills_the_gap_to_the_next_milestone_and_never_passes_it(self):
        ceiling = self.answer["ceiling"]
        self.assertLess(ceiling, 1.0)
        for mode, rows in self.answer["within"].items():
            for place, following, shares in rows:
                with self.subTest(mode=mode, place=place):
                    self.assertGreater(following, place)
                    self.assertEqual(shares[0], place, "nothing done is the milestone itself")
                    self.assertEqual(shares, sorted(shares), "more done never moves it back")
                    for share in shares:
                        self.assertLessEqual(share, following + 1e-9, "never past the next milestone")
                        self.assertLessEqual(share, max(place, ceiling) + 1e-9, "the whole bar is the finish's alone")
                    if following < 1.0:
                        self.assertAlmostEqual(shares[-1], following, places=9)
                        self.assertAlmostEqual(shares[3], place + (following - place) * 3 / 7, places=9)

    def test_the_next_milestone_is_the_nearest_place_beyond(self):
        install = {round(place, 2): following for place, following, _ in self.answer["within"]["install"]}
        self.assertEqual(install[0.5], 0.6)
        self.assertEqual(install[0.62], 0.78)
        self.assertEqual(install[0.92], 1.0)
        remove = {round(place, 2): following for place, following, _ in self.answer["within"]["uninstall"]}
        self.assertEqual(remove[0.6], 0.7)
        self.assertEqual(remove[0.7], 0.95)

    def test_progress_moves_forward_only_and_only_for_the_step_under_way(self):
        files, check, remove = self.answer["progressed"]
        self.assertEqual([moved for moved, _ in files], [True, True, False, False, False, True])
        self.assertAlmostEqual(files[0][1], 0.51)
        self.assertAlmostEqual(files[1][1], 0.55)
        self.assertAlmostEqual(files[2][1], 0.55, msg="a smaller count never moves it back")
        self.assertAlmostEqual(files[3][1], 0.55, msg="another step's line is not this step's")
        self.assertAlmostEqual(files[4][1], 0.55, msg="a line that is no progress line is not read here")
        self.assertAlmostEqual(files[5][1], 0.60)
        self.assertAlmostEqual(check[0][1], 0.96)
        self.assertAlmostEqual(check[1][1], self.answer["ceiling"], msg="the last step stops short of the whole bar")
        self.assertAlmostEqual(remove[0][1], 0.825)
        self.assertAlmostEqual(remove[1][1], 0.95)

    def test_without_progress_lines_the_bar_reads_the_lines_as_it_did(self):
        """An older installer, a bootstrap from an older version: no progress line comes, and the bar is where
        InstallerProgress.Advance alone puts it - line by line, the step too."""
        for name in ("install_plain", "update_plain", "uninstall_plain"):
            for at, step, value, shown, _, advanced, advanced_step in self.answer["windows"][name]["seen"]:
                with self.subTest(name, at=at):
                    self.assertEqual((at, step), (advanced, advanced_step))
                    self.assertEqual(value, advanced)
                    self.assertEqual(shown, advanced, "not shown, so nothing glides: it draws the milestone itself")

    def test_the_window_follows_the_counts_and_a_milestone_still_begins_its_step(self):
        seen = {line.strip(): row for line, row in zip(COUNTED, self.answer["windows"]["install_counted"]["seen"])}
        self.assertAlmostEqual(seen["progress: files 1/4"][0], 0.525)
        self.assertAlmostEqual(seen["progress: files 2/4"][0], 0.55)
        self.assertAlmostEqual(seen["progress: setup 1/7"][0], 0.55, msg="not the step under way")
        self.assertAlmostEqual(seen["progress: files 4/4"][0], 0.60)
        # Counted to its end, the copy stands at the next milestone's place; that milestone's line still names its step.
        self.assertEqual(seen["[ok] Bundled Python 3.13 (no system Python needed)"][:2], [0.6, "plugin"])
        self.assertAlmostEqual(seen["progress: plugin 2/3"][0], 0.62 + 0.16 * 2 / 3)
        self.assertEqual(seen["progress: plugin 3/3"][0], 0.78)
        self.assertEqual(seen["Setting up the watcher"][:2], [0.78, "setup"])
        self.assertAlmostEqual(seen["progress: setup 3/7"][0], 0.78 + 0.14 * 3 / 7)
        self.assertEqual(seen["Checking the installation"][:2], [0.92, "check"])
        self.assertEqual(seen["progress: check 8/8"][0], self.answer["ceiling"])
        previous = 0.0
        for at, _, value, shown, said, _, _ in self.answer["windows"]["install_counted"]["seen"]:
            self.assertGreaterEqual(at, previous, "never back")
            previous = at
            self.assertEqual((value, shown), (at, at))
            if at > 0:
                self.assertEqual(said, "%d%%" % round(shown * 100), "read out as the whole percent drawn")

    def test_the_window_keeps_progress_lines_out_of_the_log(self):
        log = self.answer["windows"]["install_counted"]["log"]
        self.assertNotIn("progress:", log)
        self.assertIn("Copying the program files into place", log)
        self.assertIn("Installed and running.", log)

    def test_only_the_finish_fills_the_bar(self):
        for name, run in self.answer["windows"].items():
            with self.subTest(name):
                self.assertTrue(all(row[0] < 1.0 for row in run["seen"]))
                self.assertEqual(run["page"], "finish")
                self.assertEqual(run["shown"], 1.0, "a run that ended well fills it")
                self.assertFalse(run["moving"], "and no timer is left running")
        self.assertLessEqual(self.answer["finish_seconds"], 0.4)

    def test_the_glide_closes_on_the_target_never_past_it_never_back(self):
        for start, target, path in self.answer["glide"]:
            with self.subTest(start=start, target=target):
                self.assertTrue(path)
                self.assertEqual(path[-1], target, "it arrives")
                self.assertLessEqual(len(path), 30, "a milestone's jump takes well under a second at 60 frames a second")
                self.assertEqual(path, sorted(path))
                self.assertTrue(all(start < shown <= target for shown in path))
        self.assertEqual(self.answer["glide_back"], 0.5)
        self.assertEqual(self.answer["glide_still"], 0.5)

    def test_nothing_moves_under_a_capture_or_out_of_sight_and_reduced_motion_jumps(self):
        motion = self.answer["motion"]
        for key, moves in motion.items():
            capture, seen, reduced = (part == "True" for part in key.split("/"))
            with self.subTest(key):
                if capture or not seen:
                    self.assertEqual(moves, "None")
                else:
                    self.assertEqual(moves, "Reduced" if reduced else "Glide")


def _lift(start: str, end: str, text: str = INSTALL_PS1) -> str:
    first = text.index(start)
    return text[first:text.index(end, first)]


VOICE = ("[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false\n"
         "function Step { param([string]$m) Write-Host ('  ' + $m) }\n"
         "function Ok   { param([string]$m) Write-Host ('  [ok] ' + $m) }\n"
         "function Warn { param([string]$m) Write-Host ('  [!]  ' + $m) }\n"
         "function Fail { param([string]$m) Write-Host ('  [x]  ' + $m) }\n")
PROGRESS = _lift("function Progress {", "\n}\n") + "\n}\n" if "function Progress {" in INSTALL_PS1 else ""


def _probe(script: str, environment: dict | None = None) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory(prefix="installer-progress-ps-") as name:
        path = Path(name) / "probe.ps1"
        path.write_text(VOICE + script, encoding="utf-8-sig")
        env = {key: value for key, value in os.environ.items() if key != VARIABLE}
        env.update(environment or {})
        return subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                               str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=180, creationflags=NO_WINDOW, env=env)


def _progress_lines(output: str) -> list:
    return [line.strip() for line in output.splitlines() if line.strip().startswith("progress: ")]


@unittest.skipUnless(POWERSHELL.is_file(), "needs Windows PowerShell")
class ScriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="installer-progress-tree-"))
        self.addCleanup(shutil.rmtree, self.temp, True)

    def run_lifted(self, body: str, asked: bool) -> subprocess.CompletedProcess:
        environment = {VARIABLE: "1"} if asked else {}
        gate = _lift("$script:ProgressLines = $env:", "\n\n")
        result = _probe(PROGRESS + gate + "\n" + body, environment)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_progress_says_nothing_unless_the_window_asked(self):
        body = ("Progress 'files' 1 4\nProgress 'files' 4 4\n"
                "Write-Host ('left: [' + $env:CODEX_AUTO_RESUME_PROGRESS_LINES + ']')\n")
        quiet = self.run_lifted(body, asked=False)
        self.assertEqual(_progress_lines(quiet.stdout), [])
        asked = self.run_lifted(body, asked=True)
        self.assertEqual(_progress_lines(asked.stdout), ["progress: files 1/4", "progress: files 4/4"])
        self.assertIn("left: []", asked.stdout, "read once, and taken out of what this run starts")

    def test_at_most_one_line_a_percent(self):
        asked = self.run_lifted("foreach ($i in 1..1000) { Progress 'files' $i 1000 }\n", asked=True)
        lines = _progress_lines(asked.stdout)
        self.assertLessEqual(len(lines), 100)
        self.assertEqual(lines[0], "progress: files 10/1000")
        self.assertEqual(lines[-1], "progress: files 1000/1000")

    def make_payload(self) -> Path:
        payload = self.temp / "payload"
        for relative in ("app/src/pkg/a.py", "app/src/pkg/b.py", "app/scripts/plugin_setup.py", "runtime/python.exe",
                         "runtime/Lib/x.pyc"):
            path = payload / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(relative, encoding="utf-8")
        (payload / "app" / "empty").mkdir()
        hidden = payload / "app" / ".hidden"
        hidden.write_text("hidden", encoding="utf-8")
        subprocess.run(["attrib", "+h", str(hidden)], check=True, creationflags=NO_WINDOW)
        return payload

    def copy_body(self, payload: Path, home: Path) -> str:
        functions = _lift("function Get-PayloadTree", "function Invoke-Setup")
        copy = _lift("        $copying = @()", "    } catch {")
        return (functions + "\n$Payload = '%s'\n" % payload +
                "$pairs = @(@{ src = 'app'; dst = '%s' }, @{ src = 'runtime'; dst = '%s' })\n"
                % (home / "app", home / "runtime") + "try {\n" + copy + "} catch { Write-Host ('failed: ' + $_); exit 3 }\n")

    def test_the_copy_counts_every_file_and_copies_what_the_whole_tree_did(self):
        payload = self.make_payload()
        for asked in (False, True):
            home = self.temp / ("home-%s" % asked)
            result = self.run_lifted(self.copy_body(payload, home), asked=asked)
            with self.subTest(asked=asked):
                copied = sorted(str(path.relative_to(home)) for path in home.rglob("*"))
                expected = sorted(str(path.relative_to(payload)) for path in payload.rglob("*"))
                self.assertEqual(copied, expected, "every file and folder, the hidden file and the empty folder too")
                self.assertEqual((home / "runtime" / "Lib" / "x.pyc").read_text(encoding="utf-8"), "runtime/Lib/x.pyc")
                lines = _progress_lines(result.stdout)
                if asked:
                    self.assertEqual(lines, ["progress: files %d/6" % done for done in range(1, 7)])
                else:
                    self.assertEqual(lines, [])

    def test_a_failed_copy_still_reaches_the_rollback(self):
        payload = self.make_payload()
        home = self.temp / "home"
        (home / "app").mkdir(parents=True)
        # A folder where a file is to go: the copy of that file fails, and the catch around it runs.
        (home / "app" / "src" / "pkg" / "a.py").mkdir(parents=True)
        result = _probe(PROGRESS + self.copy_body(payload, home))
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)

    def test_the_removal_counts_each_entry_and_each_folder(self):
        functions = (_lift("function Resolve-Canonical", "function Get-Edition") +
                     _lift("function Remove-OwnedItem", "function Get-PayloadTree"))
        removal = _lift("    $stuck = @()", "    if ($stuck.Count -gt 0)")
        for asked in (False, True):
            home = self.temp / ("installed-%s" % asked)
            for relative in ("app/src/a.py", "app/scripts/b.py", "app/README.txt", "runtime/python.exe"):
                path = home / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("x", encoding="utf-8")
            body = (functions + "\n$OwnedHome = '%s'\n$AppDir = '%s'\n$RunDir = '%s'\n" % (home, home / "app", home / "runtime")
                    + removal + "Write-Host ('stuck: ' + $stuck.Count)\n")
            result = self.run_lifted(body, asked=asked)
            with self.subTest(asked=asked):
                self.assertIn("stuck: 0", result.stdout)
                self.assertFalse((home / "app").exists())
                self.assertFalse((home / "runtime").exists())
                lines = _progress_lines(result.stdout)
                self.assertEqual(lines, ["progress: remove_files %d/6" % done for done in range(1, 7)] if asked else [])

    def test_setup_and_the_health_check_alone_are_asked_to_count(self):
        app = self.temp / "app"
        (app / "scripts").mkdir(parents=True)
        # A stand-in setup that says which command it ran and whether it was asked to count.
        (app / "scripts" / "plugin_setup.py").write_text(
            "import os, sys\nprint(sys.argv[1] + ' ' + os.environ.get('%s', '-'))\n" % VARIABLE, encoding="utf-8")
        function = _lift("function Invoke-Setup", "\nfunction ")
        body = (function + "\n$AppDir = '%s'\n$Python = '%s'\n" % (app, sys.executable) +
                "foreach ($command in @('setup', 'doctor', 'stop', 'watcher-running')) { $null = Invoke-Setup @($command) }\n"
                "Write-Host ('after: [' + $env:CODEX_AUTO_RESUME_PROGRESS_LINES + ']')\n")
        asked = self.run_lifted(body, asked=True)
        self.assertIn("setup 1", asked.stdout)
        self.assertIn("doctor 1", asked.stdout)
        self.assertIn("stop -", asked.stdout)
        self.assertIn("watcher-running -", asked.stdout)
        self.assertIn("after: []", asked.stdout)
        quiet = self.run_lifted(body, asked=False)
        for command in ("setup", "doctor", "stop", "watcher-running"):
            self.assertIn("%s -" % command, quiet.stdout)

    def test_the_plugin_s_three_commands_are_counted_in_order(self):
        step = _lift("    Step 'Registering the Codex plugin'", "    Step 'Setting up the watcher'")
        marks = [step.index("Progress 'plugin' %d 3" % done) for done in (1, 2, 3)]
        self.assertEqual(marks, sorted(marks))
        self.assertLess(step.index("'marketplace', 'add'"), marks[0])
        self.assertLess(step.index("'marketplace', 'upgrade'"), marks[1])
        self.assertLess(marks[1], step.index("@('plugin', 'add'"))
        self.assertLess(step.index("Ok 'Codex plugin installed'"), marks[2])

    def test_the_variable_is_read_after_the_outside_gate_and_taken_out(self):
        gate = INSTALL_PS1.index("if ($null -ne $outsideCode) { exit $outsideCode }")
        read = INSTALL_PS1.index("$script:ProgressLines = $env:%s -ceq '1'" % VARIABLE)
        cleared = INSTALL_PS1.index("$env:%s = $null" % VARIABLE, read)
        self.assertLess(gate, read)
        self.assertLess(cleared - read, 120)
        self.assertLess(cleared, INSTALL_PS1.index("Step 'Copying the program files into place'"))

    def test_the_bootstrap_passes_the_request_to_the_installer_alone(self):
        read = BOOTSTRAP.index("$progressLines = $env:%s -ceq '1'" % VARIABLE)
        cleared = BOOTSTRAP.index("$env:%s = $null" % VARIABLE, read)
        self.assertLess(cleared - read, 120)
        self.assertLess(cleared, BOOTSTRAP.index("Get-PluginVersion\n"), "before anything is started")
        given = BOOTSTRAP.index("if ($progressLines) { $env:%s = '1' }" % VARIABLE)
        self.assertEqual(BOOTSTRAP[given:].splitlines()[1].strip(), "& $installer @arguments")
        self.assertEqual(BOOTSTRAP.count("$env:%s = '1'" % VARIABLE), 1)
        # Its own one count is the archive's bytes (tests/test_bootstrap_streamed_download.py): that line alone, and
        # only for the archive, only when the window asked.
        self.assertEqual(BOOTSTRAP.count("progress: "), BOOTSTRAP.count("progress: download "))
        self.assertEqual(BOOTSTRAP.count("Write-Host ('  progress: download '"), 1)
        self.assertEqual(BOOTSTRAP.count("-Count:$progressLines"), 1)
        self.assertIn("Get-Remote -Uri ($base + $name) -OutFile $zip -What 'The archive' -Count:$progressLines\n",
                      BOOTSTRAP)


class PythonTests(unittest.TestCase):
    def test_a_progress_line_only_when_asked(self):
        from codex_auto_resume.commands import base
        for value, expected in ((None, ""), ("0", ""), ("1", "progress: setup 2/7\n")):
            environment = {key: item for key, item in os.environ.items() if key != VARIABLE}
            if value is not None:
                environment[VARIABLE] = value
            with mock.patch.dict(os.environ, environment, clear=True):
                said = io.StringIO()
                with contextlib.redirect_stdout(said):
                    base.progress("setup", 2, 7)
                    base.progress("setup", 1, 0)
                self.assertEqual(said.getvalue(), expected, value)

    def counted(self, text: str, function: str, step: str, constant: str) -> list:
        start = text.index("def %s(" % function)
        body = text[start:text.index("\ndef ", start + 1)]
        return [int(done) for done in re.findall(r'progress\("%s", (\d+), %s\)' % (step, constant), body)]

    def test_setup_counts_each_of_its_steps_once_in_order(self):
        text = (ROOT / "scripts" / "plugin_setup.py").read_text(encoding="utf-8")
        total = int(re.search(r"^SETUP_STEPS = (\d+)$", text, re.M).group(1))
        self.assertEqual(self.counted(text, "cmd_setup", "setup", "SETUP_STEPS"), list(range(1, total + 1)))
        body = text[text.index("def cmd_setup("):]
        self.assertLess(body.index("start_watcher(home)"), body.index('progress("setup", %d' % total),
                        "the watcher is counted once it is started, not before")

    def test_the_health_check_counts_each_of_its_checks_once_in_order(self):
        text = (ROOT / "src" / "codex_auto_resume" / "commands" / "status.py").read_text(encoding="utf-8")
        total = int(re.search(r"^DOCTOR_CHECKS = (\d+)$", text, re.M).group(1))
        self.assertEqual(self.counted(text, "cmd_doctor", "check", "DOCTOR_CHECKS"), list(range(1, total + 1)))

    def test_the_watcher_never_inherits_the_request(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("plugin_setup_progress", ROOT / "scripts" / "plugin_setup.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as name:
            home = Path(name)
            started = {}

            class App:
                def __init__(self, *arguments, **keywords):
                    pass

                def watcher_running(self):
                    return False

            def popen(*arguments, **keywords):
                started.update(keywords)
                return object()

            with mock.patch.dict(os.environ, {VARIABLE: "1"}), \
                    mock.patch.object(module, "App", App), \
                    mock.patch.object(module, "python_for_watcher", return_value=Path(name) / "pythonw.exe"), \
                    mock.patch.object(module.subprocess, "Popen", side_effect=popen), \
                    mock.patch.object(module.control, "await_watcher", return_value={"state": "running"}):
                self.assertEqual(module.start_watcher(home), "running")
        self.assertIn("env", started)
        self.assertNotIn(VARIABLE, started["env"])
        self.assertIn("PATH", {key.upper() for key in started["env"]}, "the rest of the environment is kept")


class RouteTests(unittest.TestCase):
    def test_a_setup_program_asks_only_for_its_window(self):
        setup = (ROOT / "build" / "setup" / "Setup.cs").read_text(encoding="utf-8")
        self.assertIn("if (heard != null) start.EnvironmentVariables[CodexAutoResume.InstallerProgress.Variable] = \"1\";",
                      setup)
        self.assertIn("else start.EnvironmentVariables.Remove(CodexAutoResume.InstallerProgress.Variable);", setup)

    def test_the_dashboard_s_update_asks_only_for_its_window_and_keeps_no_progress_line(self):
        dashboard = (ROOT / "gui" / "DashboardMaintenance.cs").read_text(encoding="utf-8")
        # Asked for only while its window hears the lines: tests/test_gui_pick_window.py holds those two.
        self.assertIn("if (!InstallerProgress.IsProgress(line)) lines.Append(line)", dashboard)

    def test_the_uninstall_from_settings_asks_for_its_window(self):
        remove = (ROOT / "gui" / "SettingsRemove.cs").read_text(encoding="utf-8")
        self.assertIn("start.EnvironmentVariables[InstallerProgress.Variable] = \"1\";", remove)


if __name__ == "__main__":
    unittest.main()
