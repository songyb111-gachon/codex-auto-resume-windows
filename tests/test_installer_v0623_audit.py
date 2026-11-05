r"""The installer findings of the v0.6.23 audit (plans/v0623-audit/windows-and-tooling.md, Area B, N1 to N13).

One class per finding, each lifting the functions it is about out of build/install/install.ps1 (or scripts/bootstrap.ps1)
and running them against scratch folders and stand-ins: no codex, no registry, no real installation, no running process.
A class fails when its fix is reverse-applied.
"""
from __future__ import annotations

import json
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
    sys.path.insert(0, _HERE)

import test_edition_installer as editions_run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
INSTALL_PS1 = (ROOT / "build" / "install" / "install.ps1").read_text(encoding="utf-8")
BOOTSTRAP_PS1 = (ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")
SYSTEM = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
POWERSHELL = SYSTEM / "WindowsPowerShell" / "v1.0" / "powershell.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
WINDOWS = os.name == "nt"

# Every function a script defines, as its own text defines it, lifted by the parser (the way test_edition_installer does).
LIFT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:CAR_SCRIPT, [ref]$null, [ref]$errors)
if ($errors -and $errors.Count) { throw 'the script does not parse' }
foreach ($node in $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    Invoke-Expression $node.Extent.Text
}
$script:Failed = $false
$script:Said = New-Object System.Collections.ArrayList
function Warn { param([string]$m) $null = $script:Said.Add('warn: ' + $m) }
function Ok { param([string]$m) $null = $script:Said.Add('ok: ' + $m) }
function Step { param([string]$m) $null = $script:Said.Add('step: ' + $m) }
function Fail { param([string]$m) $null = $script:Said.Add('fail: ' + $m); $script:Failed = $true }
"""


def run_ps(body: str, script: Path = ROOT / "build" / "install" / "install.ps1", timeout: int = 300, **environment):
    """Run `body` after the script's functions are defined; its last line of output is JSON."""
    done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
                           LIFT + body],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, creationflags=NO_WINDOW,
                          env=dict(os.environ, CAR_SCRIPT=str(script), **environment))
    return done.returncode, done.stdout


def last_json(output: str):
    return json.loads([line for line in output.splitlines() if line.strip()][-1])


def block(text: str, start: str, end: str) -> str:
    first = text.index(start)
    return text[first:text.index(end, first + len(start))]


class Scratch(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)


@unittest.skipUnless(WINDOWS and POWERSHELL.is_file(), "the installer is PowerShell on Windows")
class N9InterruptedAdvancedUpdate(Scratch):
    """An update cut off while its files were copied left a half-copied app\\src, which read as the standard edition."""

    JOURNAL = ".codex-auto-resume-install-journal.json"

    def interrupted(self, copied, home=None):
        """An advanced installation moved aside whole (app.old-1), and its new app\\ half copied: no advanced package."""
        home = home or self.root / "home"
        editions_run.tree(home / "app.old-1", "advanced", "the whole old tree")
        (home / "runtime.old-1").mkdir(parents=True)
        (home / "runtime.old-1" / "python.exe").write_bytes(b"old runtime")
        editions_run.tree(home / "app", "standard", "half of the new tree")     # the package's file is not copied yet
        (home / "runtime").mkdir()
        entries = [{"name": "app", "target": str(home / "app"), "movedAside": str(home / "app.old-1")},
                   {"name": "runtime", "target": str(home / "runtime"), "movedAside": str(home / "runtime.old-1")}]
        record = {"version": 1, "written": "2026-01-01T01:01:01+09:00", "home": str(home), "moved": entries}
        if copied is not None:
            record["copied"] = copied
        (home / self.JOURNAL).write_text(json.dumps(record), encoding="utf-8")
        return home

    def restore(self, home):
        code, output = run_ps(
            "$OwnedHome = Resolve-Canonical $env:CAR_HOME\n"
            "$claimed = @(Restore-InterruptedCopy -Path (Join-Path $OwnedHome '%s') -Root $OwnedHome)\n"
            "$names = @(); foreach ($each in @($claimed)) { if (-not $each) { continue }; $names += (Split-Path -Leaf $each) }\n"
            "@{ claimed = $names; said = @($script:Said); "
            "edition = (Get-Edition -Src (Join-Path $OwnedHome 'app\\src')) } | ConvertTo-Json -Compress\n" % self.JOURNAL,
            CAR_HOME=str(home))
        self.assertEqual(code, 0, output[-1500:])
        return last_json(output)

    def test_a_half_copied_tree_gives_way_to_the_whole_one_before_the_edition_is_read(self):
        home = self.interrupted(copied=False)
        answer = self.restore(home)
        self.assertEqual(answer["edition"], "advanced")
        self.assertEqual((home / "app" / "marker.txt").read_text(encoding="utf-8"), "the whole old tree")
        self.assertEqual((home / "runtime" / "python.exe").read_bytes(), b"old runtime")
        self.assertFalse((home / "app.old-1").exists())
        self.assertEqual(answer["claimed"], [], "once it is back there is nothing left to protect")

    def test_a_finished_copy_is_kept_and_the_aside_tree_stays_protected(self):
        home = self.interrupted(copied=True)
        answer = self.restore(home)
        self.assertEqual((home / "app" / "marker.txt").read_text(encoding="utf-8"), "half of the new tree")
        self.assertTrue((home / "app.old-1" / "marker.txt").is_file())
        self.assertEqual(sorted(answer["claimed"]), ["app.old-1", "runtime.old-1"])

    def test_a_journal_from_before_the_marker_is_read_as_it_always_was(self):
        home = self.interrupted(copied=None)
        answer = self.restore(home)
        self.assertEqual((home / "app" / "marker.txt").read_text(encoding="utf-8"), "half of the new tree")
        self.assertEqual(sorted(answer["claimed"]), ["app.old-1", "runtime.old-1"])

    def test_the_journal_is_written_unfinished_and_finished_once_every_file_is_in_place(self):
        copy = block(INSTALL_PS1, "Write-CopyJournal -Path $Journal -Root $OwnedHome -Entries $plan }",
                     "} catch {")
        self.assertIn("-Entries $plan -Copied", copy)
        first = INSTALL_PS1.index("Write-CopyJournal -Path $Journal -Root $OwnedHome -Entries $plan }")
        self.assertLess(first, INSTALL_PS1.index("Move-Item -LiteralPath $pair.dst -Destination $aside"))
        self.assertLess(INSTALL_PS1.index("Progress 'files' $copied $copyFiles"),
                        INSTALL_PS1.index("-Entries $plan -Copied"))
        self.assertLess(INSTALL_PS1.index("-Entries $plan -Copied"), INSTALL_PS1.index("Remove-OwnedItem $Journal"))

    def test_the_rerun_of_an_interrupted_advanced_update_is_an_update_not_a_change_of_edition(self):
        """The whole region, with the recovery before it as the installer runs it: no question, no `--edition-from`."""
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        work = Path(folder.name)
        home = work / "home"
        payload = work / "payload"
        self.interrupted(copied=False, home=home)
        editions_run.tree(payload / "app", "advanced", "payload")
        (payload / "runtime").mkdir(parents=True)
        (payload / "runtime" / "python.exe").write_bytes(b"the payload runtime")
        for name in ("CodexAutoResumeSettings.exe", "codex-auto-resume.ico"):
            (payload / name).write_bytes(b"x")
        region = editions_run.REGION.replace(
            "$claimedAside = @()",
            "$claimedAside = Restore-InterruptedCopy -Path $Journal -Root $OwnedHome")
        self.assertNotEqual(region, editions_run.REGION)
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-Command", region], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                              encoding="utf-8", errors="replace", timeout=300, creationflags=NO_WINDOW,
                              env=dict(os.environ, CAR_INSTALLER=str(ROOT / "build" / "install" / "install.ps1"),
                                       CAR_HOME=str(home), CAR_PAYLOAD=str(payload), CAR_ALLOW="0"))
        self.assertEqual(done.returncode, 0, done.stdout[-1500:])
        self.assertNotIn(" -> ", done.stdout, "no change of edition was announced")
        setup = [line for line in done.stdout.splitlines() if line.startswith("SETUP ")][0].split()
        self.assertNotIn("--edition-from", setup)
        self.assertTrue((home / "app" / "src" / editions_run.PACKAGE / "__init__.py").is_file())


@unittest.skipUnless(WINDOWS and POWERSHELL.is_file(), "the installer is PowerShell on Windows")
class N1CodexJsonIsUtf8(Scratch):
    """Codex writes UTF-8 to the file its output is redirected to; Windows PowerShell read it in the ANSI code page."""

    def test_a_path_with_korean_letters_comes_back_as_it_was_written(self):
        # Start-Process is stood in for: it writes what a native program writes to a redirected stdout, UTF-8 and no BOM.
        code, output = run_ps(
            "function Start-Process { param($FilePath, $ArgumentList, [switch]$NoNewWindow, [switch]$Wait, [switch]$PassThru,\n"
            "                              $RedirectStandardOutput, $RedirectStandardError)\n"
            "    $json = '{\"marketplaces\":[{\"name\":\"m\",\"root\":\"' + $env:CAR_ROOT.Replace('\\', '\\\\') + '\"}]}'\n"
            "    [IO.File]::WriteAllBytes($RedirectStandardOutput, (New-Object System.Text.UTF8Encoding $false).GetBytes($json))\n"
            "    return [pscustomobject]@{ ExitCode = 0 } }\n"
            "$root = Get-MarketplaceRoot -Exe 'codex.exe' -Name 'm'\n"
            "@{ root = $root } | ConvertTo-Json -Compress\n",
            CAR_ROOT="C:\\Users\\\uae40\ubbfc\uc218\\.codex-auto-resume\\app")
        self.assertEqual(code, 0, output[-1500:])
        self.assertEqual(last_json(output)["root"], "C:\\Users\\\uae40\ubbfc\uc218\\.codex-auto-resume\\app")

    def test_the_reads_name_the_file_and_its_encoding_and_the_cleanup_takes_it_literally(self):
        body = block(INSTALL_PS1, "function Invoke-Codex", "function Get-CodexCli")
        self.assertIn("Get-Content -LiteralPath $out -Raw -Encoding UTF8", body)
        self.assertIn("Get-Content -LiteralPath $err -Raw -Encoding UTF8", body)
        self.assertIn("Remove-Item -Force -ErrorAction SilentlyContinue -LiteralPath $out, $err", body)


if __name__ == "__main__":
    unittest.main()
