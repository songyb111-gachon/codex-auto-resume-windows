r"""One rule for this product's own version, wherever it is checked.

A version is MAJOR.MINOR.PATCH in ASCII digits, then `-alpha`, `-beta` or nothing, in exactly
that case, then - after a word, if the build is a stage's later pre-release - `.N` with N from 2 to
999 and no leading zero, and nothing before or after it: no space, no line break, no other word, no
other script's digits. The plain word is a stage's first pre-release, so there is no `.1` and no
`.0`, and the order is 0.6.11-alpha, 0.6.11-alpha.2, 0.6.11-beta, 0.6.11-beta.2, 0.6.11 (ORDER).
It is checked in six places, and each says it applies the rule the others do:
the bootstrap's Get-PluginVersion (the version it splices into a URL) and Get-VersionParts (the
one it compares), the settings window's build (build/make_gui.ps1), the release workflow's build
job, the order the published bootstraps are checked in (build/legacy_bootstraps.py), and the
version the product reads its compatibility data as (compat/files.py, product_version).

They disagreed at the edges, and each edge is a case below. PowerShell's `$` matches before a final
line break as well as at the end, so every PowerShell check took `0.6.11-beta` followed by a
newline, which Python refused. And `\d` matches any script's digits, in .NET and in Python alike,
so the workflow, the window's build and Python took `0.6.1` followed by a fullwidth one, which the
bootstrap refused. None of it could be published - the publish job's own bash check refuses all of
it - but a rule that five copies state is only one rule while a test holds them to it.

The PowerShell checks are run as written: the bootstrap's two functions lifted out of the script
by the parser, and the other two files' patterns taken from the line that applies them, with the
operator that line uses.
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
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
_BUILD = str(ROOT / "build")
if _BUILD not in sys.path:
    sys.path.insert(0, _BUILD)

import legacy_bootstraps as legacy  # noqa: E402

BOOTSTRAP = ROOT / "scripts" / "bootstrap.ps1"
MAKE_GUI = ROOT / "build" / "make_gui.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")

ACCEPTED = ["0.6.11", "0.6.11-alpha", "0.6.11-beta", "10.20.30", "0.0.0",
            # A stage's later pre-releases: 2 to 999, no leading zero.
            "0.6.11-alpha.2", "0.6.11-beta.2", "0.6.11-beta.3", "0.6.11-beta.9", "0.6.11-beta.10",
            "0.6.11-alpha.99", "0.6.11-beta.100", "0.6.11-beta.999", "10.20.30-beta.2"]
REFUSED = [
    # Another word, another case, or more after one of the two.
    "0.6.11-gamma", "0.6.11-rc", "0.6.11-rc1", "0.6.11-Beta", "0.6.11-BETA", "0.6.11-Alpha",
    "0.6.11-beta1", "0.6.11-alpha-beta", "0.6.11-", "0.6.11-betaa",
    # A number the rule does not give: the plain word is the first, so no .1 and no .0; no
    # leading zero, no fourth digit, nothing after it, and never on a release or another word.
    "0.6.11-beta.1", "0.6.11-alpha.1", "0.6.11-beta.0", "0.6.11-beta.00", "0.6.11-beta.01",
    "0.6.11-beta.02", "0.6.11-beta.010", "0.6.11-beta.1000", "0.6.11-beta.9999", "0.6.11-beta.",
    "0.6.11-beta..2", "0.6.11-beta.2.1", "0.6.11-beta.2.", "0.6.11-beta.2-alpha", "0.6.11-beta-2",
    "0.6.11-beta2", "0.6.11-beta.x", "0.6.11-beta.+2", "0.6.11-beta.-2", "0.6.11-Beta.2",
    "0.6.11-rc.2", "0.6.11.2", "0.6.11-.2", "0.6.11-beta.2 ", "0.6.11-beta.2\n", "0.6.11-beta.2\r\n",
    " 0.6.11-beta.2", "0.6.11-beta.\uff12", "0.6.11-beta.\u0662", "0.6.11-beta.\u00b2",
    # Anything around it: `$` in .NET takes a final "\n" as the end.
    " 0.6.11", "0.6.11 ", "0.6.11-beta ", "0.6.11\n", "0.6.11-beta\n", "0.6.11-alpha\n",
    "0.6.11-beta\r\n", "\n0.6.11", "0.6.11\t",
    # Another script's digits, or another dash: `\d` takes the first two.
    "\u0660.\u0666.\u0661\u0661-beta", "0.6.1\uff11-beta", "\uff10.6.11", "0.6.11\u2010beta",
    # Not three numbers.
    "0.6", "0.6.11.1", "v0.6.11", "", "0.6.x",
]
CASES = [(version, True) for version in ACCEPTED] + [(version, False) for version in REFUSED]
# In the order they are published and compared: each stage's pre-releases just before the next,
# the numbers as numbers (.9 before .10), and the release after all of them.
ORDER = ["0.6.10", "0.6.11-alpha", "0.6.11-alpha.2", "0.6.11-alpha.10", "0.6.11-beta", "0.6.11-beta.2",
         "0.6.11-beta.3", "0.6.11-beta.9", "0.6.11-beta.10", "0.6.11-beta.999", "0.6.11", "0.6.12-alpha"]


def applied_pattern(path: Path, variable: str) -> tuple:
    """The operator and pattern of the one line in `path` that checks `$variable` as a version."""
    found = re.findall(r"\$%s (-c?notmatch) '([^']+)'" % re.escape(variable), path.read_text(encoding="utf-8"))
    if len(found) != 1:
        raise AssertionError("%s checks $%s %d times, not once" % (path.name, variable, len(found)))
    return found[0]


PROBE = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:CAR_BOOTSTRAP, [ref]$null, [ref]$errors)
if ($errors -and $errors.Count) { throw 'bootstrap.ps1 does not parse' }
$wanted = @('Read-Json', 'Get-PluginVersion', 'Get-VersionParts', 'Compare-ProductVersion')
foreach ($node in $ast.FindAll({ param($n)
        $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    if ($wanted -contains $node.Name) { Invoke-Expression $node.Extent.Text }
}
$input_ = Get-Content -LiteralPath $env:CAR_INPUT -Raw -Encoding UTF8 | ConvertFrom-Json
# The two lines outside the bootstrap, each with its own operator: -notmatch would ignore case.
$lines = @{}
foreach ($pair in $input_.lines.PSObject.Properties) {
    $lines[$pair.Name] = [scriptblock]::Create('param($v, $p) -not ($v ' + $pair.Value.operator + ' $p)')
}
$PluginRoot = $env:CAR_PLUGIN
New-Item -ItemType Directory -Force -Path (Join-Path $PluginRoot '.codex-plugin') | Out-Null
$manifest = Join-Path $PluginRoot '.codex-plugin\plugin.json'
$answers = @()
foreach ($version in $input_.versions) {
    $version = [string]$version
    $answer = [ordered]@{}
    # Written as the manifest it would be read from, so the text reaches the check as JSON gives it.
    [IO.File]::WriteAllText($manifest, (ConvertTo-Json @{ name = 'codex-auto-resume'; version = $version } -Compress),
                            (New-Object Text.UTF8Encoding($false)))
    try { $null = Get-PluginVersion; $answer.plugin = $true } catch { $answer.plugin = $false }
    try { $null = Get-VersionParts $version; $answer.parts = $true } catch { $answer.parts = $false }
    foreach ($name in $lines.Keys) {
        $answer[$name] = [bool](& $lines[$name] $version $input_.lines.$name.pattern)
    }
    $answers += [pscustomobject]$answer
}
# Every ordered pair of ORDER, as Compare-ProductVersion signs it.
$signs = @()
foreach ($left in $input_.order) {
    foreach ($right in $input_.order) {
        $signs += [int](Compare-ProductVersion -Left ([string]$left) -Right ([string]$right))
    }
}
ConvertTo-Json -InputObject ([ordered]@{ answers = @($answers); signs = @($signs) }) -Depth 4 -Compress
"""


class PythonTests(unittest.TestCase):
    def test_the_published_bootstraps_order_takes_exactly_the_rule(self):
        for version, accepted in CASES:
            with self.subTest(ascii(version)):
                if accepted:
                    legacy.order(version)
                else:
                    with self.assertRaises(ValueError):
                        legacy.order(version)

    def test_the_published_bootstraps_order_is_the_order_releases_are_made_in(self):
        self.assertEqual(sorted(reversed(ORDER), key=legacy.order), ORDER)
        self.assertEqual(len({legacy.order(version) for version in ORDER}), len(ORDER),
                         "two versions sort as one")

    def test_the_product_reads_exactly_the_rule(self):
        from codex_auto_resume.compat import files
        for version, accepted in CASES:
            with self.subTest(ascii(version)), patch.object(files.config, "version", return_value=version):
                expected = version.split("-")[0] if accepted else "unknown"
                self.assertEqual(files.product_version(), expected)


@unittest.skipUnless(POWERSHELL.is_file(), "the checks are Windows PowerShell")
class PowerShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        lines = {}
        for name, (path, variable) in {"make_gui": (MAKE_GUI, "version"),
                                       "release_build": (WORKFLOW, "declared")}.items():
            operator, pattern = applied_pattern(path, variable)
            lines[name] = {"operator": operator, "pattern": pattern}
        cls.lines = lines
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "input.json"
            source.write_text(json.dumps({"versions": [version for version, _ in CASES], "lines": lines,
                                          "order": ORDER}), encoding="utf-8")
            done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", PROBE],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=300, env=dict(os.environ, CAR_BOOTSTRAP=str(BOOTSTRAP),
                                                        CAR_INPUT=str(source),
                                                        CAR_PLUGIN=str(Path(folder) / "plugin")))
        cls.done = done
        found = json.loads(done.stdout) if done.returncode == 0 and done.stdout.strip() else None
        cls.answers = found["answers"] if found else None
        cls.signs = found["signs"] if found else None

    def setUp(self):
        if self.answers is None:
            self.fail("the probe did not run: " + (self.done.stderr or self.done.stdout)[-2000:])

    def verdicts(self, name):
        return {version: answer[name] for (version, _), answer in zip(CASES, self.answers)}

    def check(self, name):
        verdicts = self.verdicts(name)
        for version, accepted in CASES:
            with self.subTest(ascii(version)):
                self.assertEqual(verdicts[version], accepted)

    def test_the_bootstrap_fetches_exactly_the_rule(self):
        self.check("plugin")

    def test_the_bootstrap_compares_exactly_the_rule(self):
        self.check("parts")

    def test_the_bootstrap_compares_in_the_order_releases_are_made_in(self):
        """Every pair, both ways round: the one comparison an update check makes."""
        signs = iter(self.signs)
        for i, left in enumerate(ORDER):
            for j, right in enumerate(ORDER):
                with self.subTest(left=left, right=right):
                    self.assertEqual(next(signs), (i > j) - (i < j))

    def test_the_windows_build_takes_exactly_the_rule(self):
        self.assertEqual(self.lines["make_gui"]["operator"], "-cnotmatch")
        self.check("make_gui")

    def test_the_release_build_takes_exactly_the_rule(self):
        self.assertEqual(self.lines["release_build"]["operator"], "-cnotmatch")
        self.check("release_build")


if __name__ == "__main__":
    unittest.main()
