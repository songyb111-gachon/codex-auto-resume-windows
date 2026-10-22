r"""Install another version... and the state's readable-from mark (v0.6.18, store/schema.py READABLE_FROM).

The picker keeps the state as it is (`kept`) for a target that reads it: one on this version's own
schema, as before - and one from $StateMarkSince on whose schema is $StateReadableFrom or later,
which reads a later state so marked as its own. A version before $StateMarkSince knows no mark and
reads its own schema alone, so a later schema is never `kept` for it; schemas 4 and 3 are converted
first, as before. Today the two rules agree (schema 5, readable from 5); a later schema marked
readable from 5 is played here by giving the lifted verdict that version's table.

Get-VersionVerdict is lifted out of scripts/bootstrap.ps1 by the PowerShell parser, as
tests/test_version_picker.py lifts it, and run with no network and no registry.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

_HERE = str(Path(__file__).resolve().parent)
for entry in (str(Path(_HERE).parent / "src"), _HERE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from codex_auto_resume.store.schema import READABLE_FROM, SCHEMA_VERSION  # noqa: E402
from test_version_picker import BOOTSTRAP, POWERSHELL, RELEASE, ROOT, row  # noqa: E402

LIFT = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:CAR_BOOTSTRAP, [ref]$null, [ref]$errors)
if ($errors -and $errors.Count) { throw 'bootstrap.ps1 does not parse' }
$wanted = @('Get-VersionParts', 'Compare-ProductVersion', 'Format-UnreadVersion', 'Get-PrereleaseVersion',
            'Get-SinceValue', 'Get-PinnedDigest', 'Get-EditionRelease', 'Get-VersionVerdict')
foreach ($node in $ast.FindAll({ param($n)
        $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    if ($wanted -contains $node.Name) { Invoke-Expression $node.Extent.Text }
}
$constants = [ordered]@{}
foreach ($name in @('$PickFloor', '$EditionsSince', '$PolicySince', '$StateSchemaSince', '$StateReadableFrom',
                    '$StateMarkSince', '$AdvancedStateSince', '$PickNewerPrereleases', '$PickOlderPrereleases')) {
    $found = $ast.FindAll({ param($n)
        $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -eq $name }, $true)
    if (-not $found) { throw ('bootstrap.ps1 has no ' + $name) }
    Invoke-Expression $found[0].Extent.Text
    $constants[$name.Substring(1)] = (Get-Variable -Name $name.Substring(1)).Value
}
$cases = Get-Content -LiteralPath $env:CAR_CASES -Raw -Encoding UTF8 | ConvertFrom-Json
$Release = Get-Content -LiteralPath $env:CAR_RELEASE -Raw -Encoding UTF8 | ConvertFrom-Json
$today = $StateSchemaSince
$verdicts = @(foreach ($case in $cases) {
    # A later version's own table, newest row first, played over this one's.
    $StateSchemaSince = $today
    if ($case.later) { $StateSchemaSince = @(,@([string]$case.later[0], [int]$case.later[1])) + $today }
    $StateReadableFrom = [int]$case.readable_from
    $listed = [pscustomobject]@{ Version = $case.entry.version; Prerelease = $case.entry.prerelease;
                                 Assets = @($case.entry.assets) }
    $row = Get-VersionVerdict -Entry $listed -Edition $case.edition -Installed $case.installed `
                              -InstalledEdition $case.installed_edition -Release $Release -Policy ([bool]$case.policy) `
                              -Offer $case.offer -Latest $case.latest
    if ($null -eq $row) { 'omitted' } else { $row.Answer + ' ' + $row.Detail }
})
ConvertTo-Json -InputObject ([ordered]@{ constants = $constants; verdicts = $verdicts }) -Depth 6 -Compress
"""

INSTALLED, LATER = "0.6.18", "0.6.19"


def case(version, expected, *, later=None, readable_from=READABLE_FROM, installed=INSTALLED, latest=INSTALLED):
    made, answer = row(version, expected, installed=installed, latest=latest)
    return dict(made, later=later, readable_from=readable_from), answer


# Today: schema 5, readable from 5 - the targets on schema 5 keep the state, 4 and 3 are converted, as before.
TODAY = [case("0.6.17", "offered older,release,kept"), case("0.6.16", "offered older,release,kept"),
         case("0.6.16-beta.4", "offered older,prerelease,kept"), case("0.6.15", "offered older,release,convert3"),
         case("0.6.15-beta", "offered older,prerelease,kept"), case("0.6.14", "offered older,release,convert3"),
         case("0.6.10", "offered older,release,convert3")]
# A later schema 6 marked readable from 5: kept for a target that reads the mark, never for one before it.
READABLE = [case(version, expected, later=[LATER, 6], installed=LATER, latest=LATER) for version, expected in (
    ("0.6.18", "offered older,release,kept"), ("0.6.17", "omitted"), ("0.6.16", "omitted"),
    ("0.6.15", "offered older,release,convert3"), ("0.6.10", "offered older,release,convert3"))]
# A later schema 6 readable from 6 alone: no older version keeps it.
UNREADABLE = [case(version, expected, later=[LATER, 6], readable_from=6, installed=LATER, latest=LATER)
              for version, expected in (("0.6.18", "omitted"), ("0.6.17", "omitted"),
                                        ("0.6.15", "offered older,release,convert3"))]
CASES = TODAY + READABLE + UNREADABLE


@unittest.skipUnless(POWERSHELL.is_file(), "the bootstrap is PowerShell on Windows")
class ReadableFromTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory()
        cls.folder = folder
        work = Path(folder.name)
        (work / "release.json").write_text(json.dumps(RELEASE), encoding="utf-8")
        (work / "cases.json").write_text(json.dumps([made for made, _ in CASES]), encoding="utf-8")
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", LIFT],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                              env=dict(os.environ, CAR_BOOTSTRAP=str(BOOTSTRAP), CAR_CASES=str(work / "cases.json"),
                                       CAR_RELEASE=str(work / "release.json")))
        cls.done = done
        cls.answer = json.loads(done.stdout) if done.returncode == 0 and done.stdout.strip() else None

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if self.answer is None:
            self.fail("the probe did not run: " + (self.done.stderr or self.done.stdout)[-3000:])

    def test_the_mark_the_picker_reads_is_the_stores(self):
        c = self.answer["constants"]
        self.assertEqual(c["StateReadableFrom"], READABLE_FROM)
        self.assertLessEqual(c["StateReadableFrom"], SCHEMA_VERSION)
        self.assertEqual(c["StateSchemaSince"][0][1], SCHEMA_VERSION)
        # The first version whose store reads the mark: this one, which the plugin manifest names.
        version = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
        self.assertEqual(c["StateMarkSince"], "0.6.18")
        self.assertEqual(version.split("-")[0], c["StateMarkSince"])

    def verdicts(self, cases):
        start = CASES.index(cases[0])
        return dict(zip([made["entry"]["version"] for made, _ in cases],
                        self.answer["verdicts"][start:start + len(cases)]))

    def expected(self, cases):
        return {made["entry"]["version"]: answer for made, answer in cases}

    def test_today_schema_5_is_kept_and_4_or_3_converted_as_before(self):
        self.assertEqual(self.verdicts(TODAY), self.expected(TODAY))

    def test_a_later_schema_marked_readable_is_kept_only_where_the_mark_is_read(self):
        self.assertEqual(self.verdicts(READABLE), self.expected(READABLE))

    def test_a_later_schema_not_marked_readable_is_kept_nowhere_older(self):
        self.assertEqual(self.verdicts(UNREADABLE), self.expected(UNREADABLE))


if __name__ == "__main__":
    unittest.main()
