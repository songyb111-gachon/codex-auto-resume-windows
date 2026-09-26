r"""The bootstrap's editions: which one a run installs, and that an update never crosses them.

v0.6.11 has two editions, and an installation is one or the other by whether the advanced
package is in its app\src (src/codex_auto_resume/edition.py). The bootstrap installs the edition
-Edition names, otherwise the installed one, otherwise its own tree's; -Update refuses -Edition;
replacing one edition with the other takes -Edition and -Force, and without -Force nothing is
downloaded and the run exits 14; an archive of the other edition is refused before it is
unpacked.

The functions are lifted out of scripts/bootstrap.ps1 by the PowerShell parser, as
tests/test_update_check.py does. The whole-script runs start a scratch copy of the plugin in a
session where Invoke-WebRequest is a stub that writes down what it was asked and answers nothing
but the update question - with a scratch installation home and a scratch TEMP, never the real
installation, and with the plugin's addresses pointed at a port nothing listens on in case the
stub were ever bypassed. An archive that passes every check is unpacked and its installer run;
that installer is a stub too, with the real one's parameters, which only writes down how it was
bound.
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
import zipfile

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)        # editions lives next to this file

import editions  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts" / "bootstrap.ps1"
INSTALLER = ROOT / "build" / "install" / "install.ps1"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
PACKAGE = editions.PACKAGE
SKILL = "codex-auto-resume-advanced"
RELEASE = json.loads((ROOT / "scripts" / "release.json").read_text(encoding="utf-8"))
TAG = "https://github.com/%s/%s/releases/tag/" % (RELEASE["owner"], RELEASE["repo"])
# Nothing listens here, so a request that got past the stub would fail rather than leave.
NOWHERE = "https://127.0.0.1:1/releases"


def required_entries() -> list:
    """What Test-Archive requires of any archive, read from the script itself."""
    text = BOOTSTRAP.read_text(encoding="utf-8")
    listed = re.search(r"\$required = @\((.*?)\)", text, re.S)
    return re.findall(r"'([^']+)'", listed.group(1)) + ["payload/codex-auto-resume.ico"]


def archive(path: Path, version="9.9.9", extra=(), installer="x", raw=()) -> Path:
    """An archive shaped like a release of `version`, plus `extra` entries. `raw` entries keep
    their names exactly, backslashes included, which ZipInfo would otherwise rewrite."""
    with zipfile.ZipFile(path, "w") as bundle:
        for entry in required_entries() + list(extra):
            if entry.endswith(".codex-plugin/plugin.json"):
                bundle.writestr(entry, json.dumps({"name": "codex-auto-resume", "version": version}))
            elif entry == "install/install.ps1":
                bundle.writestr(entry, installer)
            else:
                bundle.writestr(entry, "x")
        for name in raw:
            info = zipfile.ZipInfo("placeholder")
            info.filename = name
            bundle.writestr(info, "x")
    return path


LIFT = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:CAR_SCRIPT, [ref]$null, [ref]$errors)
if ($errors -and $errors.Count) { throw 'the script does not parse' }
$wanted = @($env:CAR_FUNCTIONS -split ',')
foreach ($node in $ast.FindAll({ param($n)
        $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    if ($wanted -contains $node.Name) { Invoke-Expression $node.Extent.Text }
}
foreach ($name in $wanted) {
    if (-not (Get-Command $name -CommandType Function -ErrorAction SilentlyContinue)) {
        throw ('the script has no ' + $name)
    }
}
$cases = ConvertFrom-Json $env:CAR_CASES
"""


def lifted(script: Path, functions, body: str, cases) -> list:
    """Run `body` for `cases` with the named functions of `script` defined; its JSON answer."""
    done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", LIFT + body],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
                          env=dict(os.environ, CAR_SCRIPT=str(script), CAR_FUNCTIONS=",".join(functions),
                                   CAR_CASES=json.dumps(cases)))
    if done.returncode != 0 or not done.stdout.strip():
        raise AssertionError("the probe did not run: " + (done.stderr or done.stdout)[-2000:])
    return json.loads(done.stdout.strip().splitlines()[-1])


# ----------------------------------------------------------------------------- which edition
# asked (-Edition), installed, the tree's own, -Force -> the edition installed, and the verdict.
RESOLUTION = [
    ("", "", "standard", False, "standard", "same"),        # a plugin added from GitHub
    ("", "", "advanced", False, "advanced", "same"),        # an advanced tree, nothing installed
    ("", "standard", "advanced", False, "standard", "same"),  # the installed edition beats the tree's
    ("", "advanced", "standard", False, "advanced", "same"),  # so an update never leaves it
    ("", "advanced", "standard", True, "advanced", "same"),   # and -Force alone does not either
    ("Advanced", "", "standard", False, "advanced", "same"),  # named, over nothing
    ("Standard", "standard", "advanced", False, "standard", "same"),
    ("Advanced", "standard", "standard", False, "advanced", "refused"),
    ("Standard", "advanced", "advanced", False, "standard", "refused"),
    ("Advanced", "standard", "standard", True, "advanced", "change"),
    ("Standard", "advanced", "standard", True, "standard", "change"),
]


@unittest.skipUnless(POWERSHELL.is_file(), "the bootstrap is PowerShell on Windows")
class ResolutionTests(unittest.TestCase):
    def test_the_edition_named_then_the_installed_one_then_the_trees(self):
        body = r"""
$out = @()
foreach ($row in $cases) {
    $plan = Resolve-Edition -Asked $row[0] -Installed $row[1] -Tree $row[2] -Force:([bool]$row[3])
    $out += ,@($plan.Edition, $plan.Verdict)
}
ConvertTo-Json -InputObject $out -Compress
"""
        answers = lifted(BOOTSTRAP, ["Resolve-Edition"], body, [list(row[:4]) for row in RESOLUTION])
        self.assertEqual(len(answers), len(RESOLUTION))
        for row, answer in zip(RESOLUTION, answers):
            with self.subTest(row[:4]):
                self.assertEqual(tuple(answer), row[4:])

    def test_the_installed_edition_is_read_by_the_installers_rule(self):
        """An `app` folder is an installation, whatever else is missing, and its `src` says which
        edition - as install.ps1 decides `$upgrade` and the edition it replaces."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            homes = {"nothing": root / "nothing", "no_app": root / "no_app", "bare_app": root / "bare",
                     "standard": root / "standard", "advanced": root / "advanced",
                     "cache_only": root / "cache_only"}
            (homes["no_app"] / "runtime").mkdir(parents=True)
            (homes["bare_app"] / "app").mkdir(parents=True)
            (homes["standard"] / "app" / "src" / "codex_auto_resume").mkdir(parents=True)
            (homes["advanced"] / "app" / "src" / PACKAGE).mkdir(parents=True)
            (homes["advanced"] / "app" / "src" / PACKAGE / "__init__.py").write_text("", encoding="utf-8")
            (homes["cache_only"] / "app" / "src" / PACKAGE / "__pycache__").mkdir(parents=True)
            # A plugin tree is read the same way: an installation's app folder is one.
            trees = {"tree_advanced": homes["advanced"] / "app", "tree_standard": homes["standard"] / "app"}
            body = r"""
$out = @{}
foreach ($pair in $cases.homes.PSObject.Properties) {
    $found = Get-InstalledEdition -Home_ $pair.Value
    if ($null -eq $found) { $found = 'none' }
    $out[$pair.Name] = $found
}
foreach ($pair in $cases.trees.PSObject.Properties) { $out[$pair.Name] = Get-TreeEdition -Root $pair.Value }
ConvertTo-Json $out -Compress
"""
            answers = lifted(BOOTSTRAP, ["Get-Edition", "Get-InstalledEdition", "Get-TreeEdition"], body,
                             {"homes": {name: str(path) for name, path in homes.items()},
                              "trees": {name: str(path) for name, path in trees.items()}})
        self.assertEqual(answers, {"nothing": "none", "no_app": "none", "bare_app": "standard",
                                   "standard": "standard", "advanced": "advanced",
                                   "cache_only": "standard", "tree_advanced": "advanced",
                                   "tree_standard": "standard"})
        installer = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("$upgrade = Test-Path $AppDir", installer)
        self.assertIn("$previousEdition = Get-Edition -Src (Join-Path $AppDir 'src')", installer)


@unittest.skipUnless(POWERSHELL.is_file(), "the bootstrap is PowerShell on Windows")
class StatementTests(unittest.TestCase):
    """The one line an edition change is announced with. The bootstrap says it before anything is
    fetched and the installer as it replaces the program files, so the two copies must agree."""

    BODY = r"""
$out = @()
foreach ($row in $cases) { $out += Get-EditionStatement -From $row[0] -To $row[1] }
ConvertTo-Json -InputObject $out -Compress
"""
    WAYS = [["standard", "advanced"], ["advanced", "standard"]]

    def test_both_scripts_say_the_same_thing_both_ways(self):
        said = {script.name: lifted(script, ["Get-EditionStatement"], self.BODY, self.WAYS)
                for script in (BOOTSTRAP, INSTALLER)}
        self.assertEqual(said["bootstrap.ps1"], said["install.ps1"])
        into, out_of = said["bootstrap.ps1"]
        self.assertEqual(into, "Standard edition -> Advanced edition; settings and pending recoveries "
                               "are kept; every advanced feature starts off")
        self.assertTrue(out_of.startswith("Advanced edition -> Standard edition; settings and pending "
                                          "recoveries are kept; "), out_of)


@unittest.skipUnless(POWERSHELL.is_file(), "the bootstrap is PowerShell on Windows")
class ArchiveEditionTests(unittest.TestCase):
    """Test-Archive refuses an archive of the edition the run did not ask for."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        root = Path(cls.folder.name)
        init = "payload/app/src/%s/__init__.py" % PACKAGE
        cls.archives = {
            "standard": archive(root / "standard.zip"),
            "advanced": archive(root / "advanced.zip", extra=[init, "payload/app/src/%s/plug.py" % PACKAGE,
                                                              "payload/app/skills/%s/SKILL.md" % SKILL]),
            # Either of its two places is enough to make an archive not the standard edition.
            "skill_only": archive(root / "skill.zip", extra=["payload/app/skills/%s/SKILL.md" % SKILL]),
            "other_case": archive(root / "case.zip",
                                  extra=["payload/app/src/Codex_Auto_Resume_Advanced/plug.py"]),
            "backslashes": archive(root / "slashes.zip",
                                   raw=["payload\\app\\src\\%s\\__init__.py" % PACKAGE]),
            # Its package without the file that makes it one is not the advanced edition either.
            "no_init": archive(root / "no_init.zip", extra=["payload/app/src/%s/plug.py" % PACKAGE]),
            # A name that merely begins like the package's is not the package.
            "look_alike": archive(root / "look_alike.zip",
                                  extra=["payload/app/src/%s_notes.txt" % PACKAGE]),
            # Names the extraction writes into the package's own directory all the same.
            "dot": archive(root / "dot.zip", raw=["payload/app/src/./%s/__init__.py" % PACKAGE]),
            "double_slash": archive(root / "double_slash.zip",
                                    raw=["payload/app/src//%s/__init__.py" % PACKAGE]),
            # The package in another case: no package to Python, so no advanced edition either.
            "shouting": archive(root / "shouting.zip",
                                extra=["payload/app/src/%s/__init__.py" % PACKAGE.upper()]),
        }
        cases = [[name, str(path), edition] for name, path in cls.archives.items()
                 for edition in ("standard", "advanced", "")]
        body = r"""
$out = @{}
foreach ($row in $cases) {
    try {
        if ($row[2]) { Test-Archive -Zip $row[1] -Version '9.9.9' -Edition $row[2] }
        else { Test-Archive -Zip $row[1] -Version '9.9.9' }
        $out[$row[0] + ' ' + $row[2]] = 'accepted'
    } catch { $out[$row[0] + ' ' + $row[2]] = [string]$_.Exception.Message }
}
ConvertTo-Json $out -Compress
"""
        cls.answers = lifted(BOOTSTRAP, ["Test-Archive"], body, cases)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def verdict(self, name, edition):
        return self.answers["%s %s" % (name, edition)]

    def test_each_edition_takes_its_own_archive(self):
        self.assertEqual(self.verdict("standard", "standard"), "accepted")
        self.assertEqual(self.verdict("advanced", "advanced"), "accepted")
        self.assertEqual(self.verdict("look_alike", "standard"), "accepted")

    def test_a_standard_run_refuses_anything_of_the_advanced_edition(self):
        for name in ("advanced", "skill_only", "other_case", "backslashes", "no_init", "dot",
                     "double_slash", "shouting"):
            with self.subTest(name):
                self.assertIn("holds the advanced edition", self.verdict(name, "standard"))

    def test_an_advanced_run_refuses_an_archive_without_the_package(self):
        for name in ("standard", "skill_only", "no_init", "look_alike", "shouting"):
            with self.subTest(name):
                self.assertIn("not the advanced edition", self.verdict(name, "advanced"))

    def test_an_archive_nothing_asked_an_edition_of_is_held_to_the_standard_one(self):
        """What every archive was before there were two, and what the lifted Test-Archive in
        tests/test_installer.py is called without."""
        for name in self.archives:
            with self.subTest(name):
                self.assertEqual(self.verdict(name, ""), self.verdict(name, "standard"))


# --------------------------------------------------------------------------- the whole script
RUN = r"""
# Where the network was: every request is written down, and none leaves this process. HEAD - the
# update question - is answered with the redirect a case names; anything else fails the way an
# offline machine does.
function global:Invoke-WebRequest {
    param([string]$Uri, [string]$OutFile, [switch]$UseBasicParsing, [switch]$PassThru,
          [int]$MaximumRedirection, [int]$TimeoutSec, [string]$Method)
    Add-Content -LiteralPath $env:CAR_REQUESTS -Value (([string]$Method) + ' ' + $Uri) -Encoding UTF8
    if ($Method -eq 'Head' -and $env:CAR_LATEST) {
        $base = New-Object psobject
        $base | Add-Member -MemberType NoteProperty -Name ResponseUri -Value ([Uri]$env:CAR_LATEST)
        $response = New-Object psobject
        $response | Add-Member -MemberType NoteProperty -Name BaseResponse -Value $base
        return $response
    }
    throw 'there is no network here'
}
$arguments = @{}
foreach ($pair in (ConvertFrom-Json $env:CAR_ARGUMENTS).PSObject.Properties) {
    $arguments[$pair.Name] = $pair.Value
}
& $env:CAR_SCRIPT @arguments
exit $LASTEXITCODE
"""

# Stands in for the archive's installer: the real one's parameters, and nothing but a record of
# how the bootstrap bound them.
RECORD = r"""
$bound = @{ PluginName = $PluginName }
foreach ($key in $PSBoundParameters.Keys) { $bound[$key] = [string]$PSBoundParameters[$key] }
Set-Content -LiteralPath $env:CAR_INSTALLED -Value (ConvertTo-Json $bound -Compress) -Encoding UTF8
exit 0
"""


def stub_installer() -> str:
    text = INSTALLER.read_text(encoding="utf-8")
    start = text.index("[CmdletBinding()]")
    return text[start:text.index("\n)\n", start) + 3] + RECORD


@unittest.skipUnless(POWERSHELL.is_file(), "the bootstrap is PowerShell on Windows")
class WholeScriptTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.plugin = self.root / "plugin"
        (self.plugin / "scripts").mkdir(parents=True)
        (self.plugin / ".codex-plugin").mkdir()
        shutil.copyfile(BOOTSTRAP, self.plugin / "scripts" / "bootstrap.ps1")
        manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        (self.plugin / ".codex-plugin" / "plugin.json").write_text(
            json.dumps(dict(manifest, version="9.9.9")), encoding="utf-8")
        release = dict(RELEASE, download=NOWHERE + "/download/v{version}/", latest=NOWHERE + "/latest")
        (self.plugin / "scripts" / "release.json").write_text(json.dumps(release), encoding="utf-8")
        self.home = self.root / "home"
        self.temp = self.root / "temp"
        self.temp.mkdir()
        self.requests = self.root / "requests.txt"
        self.installed = self.root / "installed.json"

    def tree(self, edition):
        """The plugin tree's own edition: what a plugin added from somewhere else carries."""
        if edition == "advanced":
            (self.plugin / "src" / PACKAGE).mkdir(parents=True)
            (self.plugin / "src" / PACKAGE / "__init__.py").write_text("", encoding="utf-8")

    def installation(self, version, edition):
        """What Get-InstalledVersion and Get-InstalledEdition read, and nothing else."""
        (self.home / "runtime").mkdir(parents=True)
        (self.home / "runtime" / "python.exe").write_bytes(b"not a real interpreter")
        (self.home / "app" / ".codex-plugin").mkdir(parents=True)
        (self.home / "app" / ".codex-plugin" / "plugin.json").write_text(
            json.dumps({"name": "codex-auto-resume", "version": version}), encoding="utf-8")
        (self.home / "app" / "scripts").mkdir()
        (self.home / "app" / "src" / "codex_auto_resume").mkdir(parents=True)
        if edition == "advanced":
            (self.home / "app" / "src" / PACKAGE).mkdir()
            (self.home / "app" / "src" / PACKAGE / "__init__.py").write_text("", encoding="utf-8")

    def archive(self, edition) -> Path:
        extra = ["payload/app/src/%s/__init__.py" % PACKAGE] if edition == "advanced" else []
        return archive(self.root / ("%s.zip" % edition), extra=extra, installer=stub_installer())

    def listing(self) -> list:
        """The home, the plugin and any working folder of ours: PowerShell keeps files of its own
        in TEMP for a moment, and those are not this script's."""
        found = [path for folder in (self.home, self.plugin) for path in folder.rglob("*")]
        found += self.workfolders()
        return sorted(str(path.relative_to(self.root)) for path in found)

    def workfolders(self) -> list:
        return sorted(self.temp.glob("codex-auto-resume-*"))

    def run_it(self, latest=None, **arguments):
        environment = dict(os.environ, CODEX_AUTO_RESUME_PLUGIN_HOME=str(self.home),
                           TEMP=str(self.temp), TMP=str(self.temp),
                           CAR_SCRIPT=str(self.plugin / "scripts" / "bootstrap.ps1"),
                           CAR_ARGUMENTS=json.dumps(arguments), CAR_REQUESTS=str(self.requests),
                           CAR_INSTALLED=str(self.installed), CAR_LATEST=latest or "")
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                               "Bypass", "-Command", RUN],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                              errors="replace", timeout=300, env=environment)
        asked = []
        if self.requests.is_file():
            asked = [line.split(" ", 1) for line in
                     self.requests.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
        return done.returncode, done.stdout, asked

    def bound(self) -> dict:
        return json.loads(self.installed.read_text(encoding="utf-8-sig"))

    def test_the_other_edition_is_not_replaced_without_force(self):
        """And it is not "already installed" either, at the very same version: the repair branch
        checks over only the edition the run installs. Nothing is asked, fetched or written."""
        for installed, asked in (("standard", "Advanced"), ("advanced", "Standard")):
            with self.subTest(installed):
                shutil.rmtree(self.home, ignore_errors=True)
                self.installation("9.9.9", installed)
                before = self.listing()
                code, output, requests = self.run_it(Edition=asked)
                self.assertEqual(code, 14, output[-1500:])
                self.assertEqual(requests, [])
                self.assertIn("edition: " + installed, output)
                self.assertIn("-Edition %s -Force" % asked, output)
                for absent in ("already installed", "Downloading", "Checking it over"):
                    self.assertNotIn(absent, output)
                self.assertEqual(self.listing(), before, "the run left something behind")

    def test_with_force_the_change_is_said_first_and_the_other_archive_fetched(self):
        self.installation("9.9.9", "advanced")
        code, output, requests = self.run_it(Edition="Standard", Force=True)
        self.assertEqual(code, 1, "the stub network refuses the download: " + output[-1500:])
        statement = output.index("Advanced edition -> Standard edition")
        self.assertLess(statement, output.index("edition: standard"))
        self.assertLess(statement, output.index("Downloading v9.9.9"))
        self.assertNotIn("already installed", output)
        self.assertEqual(requests, [["", NOWHERE + "/download/v9.9.9/CodexAutoResume-v9.9.9-win-x64.zip"]])

    def test_the_same_edition_at_the_same_version_is_still_checked_over(self):
        """The guard above is not a guard against the case it was never about."""
        self.tree("standard")
        self.installation("9.9.9", "advanced")
        code, output, requests = self.run_it()
        self.assertIn("edition: advanced", output)
        self.assertIn("already installed", output)
        self.assertEqual(requests, [])

    def test_an_update_stays_in_the_installed_edition(self):
        """An advanced installation updates to the advanced archive, through the advanced
        template; a standard one to the name every published bootstrap has always built."""
        names = {"standard": "CodexAutoResume-v9.9.9-win-x64.zip",
                 "advanced": "CodexAutoResume-Advanced-v9.9.9-win-x64.zip"}
        for edition, name in names.items():
            with self.subTest(edition):
                shutil.rmtree(self.home, ignore_errors=True)
                self.requests.unlink(missing_ok=True)
                self.installation("0.6.0", edition)
                code, output, requests = self.run_it(latest=TAG + "v9.9.9", Update=True)
                self.assertIn("update: available 0.6.0 9.9.9", output)
                self.assertIn("edition: " + edition, output)
                self.assertEqual(requests, [["Head", NOWHERE + "/latest"],
                                            ["", NOWHERE + "/download/v9.9.9/" + name]], output[-1500:])

    def test_an_update_or_its_question_refuses_an_edition(self):
        self.installation("0.6.0", "standard")
        for switch in ("Update", "CheckOnly"):
            with self.subTest(switch):
                code, output, requests = self.run_it(latest=TAG + "v9.9.9", Edition="Advanced",
                                                     **{switch: True})
                self.assertEqual(code, 12, output[-1500:])
                self.assertIn("An update stays in the edition that is installed", output)
                self.assertEqual(requests, [])
        code, output, requests = self.run_it(Compatibility=True, Edition="Advanced")
        self.assertEqual(code, 12)
        self.assertIn("compatibility: unavailable", output)
        self.assertEqual(requests, [])

    def test_with_nothing_installed_the_tree_decides(self):
        for edition, name in (("standard", "CodexAutoResume-v9.9.9-win-x64.zip"),
                              ("advanced", "CodexAutoResume-Advanced-v9.9.9-win-x64.zip")):
            with self.subTest(edition):
                self.requests.unlink(missing_ok=True)
                self.tree(edition)
                code, output, requests = self.run_it()
                self.assertIn("edition: " + edition, output)
                self.assertEqual(requests, [["", NOWHERE + "/download/v9.9.9/" + name]], output[-1500:])

    def test_the_installer_is_told_its_switches_by_name(self):
        """-NoStartup used to reach the installer in a list, which binds by position: the
        installer read '-SkipStartup' as the plugin's name and registered the sign-in start
        anyway. By name, the switch is the switch and the name keeps its default."""
        self.installation("0.6.0", "standard")
        code, output, requests = self.run_it(ArchivePath=str(self.archive("standard")), NoStartup=True)
        self.assertEqual(code, 0, output[-1500:])
        self.assertEqual(self.bound(), {"PluginName": "codex-auto-resume", "SkipStartup": "True"})
        self.assertEqual(requests, [])

    def test_only_an_asked_for_change_is_passed_on_as_allowed(self):
        self.installation("0.6.0", "standard")
        code, output, _ = self.run_it(ArchivePath=str(self.archive("advanced")), Edition="Advanced",
                                      Force=True)
        self.assertEqual(code, 0, output[-1500:])
        self.assertEqual(self.bound(), {"PluginName": "codex-auto-resume", "AllowEditionChange": "True"})
        self.assertLess(output.index("Standard edition -> Advanced edition"),
                        output.index("Using the archive you provided"))

    def test_an_update_within_an_edition_is_not_a_change(self):
        self.installation("0.6.0", "advanced")
        code, output, _ = self.run_it(ArchivePath=str(self.archive("advanced")))
        self.assertEqual(code, 0, output[-1500:])
        self.assertEqual(self.bound(), {"PluginName": "codex-auto-resume"})
        self.assertNotIn(" -> ", output)

    def test_an_archive_of_the_other_edition_is_never_unpacked(self):
        cases = (("standard", "advanced", {}, "holds the advanced edition"),
                 (None, "standard", {"Edition": "Advanced"}, "not the advanced edition"))
        for installed, given, arguments, refusal in cases:
            with self.subTest(given):
                shutil.rmtree(self.home, ignore_errors=True)
                if installed:
                    self.installation("0.6.0", installed)
                code, output, _ = self.run_it(ArchivePath=str(self.archive(given)), **arguments)
                self.assertEqual(code, 1, output[-1500:])
                self.assertIn(refusal, output)
                self.assertIn("Nothing was installed.", output)
                self.assertFalse(self.installed.exists(), "its installer ran")
                self.assertEqual(self.workfolders(), [], "the download outlived the refusal")


if __name__ == "__main__":
    unittest.main()
