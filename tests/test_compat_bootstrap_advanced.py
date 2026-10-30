"""The bootstrap's fetch of the advanced edition's measurement data (v0.6.20, Update-AdvancedCompatibilityData).

Asked for at the two moments the standard data is - -Compatibility, which the Diagnostics refresh runs, and an update
check that reached github.com - by the same rules: one GET to one constant URL, raw.githubusercontent.com only, at most
the validator's cap, never parsed by PowerShell; and only for an installation whose tree holds the advanced package. A
standard installation asks nothing more and prints nothing more. The body is moved, unread, to
config/compat-advanced.download.json, which the advanced edition judges at its next read (compatdata.py).

Each test runs the function itself, cut out of bootstrap.ps1, with Invoke-WebRequest played by a stand-in that records
every request: no network is reached.
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
BOOTSTRAP = ROOT / "scripts" / "bootstrap.ps1"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
URL = ("https://raw.githubusercontent.com/songyb111-gachon/codex-auto-resume-windows/main/advanced/compat/"
       "codex_compat_advanced.json")

PROBE = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:CAR_BOOTSTRAP, [ref]$null, [ref]$errors)
if ($errors -and $errors.Count) { throw 'bootstrap.ps1 does not parse' }
$wanted = @('Step', 'Get-FinalUri', 'Assert-TrustedHost', 'Invoke-BoundedWebRequest', 'Get-Remote',
            'Update-AdvancedCompatibilityData', 'Get-Edition')
foreach ($node in $ast.FindAll({ param($n)
        $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    if ($wanted -contains $node.Name) { Invoke-Expression $node.Extent.Text }
}
foreach ($name in @('$AllowedHosts', '$AdvancedCompatibilityUrl', '$CompatibilityHosts', '$CompatibilityMaxBytes')) {
    $found = $ast.FindAll({ param($n)
        $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and
        $n.Left.Extent.Text -eq $name }, $true)
    if (-not $found) { throw ('bootstrap.ps1 has no ' + $name) }
    Invoke-Expression $found[0].Extent.Text
}
[IO.File]::WriteAllText($env:CAR_REQUESTS, '')
function New-DownloadRequest { throw 'not here' }
function Invoke-WebRequest {
    param([string]$Uri, [string]$OutFile, [switch]$UseBasicParsing, [switch]$PassThru,
          [int]$MaximumRedirection, [int]$TimeoutSec, [string]$Method)
    [IO.File]::AppendAllText($env:CAR_REQUESTS, $Uri + "`n")
    [IO.File]::WriteAllBytes($OutFile, [IO.File]::ReadAllBytes($env:CAR_BODY))
    $base = New-Object psobject
    $base | Add-Member -MemberType NoteProperty -Name ResponseUri -Value ([Uri]$env:CAR_FINAL)
    $response = New-Object psobject
    $response | Add-Member -MemberType NoteProperty -Name BaseResponse -Value $base
    return $response
}
$answer = Update-AdvancedCompatibilityData -Home_ $env:CAR_HOME -Source $env:CAR_SOURCE
$requests = @([IO.File]::ReadAllLines($env:CAR_REQUESTS) | Where-Object { $_ })
'@@' + (@{ answer = $answer; requests = $requests } | ConvertTo-Json -Compress)
"""


@unittest.skipUnless(POWERSHELL.is_file(), "the bootstrap is PowerShell on Windows")
class AdvancedFetchTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.home = self.root / "home"
        (self.home / "config").mkdir(parents=True)
        self.source = self.home / "app" / "src"
        (self.source / "codex_auto_resume").mkdir(parents=True)
        self.body = self.root / "body.json"
        self.landed = self.home / "config" / "compat-advanced.download.json"

    def run_probe(self, body=b'{"sequence": 2}', *, advanced=True, final=URL):
        if advanced:
            # The advanced edition as Get-Edition reads it: the package's folder, in its case, with its __init__.py.
            package = self.source / "codex_auto_resume_advanced"
            package.mkdir(exist_ok=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
        self.body.write_bytes(body)
        environment = dict(os.environ, CAR_BOOTSTRAP=str(BOOTSTRAP), CAR_HOME=str(self.home),
                           CAR_SOURCE=str(self.source), CAR_BODY=str(self.body), CAR_FINAL=final,
                           CAR_REQUESTS=str(self.root / "requests.txt"))
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", PROBE],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
                              env=environment, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(done.returncode, 0, done.stderr[-2000:] + done.stdout[-2000:])
        printed, _, tail = done.stdout.rpartition("@@")
        result = json.loads(tail)
        requests = result["requests"]
        result["requests"] = [requests] if isinstance(requests, str) else (requests or [])
        result["printed"] = printed
        return result

    def test_the_advanced_edition_asks_the_one_constant_and_lands_the_body_unread(self):
        result = self.run_probe(b'{"anything": "unread"}')
        self.assertEqual((result["answer"], result["requests"]), ("fetched", [URL]))
        self.assertEqual(self.landed.read_bytes(), b'{"anything": "unread"}')
        self.assertIn("raw.githubusercontent.com", result["printed"])
        self.assertNotIn("compatibility: ", result["printed"])

    def test_the_standard_edition_asks_nothing_and_says_nothing(self):
        result = self.run_probe(advanced=False)
        self.assertEqual((result["answer"], result["requests"], result["printed"].strip()), (None, [], ""))
        self.assertFalse(self.landed.exists())

    def test_another_host_or_an_oversized_body_lands_nothing(self):
        for name, body, final in (("another host", b"{}", "https://example.invalid/x.json"),
                                  ("http", b"{}", URL.replace("https:", "http:")),
                                  ("oversized", b" " * 262145, URL)):
            with self.subTest(name):
                result = self.run_probe(body, final=final)
                self.assertEqual(result["answer"], "unavailable")
                self.assertFalse(self.landed.exists())


class WiringTests(unittest.TestCase):
    TEXT = BOOTSTRAP.read_text(encoding="utf-8-sig")

    def test_it_rides_on_both_moments_and_never_changes_their_answer(self):
        compatibility = self.TEXT[self.TEXT.index("if ($Compatibility) {"):]
        compatibility = compatibility[:compatibility.index("exit (Get-CompatibilityExit $answer)")]
        self.assertIn("$null = Update-AdvancedCompatibilityData -Home_ $installHome", compatibility)
        check = self.TEXT[self.TEXT.index("Write-Host ('compatibility: ' + (Update-CompatibilityData -Home_ $installHome"):]
        self.assertRegex(check[:600], r"\$null = Update-AdvancedCompatibilityData -Home_ \$installHome `\s+"
                                      r"-TimeoutSec \(Get-CompatibilityTimeout -Elapsed")

    def test_the_address_is_one_constant_on_main_at_the_allowed_host(self):
        found = re.findall(r"^\$AdvancedCompatibilityUrl = '([^']*)'$", self.TEXT, re.M)
        self.assertEqual(found, [URL])
        body = self.TEXT[self.TEXT.index("function Update-AdvancedCompatibilityData"):]
        body = body[:body.index("\nfunction ")]
        self.assertIn("-Hosts $CompatibilityHosts", body)
        self.assertIn("-MaxBytes $CompatibilityMaxBytes", body)
        for word in ("ConvertFrom-Json", "Invoke-Expression", "& $Python", "| &"):
            self.assertNotIn(word, body)


if __name__ == "__main__":
    unittest.main()
