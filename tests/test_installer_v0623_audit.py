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


@unittest.skipUnless(WINDOWS and POWERSHELL.is_file(), "the bootstrap is PowerShell on Windows")
class N2InstallerThatThrows(Scratch):
    """A pick whose installer throws (rather than exits with a code) is put back, like one that exits non-zero."""

    def run_it(self, pick, installer_body):
        installer = self.root / "install.ps1"
        installer.write_text(installer_body, encoding="utf-8-sig")
        start = BOOTSTRAP_PS1.index("    if ($progressLines) { $env:CODEX_AUTO_RESUME_PROGRESS_LINES = '1' }")
        region = BOOTSTRAP_PS1[start:BOOTSTRAP_PS1.index("    exit $code\n", start) + len("    exit $code")]
        script = (
            "Set-StrictMode -Version 2.0\n$ErrorActionPreference = 'Stop'\n"
            "function Step { param([string]$m) Write-Host ('  ' + $m) }\n"
            "function Fail { param([string]$m) Write-Host ('  [!] ' + $m) }\n"
            "function Restore-AfterFailedPick { param($Home_, $Installed, $Converted, $Since, $KeptCopy, [switch]$NoStartup, [switch]$WasStopped)\n"
            "    Write-Host 'RESTORED'; return $true }\n"
            "$progressLines = $false; $Pick = $%s; $installer = '%s'; $arguments = @{}; $NoStartup = $false\n"
            "$installHome = 'C:/scratch'; $installed = '0.6.20'; $converted = 'converted 5'; $pickSince = Get-Date\n"
            "$pickKeptCopy = 'C:/scratch/k.ps1'; $pickWatcherStopped = $true; $target = '0.6.10'; $targetEdition = 'standard'\n"
            "$started = $true\n" % ("true" if pick else "false", str(installer).replace("'", "''")) + region + "\n")
        path = self.root / "region.ps1"
        path.write_text(script, encoding="utf-8-sig")
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                               str(path)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                              errors="replace", timeout=120, creationflags=NO_WINDOW)
        return done.returncode, done.stdout

    def test_a_throw_from_the_installer_restores_a_pick_and_fails_with_one(self):
        code, output = self.run_it(True, "throw 'The interrupted-installation journal has no usable move records.'")
        self.assertEqual(code, 1, output)
        self.assertIn("RESTORED", output)
        self.assertIn("The interrupted-installation journal has no usable move records.", output)
        self.assertIn("The installer had already started; read its messages above.", output)

    def test_a_throw_outside_a_pick_is_reported_and_restores_nothing(self):
        code, output = self.run_it(False, "throw 'codex.exe cannot start'")
        self.assertEqual(code, 1, output)
        self.assertNotIn("RESTORED", output)
        self.assertIn("codex.exe cannot start", output)

    def test_a_non_zero_code_still_restores_and_keeps_the_installers_code(self):
        code, output = self.run_it(True, "exit 14")
        self.assertEqual(code, 14, output)
        self.assertIn("RESTORED", output)

    def test_a_good_installer_is_untouched(self):
        code, output = self.run_it(True, "exit 0")
        self.assertEqual(code, 0, output)
        self.assertNotIn("RESTORED", output)
        self.assertIn("pick: installed 0.6.10 standard", output)


@unittest.skipUnless(WINDOWS and POWERSHELL.is_file(), "the installer is PowerShell on Windows")
class N3PurgeSaysWhatItKept(unittest.TestCase):
    """A linked config, logs or accounts folder is not followed, and the purge no longer claims it was removed."""

    def fresh(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.home = self.folder / "home"
        for relative in ("app/scripts/plugin_setup.py", "runtime/python.exe", ".owned-by-codex-auto-resume",
                         "config/settings.json", "logs/auto-resume.log", "accounts/one.dat"):
            path = self.home / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic fixture", encoding="utf-8")

    def link(self, name):
        import _winapi
        outside = self.folder / ("outside-" + name)
        outside.mkdir()
        (outside / "theirs.txt").write_text("not ours", encoding="utf-8")
        shutil.rmtree(self.home / name)
        _winapi.CreateJunction(str(outside), str(self.home / name))
        return outside

    def purge(self):
        from test_installer_uninstall_sweep import tail
        return tail(self.home, self.folder, purge=True)

    def test_a_linked_folder_is_kept_and_named_and_the_purge_does_not_claim_it(self):
        for name in ("logs", "accounts", "config"):
            with self.subTest(name):
                self.fresh()
                outside = self.link(name)
                done = self.purge()
                self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
                self.assertNotIn("Removed, including settings and recovery history.", done.stdout)
                self.assertIn("could not be removed", done.stdout)
                self.assertIn(str(self.home / name), done.stdout)
                self.assertIn("is a link", done.stdout)
                self.assertEqual((outside / "theirs.txt").read_text(encoding="utf-8"), "not ours")

    def test_with_no_link_it_still_says_it_removed_everything(self):
        self.fresh()
        done = self.purge()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("Removed, including settings and recovery history.", done.stdout)
        for name in ("config", "logs", "accounts"):
            self.assertFalse((self.home / name).exists(), name)


@unittest.skipUnless(WINDOWS and POWERSHELL.is_file(), "the installer is PowerShell on Windows")
class N4RuntimeVersionProbe(Scratch):
    """The bundled interpreter's version probe survives a line on stderr when the streams are merged (run outside)."""

    def probe(self, interpreter_body):
        start = INSTALL_PS1.index("    $runtimeVersion = ")
        end = INSTALL_PS1.index("    Ok ('Bundled Python '", start) + len("    Ok ('Bundled Python ' + $runtimeVersion + ' (no system Python needed)')")
        python = self.root / "python.cmd"
        python.write_text("@echo off\r\n" + interpreter_body, encoding="ascii")
        script = ("Set-StrictMode -Version 2.0\n$ErrorActionPreference = 'Stop'\n"
                  "function Ok { param([string]$m) Write-Host ('  [ok] ' + $m) }\n"
                  "$Python = '%s'\nWrite-Host 'start'\n" % str(python).replace("'", "''") + INSTALL_PS1[start:end] +
                  "\nWrite-Host 'went on'\n")
        path = self.root / "probe.ps1"
        path.write_text(script, encoding="utf-8-sig")
        # The outside wrapper's own merge: every stream of the script into one.
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
                               "& '%s' *>&1 | ForEach-Object { [string]$_ }" % str(path).replace("'", "''")],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                              errors="replace", timeout=120, creationflags=NO_WINDOW)
        return done.stdout

    def test_a_line_on_stderr_does_not_end_the_update(self):
        output = self.probe("echo a warning from the interpreter 1>&2\r\necho 3.13\r\n")
        self.assertIn("Bundled Python 3.13 (no system Python needed)", output)
        self.assertIn("went on", output)

    def test_a_quiet_interpreter_is_read_as_before(self):
        output = self.probe("echo 3.15\r\n")
        self.assertIn("Bundled Python 3.15 (no system Python needed)", output)
        self.assertIn("went on", output)


@unittest.skipUnless(WINDOWS and POWERSHELL.is_file(), "the installer is PowerShell on Windows")
class N5SetupThatCannotStart(Scratch):
    """An interpreter that cannot be started is a failed setup step, never the last native call's exit code."""

    def installer_code(self, earlier_native_call):
        code, output = run_ps(
            "Set-StrictMode -Version 2.0\n"
            "$AppDir = Join-Path $env:CAR_DIR 'app'; $Python = Join-Path $env:CAR_DIR 'runtime/python.exe'\n"
            "$script:ProgressLines = $false\n"
            + ("& cmd.exe /c exit 0\n" if earlier_native_call else "") +
            "$got = @(Invoke-Setup @('doctor'))\n"
            "@{ code = $got[-1]; count = $got.Count } | ConvertTo-Json -Compress\n", CAR_DIR=str(self.root))
        self.assertEqual(code, 0, output[-1500:])
        return last_json(output)

    def test_install_ps1_reads_a_missing_interpreter_as_failure(self):
        for earlier in (True, False):
            with self.subTest(earlier_native_call=earlier):
                self.assertEqual(self.installer_code(earlier)["code"], 1)

    def bootstrap_code(self, earlier_native_call):
        code, output = run_ps(
            "Set-StrictMode -Version 2.0\n"
            + ("& cmd.exe /c exit 0\n" if earlier_native_call else "") +
            "$got = Invoke-InstalledSetup -Home_ $env:CAR_DIR -Arguments @('doctor')\n"
            "@{ code = $got.Code } | ConvertTo-Json -Compress\n", script=ROOT / "scripts" / "bootstrap.ps1",
            CAR_DIR=str(self.root))
        return code, output

    def test_the_bootstraps_installed_setup_reads_it_the_same_way(self):
        for earlier in (True, False):
            with self.subTest(earlier_native_call=earlier):
                code, output = self.bootstrap_code(earlier)
                self.assertEqual(code, 0, output[-1500:])
                self.assertEqual(last_json(output)["code"], 1)


@unittest.skipUnless(WINDOWS and POWERSHELL.is_file(), "the bootstrap is PowerShell on Windows")
class N6PickLockAndTheRelaunchedInstaller(Scratch):
    """A pick from inside a packaged app must not hold the install lock the relaunched installer needs."""

    def child_can_take(self, inside_app):
        name = "Local\\CarV0623Audit-" + os.urandom(6).hex()
        code, output = run_ps(
            "function Find-PackagedAncestor { param($Table, $Self) %s }\n"
            "function Get-ProcessTable { param($Self) return @() }\n"
            "$lock = New-Object System.Threading.Mutex($false, $env:CAR_MUTEX)\n"
            "$held = $lock.WaitOne(0)\n"
            "$held = Release-PickLockForRunOutside -Lock $lock -Held $held\n"
            "$child = @'\n"
            "$m = New-Object System.Threading.Mutex($false, $env:CAR_MUTEX)\n"
            "try { $got = $m.WaitOne(0) } catch { $got = $true }\n"
            "if ($got) { 'free' } else { 'busy' }\n"
            "'@\n"
            "$answer = & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command $child\n"
            "@{ held = $held; child = [string]$answer } | ConvertTo-Json -Compress\n" % ("return 'OpenAI.Codex_1_x64__abc'" if inside_app else "return $null"),
            script=ROOT / "scripts" / "bootstrap.ps1", CAR_MUTEX=name)
        self.assertEqual(code, 0, output[-1500:])
        return last_json(output)

    def test_inside_a_packaged_app_the_lock_is_let_go_so_the_relaunched_installer_can_take_it(self):
        answer = self.child_can_take(True)
        self.assertEqual(answer, {"held": False, "child": "free"})

    def test_anywhere_else_the_lock_is_kept(self):
        answer = self.child_can_take(False)
        self.assertEqual(answer, {"held": True, "child": "busy"})

    def test_it_is_let_go_of_after_the_state_is_converted_and_right_before_the_installer(self):
        call = "$pickHeld = Release-PickLockForRunOutside -Lock $pickLock -Held $pickHeld"
        self.assertEqual(BOOTSTRAP_PS1.count(call), 1)
        at = BOOTSTRAP_PS1.index(call)
        self.assertGreater(at, BOOTSTRAP_PS1.index("$converted = Convert-StateForOlder"))
        self.assertLess(at, BOOTSTRAP_PS1.index("& $installer @arguments"))
        self.assertLess(BOOTSTRAP_PS1.index("$pickLock = New-Object System.Threading.Mutex"), at)


@unittest.skipUnless(WINDOWS and POWERSHELL.is_file(), "the installer is PowerShell on Windows")
class N7BracketsInFolderNames(Scratch):
    """A folder with [ or ] in its name is a folder: the paths the scripts read are literal."""

    def folder(self):
        folder = self.root / "Kim [work] x64"
        folder.mkdir()
        return folder

    def test_the_engine_is_found_under_a_profile_with_brackets(self):
        local = self.folder() / "Local"
        engine = local / "OpenAI" / "Codex" / "bin" / "abc123"
        engine.mkdir(parents=True)
        (engine / "codex.exe").write_bytes(b"MZ")
        code, output = run_ps("@{ found = [string](Get-CodexCli) } | ConvertTo-Json -Compress\n", LOCALAPPDATA=str(local))
        self.assertEqual(code, 0, output[-1500:])
        self.assertEqual(last_json(output)["found"], str(engine / "codex.exe"))

    def test_the_bootstrap_hashes_and_reads_files_under_such_a_folder(self):
        folder = self.folder()
        (folder / "x.zip").write_bytes(b"abc")
        (folder / "plugin.json").write_text('{"version": "1.2.3"}', encoding="utf-8")
        code, output = run_ps(
            "$digest = Get-Sha256 -Path (Join-Path $env:CAR_DIR 'x.zip')\n"
            "$json = Read-Json -Path (Join-Path $env:CAR_DIR 'plugin.json')\n"
            "@{ digest = $digest; version = $json.version } | ConvertTo-Json -Compress\n",
            script=ROOT / "scripts" / "bootstrap.ps1", CAR_DIR=str(folder))
        self.assertEqual(code, 0, output[-1500:])
        self.assertEqual(last_json(output), {"digest": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
                                             "version": "1.2.3"})

    def test_no_path_a_script_reads_goes_through_a_wildcard(self):
        """Every Test-Path, Get-Item, Get-ChildItem, Get-Content, Resolve-Path and Remove-Item of the scripts names its
        path with -LiteralPath (a New-Item or an Env: drive path is no wildcard)."""
        pattern = re.compile(r"\b(Test-Path|Get-Item|Get-ChildItem|Get-Content|Resolve-Path|Remove-Item|Copy-Item|Move-Item)\b")
        for relative in ("build/install/install.ps1", "scripts/bootstrap.ps1", "build/make_gui.ps1", "build/preview_gui.ps1"):
            lines = (ROOT / relative).read_text(encoding="utf-8").splitlines()
            for number, line in enumerate(lines, 1):
                code = line.split("#")[0] if line.lstrip().startswith("#") else line
                if line.lstrip().startswith("#") or not pattern.search(code):
                    continue
                if "-LiteralPath" in line or "Env:" in line or "-Literal" in line:
                    continue
                # Prose in a comment after code, or inside a here-string, is not a call.
                if re.search(r"(Test-Path|Get-Item|Get-ChildItem|Get-Content|Resolve-Path|Remove-Item|Copy-Item|Move-Item)\s+(-\w+\s+)*[$(\"']", line):
                    self.fail("%s:%d reads a path as a wildcard: %s" % (relative, number, line.strip()))


@unittest.skipUnless(WINDOWS and POWERSHELL.is_file(), "the bootstrap is PowerShell on Windows")
class N8PrereleaseOfferNeedsItsArchive(Scratch):
    """The update check offers a pre-release only when the installed edition's archive is uploaded."""

    def offer(self, edition):
        code, output = run_ps(
            "Set-StrictMode -Version 2.0\n"
            "function Entry($tag, $names) {\n"
            "    $assets = @(foreach ($n in $names) { [pscustomobject]@{ name = $n } })\n"
            "    [pscustomobject]@{ draft = $false; prerelease = $true; tag_name = $tag; assets = $assets } }\n"
            "function Read-ReleasesPage { param($Release, [string]$Uri, [int]$TimeoutSec)\n"
            "    return ,@(\n"
            "        (Entry 'v1.6.0-beta.2' @('Other.txt')),\n"
            "        (Entry 'v1.5.0-beta.3' @('CodexAutoResume-v1.5.0-beta.3-win-x64.zip', 'CodexAutoResume-v1.5.0-beta.3-win-x64.zip.sha256')),\n"
            "        (Entry 'v1.5.0-beta.2' @('CodexAutoResume-v1.5.0-beta.2-win-x64.zip')),\n"
            "        (Entry 'v1.4.1-beta.2' @('CodexAutoResume-Advanced-v1.4.1-beta.2-win-x64.zip')) ) }\n"
            "$Release = [pscustomobject]@{ owner = 'o'; repo = 'r'; releases = 'https://api.github.com/repos/o/r/releases'\n"
            "    archive = 'CodexAutoResume-v{version}-win-x64.zip'; sha256 = [pscustomobject]@{}\n"
            "    advanced = [pscustomobject]@{ archive = 'CodexAutoResume-Advanced-v{version}-win-x64.zip'\n"
            "                                  sha256 = [pscustomobject]@{ '1.4.1-beta.2' = ('a' * 64) } } }\n"
            "$best = Get-NewerPrerelease -Release $Release -Installed '1.4.0' -Stable '1.4.0' -TimeoutSec 5%s\n"
            "$all = Get-PublishedPrereleases -Release $Release -TimeoutSec 5%s\n"
            "@{ best = [string]$best; all = @($all) } | ConvertTo-Json -Compress\n"
            % ((" -Edition " + edition, " -Edition " + edition) if edition else ("", "")),
            script=ROOT / "scripts" / "bootstrap.ps1")
        self.assertEqual(code, 0, output[-1500:])
        return last_json(output)

    def test_one_whose_archive_is_not_uploaded_is_not_offered(self):
        answer = self.offer("'standard'")
        self.assertEqual(answer["best"], "1.5.0-beta.3")
        self.assertEqual(answer["all"], ["1.5.0-beta.3"], "no archive, or an archive with no checksum, is not listed")

    def test_each_edition_reads_its_own_archive_and_a_pinned_digest_stands_for_the_sidecar(self):
        answer = self.offer("'advanced'")
        self.assertEqual(answer["all"], ["1.4.1-beta.2"])
        self.assertEqual(answer["best"], "1.4.1-beta.2")

    def test_asked_nothing_about_an_edition_it_lists_every_published_pre_release_as_before(self):
        answer = self.offer(None)
        self.assertEqual(answer["best"], "1.6.0-beta.2")
        self.assertEqual(sorted(answer["all"]), ["1.4.1-beta.2", "1.5.0-beta.2", "1.5.0-beta.3", "1.6.0-beta.2"])

    def test_the_check_and_the_pick_of_a_version_ask_for_the_edition_they_install(self):
        self.assertIn("-Edition $targetEdition", block(BOOTSTRAP_PS1, "$prerelease = Get-NewerPrerelease", "} catch {"))
        self.assertIn("Get-PublishedPrereleases -Release $release -TimeoutSec $ReleasesVersionTimeout -Edition $targetEdition",
                      BOOTSTRAP_PS1)


@unittest.skipUnless(WINDOWS and POWERSHELL.is_file(), "the installer is PowerShell on Windows")
class N10LinkedProgramFolderIsNamed(Scratch):
    """A runtime or app folder that is a link is refused as before, and the refusal says that is why."""

    def say(self, linked):
        import _winapi
        home = self.root / "home"
        (home / "app").mkdir(parents=True)
        outside = self.root / "other-drive-runtime"
        outside.mkdir()
        if linked == "runtime":
            _winapi.CreateJunction(str(outside), str(home / "runtime"))
        else:
            (home / "runtime").mkdir()
        code, output = run_ps(
            "$InstallHome = $env:CAR_HOME; $AppDir = Join-Path $InstallHome 'app'; $RunDir = Join-Path $InstallHome 'runtime'\n"
            "Write-RootNotResolved -Done 'installed'\n"
            "@{ said = @($script:Said); failed = $script:Failed } | ConvertTo-Json -Compress\n", CAR_HOME=str(home))
        self.assertEqual(code, 0, output[-1500:])
        return last_json(output), output

    def test_a_linked_runtime_is_named(self):
        answer, output = self.say("runtime")
        self.assertIs(answer["failed"], True)
        self.assertIn("fail: The installation root could not be resolved; nothing was installed.", answer["said"])
        self.assertIn("is a link to another place", output)
        self.assertIn(str(self.root / "home" / "runtime"), output)

    def test_without_a_link_the_refusal_is_the_one_line_it_was(self):
        answer, output = self.say(None)
        self.assertEqual(answer["said"], ["fail: The installation root could not be resolved; nothing was installed."])

    def test_both_refusals_use_it(self):
        self.assertEqual(INSTALL_PS1.count("Write-RootNotResolved -Done"), 2)
        self.assertNotIn("Fail 'The installation root could not be resolved", INSTALL_PS1)


@unittest.skipUnless(WINDOWS and POWERSHELL.is_file(), "the launchers are Windows batch files")
class N11LaunchersPutTheCodePageBack(Scratch):
    """Install.cmd and Uninstall.cmd end with the console in the code page it was in when they began."""

    def pages(self, name, *arguments, code=0):
        from test_add_remove import Launcher, SYSTEM32
        launcher = Launcher(self, name)
        wrapper = self.root / ("wrap-" + name.lower().replace(".cmd", "") + ".bat")
        wrapper.write_bytes(("@echo off\r\n\"%s\" 850 >nul\r\ncall \"%s\" %%*\r\nset \"RC=%%ERRORLEVEL%%\"\r\n\"%s\"\r\n"
                             "exit /b %%RC%%\r\n" % (SYSTEM32 / "chcp.com", launcher.script, SYSTEM32 / "chcp.com")).encode("ascii"))
        done = subprocess.run([str(SYSTEM32 / "cmd.exe"), "/d", "/c", str(wrapper), *arguments],
                              capture_output=True, stdin=subprocess.DEVNULL, timeout=120, creationflags=NO_WINDOW,
                              env=dict(os.environ, STUB_RECORD=str(launcher.record), STUB_EXIT=str(code)),
                              cwd=str(launcher.base))
        return done.returncode, done.stdout.decode("mbcs", "replace")

    def test_the_page_the_window_was_in_is_the_page_it_is_left_in(self):
        for name in ("Install.cmd", "Uninstall.cmd"):
            for exit_code in (0, 1):
                with self.subTest(name=name, exit_code=exit_code):
                    code, output = self.pages(name, "-Silent", code=exit_code)
                    self.assertEqual(code, exit_code, output)
                    self.assertIn("850", output.strip().splitlines()[-1], output)
                    self.assertNotIn("65001", output)

    def test_the_answer_no_to_an_edition_change_leaves_it_so_too(self):
        code, output = self.pages("Install.cmd", code=14)
        self.assertEqual(code, 14, output)
        self.assertIn("850", output.strip().splitlines()[-1], output)

    def test_the_old_page_is_read_before_it_is_changed_and_put_back_before_the_exit(self):
        for name in ("Install.cmd", "Uninstall.cmd"):
            text = (ROOT / "build" / "install" / name).read_text(encoding="ascii")
            self.assertLess(text.index("for /f"), text.index("chcp.com\" 65001"))
            self.assertLess(text.index("chcp.com\" %OLDCP%"), text.index("exit /b %EXIT_CODE%"))
            self.assertEqual(text.count("exit /b"), 1)


@unittest.skipUnless(WINDOWS and POWERSHELL.is_file(), "the installer is PowerShell on Windows")
class N12WhatAnUninstallLeaves(unittest.TestCase):
    """A purge leaves no empty installation folder, and a plain uninstall names the saved accounts it keeps."""

    def fresh(self, accounts=False, stray=False):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.home = self.folder / "home"
        files = ["app/scripts/plugin_setup.py", "runtime/python.exe", ".owned-by-codex-auto-resume",
                 "config/settings.json", "logs/auto-resume.log"]
        if accounts:
            files.append("accounts/one.dat")
        if stray:
            files.append("somebodys-notes.txt")
        for relative in files:
            path = self.home / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic fixture", encoding="utf-8")

    def uninstall(self, purge):
        from test_installer_uninstall_sweep import tail
        return tail(self.home, self.folder, purge=purge)

    def test_a_purge_that_took_everything_takes_the_folder(self):
        self.fresh(accounts=True)
        done = self.uninstall(True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("Removed, including settings and recovery history.", done.stdout)
        self.assertFalse(self.home.exists(), "an empty installation folder was left")

    def test_a_folder_with_anything_else_in_it_stays_with_it(self):
        self.fresh(stray=True)
        done = self.uninstall(True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual((self.home / "somebodys-notes.txt").read_text(encoding="utf-8"), "synthetic fixture")

    def test_a_plain_uninstall_keeps_the_folder_and_says_the_accounts_stay(self):
        self.fresh(accounts=True)
        done = self.uninstall(False)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("The Codex accounts you saved for switching were kept too", done.stdout)
        self.assertTrue((self.home / "accounts" / "one.dat").is_file())
        self.assertTrue((self.home / "config" / "settings.json").is_file())

    def test_with_no_saved_accounts_it_says_nothing_of_them(self):
        self.fresh()
        done = self.uninstall(False)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertNotIn("saved for switching", done.stdout)
        self.assertIn("Removed. Settings and pending recoveries were kept.", done.stdout)


@unittest.skipUnless(WINDOWS and POWERSHELL.is_file(), "the tool is PowerShell on Windows")
class N13PreviewToolRefusesTheRealInstallation(Scratch):
    """build/preview_gui.ps1 deployed over the real installation and stopped every settings window. It is never run
    here: its refusal is lifted out and asked about paths, and the order of the script is read."""

    PREVIEW = ROOT / "build" / "preview_gui.ps1"
    SOURCE = PREVIEW.read_text(encoding="utf-8")

    def refusal(self, target, profile, override=""):
        code, output = run_ps(
            "$r = Get-PreviewRefusal -Target $env:CAR_T -Profile $env:CAR_P -Override $env:CAR_O\n"
            "@{ refusal = $r } | ConvertTo-Json -Compress\n", script=self.PREVIEW,
            CAR_T=target, CAR_P=profile, CAR_O=override)
        self.assertEqual(code, 0, output[-1500:])
        return last_json(output)["refusal"]

    def test_the_real_installations_are_refused_in_every_form(self):
        sep = os.sep
        profile = str(self.root / "profile")
        override = str(self.root / "elsewhere" / "car-home")
        real = profile + sep + ".codex-auto-resume"
        for target in (real, real + sep, real.upper(), real + sep + "app", real + sep + "app" + sep + "src" + sep + ".." + sep + "..",
                       profile, override, override + sep + "runtime", str(self.root / "elsewhere")):
            with self.subTest(target=target):
                why = self.refusal(target, profile, override)
                self.assertIsNotNone(why)
                self.assertIn("real installation", why)

    def test_no_target_is_refused_and_says_what_to_pass(self):
        for target in ("", "   "):
            why = self.refusal(target, str(self.root / "profile"))
            self.assertIn("-Target", why)
            self.assertIn("never uses the real installation", why)

    def test_a_scratch_copy_is_the_only_thing_it_will_deploy_over(self):
        profile = str(self.root / "profile")
        self.assertIsNone(self.refusal(str(self.root / "scratch-copy"), profile, str(self.root / "elsewhere" / "car-home")))
        self.assertIsNone(self.refusal(str(self.root / "profile-copy" / ".codex-auto-resume"), profile))

    def test_it_refuses_before_it_builds_stops_or_copies_anything(self):
        text = self.SOURCE[self.SOURCE.index("#>") + 2:]            # the code, not the header
        call = text.index("$refusal = Get-PreviewRefusal -Target $Target")
        self.assertIn("exit 2", text[call:call + 300])
        for later in ("Add-Type @'", "make_gui.ps1') -Root", "Get-Process -Name", "Copy-Item", "Start-Process", "CopyFromScreen"):
            self.assertLess(call, text.index(later), later)

    def test_it_stops_only_the_window_that_runs_from_the_target_and_never_names_the_profile(self):
        text = self.SOURCE
        for found in re.finditer(r"Get-Process -Name 'CodexAutoResumeSettings'", text):
            self.assertIn("$_.Path -ieq $target", text[found.start():found.start() + 220])
        self.assertNotIn("Join-Path $env:USERPROFILE '.codex-auto-resume'", text.replace("(Join-Path $Profile", ""))
        self.assertEqual(text.count("$_.Kill()"), 1)


if __name__ == "__main__":
    unittest.main()
