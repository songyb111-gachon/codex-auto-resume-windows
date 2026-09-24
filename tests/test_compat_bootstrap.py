r"""The bootstrap's compatibility refresh: one GET, one host, one writer.

The real function definitions are lifted out of `scripts/bootstrap.ps1` by the PowerShell
parser, as tests/test_update_check.py does, into a session where `Invoke-WebRequest` is a
stub that writes a canned body - so the shipped code runs and no test reaches the network.
The validator it hands the download to is the real one: this repository's own
`controlcli compat-import`, run by the interpreter running the tests, against a scratch
installation home.

The whole-script runs point the one address at a port nothing listens on, in a scratch copy,
with a scratch home - never the real installation.
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
import guiscan
import unittest

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts" / "bootstrap.ps1"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
RAW = "https://raw.githubusercontent.com/songyb111-gachon/codex-auto-resume-windows/main/src/codex_auto_resume/data/codex_compat.json"

PROBE = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:CAR_BOOTSTRAP, [ref]$null, [ref]$errors)
if ($errors -and $errors.Count) { throw 'bootstrap.ps1 does not parse' }
$wanted = @('Step', 'Get-FinalUri', 'Assert-TrustedHost', 'Get-Remote',
            'Update-CompatibilityData', 'Get-CompatibilityExit')
foreach ($node in $ast.FindAll({ param($n)
        $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    if ($wanted -contains $node.Name) { Invoke-Expression $node.Extent.Text }
}
foreach ($name in @('$AllowedHosts', '$CompatibilityUrl', '$CompatibilityHosts',
                    '$CompatibilityMaxBytes', '$ExitUnavailable', '$ExitCompatibilityRefused')) {
    $found = $ast.FindAll({ param($n)
        $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and
        $n.Left.Extent.Text -eq $name }, $true)
    if (-not $found) { throw ('bootstrap.ps1 has no ' + $name) }
    Invoke-Expression $found[0].Extent.Text
}

$script:Requests = @()
function Invoke-WebRequest {
    param([string]$Uri, [string]$OutFile, [switch]$UseBasicParsing, [switch]$PassThru,
          [int]$MaximumRedirection, [int]$TimeoutSec, [string]$Method)
    $script:Requests += ,@($Uri, $Method, $TimeoutSec)
    if ($env:CAR_MODE -eq 'throw') { throw 'the network is not there' }
    [IO.File]::WriteAllBytes($OutFile, [IO.File]::ReadAllBytes($env:CAR_BODY))
    $base = New-Object psobject
    $base | Add-Member -MemberType NoteProperty -Name ResponseUri -Value ([Uri]$env:CAR_FINAL)
    $response = New-Object psobject
    $response | Add-Member -MemberType NoteProperty -Name BaseResponse -Value $base
    return $response
}

function Get-Workfolders {
    @(Get-ChildItem -LiteralPath ([IO.Path]::GetTempPath()) -Filter 'codex-auto-resume-compat-*' `
                    -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
}
$before = Get-Workfolders
$arguments = @{ Home_ = $env:CAR_HOME; Python = $env:CAR_PYTHON; Source = $env:CAR_SOURCE }
if ($env:CAR_TIMEOUT) { $arguments['TimeoutSec'] = [int]$env:CAR_TIMEOUT }
$answer = Update-CompatibilityData @arguments
$leftovers = @(Get-Workfolders | Where-Object { $before -notcontains $_ })
@{ answer = $answer; exit = (Get-CompatibilityExit $answer); requests = $script:Requests;
   url = $CompatibilityUrl; hosts = $CompatibilityHosts; leftovers = $leftovers } |
    ConvertTo-Json -Depth 5 -Compress
"""


def a_document(sequence=4, **extra):
    value = {"format": "codex-auto-resume-compat/1", "sequence": sequence,
             "published_at": "2026-09-18T00:00:00Z", "expires_at": "2027-06-01T00:00:00Z",
             "min_product": "0.6.4", "requires_signature": False, "engines": [], "advisories": []}
    value.update(extra)
    return value


@unittest.skipUnless(POWERSHELL.is_file(), "the bootstrap is PowerShell on Windows")
class RefreshFunctionTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.home = self.root / "home"
        (self.home / "config").mkdir(parents=True)
        self.body = self.root / "body.json"

    def run_probe(self, body: bytes, *, final=RAW, mode="ok", python=None, source=None,
                  timeout=None):
        self.body.write_bytes(body)
        environment = dict(os.environ, CAR_BOOTSTRAP=str(BOOTSTRAP), CAR_HOME=str(self.home),
                           CAR_PYTHON=str(python or sys.executable),
                           CAR_SOURCE=str(source or ROOT / "src"), CAR_BODY=str(self.body),
                           CAR_FINAL=final, CAR_MODE=mode)
        environment.pop("PYTHONPATH", None)
        environment.pop("CAR_TIMEOUT", None)
        if timeout is not None:
            environment["CAR_TIMEOUT"] = str(timeout)
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", PROBE],
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=300, env=environment)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:] + done.stdout[-2000:])
        lines = done.stdout.strip().splitlines()
        result = json.loads(lines[-1])
        result["printed"] = "\n".join(lines[:-1])
        return result

    @property
    def cache(self):
        return self.home / "config" / "compat-cache.json"

    def test_a_valid_document_is_imported_by_the_validator(self):
        result = self.run_probe(json.dumps(a_document()).encode("utf-8"))
        self.assertEqual((result["answer"], result["exit"]), ("refreshed 4", 0))
        envelope = json.loads(self.cache.read_text(encoding="utf-8"))
        self.assertEqual((envelope["origin"], envelope["document"]["sequence"]), ("main", 4))

    def test_one_get_to_the_one_constant(self):
        result = self.run_probe(json.dumps(a_document()).encode("utf-8"))
        self.assertEqual(result["url"], RAW)
        requests = result["requests"]
        if requests and isinstance(requests[0], str):
            requests = [requests]
        self.assertEqual(len(requests), 1)
        uri, method, timeout = requests[0]
        self.assertEqual(uri, RAW)
        self.assertIn(method, ("", None), "a plain GET: nothing is sent in a body")
        self.assertEqual(timeout, 60)
        self.assertIn(result["hosts"], ("raw.githubusercontent.com", ["raw.githubusercontent.com"]))

    def test_a_document_the_validator_refuses_is_not_kept(self):
        cases = {b"{": "not_json",
                 json.dumps(a_document(advisories=[{"id": "CAR-2026-0001", "match": {"version_gte": "0.1.0"},
                                                    "capabilities": ["usage_probe"], "state": "VERIFIED"}]))
                 .encode("utf-8"): "range_cannot_grant",
                 json.dumps(a_document(requires_signature=True)).encode("utf-8"): "signature_required"}
        for body, reason in cases.items():
            with self.subTest(reason=reason):
                result = self.run_probe(body)
                self.assertEqual((result["answer"], result["exit"]), ("refused " + reason, 13))
                self.assertFalse(self.cache.exists())

    def test_a_download_from_any_other_host_is_refused_before_python_sees_it(self):
        for final in ("https://github.com/x.json", "https://objects.githubusercontent.com/x.json",
                      "http://raw.githubusercontent.com/x.json",
                      "https://raw.githubusercontent.com.example.invalid/x.json"):
            with self.subTest(final=final):
                result = self.run_probe(json.dumps(a_document()).encode("utf-8"), final=final)
                self.assertEqual((result["answer"], result["exit"]), ("unavailable", 12))
                self.assertFalse(self.cache.exists())

    def test_no_network_is_an_answer_not_an_error(self):
        result = self.run_probe(b"", mode="throw")
        self.assertEqual((result["answer"], result["exit"]), ("unavailable", 12))

    def test_an_oversized_download_is_refused_before_python_starts(self):
        result = self.run_probe(b" " * 262145, python=self.root / "no-python.exe",
                                source=ROOT / "src")
        # With no interpreter there is nothing to validate with, so nothing is fetched.
        self.assertEqual(result["answer"], "unavailable")
        self.assertEqual(result["requests"], [] if isinstance(result["requests"], list) else None)
        fake_python = self.root / "python.exe"
        fake_python.write_bytes(b"not an interpreter")
        result = self.run_probe(b" " * 262145, python=fake_python)
        self.assertEqual((result["answer"], result["exit"]), ("refused too_large", 13))

    def test_the_download_does_not_outlive_the_refresh(self):
        result = self.run_probe(json.dumps(a_document()).encode("utf-8"))
        self.assertEqual(result["leftovers"], [] if isinstance(result["leftovers"], list) else None)

    def test_it_says_which_host_it_asks_before_it_asks(self):
        """An update check used to contact raw.githubusercontent.com without a word, right
        after saying it was asking github.com and reading no page."""
        result = self.run_probe(json.dumps(a_document()).encode("utf-8"))
        self.assertEqual(result["answer"], "refreshed 4")
        self.assertIn("raw.githubusercontent.com", result["printed"])
        self.assertIn("Codex compatibility data", result["printed"])

    def test_with_no_time_left_nothing_is_asked(self):
        result = self.run_probe(json.dumps(a_document()).encode("utf-8"), timeout=0)
        self.assertEqual((result["answer"], result["exit"]), ("unavailable", 12))
        self.assertEqual(result["requests"], [] if isinstance(result["requests"], list) else None)
        self.assertFalse(self.cache.exists())
        self.assertNotIn("Asking raw.githubusercontent.com", result["printed"],
                         "it does not claim to ask what it did not ask")

    def test_the_download_waits_only_as_long_as_it_was_given(self):
        result = self.run_probe(json.dumps(a_document()).encode("utf-8"), timeout=17)
        requests = result["requests"]
        if requests and isinstance(requests[0], str):
            requests = [requests]
        self.assertEqual([request[2] for request in requests], [17])
        self.assertEqual(result["answer"], "refreshed 4")


TIMEOUT_PROBE = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:CAR_BOOTSTRAP, [ref]$null, [ref]$errors)
if ($errors -and $errors.Count) { throw 'bootstrap.ps1 does not parse' }
foreach ($node in $ast.FindAll({ param($n)
        $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    if ($node.Name -eq 'Get-CompatibilityTimeout') { Invoke-Expression $node.Extent.Text }
}
$names = @('$CheckBudgetSeconds', '$LookupAllowanceSeconds', '$ValidatorAllowanceSeconds',
           '$CompatibilityCheckTimeoutMax', '$CompatibilityCheckTimeoutMin')
$constants = @{}
foreach ($name in $names) {
    $found = $ast.FindAll({ param($n)
        $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and
        $n.Left.Extent.Text -eq $name }, $true)
    if (-not $found) { throw ('bootstrap.ps1 has no ' + $name) }
    Invoke-Expression $found[0].Extent.Text
    $constants[$name.Substring(1)] = (Get-Variable -Name $name.Substring(1)).Value
}
$given = @{}
foreach ($elapsed in 0..130) { $given[[string]$elapsed] = Get-CompatibilityTimeout -Elapsed $elapsed }
@{ constants = $constants; given = $given } | ConvertTo-Json -Depth 4 -Compress
"""


@unittest.skipUnless(POWERSHELL.is_file(), "the bootstrap is PowerShell on Windows")
class UpdateCheckTimeTests(unittest.TestCase):
    """The refresh that rides on an update check shares that check's time. The window waits
    a fixed time for -CheckOnly and calls anything slower "running", so the refresh must end
    well inside it - or not start - whatever the network does."""

    # The HEAD to github.com: the script's own -TimeoutSec for it.
    HEAD_TIMEOUT = 60

    @classmethod
    def setUpClass(cls):
        environment = dict(os.environ, CAR_BOOTSTRAP=str(BOOTSTRAP))
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command",
                               TIMEOUT_PROBE],
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=300, env=environment)
        if done.returncode != 0:
            raise AssertionError(done.stderr[-2000:] + done.stdout[-2000:])
        answer = json.loads(done.stdout.strip().splitlines()[-1])
        cls.constants = answer["constants"]
        cls.given = {int(elapsed): seconds for elapsed, seconds in answer["given"].items()}

    def window_seconds(self):
        text = guiscan.dashboard()
        match = re.search(r"CheckMilliseconds\s*=\s*(\d+)\s*;", text)
        self.assertIsNotNone(match, "the window's wait for -CheckOnly is no longer where this looks")
        return int(match.group(1)) / 1000

    def test_the_refresh_ends_inside_the_budget_whatever_it_is_given(self):
        c = self.constants
        for elapsed, seconds in self.given.items():
            with self.subTest(elapsed=elapsed):
                self.assertGreaterEqual(seconds, 0)
                self.assertLessEqual(seconds, c["CompatibilityCheckTimeoutMax"])
                if seconds:
                    self.assertGreaterEqual(seconds, c["CompatibilityCheckTimeoutMin"])
                    self.assertLessEqual(elapsed + seconds + c["LookupAllowanceSeconds"]
                                         + c["ValidatorAllowanceSeconds"], c["CheckBudgetSeconds"])

    def test_a_slow_answer_from_github_leaves_no_time_for_the_refresh(self):
        worst_head = self.HEAD_TIMEOUT + self.constants["LookupAllowanceSeconds"]
        self.assertEqual(self.given[worst_head], 0)
        self.assertEqual(self.given[0], self.constants["CompatibilityCheckTimeoutMax"])

    def test_the_budget_sits_well_inside_what_the_window_waits(self):
        # Ten seconds for PowerShell to start and read the script before its clock starts.
        self.assertLess(self.constants["CheckBudgetSeconds"] + 10, self.window_seconds())
        text = BOOTSTRAP.read_text(encoding="utf-8")
        head = text[text.index("function Get-NewestPublishedVersion"):text.index("function Get-Remote")]
        self.assertIn("-TimeoutSec %d" % self.HEAD_TIMEOUT, head,
                      "the HEAD's own timeout, which the worst case above assumes")


@unittest.skipUnless(POWERSHELL.is_file(), "the bootstrap is PowerShell on Windows")
class WholeScriptTests(unittest.TestCase):
    """The shipped script, run, from a scratch copy whose one address goes nowhere."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        root = Path(cls.folder.name) / "plugin"
        (root / "scripts").mkdir(parents=True)
        (root / ".codex-plugin").mkdir(parents=True)
        text = BOOTSTRAP.read_text(encoding="utf-8")
        cls.assert_constant_present = RAW in text
        text = text.replace(RAW, "https://127.0.0.1:1/codex_compat.json")
        (root / "scripts" / "bootstrap.ps1").write_text(text, encoding="utf-8")
        shutil.copyfile(ROOT / ".codex-plugin" / "plugin.json", root / ".codex-plugin" / "plugin.json")
        release = json.loads((ROOT / "scripts" / "release.json").read_text(encoding="utf-8"))
        release["latest"] = "https://127.0.0.1:1/releases/latest"
        release["download"] = "https://127.0.0.1:1/releases/download/v{version}/"
        (root / "scripts" / "release.json").write_text(json.dumps(release), encoding="utf-8")
        cls.script = root / "scripts" / "bootstrap.ps1"

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def run_it(self, home, *arguments):
        return subprocess.run(
            [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(self.script), *arguments],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300, text=True,
            encoding="utf-8", errors="replace",
            env=dict(os.environ, CODEX_AUTO_RESUME_PLUGIN_HOME=str(home)))

    def test_the_copy_really_replaced_the_address(self):
        self.assertTrue(self.assert_constant_present)
        self.assertNotIn("raw.githubusercontent.com/songyb111", self.script.read_text(encoding="utf-8"))

    def test_without_an_installation_nothing_is_fetched(self):
        home = Path(self.folder.name) / "empty-home"
        home.mkdir(exist_ok=True)
        done = self.run_it(home, "-Compatibility")
        self.assertEqual(done.returncode, 12, done.stdout[-1500:])
        self.assertIn("compatibility: unavailable", done.stdout)
        self.assertEqual(sorted(p.name for p in home.iterdir()), [])

    def test_an_installation_that_cannot_reach_the_address_is_told_so(self):
        home = Path(self.folder.name) / "installed"
        (home / "runtime").mkdir(parents=True, exist_ok=True)
        (home / "runtime" / "python.exe").write_bytes(b"never started")
        package = home / "app" / "src" / "codex_auto_resume"
        package.mkdir(parents=True, exist_ok=True)
        (package / "controlcli.py").write_text("raise SystemExit(3)\n", encoding="utf-8")
        done = self.run_it(home, "-Compatibility")
        self.assertEqual(done.returncode, 12, done.stdout[-1500:])
        self.assertIn("compatibility: unavailable", done.stdout)
        self.assertIn("Nothing was changed", done.stdout)
        self.assertFalse((home / "config").exists())

    def test_it_is_asked_on_its_own(self):
        home = Path(self.folder.name) / "alone"
        home.mkdir(exist_ok=True)
        for extra in (["-CheckOnly"], ["-Update"], ["-Force"], ["-ArchivePath", str(self.script)]):
            with self.subTest(extra=extra):
                done = self.run_it(home, "-Compatibility", *extra)
                self.assertEqual(done.returncode, 12)
                self.assertIn("on its own", done.stdout)

    def test_an_update_check_that_could_not_ask_does_not_refresh_either(self):
        home = Path(self.folder.name) / "check"
        home.mkdir(exist_ok=True)
        done = self.run_it(home, "-CheckOnly")
        self.assertEqual(done.returncode, 12)
        self.assertIn("update: unavailable", done.stdout)
        self.assertNotIn("compatibility:", done.stdout)


STUBBED_CHECK = r"""
$ErrorActionPreference = 'Stop'
# Every request the script makes lands here: the HEAD is answered with this repository's
# tag page, anything else with a small body. Nothing reaches a network.
function Invoke-WebRequest {
    param([string]$Uri, [string]$OutFile, [switch]$UseBasicParsing, [switch]$PassThru,
          [int]$MaximumRedirection, [int]$TimeoutSec, [string]$Method)
    Add-Content -LiteralPath $env:CAR_ASKED -Value ($Method + ' ' + $Uri + ' ' + $TimeoutSec)
    $final = $Uri
    if ($Method -eq 'Head') { $final = $env:CAR_TAG_URL }
    if ($OutFile) { Set-Content -LiteralPath $OutFile -Value '{}' }
    $base = New-Object psobject
    $base | Add-Member -MemberType NoteProperty -Name ResponseUri -Value ([Uri]$final)
    $response = New-Object psobject
    $response | Add-Member -MemberType NoteProperty -Name BaseResponse -Value $base
    return $response
}
& $env:CAR_SCRIPT -CheckOnly
exit $LASTEXITCODE
"""


@unittest.skipUnless(POWERSHELL.is_file(), "the bootstrap is PowerShell on Windows")
class UpdateCheckWholeScriptTests(unittest.TestCase):
    """-CheckOnly, the whole script, after github.com has answered - the path the window's
    Check for updates takes. `Invoke-WebRequest` is a stub in the calling session, and the
    copy's two addresses point at a port nothing listens on, so a stub that failed to take
    would fail the test rather than reach anything."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        root = Path(cls.folder.name) / "plugin"
        (root / "scripts").mkdir(parents=True)
        (root / ".codex-plugin").mkdir(parents=True)
        text = BOOTSTRAP.read_text(encoding="utf-8").replace(RAW, "https://127.0.0.1:1/codex_compat.json")
        (root / "scripts" / "bootstrap.ps1").write_text(text, encoding="utf-8")
        cls.release = json.loads((ROOT / "scripts" / "release.json").read_text(encoding="utf-8"))
        release = dict(cls.release, latest="https://127.0.0.1:1/releases/latest",
                       download="https://127.0.0.1:1/releases/download/v{version}/")
        (root / "scripts" / "release.json").write_text(json.dumps(release), encoding="utf-8")
        cls.script = root / "scripts" / "bootstrap.ps1"
        manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8-sig"))
        # The stub answers with this version as a published tag, and only vMAJOR.MINOR.PATCH is
        # ever accepted from the network - so the copy carries a released version's manifest even
        # while this checkout is a pre-release. What is under test is the answer, not the name.
        cls.version = manifest["version"].split("-")[0]
        manifest["version"] = cls.version
        (root / ".codex-plugin" / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def check(self, home):
        asked = home.parent / (home.name + "-asked.txt")
        tag = "https://github.com/%s/%s/releases/tag/v%s" % (self.release["owner"], self.release["repo"],
                                                             self.version)
        done = subprocess.run(
            [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", STUBBED_CHECK],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300, text=True,
            encoding="utf-8", errors="replace",
            env=dict(os.environ, CODEX_AUTO_RESUME_PLUGIN_HOME=str(home), CAR_SCRIPT=str(self.script),
                     CAR_ASKED=str(asked), CAR_TAG_URL=tag))
        requests = asked.read_text(encoding="utf-8").split("\n") if asked.exists() else []
        return done, [line.split() for line in requests if line.strip()]

    def test_the_update_answer_still_comes_and_the_refresh_says_where_it_stands(self):
        home = Path(self.folder.name) / "not-installed"
        home.mkdir()
        done, requests = self.check(home)
        self.assertEqual(done.returncode, 0, done.stdout[-2000:])
        self.assertIn("update: current " + self.version, done.stdout)
        self.assertIn("compatibility: unavailable", done.stdout)
        self.assertLess(done.stdout.index("compatibility: "), done.stdout.index("update: "))
        self.assertIn("no installation here", done.stdout)
        self.assertEqual([request[0] for request in requests], ["Head"],
                         "with nothing to validate it, the data is not asked for")

    def test_an_installation_is_told_the_host_and_given_only_the_time_that_is_left(self):
        home = Path(self.folder.name) / "installed"
        (home / "runtime").mkdir(parents=True)
        (home / "runtime" / "python.exe").write_bytes(b"never started")
        package = home / "app" / "src" / "codex_auto_resume"
        package.mkdir(parents=True)
        (package / "controlcli.py").write_text("raise SystemExit(3)\n", encoding="utf-8")
        done, requests = self.check(home)
        self.assertEqual(done.returncode, 0, done.stdout[-2000:])
        self.assertIn("update: current " + self.version, done.stdout)
        self.assertIn("Asking raw.githubusercontent.com for the Codex compatibility data", done.stdout)
        self.assertIn("compatibility: unavailable", done.stdout)
        self.assertEqual(len(requests), 2, requests)
        method, uri, timeout = requests[1] if len(requests[1]) == 3 else [""] + requests[1]
        self.assertEqual(uri, "https://127.0.0.1:1/codex_compat.json")
        self.assertLessEqual(int(timeout), 30, "a share of the check's time, not the refresh's own 60 s")
        self.assertGreaterEqual(int(timeout), 5)
        self.assertFalse((home / "config").exists(), "nothing the validator did not accept is kept")


class ScriptTextTests(unittest.TestCase):
    TEXT = BOOTSTRAP.read_text(encoding="utf-8")

    def test_the_update_check_refreshes_after_github_answered_and_before_it_answers(self):
        check = self.TEXT[self.TEXT.index("if ($CheckOnly -or $Update) {\n    # \"Up to date\""):]
        refresh = check.index("Update-CompatibilityData -Home_ $installHome")
        self.assertLess(check.index("$order = Compare-ProductVersion"), refresh)
        self.assertLess(refresh, check.index("if ($order -lt 0)"))
        self.assertLess(check.index("exit $ExitUnavailable"), refresh,
                        "a check that could not ask github.com asks nothing else either")

    def test_the_update_check_gives_the_refresh_only_the_time_that_is_left(self):
        head = self.TEXT[:self.TEXT.index("$ErrorActionPreference = 'Stop'")]
        self.assertIn("$ScriptClock = [Diagnostics.Stopwatch]::StartNew()", head,
                      "the clock starts before anything else runs")
        check = self.TEXT[self.TEXT.index("if ($CheckOnly -or $Update) {\n    # \"Up to date\""):]
        call = check[:check.index("if ($order -lt 0)")]
        self.assertIn("Get-CompatibilityTimeout -Elapsed $ScriptClock.Elapsed.TotalSeconds", call)
        self.assertRegex(call, r"Update-CompatibilityData -Home_ \$installHome -TimeoutSec ")

    def test_the_host_is_named_where_the_fetch_is(self):
        refresh = self.TEXT[self.TEXT.index("function Update-CompatibilityData"):
                            self.TEXT.index("function Get-CompatibilityExit")]
        self.assertLess(refresh.index("Step 'Asking raw.githubusercontent.com"),
                        refresh.index("Get-Remote -Uri $CompatibilityUrl"))

    def test_the_archive_download_keeps_its_three_hosts(self):
        self.assertIn("Get-Remote -Uri ($base + $name) -OutFile $zip -What 'The archive'\n", self.TEXT)
        self.assertRegex(self.TEXT, r"\[string\[\]\]\$Hosts = \$AllowedHosts")

    def test_nothing_is_piped_from_the_network_into_anything(self):
        refresh = self.TEXT[self.TEXT.index("function Update-CompatibilityData"):
                            self.TEXT.index("function Get-CompatibilityExit")]
        self.assertNotIn("Invoke-Expression", refresh)
        self.assertNotIn("iex", refresh.lower().split())
        self.assertNotIn("ConvertFrom-Json", refresh[:refresh.index("& $Python")],
                         "the download is never parsed here; the validator reads it")


if __name__ == "__main__":
    unittest.main()
