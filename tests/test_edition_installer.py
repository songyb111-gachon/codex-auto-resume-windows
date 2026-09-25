r"""The installer's side of an edition change: asked for, said first, and nothing left behind.

Moving between editions is a reinstall, never an update (ROADMAP.md). So build/install/install.ps1
reads the installed edition before its move-aside, and when this archive is the other one it says
what the change keeps and changes, and stops with 14 unless -AllowEditionChange says it was asked
for - which Install.cmd passes after a y/N answer, and the bootstrap only after -Edition and
-Force. Going ahead, the old app tree goes whole, so no advanced package outlives a move to the
standard edition, and setup is told the edition it replaced, with --keep-state as for any upgrade.

The installer's own region - from the moment it decides whether this is an upgrade to the moment
both program trees are in place, and the lines that assemble setup's arguments - is lifted out
verbatim and run, with every function the installer defines and the running-watcher lookup
stubbed to find none, against a scratch installation home and a scratch payload. So what runs is
the installer's move-aside and copy, and nothing touches a real installation, the registry, Codex
or a running process. Install.cmd is run as it is, from a scratch folder, with a stub installer
beside it that only writes down how it was called.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)        # editions lives next to this file

import editions  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
INSTALL_DIR = ROOT / "build" / "install"
INSTALLER = INSTALL_DIR / "install.ps1"
LAUNCHER = INSTALL_DIR / "Install.cmd"
BOOTSTRAP = ROOT / "scripts" / "bootstrap.ps1"
SYSTEM = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
POWERSHELL = SYSTEM / "WindowsPowerShell" / "v1.0" / "powershell.exe"
CMD = SYSTEM / "cmd.exe"
PACKAGE = editions.PACKAGE

REGION = r"""
$ErrorActionPreference = 'Stop'
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:CAR_INSTALLER, [ref]$null, [ref]$errors)
if ($errors -and $errors.Count) { throw 'install.ps1 does not parse' }
foreach ($node in $ast.FindAll({ param($n)
        $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    Invoke-Expression $node.Extent.Text
}
# Nothing running belongs to a scratch installation. Said outright rather than asked of WMI, so
# no process on this machine is ever a candidate for the handover.
function Get-OwnedWatcherProcess { return ,@() }
$text = [IO.File]::ReadAllText($env:CAR_INSTALLER)
function Get-Region {
    param([string]$From, [string]$To)
    $first = $text.IndexOf($From, [StringComparison]::Ordinal)
    if ($first -lt 0) { throw ('install.ps1 has no ' + $From) }
    $last = $text.IndexOf($To, $first, [StringComparison]::Ordinal)
    if ($last -lt 0) { throw ('install.ps1 has no ' + $To) }
    return $text.Substring($first, $last - $first)
}
# What the installer has settled by the time it reaches the region.
$script:Failed = $false
$InstallHome = $env:CAR_HOME
$AppDir = Join-Path $InstallHome 'app'
$RunDir = Join-Path $InstallHome 'runtime'
$Payload = $env:CAR_PAYLOAD
$Journal = Join-Path $InstallHome '.codex-auto-resume-install-journal.json'
$OwnedHome = Resolve-Canonical $InstallHome
$claimedAside = @()
$AllowEditionChange = ($env:CAR_ALLOW -eq '1')
$SkipStartup = $false
$edition = Get-Edition -Src (Join-Path $Payload 'app\src')
Invoke-Expression (Get-Region '$upgrade = Test-Path $AppDir' '# The settings window and the icon live at the payload root')
Invoke-Expression (Get-Region "`$setupArgs = @('setup')" '# 2 means everything was done')
Write-Output ('SETUP ' + ($setupArgs -join ' '))
exit 0
"""


def tree(root: Path, edition: str, marker: str) -> None:
    """An app tree of `edition`, which says whose it is in marker.txt."""
    (root / "src" / "codex_auto_resume").mkdir(parents=True)
    (root / "src" / "codex_auto_resume" / "__init__.py").write_text("", encoding="utf-8")
    (root / "marker.txt").write_text(marker, encoding="utf-8")
    if edition == "advanced":
        (root / "src" / PACKAGE).mkdir()
        (root / "src" / PACKAGE / "__init__.py").write_text("", encoding="utf-8")


def snapshot(root: Path) -> dict:
    return {str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
            for path in sorted(root.rglob("*"))}


@unittest.skipUnless(POWERSHELL.is_file(), "the installer is PowerShell on Windows")
class EditionChangeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.home = self.root / "home"
        self.payload = self.root / "payload"

    def given(self, installed, payload):
        """An installation of edition `installed` (None: nothing yet) with a setting of its own,
        and a payload of edition `payload`."""
        if installed:
            tree(self.home / "app", installed, "installed")
            (self.home / "runtime").mkdir(parents=True)
            (self.home / "runtime" / "python.exe").write_bytes(b"the installed runtime")
            (self.home / "config").mkdir()
            (self.home / "config" / "settings.json").write_text('{"enabled": false}', encoding="utf-8")
        else:
            self.home.mkdir()
        tree(self.payload / "app", payload, "payload")
        (self.payload / "runtime").mkdir(parents=True)
        (self.payload / "runtime" / "python.exe").write_bytes(b"the payload runtime")
        for name in ("CodexAutoResumeSettings.exe", "codex-auto-resume.ico"):
            (self.payload / name).write_bytes(b"x")

    def run_region(self, allow=False):
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-Command", REGION],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                              errors="replace", timeout=300,
                              env=dict(os.environ, CAR_INSTALLER=str(INSTALLER), CAR_HOME=str(self.home),
                                       CAR_PAYLOAD=str(self.payload), CAR_ALLOW="1" if allow else "0"))
        setup = [line[len("SETUP "):] for line in done.stdout.splitlines() if line.startswith("SETUP ")]
        return done.returncode, done.stdout, (setup[0].split() if setup else None)

    @property
    def package(self) -> Path:
        return self.home / "app" / "src" / PACKAGE

    def test_a_change_nobody_asked_for_is_said_and_refused_before_anything_moves(self):
        for installed, payload, statement in (
                ("advanced", "standard", "Advanced edition -> Standard edition; settings and pending "
                                         "recoveries are kept; "),
                ("standard", "advanced", "Standard edition -> Advanced edition; settings and pending "
                                         "recoveries are kept; every advanced feature starts off")):
            with self.subTest(installed):
                shutil.rmtree(self.home, ignore_errors=True)
                shutil.rmtree(self.payload, ignore_errors=True)
                self.given(installed, payload)
                before = snapshot(self.home)
                code, output, setup = self.run_region()
                self.assertEqual(code, 14, output[-1500:])
                self.assertIn(statement, output)
                self.assertIn("-AllowEditionChange", output)
                self.assertIsNone(setup)
                self.assertEqual(snapshot(self.home), before, "something was moved, swept or written")

    def test_a_move_to_the_standard_edition_leaves_no_advanced_code(self):
        self.given("advanced", "standard")
        code, output, setup = self.run_region(allow=True)
        self.assertEqual(code, 0, output[-1500:])
        self.assertFalse(self.package.exists(), "the advanced package outlived the move")
        self.assertEqual((self.home / "app" / "marker.txt").read_text(encoding="utf-8"), "payload")
        self.assertEqual((self.home / "config" / "settings.json").read_text(encoding="utf-8"),
                         '{"enabled": false}')
        self.assertEqual(sorted(path.name for path in self.home.iterdir()), ["app", "config", "runtime"],
                         "a copy moved aside, or the journal, was left behind")
        self.assertEqual(setup, ["setup", "--keep-state", "--edition-from", "advanced"])

    def test_a_move_to_the_advanced_edition_tells_setup_where_it_came_from(self):
        """The new edition's own setup is what starts every advanced feature off
        (`install --edition-from`); the installer only has to tell it."""
        self.given("standard", "advanced")
        code, output, setup = self.run_region(allow=True)
        self.assertEqual(code, 0, output[-1500:])
        self.assertTrue((self.package / "__init__.py").is_file())
        self.assertEqual(setup, ["setup", "--keep-state", "--edition-from", "standard"])
        self.assertIn("Standard edition -> Advanced edition", output)

    def test_the_same_edition_is_an_ordinary_upgrade(self):
        for edition in ("standard", "advanced"):
            with self.subTest(edition):
                shutil.rmtree(self.home, ignore_errors=True)
                shutil.rmtree(self.payload, ignore_errors=True)
                self.given(edition, edition)
                code, output, setup = self.run_region()
                self.assertEqual(code, 0, output[-1500:])
                self.assertNotIn(" -> ", output)
                self.assertEqual(setup, ["setup", "--keep-state"])
                self.assertEqual(self.package.exists(), edition == "advanced")

    def test_a_first_install_changes_no_edition(self):
        self.given(None, "advanced")
        code, output, setup = self.run_region()
        self.assertEqual(code, 0, output[-1500:])
        self.assertNotIn(" -> ", output)
        self.assertEqual(setup, ["setup"])


class EditionChangeTextTests(unittest.TestCase):
    def setUp(self):
        self.text = INSTALLER.read_text(encoding="utf-8")

    def test_the_edition_is_read_before_the_sweep_the_handover_and_the_move(self):
        read = self.text.index("$previousEdition = Get-Edition -Src (Join-Path $AppDir 'src')")
        refused = self.text.index("exit $EDITION_CHANGE_REFUSED")
        self.assertLess(self.text.index("$upgrade = Test-Path $AppDir"), read)
        self.assertLess(read, refused)
        for later in ("Get-ChildItem -Path $OwnedHome -Directory -Filter '*.old-*'",
                      "if ((Get-OwnedWatcherProcess).Count -gt 0)", "Write-CopyJournal -Path $Journal",
                      "Move-Item -Path $pair.dst -Destination $aside"):
            with self.subTest(later):
                self.assertLess(refused, self.text.index(later))

    def test_the_three_scripts_mean_the_same_thing_by_14(self):
        """The bootstrap's refusal, the installer's, and the code Install.cmd reads as its cue to
        ask - one number, or a refusal would reach the person as a failure with no question."""
        bootstrap = re.search(r"\$ExitOtherEdition = (\d+)", BOOTSTRAP.read_text(encoding="utf-8"))
        installer = re.search(r"\$EDITION_CHANGE_REFUSED = (\d+)", self.text)
        launcher = re.search(r'if "%EXIT_CODE%"=="(\d+)" goto ask', LAUNCHER.read_text(encoding="utf-8"))
        self.assertEqual({bootstrap.group(1), installer.group(1), launcher.group(1)}, {"14"})
        self.assertNotIn("exit 14", self.text, "by name, so the three can be found together")

    def test_setup_accepts_what_the_installer_passes(self):
        """A flag setup does not define is an argparse error and a failed install."""
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import plugin_setup
        finally:
            sys.path.remove(str(ROOT / "scripts"))
        for edition in ("standard", "advanced"):
            parsed = plugin_setup.build_parser().parse_args(
                ["setup", "--keep-state", "--edition-from", edition])
            self.assertEqual((parsed.keep_state, parsed.edition_from), (True, edition))

    def test_only_the_bootstrap_and_install_cmd_pass_the_permission(self):
        self.assertIn("[switch]$AllowEditionChange", self.text)
        bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn("if ($plan.Verdict -eq 'change') { $arguments['AllowEditionChange'] = $true }",
                      bootstrap)
        self.assertEqual(bootstrap.count("AllowEditionChange"), 1)
        launcher = LAUNCHER.read_text(encoding="utf-8")
        self.assertEqual(launcher.count("-AllowEditionChange"), 1)
        self.assertLess(launcher.index(":change"), launcher.index("-AllowEditionChange"))


# Stands in for install\install.ps1 beside Install.cmd: it writes down each call, and refuses the
# first with the code a case names unless it was allowed.
STUB = r"""
param([switch]$AllowEditionChange, [switch]$SkipStartup)
Add-Content -LiteralPath (Join-Path $PSScriptRoot 'calls.txt') -Encoding ASCII `
            -Value ('allow=' + [bool]$AllowEditionChange + ' skip=' + [bool]$SkipStartup)
if ($AllowEditionChange) { exit 0 }
exit ([int]$env:CAR_FIRST_EXIT)
"""


@unittest.skipUnless(CMD.is_file() and POWERSHELL.is_file(), "Install.cmd is a Windows batch file")
class InstallCmdTests(unittest.TestCase):
    """Install.cmd asks, and only when the installer stopped for an edition change."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        shutil.copyfile(LAUNCHER, self.folder / "Install.cmd")
        (self.folder / "install").mkdir()
        (self.folder / "install" / "install.ps1").write_text(STUB, encoding="utf-8")

    def run_it(self, first_exit, answer):
        done = subprocess.run([str(CMD), "/d", "/c", str(self.folder / "Install.cmd"), "-SkipStartup"],
                              input=answer, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=120,
                              env=dict(os.environ, CAR_FIRST_EXIT=str(first_exit)))
        calls = (self.folder / "install" / "calls.txt")
        return done.returncode, done.stdout, calls.read_text(encoding="ascii").split() if calls.is_file() else []

    def test_yes_runs_it_again_with_the_permission_and_the_same_arguments(self):
        for answer in ("y\r\n", "Y\r\n", "yes\r\n"):
            with self.subTest(answer):
                (self.folder / "install" / "calls.txt").unlink(missing_ok=True)
                code, output, calls = self.run_it(14, answer)
                self.assertEqual(code, 0, output)
                self.assertIn("Change the edition? [y/N]", output)
                self.assertEqual(calls, ["allow=False", "skip=True", "allow=True", "skip=True"])

    def test_anything_else_changes_nothing(self):
        """No is the default: Enter, another word, the end of input, and an answer written to
        break out of the comparison all leave the installed edition as it is."""
        for answer in ("\r\n", "n\r\n", "no\r\n", "", 'y" == "y" goto change\r\n', "y&echo broken\r\n"):
            with self.subTest(answer):
                (self.folder / "install" / "calls.txt").unlink(missing_ok=True)
                code, output, calls = self.run_it(14, answer)
                self.assertEqual(code, 14, output)
                self.assertIn("Nothing was changed.", output)
                self.assertNotIn("broken", output)
                self.assertEqual(calls, ["allow=False", "skip=True"])

    def test_it_asks_only_after_an_edition_refusal(self):
        for first in (0, 1, 2):
            with self.subTest(first):
                (self.folder / "install" / "calls.txt").unlink(missing_ok=True)
                code, output, calls = self.run_it(first, "y\r\n")
                self.assertEqual(code, first, output)
                self.assertNotIn("Change the edition?", output)
                self.assertEqual(calls, ["allow=False", "skip=True"])


if __name__ == "__main__":
    unittest.main()
