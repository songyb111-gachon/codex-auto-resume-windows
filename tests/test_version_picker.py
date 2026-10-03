r"""Install another version... in the bootstrap: the list a person picks from, and the pick (v0.6.12).

`-Versions` reads this repository's whole list of releases, page by page, through the one other
address api.github.com is allowed for (`release_pages`), and answers with a line per version and
edition - offered, with what picking it means, or refused, with why - and a last line saying what
they were judged against. A page that cannot be read lists nothing: `versions: unavailable`, exit
12. It installs nothing, and it never asks for the Codex compatibility data.

`-Pick <version> -Edition <edition> [-Force]` installs one row of it: -Force exactly when the row is
older or of the other edition, the list read again and the row still offered as it was shown, the
archive fetched and checked as every install's is - and only after it passed, under the install
lock, the state converted where the row says `convert3`, and then the archive's installer run. Each
answer is a `pick:` line; a refusal exits 15 and changes nothing.

The functions are lifted out of scripts/bootstrap.ps1 by the PowerShell parser and run with
`Invoke-WebRequest` and the registry replaced, as tests/test_prerelease_offer.py does: the reader
asks the network from a runspace of its own (Invoke-BoundedWebRequest), so the stand-in keeps what
it is told and what it was asked in files. The whole-script runs start a scratch copy of the plugin
(test_prerelease_offer.ScriptRun) with a scratch installation home and TEMP, the network a stub
that answers from files this test wrote, and the policy keys a stub too, so this machine's registry
is never read and a policy set here cannot change an answer. The copy's addresses point at a port
nothing listens on in case the stub were ever bypassed. In the pick's runs the copy's conversion and
its restart of the watcher are stand-ins too, which write down when they were asked and what was so
then; the conversion's own reading of downgrade-state's line is lifted and run on its own.
"""
from __future__ import annotations

import hashlib
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

from test_edition_bootstrap import archive, stub_installer  # noqa: E402
from test_prerelease_offer import LIST, NOWHERE, ScriptRun  # noqa: E402
from test_version_rule import ACCEPTED, REFUSED  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build"))
import legacy_bootstraps as legacy  # noqa: E402

BOOTSTRAP = ROOT / "scripts" / "bootstrap.ps1"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
RELEASE = json.loads((ROOT / "scripts" / "release.json").read_text(encoding="utf-8"))
STANDARD, ADVANCED = RELEASE["archive"], RELEASE["advanced"]["archive"]
PAGES = NOWHERE + "/pages?per_page=30&page={page}"
# The one value of managed.VALUES that guards a feature no older version has (v0.6.12's power
# action), so no older version could stop applying it: it never refuses an older row.
NEWER_ONLY = {"DisablePowerAction"}


def assets(version, editions=("standard", "advanced"), sums=True):
    """The file names a release of `version` carries: each edition's archive, and its .sha256."""
    names = []
    for edition in editions:
        name = (ADVANCED if edition == "advanced" else STANDARD).replace("{version}", version)
        names += [name] + ([name + ".sha256"] if sums else [])
    return names


def listed(value):
    """A list PowerShell handed back, which it may have made a single value of one."""
    return [value] if isinstance(value, str) else list(value)


def entry(version, prerelease=None, draft=False, files=None, **more):
    """One release as GitHub's list gives it, with the fields the reader looks at."""
    prerelease = "-" in version if prerelease is None else prerelease
    files = assets(version) if files is None else files
    return dict({"tag_name": "v" + version, "prerelease": prerelease, "draft": draft,
                 "assets": [{"name": name, "size": 1} for name in files]}, **more)


LIFT = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:CAR_BOOTSTRAP, [ref]$null, [ref]$errors)
if ($errors -and $errors.Count) { throw 'bootstrap.ps1 does not parse' }
$wanted = @('Get-FinalUri', 'Assert-TrustedHost', 'Invoke-BoundedWebRequest', 'Get-VersionParts',
            'Compare-ProductVersion', 'Format-UnreadVersion', 'Get-PrereleaseVersion', 'Get-ChosenVersion',
            'Read-ReleasesPage', 'Get-ReleasePages', 'Get-PolicyInForce', 'Get-SinceValue', 'Get-PinnedDigest',
            'Get-EditionRelease', 'Get-VersionVerdict', 'Get-VersionTable')
foreach ($node in $ast.FindAll({ param($n)
        $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    if ($wanted -contains $node.Name) { Invoke-Expression $node.Extent.Text }
}
foreach ($name in $wanted) {
    if (-not (Get-Command $name -CommandType Function -ErrorAction SilentlyContinue)) { throw ('bootstrap.ps1 has no ' + $name) }
}
$constants = @{}
foreach ($name in @('$ReleasesHosts', '$ReleasesMaxChars', '$ReleasesTimeoutMin', '$PickFloor', '$EditionsSince',
                    '$PolicySince', '$PolicyKeys', '$PolicyPath', '$PolicyValues', '$StateSchemaSince',
                    '$AdvancedStateSince', '$PickPageSize', '$PickMaxPages', '$PickBudgetSeconds', '$PickPageTimeoutMax',
                    '$PickNewerPrereleases', '$PickOlderPrereleases')) {
    $found = $ast.FindAll({ param($n)
        $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -eq $name }, $true)
    if (-not $found) { throw ('bootstrap.ps1 has no ' + $name) }
    Invoke-Expression $found[0].Extent.Text
    $constants[$name.Substring(1)] = (Get-Variable -Name $name.Substring(1)).Value
}
$cases = Get-Content -LiteralPath $env:CAR_CASES -Raw -Encoding UTF8 | ConvertFrom-Json
$Release = Get-Content -LiteralPath $env:CAR_RELEASE -Raw -Encoding UTF8 | ConvertFrom-Json
$out = [ordered]@{ constants = $constants }

# Get-ChosenVersion, over the version rule's cases: what it gives back, or THROWS.
$out.chosen = @(foreach ($text in $cases.chosen) {
    try { [string](Get-ChosenVersion ([string]$text)) } catch { 'THROWS' } })

# Get-ReleasePages, with the network a stand-in that answers each page from a folder of its own and
# writes down what it was asked. It runs in the reader's own runspace, which shares the environment.
$env:CAR_STUB_CALLS = Join-Path $env:CAR_WORK 'calls.txt'
$env:CAR_STUB_LARGE = [string]$ReleasesMaxChars
function Invoke-WebRequest {
    param([string]$Uri, [switch]$UseBasicParsing, [string]$Method, [int]$MaximumRedirection,
          [int]$TimeoutSec, [string]$OutFile, [switch]$PassThru)
    [IO.File]::AppendAllText($env:CAR_STUB_CALLS, (ConvertTo-Json -Compress @([string]$Method, $Uri, $MaximumRedirection,
                                                                             $TimeoutSec, [bool]$OutFile)) + "`n")
    $page = 'none'
    if ($Uri -match '[?&]page=([0-9]+)\z') { $page = $Matches[1] }
    $folder = Join-Path $env:CAR_STUB_PAGES $page
    if (-not (Test-Path -LiteralPath (Join-Path $folder 'mode'))) { throw 'the network is not there' }
    $mode = [IO.File]::ReadAllText((Join-Path $folder 'mode'))
    if ($mode -eq 'throw') { throw 'the network is not there' }
    $base = New-Object psobject
    $final = [IO.File]::ReadAllText((Join-Path $folder 'final'))
    if ($final) { $base | Add-Member -MemberType NoteProperty -Name ResponseUri -Value ([Uri]$final) }
    $response = New-Object psobject
    $response | Add-Member -MemberType NoteProperty -Name BaseResponse -Value $base
    if ($mode -eq 'large') {
        $response | Add-Member -MemberType NoteProperty -Name Content -Value ('[' + (' ' * [int]$env:CAR_STUB_LARGE) + ']')
    } elseif ($mode -eq 'body') {
        $response | Add-Member -MemberType NoteProperty -Name Content -Value ([IO.File]::ReadAllText((Join-Path $folder 'body')))
    }
    return $response
}
$out.pages = [ordered]@{}
foreach ($case in $cases.pages) {
    $env:CAR_STUB_PAGES = $case.folder
    [IO.File]::WriteAllText($env:CAR_STUB_CALLS, '')
    $answer = [ordered]@{}
    try {
        $read = Get-ReleasePages -Release $Release
        $answer.found = @($read | ForEach-Object {
            $_.Version + ' ' + ([string]$_.Prerelease).ToLower() + ' ' + (@($_.Assets) -join '|') })
    } catch { $answer.found = 'THROWS' }
    $answer.calls = @([IO.File]::ReadAllLines($env:CAR_STUB_CALLS) | Where-Object { $_ })
    $out.pages[$case.name] = $answer
}

# Get-PolicyInForce, with the registry a stand-in: each case says what each of the two keys is.
$script:asked = @()
function Get-Item {
    [CmdletBinding()]
    param([string]$LiteralPath)
    $script:asked += ,$LiteralPath
    $root = $LiteralPath.Substring('Registry::'.Length).Split('\')[0]
    $state = $null
    if ($script:policy.PSObject.Properties.Match($root).Count) { $state = $script:policy.$root }
    if ($null -eq $state) { throw (New-Object Management.Automation.ItemNotFoundException ('Cannot find path ' + $LiteralPath)) }
    if ($state -is [string] -and $state -eq 'unreadable') { throw (New-Object Security.SecurityException 'Requested registry access is not allowed.') }
    $key = New-Object psobject
    if ($state -is [string] -and $state -eq 'names-unreadable') {
        $key | Add-Member -MemberType ScriptMethod -Name GetValueNames -Value { throw 'access denied' }
    } else {
        $key | Add-Member -MemberType NoteProperty -Name Names -Value @($state)
        $key | Add-Member -MemberType ScriptMethod -Name GetValueNames -Value { return @($this.Names) }
    }
    return $key
}
$out.policy = @(foreach ($case in $cases.policy) {
    $script:policy = $case
    $script:asked = @()
    [ordered]@{ answer = [bool](Get-PolicyInForce); asked = @($script:asked) }
})
Remove-Item Function:\Get-Item

# Get-VersionVerdict, row by row, with the two I12 switches as each row sets them.
$out.verdicts = @(foreach ($case in $cases.verdicts) {
    $PickNewerPrereleases = [bool]$case.newer
    $PickOlderPrereleases = [bool]$case.older
    $listed = [pscustomobject]@{ Version = $case.entry.version; Prerelease = $case.entry.prerelease;
                                 Assets = @($case.entry.assets) }
    $row = Get-VersionVerdict -Entry $listed -Edition $case.edition -Installed $case.installed `
                              -InstalledEdition $case.installed_edition -Release $Release -Policy ([bool]$case.policy) `
                              -Offer $case.offer -Latest $case.latest
    if ($null -eq $row) { 'omitted' } else { $row.Answer + ' ' + $row.Detail }
})
$PickNewerPrereleases = $constants.PickNewerPrereleases
$PickOlderPrereleases = $constants.PickOlderPrereleases

# Get-VersionTable over a whole list, with the two I12 switches as each list sets them.
$out.tables = @(foreach ($case in $cases.tables) {
    $PickNewerPrereleases = [bool]$case.newer
    $PickOlderPrereleases = [bool]$case.older
    $listed = @(foreach ($item in $case.listed) {
        [pscustomobject]@{ Version = $item.version; Prerelease = $item.prerelease; Assets = @($item.assets) } })
    $table = Get-VersionTable -Listed $listed -Installed $case.installed -InstalledEdition $case.installed_edition `
                              -Release $Release -Policy ([bool]$case.policy)
    [ordered]@{ rows = @($table.Rows | ForEach-Object { $_.Version + ' ' + $_.Edition + ' ' + $_.Answer + ' ' + $_.Detail });
                latest = [string]$table.Latest; offer = [string]$table.Offer }
})
ConvertTo-Json -InputObject $out -Depth 8 -Compress
"""

# ------------------------------------------------------------------------------ the pages
GOOD_FINAL = LIST + "?per_page=30&page=%d"


def junk(count):
    """`count` entries the reader passes over, each in its own way, so a page is full without them."""
    shapes = [5, None, "v0.6.9", {"tag_name": "v0.6.9"}, entry("0.6.9", draft=True),
              entry("0.6.9-gamma"), entry("0.6.9", prerelease=True), entry("0.6.9-beta", prerelease=False)]
    return [shapes[index % len(shapes)] for index in range(count)]


# name -> the pages as (mode, body, final) by number from 1, and what Get-ReleasePages must give
# back: THROWS, or each kept entry as "version prerelease assets".
def kept(version, files=None):
    files = assets(version) if files is None else files
    return "%s %s %s" % (version, str("-" in version).lower(), "|".join(files))


PAGE_CASES = {
    "one_short_page": ([("body", [entry("0.6.11"), entry("0.6.12-beta")], None)],
                       [kept("0.6.11"), kept("0.6.12-beta")], 1),
    "an_empty_list": ([("body", [], None)], [], 1),
    "a_full_page_then_a_short_one": ([("body", junk(29) + [entry("0.6.11")], None),
                                      ("body", [entry("0.6.10")], None)],
                                     [kept("0.6.11"), kept("0.6.10")], 2),
    "a_full_page_then_an_empty_one": ([("body", junk(29) + [entry("0.6.11")], None), ("body", [], None)],
                                      [kept("0.6.11")], 2),
    # Five full pages may not be all of it: never a sixth asked for, and never a part of the list
    # taken for all of it, which would drop the oldest unsaid.
    "never_a_sixth_page": ([("body", junk(29) + [entry("0.6.%d" % number)], None) for number in range(2, 8)],
                           "THROWS", 5),
    "a_fifth_page_that_is_short": ([("body", junk(29) + [entry("0.6.%d" % number)], None) for number in range(2, 6)]
                                   + [("body", [entry("0.6.6")], None)],
                                   [kept("0.6.%d" % number) for number in range(2, 7)], 5),
    "a_page_that_fails": ([("body", junk(30), None), ("throw", None, None)], "THROWS", 2),
    "a_page_not_there": ([("body", junk(30), None)], "THROWS", 2),
    "another_host": ([("body", [entry("0.6.11")], "https://api.github.com.example.invalid/repos/%s/%s/releases"
                       % (RELEASE["owner"], RELEASE["repo"]))], "THROWS", 1),
    "the_download_host": ([("body", [entry("0.6.11")], "https://github.com/repos/%s/%s/releases"
                            % (RELEASE["owner"], RELEASE["repo"]))], "THROWS", 1),
    "another_repository": ([("body", [entry("0.6.11")], "https://api.github.com/repos/%s/some-fork/releases"
                             % RELEASE["owner"])], "THROWS", 1),
    "another_list": ([("body", [entry("0.6.11")], "https://api.github.com/repos/%s/%s/tags"
                       % (RELEASE["owner"], RELEASE["repo"]))], "THROWS", 1),
    "plain_http": ([("body", [entry("0.6.11")], "http://api.github.com/repos/%s/%s/releases"
                     % (RELEASE["owner"], RELEASE["repo"]))], "THROWS", 1),
    "nowhere_said": ([("body", [entry("0.6.11")], "")], "THROWS", 1),
    "a_later_page_elsewhere": ([("body", junk(30), None), ("body", [entry("0.6.11")], "https://api.github.com/"
                                "repos/someone-else/%s/releases" % RELEASE["repo"])], "THROWS", 2),
    "too_large": ([("large", None, None)], "THROWS", 1),
    "not_a_list": ([("body", {"message": "API rate limit exceeded"}, None)], "THROWS", 1),
    "not_json": ([("raw", "<html>", None)], "THROWS", 1),
    "no_body": ([("nobody", None, None)], "THROWS", 1),
    "entries_it_passes_over": ([("body", [
        entry("0.6.11", draft=True), entry("0.6.11-beta", prerelease=False), entry("0.6.10", prerelease=True),
        entry("0.6.9", draft="false"), entry("0.6.9-beta", prerelease="true"),
        {"tag_name": "v0.6.8", "prerelease": False, "draft": False},
        {"tag_name": "v0.6.8", "prerelease": False, "draft": False, "assets": "CodexAutoResume-v0.6.8-win-x64.zip"},
        {"tag_name": "v0.6.8", "prerelease": False, "draft": False, "assets": None},
        entry("0.6.7", tag_name="0.6.7"), entry("0.6.7", tag_name="V0.6.7"), entry("0.6.7", tag_name="v0.6.07"),
        entry("0.6.7", tag_name="v0.6.7 "), entry("0.6.7", tag_name="v0.6.7-rc1"), entry("0.6.7", tag_name=7),
        entry("0.6.12-beta.2"), entry("0.6.12-beta.2", files=["another.zip"]),
        {"tag_name": "v0.6.6", "prerelease": False, "draft": False,
         "assets": [{"name": "CodexAutoResume-v0.6.6-win-x64.zip"}, {"name": 5}, {"size": 1}, "x", None]},
        entry("0.6.5", files=[])], None)],
        [kept("0.6.12-beta.2"), kept("0.6.6", ["CodexAutoResume-v0.6.6-win-x64.zip"]), kept("0.6.5", [])], 1),
}

# ------------------------------------------------------------------------------ the policy
HKLM, HKCU = "HKEY_LOCAL_MACHINE", "HKEY_CURRENT_USER"
SIX = ["DisableAutoResume", "ForceObserveOnly", "DisableUpdateCheck", "DisableStatusFile",
       "MaxRecoveryAttempts", "QuietHours"]
POLICY_CASES = ([({}, False), ({HKLM: [], HKCU: []}, False), ({HKCU: ["Something", "DisablePowerAction"]}, False),
                 ({HKLM: "unreadable"}, True), ({HKCU: "unreadable"}, True), ({HKCU: "names-unreadable"}, True),
                 ({HKLM: ["quiethours"]}, True)]
                + [({root: [name]}, True) for root in (HKLM, HKCU) for name in SIX])

# ------------------------------------------------------------------------------ the rows
# (the entry, its edition, installed, installed edition, policy, offer, latest, newer, older) -> answer
INSTALLED = "0.6.12-beta"


def row(version, expected, edition="standard", installed=INSTALLED, installed_edition="standard", policy=False,
        offer=None, latest="0.6.11", newer=False, older=False, files=None, prerelease=None):
    made = entry(version, prerelease=prerelease, files=files)
    return ({"entry": {"version": version, "prerelease": made["prerelease"],
                       "assets": [item["name"] for item in made["assets"]]},
             "edition": edition, "installed": installed, "installed_edition": installed_edition, "policy": policy,
             "offer": offer, "latest": latest, "newer": newer, "older": older}, expected)


VERDICT_CASES = [
    # Below the floor, and the advanced edition before it existed: not shown at all.
    row("0.6.1", "omitted"), row("0.5.7", "omitted"), row("0.6.10", "omitted", edition="advanced"),
    row("0.6.6-beta", "omitted", edition="advanced"),
    row("0.6.2", "offered older,release,convert3"),
    row(INSTALLED, "installed -"),
    # The version installed, in the other edition: no offer the update check makes, so I12 as written
    # greys it, and as amended it is offered.
    row(INSTALLED, "refused not-offered", edition="advanced"),
    row(INSTALLED, "refused not-offered", edition="advanced", offer="0.6.12-beta.2"),
    row(INSTALLED, "offered same,prerelease,kept,edition", edition="advanced", newer=True),
    # v0.6.6-alpha and -beta carry v0.6.6's file names.
    row("0.6.6-alpha", "refused no-archive", files=assets("0.6.6"), older=True),
    row("0.6.11", "refused no-archive", edition="advanced", files=assets("0.6.11", ("standard",))),
    # No pin and no published checksum; a pinned release needs none.
    row("0.6.12-beta.2", "refused no-checksum", files=assets("0.6.12-beta.2", sums=False), offer="0.6.12-beta.2"),
    row("0.6.11", "offered older,release,kept,latest", files=assets("0.6.11", sums=False)),
    row("0.6.11", "offered older,release,kept,latest,edition", edition="advanced", files=assets("0.6.11", sums=False)),
    # An edition change to an installer that predates editions.
    row("0.6.10", "refused edition-first", installed_edition="advanced"),
    row("0.6.2", "refused edition-first", installed_edition="advanced"),
    row("0.6.11-alpha", "offered older,prerelease,convert3,edition,advanced-off", edition="advanced", older=True),
    # A policy in force: nothing below v0.6.11-beta, and only then.
    row("0.6.10", "refused managed-policy", policy=True), row("0.6.2", "refused managed-policy", policy=True),
    row("0.6.11-alpha", "refused managed-policy", policy=True, older=True),
    row("0.6.11-beta", "offered older,prerelease,kept", policy=True, older=True),
    row("0.6.11", "offered older,release,kept,latest", policy=True),
    row("0.6.10", "offered older,release,convert3"),
    # I12 as written (both switches off): no older pre-release, and of the newer ones only the update
    # check's own offer. As amended (both on), every one of them is offered.
    row("0.6.11-beta.3", "refused older-prerelease"),
    row("0.6.11-beta.3", "offered older,prerelease,kept", older=True),
    row("0.6.12-beta.2", "refused not-offered", latest="0.6.12"),
    row("0.6.12-beta.2", "offered newer,prerelease,kept", latest="0.6.12", newer=True),
    row("0.6.12", "offered newer,release,kept,latest", latest="0.6.12"),
    row("0.6.12-beta.2", "offered newer,prerelease,kept", offer="0.6.12-beta.2"),
    row("0.6.12-beta.2", "refused not-offered", edition="advanced", offer="0.6.12-beta.2"),
    row("0.6.12-beta.3", "refused not-offered", offer="0.6.12-beta.2"),
    row("0.6.12-beta.3", "offered newer,prerelease,kept", offer="0.6.12-beta.2", newer=True),
    row("0.6.12-beta.2", "offered newer,prerelease,kept,edition", edition="advanced", offer="0.6.12-beta.2",
        newer=True),
    # The schema: converted for 0.6.0 to 0.6.11-alpha, kept from 0.6.11-beta.
    row("0.6.9", "offered older,release,convert3"),
    row("0.6.11-alpha.2", "offered older,prerelease,convert3", older=True),
    row("0.6.11-beta", "offered older,prerelease,kept", older=True),
    # The advanced settings: an advanced target before 0.6.11-beta.2 cannot read them.
    row("0.6.11-beta", "offered older,prerelease,kept,advanced-off", edition="advanced",
        installed_edition="advanced", older=True),
    row("0.6.11-beta.2", "offered older,prerelease,kept", edition="advanced", installed_edition="advanced",
        older=True),
    row("0.6.13", "offered newer,release,kept,edition", edition="advanced", latest="0.6.14"),
]

TABLE_CASES = [
    # The installed-0.6.12-beta case under I12 as written: the check offers 0.6.12 alone, so neither
    # 0.6.12-beta.2 nor 0.6.12-beta in the other edition is offered.
    ({"listed": [{"version": v, "prerelease": "-" in v, "assets": assets(v)}
                 for v in ("0.6.12-beta.2", "0.6.12", "0.6.11", INSTALLED)],
      "installed": INSTALLED, "installed_edition": "standard", "policy": False, "newer": False, "older": False},
     {"rows": ["0.6.12 standard offered newer,release,kept,latest",
               "0.6.12 advanced offered newer,release,kept,latest,edition",
               "0.6.12-beta.2 standard refused not-offered", "0.6.12-beta.2 advanced refused not-offered",
               "0.6.12-beta standard installed -", "0.6.12-beta advanced refused not-offered",
               "0.6.11 standard offered older,release,kept", "0.6.11 advanced offered older,release,kept,edition"],
      "latest": "0.6.12", "offer": ""}),
    # The same list under I12 as amended: every pre-release is offered, the one installed in the other
    # edition too.
    ({"listed": [{"version": v, "prerelease": "-" in v, "assets": assets(v)}
                 for v in ("0.6.12-beta.2", "0.6.12", "0.6.11", "0.6.11-beta.3", INSTALLED)],
      "installed": INSTALLED, "installed_edition": "standard", "policy": False, "newer": True, "older": True},
     {"rows": ["0.6.12 standard offered newer,release,kept,latest",
               "0.6.12 advanced offered newer,release,kept,latest,edition",
               "0.6.12-beta.2 standard offered newer,prerelease,kept",
               "0.6.12-beta.2 advanced offered newer,prerelease,kept,edition",
               "0.6.12-beta standard installed -", "0.6.12-beta advanced offered same,prerelease,kept,edition",
               "0.6.11 standard offered older,release,kept", "0.6.11 advanced offered older,release,kept,edition",
               "0.6.11-beta.3 standard offered older,prerelease,kept",
               "0.6.11-beta.3 advanced offered older,prerelease,kept,edition"],
      "latest": "0.6.12", "offer": ""}),
    # Newest first by the numbers (.10 after .9), the installed edition first at each version, and the
    # check's own offer: the newest pre-release newer than both.
    ({"listed": [{"version": v, "prerelease": "-" in v, "assets": assets(v)}
                 for v in ("0.6.9", "0.6.10", "0.6.12-beta.9", "0.6.12-beta.10", "0.6.11")],
      "installed": "0.6.11", "installed_edition": "advanced", "policy": False, "newer": False, "older": False},
     {"rows": ["0.6.12-beta.10 advanced offered newer,prerelease,kept",
               "0.6.12-beta.10 standard refused not-offered",
               "0.6.12-beta.9 advanced refused not-offered", "0.6.12-beta.9 standard refused not-offered",
               "0.6.11 advanced installed -", "0.6.11 standard offered same,release,kept,latest,edition",
               "0.6.10 standard refused edition-first", "0.6.9 standard refused edition-first"],
      "latest": "0.6.11", "offer": "0.6.12-beta.10"}),
]


@unittest.skipUnless(POWERSHELL.is_file(), "the bootstrap is PowerShell on Windows")
class ListingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory()
        cls.folder = folder
        work = Path(folder.name)
        release = dict(RELEASE, release_pages=PAGES)
        (work / "release.json").write_text(json.dumps(release), encoding="utf-8")
        pages = []
        for name, (served, _, _) in PAGE_CASES.items():
            for number, (mode, body, final) in enumerate(served, start=1):
                page = work / "pages" / name / str(number)
                page.mkdir(parents=True)
                (page / "mode").write_text("body" if mode == "raw" else mode, encoding="utf-8")
                (page / "final").write_text(GOOD_FINAL % number if final is None else final, encoding="utf-8")
                if mode in ("body", "raw"):
                    (page / "body").write_text(body if mode == "raw" else json.dumps(body), encoding="utf-8")
            pages.append({"name": name, "folder": str(work / "pages" / name)})
        cases = {"chosen": ACCEPTED + REFUSED + ["01.2.3", "1.02.3", "1.2.03", "1.2.3.", "1234567.0.0"],
                 "pages": pages, "policy": [case for case, _ in POLICY_CASES],
                 "verdicts": [case for case, _ in VERDICT_CASES], "tables": [case for case, _ in TABLE_CASES]}
        (work / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", LIFT],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
                              env=dict(os.environ, CAR_BOOTSTRAP=str(BOOTSTRAP), CAR_CASES=str(work / "cases.json"),
                                       CAR_RELEASE=str(work / "release.json"), CAR_WORK=str(work)))
        cls.done = done
        cls.cases = cases
        cls.answer = json.loads(done.stdout) if done.returncode == 0 and done.stdout.strip() else None

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if self.answer is None:
            self.fail("the probe did not run: " + (self.done.stderr or self.done.stdout)[-3000:])

    def test_a_chosen_version_is_exactly_the_rule_rebuilt(self):
        """Releases and pre-releases alike, and given back exactly as they came: a leading zero is a
        tag this product never makes."""
        for text, answer in zip(self.cases["chosen"], self.answer["chosen"]):
            with self.subTest(ascii(text)):
                self.assertEqual(answer, text if text in ACCEPTED else "THROWS")

    def test_the_pages_are_read_until_a_short_one_and_never_a_sixth(self):
        for name, (_, expected, asked) in PAGE_CASES.items():
            with self.subTest(name):
                answer = self.answer["pages"][name]
                found = answer["found"]
                self.assertEqual(found if found == "THROWS" else list(found), expected)
                calls = [json.loads(call) for call in listed(answer["calls"])]
                self.assertEqual([call[1] for call in calls],
                                 [PAGES.replace("{page}", str(page)) for page in range(1, asked + 1)])

    def test_each_page_is_one_get_with_no_redirect_followed_inside_the_budget(self):
        c = self.answer["constants"]
        self.assertEqual((c["PickPageSize"], c["PickMaxPages"], c["PickBudgetSeconds"], c["PickPageTimeoutMax"]),
                         (30, 5, 150, 30))
        for name in PAGE_CASES:
            for call in listed(self.answer["pages"][name]["calls"]):
                method, _, redirects, seconds, to_file = json.loads(call)
                with self.subTest(name):
                    self.assertEqual((method, redirects, to_file), ("Get", 0, False))
                    self.assertGreaterEqual(seconds, c["ReleasesTimeoutMin"])
                    self.assertLessEqual(seconds, c["PickPageTimeoutMax"])
        self.assertLessEqual(c["PickMaxPages"] * c["PickPageTimeoutMax"], c["PickBudgetSeconds"],
                             "a list that cannot be read is said within the window's wait")

    def test_the_policy_is_any_of_its_values_under_either_key_or_a_key_that_cannot_be_read(self):
        for (case, expected), answer in zip(POLICY_CASES, self.answer["policy"]):
            with self.subTest(case=case):
                self.assertEqual(answer["answer"], expected)
                asked = listed(answer["asked"])
                # Both keys, until one of them answers yes.
                self.assertEqual(asked[0], "Registry::HKEY_LOCAL_MACHINE\\Software\\Policies\\CodexAutoResume")
                if not expected:
                    self.assertEqual(asked, ["Registry::%s\\Software\\Policies\\CodexAutoResume" % root
                                             for root in (HKLM, HKCU)])

    def test_each_row_says_the_first_thing_that_applies(self):
        for (case, expected), answer in zip(VERDICT_CASES, self.answer["verdicts"]):
            with self.subTest(version=case["entry"]["version"], edition=case["edition"], expected=expected):
                self.assertEqual(answer, expected)

    def test_the_table_is_newest_first_with_the_checks_own_offer(self):
        for (case, expected), answer in zip(TABLE_CASES, self.answer["tables"]):
            with self.subTest(installed=case["installed"]):
                self.assertEqual(dict(answer, rows=list(answer["rows"])), expected)

    def test_the_policy_values_are_the_ones_an_older_version_would_drop(self):
        """managed.VALUES, less a value that guards a feature no older version has: it holds both before
        and after such a value is added there."""
        from codex_auto_resume import managed
        values = self.answer["constants"]["PolicyValues"]
        self.assertEqual(values, [name for name in managed.VALUES if name not in NEWER_ONLY])
        self.assertEqual(values, SIX)
        self.assertEqual(self.answer["constants"]["PolicyPath"], managed.KEY)
        self.assertEqual(self.answer["constants"]["PolicyKeys"], [HKLM, HKCU])

    def test_the_versions_it_is_judged_by(self):
        c = self.answer["constants"]
        self.assertEqual((c["PickFloor"], c["EditionsSince"], c["PolicySince"]), ("0.6.2", "0.6.11-alpha", "0.6.11-beta"))
        self.assertEqual(c["EditionsSince"], RELEASE["advanced"]["since"] + "-alpha")
        from codex_auto_resume.store import SCHEMA_VERSION
        self.assertEqual(c["StateSchemaSince"], [["0.6.11-beta", 4], ["0.6.0", 3]])
        self.assertEqual(c["StateSchemaSince"][0][1], SCHEMA_VERSION, "the first row is this version's own schema")
        self.assertEqual(c["AdvancedStateSince"], [["0.6.11-beta.2", 2], ["0.6.11-alpha", 1]])
        # I12 as the owner amended it on 2026-10-03 (design Q1): a pre-release picked by name and
        # confirmed, older or newer, as a release is.
        self.assertEqual((c["PickNewerPrereleases"], c["PickOlderPrereleases"]), (True, True))


class PolicySinceTests(unittest.TestCase):
    """$PolicySince is the first release with the policy keys: every release before it would stop
    applying one. Read from the tags; skipped where they are not in the checkout, a failure on CI."""

    def test_it_is_the_first_tag_with_managed_py(self):
        text = BOOTSTRAP.read_text(encoding="utf-8")
        since = re.search(r"^\$PolicySince = '([^']+)'$", text, re.M).group(1)
        listed = subprocess.run(["git", "-C", str(ROOT), "tag", "--list", "v*"], capture_output=True, text=True,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.split()
        tags = []
        for tag in listed:
            try:
                tags.append((legacy.order(tag[1:]), tag))
            except ValueError:
                continue
        if "v" + since not in listed:
            if os.environ.get("CI"):
                self.fail("v%s is not in this checkout; CI must fetch the tags" % since)
            self.skipTest("the tags are not in this checkout")
        with_policy = [tag for _, tag in sorted(tags) if subprocess.run(
            ["git", "-C", str(ROOT), "cat-file", "-e", "%s:src/codex_auto_resume/managed.py" % tag],
            capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).returncode == 0]
        self.assertEqual(with_policy[0], "v" + since)


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.text = BOOTSTRAP.read_text(encoding="utf-8")

    def block(self, start):
        first = self.text.index(start)
        return self.text[first:self.text.index("\n}\n", first)]

    def test_the_policy_is_read_and_never_written(self):
        reader = self.block("function Get-PolicyInForce")
        for written in ("Set-Item", "New-Item", "Remove-Item", "Set-ItemProperty", "New-ItemProperty",
                        "Remove-ItemProperty", "Clear-Item", "Rename-Item", "Copy-Item", "Move-Item",
                        "SetValue", "DeleteValue", "CreateSubKey", "GetValue("):
            self.assertNotIn(written, reader, written)
        self.assertIn("GetValueNames()", reader)
        # The bootstrap's one registry access, through the provider and nowhere else.
        self.assertEqual(self.text.count("'Registry::'"), 1)
        self.assertNotIn("Microsoft.Win32", self.text)
        self.assertNotRegex(self.text, r"(?i)\bHK(LM|CU):")

    def test_the_list_is_read_only_by_the_listing_and_the_pick(self):
        """No timer, no check on the way to anything else: -Versions, and -Pick before it installs."""
        calls = re.findall(r"Get-ReleasePages -Release \$release", self.text)
        self.assertEqual(len(calls), 2)
        pick = self.text[self.text.index("if ($Pick) {\n    if ($CheckOnly"):]
        self.assertIn("Get-ReleasePages -Release $release", pick[:pick.index("\n}\n")])
        listing = self.text[self.text.index("if ($Versions) {"):]
        listing = listing[:listing.index("\n}\n")]
        self.assertIn("Get-ReleasePages -Release $release", listing)
        self.assertNotIn("Update-CompatibilityData", listing)
        self.assertNotIn("Get-Remote", listing)
        self.assertNotIn("Invoke-WebRequest", listing)
        # Both readers of the list check one page the same way.
        self.assertEqual(len(re.findall(r"Read-ReleasesPage -Release", self.text)), 2)


@unittest.skipUnless(POWERSHELL.is_file(), "the bootstrap is PowerShell on Windows")
class PickerRun(ScriptRun):
    """ScriptRun's scratch plugin, home and TEMP, with the list served page by page and the policy keys
    a stand-in: the network and the registry this test wrote, and nothing of this machine's."""

    RUN = r"""
function global:Invoke-WebRequest {
    param([string]$Uri, [string]$OutFile, [switch]$UseBasicParsing, [switch]$PassThru,
          [int]$MaximumRedirection, [int]$TimeoutSec, [string]$Method)
    Add-Content -LiteralPath $env:CAR_REQUESTS -Value (([string]$Method) + ' ' + $Uri) -Encoding UTF8
    $base = New-Object psobject
    $response = New-Object psobject
    $page = $null
    if ($Uri -match '[?&]page=([0-9]+)\z') { $page = Join-Path $env:CAR_PAGES ($Matches[1] + '.json') }
    if ($Method -eq 'Get' -and $page -and (Test-Path -LiteralPath $page)) {
        $base | Add-Member -MemberType NoteProperty -Name ResponseUri -Value ([Uri]($env:CAR_PAGE_FINAL + $Matches[1]))
        $response | Add-Member -MemberType NoteProperty -Name Content -Value ([IO.File]::ReadAllText($page))
    } elseif ($OutFile -and $env:CAR_ZIP -and $Uri.EndsWith('.zip')) {
        Copy-Item -LiteralPath $env:CAR_ZIP -Destination $OutFile
        $base | Add-Member -MemberType NoteProperty -Name ResponseUri -Value ([Uri]'https://release-assets.githubusercontent.com/a')
    } elseif ($OutFile -and $env:CAR_SUM -and $Uri.EndsWith('.zip.sha256')) {
        Copy-Item -LiteralPath $env:CAR_SUM -Destination $OutFile
        $base | Add-Member -MemberType NoteProperty -Name ResponseUri -Value ([Uri]'https://release-assets.githubusercontent.com/b')
    } else {
        throw 'there is no network here'
    }
    $response | Add-Member -MemberType NoteProperty -Name BaseResponse -Value $base
    return $response
}
# The policy keys: what this test wrote, never this machine's.
function global:Get-Item {
    [CmdletBinding()]
    param([string]$LiteralPath, [string]$Path)
    if (-not $LiteralPath.StartsWith('Registry::')) { return Microsoft.PowerShell.Management\Get-Item @PSBoundParameters }
    Add-Content -LiteralPath $env:CAR_REQUESTS -Value ('Registry ' + $LiteralPath) -Encoding UTF8
    $policy = ConvertFrom-Json $env:CAR_POLICY
    $root = $LiteralPath.Substring('Registry::'.Length).Split('\')[0]
    if (-not $policy.PSObject.Properties.Match($root).Count) {
        throw (New-Object Management.Automation.ItemNotFoundException ('Cannot find path ' + $LiteralPath))
    }
    $key = New-Object psobject
    $key | Add-Member -MemberType NoteProperty -Name Names -Value @($policy.$root)
    $key | Add-Member -MemberType ScriptMethod -Name GetValueNames -Value { return @($this.Names) }
    return $key
}
$arguments = @{}
foreach ($pair in (ConvertFrom-Json $env:CAR_ARGUMENTS).PSObject.Properties) {
    $arguments[$pair.Name] = $pair.Value
}
& $env:CAR_SCRIPT @arguments
exit $LASTEXITCODE
"""

    def setUp(self):
        super().setUp()
        written = self.plugin / "scripts" / "release.json"
        release = json.loads(written.read_text(encoding="utf-8"))
        written.write_text(json.dumps(dict(release, release_pages=PAGES)), encoding="utf-8")
        self.pages = self.root / "pages"
        self.pages.mkdir()

    def serve(self, *pages):
        for old in self.pages.glob("*.json"):
            old.unlink()
        for number, listed in enumerate(pages, start=1):
            (self.pages / ("%d.json" % number)).write_text(json.dumps(listed), encoding="utf-8")

    def run_it(self, policy=None, more=None, **arguments):
        self.requests.unlink(missing_ok=True)
        environment = dict(os.environ, **(more or {}))
        environment.update(CODEX_AUTO_RESUME_PLUGIN_HOME=str(self.home),
                           TEMP=str(self.temp), TMP=str(self.temp),
                           CAR_SCRIPT=str(self.plugin / "scripts" / "bootstrap.ps1"),
                           CAR_ARGUMENTS=json.dumps(arguments), CAR_REQUESTS=str(self.requests),
                           CAR_INSTALLED=str(self.installed), CAR_PAGES=str(self.pages),
                           CAR_PAGE_FINAL=LIST + "?per_page=30&page=", CAR_POLICY=json.dumps(policy or {}),
                           CAR_ZIP=str(self.zip or ""), CAR_SUM=str(self.sum or ""))
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                               "Bypass", "-Command", self.RUN],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                              errors="replace", timeout=300, env=environment)
        asked = []
        if self.requests.is_file():
            asked = [line.split(" ", 1) for line in
                     self.requests.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
        return done.returncode, done.stdout, asked

    @staticmethod
    def answer_lines(output, prefix):
        return [line for line in output.splitlines() if line.startswith(prefix)]


LISTED = [entry("0.6.12-beta.2"), entry(INSTALLED), entry("0.6.11", files=assets("0.6.11", sums=False)),
          entry("0.6.11-beta"), entry("0.6.10", files=assets("0.6.10", ("standard",))),
          entry("0.6.6-alpha", files=assets("0.6.6")), entry("0.6.2", files=assets("0.6.2", ("standard",), False)),
          entry("0.6.1", files=assets("0.6.1", ("standard",))), entry("0.5.7", files=assets("0.5.7", ("standard",)))]
ROWS = ["version: 0.6.12-beta.2 standard offered newer,prerelease,kept",
        "version: 0.6.12-beta.2 advanced offered newer,prerelease,kept,edition",
        "version: 0.6.12-beta standard installed -",
        "version: 0.6.12-beta advanced offered same,prerelease,kept,edition",
        "version: 0.6.11 standard offered older,release,kept,latest",
        "version: 0.6.11 advanced offered older,release,kept,latest,edition",
        "version: 0.6.11-beta standard offered older,prerelease,kept",
        "version: 0.6.11-beta advanced offered older,prerelease,kept,edition,advanced-off",
        "version: 0.6.10 standard offered older,release,convert3",
        "version: 0.6.6-alpha standard refused no-archive",
        "version: 0.6.2 standard offered older,release,convert3"]
POLICY_READS = [["Registry", "Registry::HKEY_LOCAL_MACHINE\\Software\\Policies\\CodexAutoResume"],
              ["Registry", "Registry::HKEY_CURRENT_USER\\Software\\Policies\\CodexAutoResume"]]


class VersionsRunTests(PickerRun):
    """-Versions, the whole script."""

    def test_it_lists_every_row_and_what_they_were_judged_against(self):
        self.installation(INSTALLED)
        self.serve(LISTED)
        code, output, asked = self.run_it(Versions=True)
        self.assertEqual(code, 0, output[-2000:])
        self.assertEqual(self.answer_lines(output, "version: "), ROWS)
        self.assertEqual(self.answer_lines(output, "versions: "),
                         ["versions: listed 0.6.12-beta standard 0.6.11 v0.6.2 v0.6.11-alpha"])
        self.assertLess(output.index("version: "), output.index("versions: listed"))
        self.assertEqual(asked, [["Get", PAGES.replace("{page}", "1")]] + POLICY_READS,
                         "one page and the two policy keys, and nothing else asked")
        self.assertNotIn("compatibility:", output)
        self.assertEqual(sorted(self.temp.glob("codex-auto-resume-*")), [])

    def test_a_policy_refuses_every_row_before_it_and_nothing_else(self):
        self.installation(INSTALLED)
        self.serve(LISTED)
        for policy in ({HKLM: ["QuietHours"]}, {HKCU: ["DisableUpdateCheck", "Other"]}):
            with self.subTest(policy=policy):
                code, output, asked = self.run_it(policy=policy, Versions=True)
                self.assertEqual(code, 0, output[-2000:])
                expected = [line.replace("offered older,release,convert3", "refused managed-policy")
                            for line in ROWS]
                self.assertEqual(self.answer_lines(output, "version: "), expected)

    def test_a_value_only_a_newer_version_knows_refuses_nothing(self):
        self.installation(INSTALLED)
        self.serve(LISTED)
        code, output, asked = self.run_it(policy={HKCU: ["DisablePowerAction"]}, Versions=True)
        self.assertEqual(code, 0, output[-2000:])
        self.assertEqual(self.answer_lines(output, "version: "), ROWS)
        self.assertEqual(asked, [["Get", PAGES.replace("{page}", "1")]] + POLICY_READS)

    def test_the_pages_are_read_until_a_short_one(self):
        self.installation(INSTALLED)
        self.serve(junk(30), LISTED)
        code, output, asked = self.run_it(Versions=True)
        self.assertEqual(code, 0, output[-2000:])
        self.assertEqual(self.answer_lines(output, "version: "), ROWS)
        self.assertEqual([request[1] for request in asked if request[0] == "Get"],
                         [PAGES.replace("{page}", "1"), PAGES.replace("{page}", "2")])

    def test_a_list_that_could_not_be_read_lists_nothing(self):
        self.installation(INSTALLED)
        for pages in ((), (junk(30),), ({"message": "API rate limit exceeded"},)):
            with self.subTest(pages=len(pages)):
                self.serve(*pages)
                code, output, asked = self.run_it(Versions=True)
                self.assertEqual(code, 12, output[-2000:])
                self.assertEqual(self.answer_lines(output, "versions: "), ["versions: unavailable"])
                self.assertEqual(self.answer_lines(output, "version: "), [])
                self.assertTrue(all(request[0] == "Get" for request in asked), asked)
                self.assertNotIn("compatibility:", output)

    def test_a_list_that_goes_on_past_five_pages_lists_nothing(self):
        """Five full pages may not be all of it: a sixth is never asked for, and the part read is never
        shown as the whole list, which would leave the oldest releases out unsaid."""
        self.installation(INSTALLED)
        self.serve(*([junk(30)] * 4 + [junk(30 - len(LISTED)) + LISTED]))
        code, output, asked = self.run_it(Versions=True)
        self.assertEqual(code, 12, output[-2000:])
        self.assertEqual(self.answer_lines(output, "versions: "), ["versions: unavailable"])
        self.assertEqual(self.answer_lines(output, "version: "), [])
        self.assertEqual([request[1] for request in asked if request[0] == "Get"],
                         [PAGES.replace("{page}", str(page)) for page in range(1, 6)])

    def test_without_an_installation_it_can_read_nothing_is_asked(self):
        self.serve(LISTED)
        for installed in (None, "0.6.12-gamma"):
            with self.subTest(installed=installed):
                shutil.rmtree(self.home, ignore_errors=True)
                if installed:
                    self.installation(installed)
                code, output, asked = self.run_it(Versions=True)
                self.assertEqual(code, 12, output[-2000:])
                self.assertEqual(self.answer_lines(output, "versions: "), ["versions: unavailable"])
                self.assertEqual(asked, [])

    def test_it_goes_with_nothing_else(self):
        self.installation(INSTALLED)
        self.serve(LISTED)
        for more in ({"CheckOnly": True}, {"Update": True}, {"ArchivePath": str(self.root / "x.zip")},
                     {"Compatibility": True}, {"Version": "0.6.12-beta.2"}, {"Edition": "Advanced"},
                     {"Force": True}):
            with self.subTest(more=more):
                before = self.listing()
                code, output, asked = self.run_it(**dict(more, Versions=True))
                self.assertEqual(code, 12, output[-2000:])
                self.assertEqual(self.answer_lines(output, "versions: "), ["versions: unavailable"])
                self.assertEqual(asked, [])
                self.assertEqual(self.listing(), before)


# ------------------------------------------------------------------------------ the pick
CONVERSION = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:CAR_BOOTSTRAP, [ref]$null, [ref]$errors)
if ($errors -and $errors.Count) { throw 'bootstrap.ps1 does not parse' }
foreach ($node in $ast.FindAll({ param($n)
        $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    if (@('Convert-StateForOlder', 'Start-CurrentWatcher') -contains $node.Name) { Invoke-Expression $node.Extent.Text }
}
# The installed version's plugin_setup.py: what each case says it printed, and the code it exited with.
function Invoke-InstalledSetup {
    param([string]$Home_, [string[]]$Arguments)
    $script:asked += ,(@($Home_) + $Arguments)
    return [pscustomobject]@{ Printed = @($script:case.printed | ForEach-Object { [string]$_ }); Code = [int]$script:case.code }
}
$cases = Get-Content -LiteralPath $env:CAR_CASES -Raw -Encoding UTF8 | ConvertFrom-Json
$answers = @(foreach ($case in $cases) {
    $script:case = $case
    $script:asked = @()
    $answer = Convert-StateForOlder -Home_ 'C:\scratch-home'
    [ordered]@{ answer = $answer; asked = @($script:asked | ForEach-Object { $_ -join ' ' }) }
})
$script:case = [pscustomobject]@{ printed = @(); code = 0 }
$script:asked = @()
Start-CurrentWatcher -Home_ 'C:\scratch-home'
Start-CurrentWatcher -Home_ 'C:\scratch-home' -NoStartup
ConvertTo-Json -Compress -Depth 5 -InputObject ([ordered]@{ answers = $answers;
                                                            restarts = @($script:asked | ForEach-Object { $_ -join ' ' }) })
"""

# What downgrade-state --stop-watcher printed and exited with -> what the conversion makes of it.
CONVERSION_CASES = [
    ((["downgrade: converted 30 5 2 1 0"], 0), "converted 30 5 2 1 0"),
    ((["a line of its own", "downgrade: converted 7 0 0 0 1", ""], 0), "converted 7 0 0 0 1"),
    ((["downgrade: nothing"], 0), "nothing"),
    ((["downgrade: watcher-running"], 3), "watcher-running"),
    ((["downgrade: failed"], 1), "failed"),
    # A line and a code that disagree, no line, two lines, or a line outside its grammar: failed.
    ((["downgrade: converted 30 5 2 1 0"], 1), "failed"),
    ((["downgrade: converted 30 5 2 1 0"], 3), "failed"),
    ((["downgrade: nothing"], 3), "failed"),
    ((["downgrade: watcher-running"], 0), "failed"),
    ((["downgrade: watcher-running"], 1), "failed"),
    (([], 0), "failed"),
    ((["error: Cannot open valid auto-resume state"], 1), "failed"),
    ((["downgrade: nothing", "downgrade: nothing"], 0), "failed"),
    ((["downgrade: converted 30 5 2 1"], 0), "failed"),
    ((["downgrade: converted 30 5 2 1 2"], 0), "failed"),
    ((["downgrade: converted 30 5 2 1 0 9"], 0), "failed"),
    ((["downgrade: converted -1 5 2 1 0"], 0), "failed"),
    ((["downgrade: converted 30 5 2 1 0 "], 0), "failed"),
    ((["downgrade: Converted 30 5 2 1 0"], 0), "failed"),
    ((["downgrade: converted 3x 5 2 1 0"], 0), "failed"),
    ((["downgrade: converted \uff13 5 2 1 0"], 0), "failed"),
]


@unittest.skipUnless(POWERSHELL.is_file(), "the bootstrap is PowerShell on Windows")
class ConversionAnswerTests(unittest.TestCase):
    """Convert-StateForOlder runs the installed version's own downgrade-state --to 3 --stop-watcher and
    holds its one line to its exit code; Start-CurrentWatcher runs that version's setup --keep-state."""

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as folder:
            cases = Path(folder) / "cases.json"
            cases.write_text(json.dumps([{"printed": printed, "code": code}
                                         for (printed, code), _ in CONVERSION_CASES]), encoding="utf-8")
            cls.done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", CONVERSION],
                                      capture_output=True, text=True, encoding="utf-8", errors="replace",
                                      timeout=300, env=dict(os.environ, CAR_BOOTSTRAP=str(BOOTSTRAP),
                                                            CAR_CASES=str(cases)))
        cls.answer = json.loads(cls.done.stdout) if cls.done.returncode == 0 and cls.done.stdout.strip() else None

    def setUp(self):
        if self.answer is None:
            self.fail("the probe did not run: " + (self.done.stderr or self.done.stdout)[-3000:])

    def test_the_line_is_held_to_its_exit_code(self):
        for ((printed, code), expected), answer in zip(CONVERSION_CASES, self.answer["answers"]):
            with self.subTest(printed=printed, code=code):
                self.assertEqual(answer["answer"], expected)
                self.assertEqual(listed(answer["asked"]), ["C:\\scratch-home downgrade-state --to 3 --stop-watcher"])

    def test_the_watcher_is_started_again_as_a_repair_starts_it(self):
        self.assertEqual(listed(self.answer["restarts"]), ["C:\\scratch-home setup --keep-state",
                                                           "C:\\scratch-home setup --keep-state --no-startup"])


# Stand-ins for the copy's conversion and restart: each writes down that it was asked and what was so then
# - whether the archive was unpacked, whether its installer had run, and whether the install lock was held
# (asked by another process, since the bootstrap's own thread may always take it again).
CONVERT_STUB = r"""function Convert-StateForOlder {
    param([string]$Home_)
    $seen = [ordered]@{ home = $Home_; unpacked = [bool](Test-Path -LiteralPath (Join-Path $unpacked 'install\install.ps1'));
                        installed = [bool](Test-Path -LiteralPath $env:CAR_INSTALLED);
                        lock = [string](& $env:CAR_PYTHON -c $env:CAR_LOCK_PROBE) }
    Add-Content -LiteralPath $env:CAR_EVENTS -Value ('convert ' + (ConvertTo-Json $seen -Compress)) -Encoding UTF8
    return $env:CAR_CONVERT
}"""
RESTART_STUB = r"""function Start-CurrentWatcher {
    param([string]$Home_, [switch]$NoStartup)
    Add-Content -LiteralPath $env:CAR_EVENTS -Value ('restart ' + [string][bool]$NoStartup) -Encoding UTF8
}"""
# Single quotes alone: Windows PowerShell hands a native program an argument's double quotes mangled.
LOCK_PROBE = r"""
import ctypes
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.CreateMutexW.restype = ctypes.c_void_p
handle = ctypes.c_void_p(kernel.CreateMutexW(None, False, 'Local\\CodexAutoResume.Install'))
waited = kernel.WaitForSingleObject(handle, 0)
print('held' if waited == 258 else 'free')
if waited in (0, 128):
    kernel.ReleaseMutex(handle)
kernel.CloseHandle(handle)
"""
# Holds the install lock, as another installation would, until its input closes.
LOCK_HOLDER = r"""
import ctypes, sys
kernel = ctypes.WinDLL("kernel32", use_last_error=True)
kernel.CreateMutexW.restype = ctypes.c_void_p
handle = ctypes.c_void_p(kernel.CreateMutexW(None, True, "Local\\CodexAutoResume.Install"))
print("held", flush=True)
sys.stdin.read()
"""
# The archive's installer: the real one's parameters, a record of how it was bound, and the code it is told.
INSTALLER = stub_installer().replace("\nexit 0\n", "\nexit [int]$env:CAR_INSTALLER_EXIT\n")


def replace_function(text, name, stub):
    start = text.index("function %s {" % name)
    end = text.index("\n}\n", start) + 2
    return text[:start] + stub + text[end:]


# A list with an older release on schema 3 to pick, below the newest release.
OLDER = [entry(INSTALLED), entry("0.6.11"), entry("0.6.10", files=assets("0.6.10", ("standard",)))]


class PickRunTests(PickerRun):
    """-Pick, the whole script, over an installed 0.6.12-beta of the standard edition."""

    def setUp(self):
        super().setUp()
        script = self.plugin / "scripts" / "bootstrap.ps1"
        text = script.read_text(encoding="utf-8")
        text = replace_function(replace_function(text, "Convert-StateForOlder", CONVERT_STUB),
                                "Start-CurrentWatcher", RESTART_STUB)
        script.write_text(text, encoding="utf-8")
        self.events = self.root / "events.txt"
        self.installation(INSTALLED)

    def published(self, version, edition="standard", pin=False, served=None, digest=None):
        """The archive GitHub would serve for `version`, its .sha256 - and, with `pin`, its digest pinned
        in the copy's release.json, as every release is."""
        extra = ["payload/app/src/codex_auto_resume_advanced/__init__.py"] if edition == "advanced" else []
        self.zip = archive(self.root / "served.zip", version=served or version, extra=extra, installer=INSTALLER)
        actual = hashlib.sha256(self.zip.read_bytes()).hexdigest()
        self.sum = self.root / "served.sha256"
        self.sum.write_text("%s  x.zip\n" % (digest or actual), encoding="utf-8")
        written = self.plugin / "scripts" / "release.json"
        release = json.loads(written.read_text(encoding="utf-8"))
        table = release["advanced"]["sha256"] if edition == "advanced" else release["sha256"]
        table.pop(version, None)
        if pin:
            table[version] = digest or actual
        written.write_text(json.dumps(release), encoding="utf-8")

    def pick(self, version, edition="Standard", convert="converted 30 5 2 1 0", installer_exit=0, policy=None,
             **more):
        self.events.unlink(missing_ok=True)
        self.installed.unlink(missing_ok=True)
        environment = {"CAR_EVENTS": str(self.events), "CAR_CONVERT": convert, "CAR_PYTHON": sys.executable,
                       "CAR_LOCK_PROBE": LOCK_PROBE, "CAR_INSTALLER_EXIT": str(installer_exit)}
        arguments = dict(more, Pick=version)
        if edition:
            arguments["Edition"] = edition
        return self.run_it(policy=policy, more=environment, **arguments)

    def seen(self):
        if not self.events.is_file():
            return []
        found = []
        for line in self.events.read_text(encoding="utf-8-sig").splitlines():
            word, _, rest = line.partition(" ")
            found.append((word, json.loads(rest) if word == "convert" else rest))
        return found

    def bound(self):
        return json.loads(self.installed.read_text(encoding="utf-8-sig")) if self.installed.is_file() else None

    def downloads(self, asked):
        return [request[1].rsplit("/", 1)[1] for request in asked if request[0] == ""]

    def refused(self, reason, code=15, **pick):
        before = self.listing()
        done, output, asked = self.pick(**pick)
        self.assertEqual(done, code, output[-2000:])
        if reason:
            self.assertEqual(self.answer_lines(output, "pick: "), [reason])
        self.assertEqual(self.downloads(asked), [], "it downloaded something")
        self.assertIsNone(self.bound(), "its installer ran")
        self.assertEqual(self.seen(), [], "the state was converted or the watcher restarted")
        self.assertEqual(self.listing(), before, "the run left something behind")
        return output, asked

    # -------------------------------------------------------------- what is installed
    def test_a_newer_release_is_installed_checked_against_its_pin(self):
        self.serve([entry("0.6.12"), entry(INSTALLED), entry("0.6.11")])
        self.published("0.6.12", pin=True)
        code, output, asked = self.pick("0.6.12")
        self.assertEqual(code, 0, output[-2000:])
        self.assertEqual(self.answer_lines(output, "pick: "),
                         ["pick: offered newer,release,kept,latest", "pick: installed 0.6.12 standard"])
        self.assertIn("SHA-256 matches the digest pinned in this plugin", output)
        self.assertEqual(asked, [["Get", PAGES.replace("{page}", "1")]] + POLICY_READS
                         + [["", NOWHERE + "/download/v0.6.12/CodexAutoResume-v0.6.12-win-x64.zip"]],
                         "the list, the policy keys and the archive, and nothing else")
        self.assertEqual(self.bound(), {"PluginName": "codex-auto-resume"})
        self.assertEqual(self.seen(), [], "a version on this schema needs no conversion")
        self.assertEqual(sorted(self.temp.glob("codex-auto-resume-*")), [], "the download outlived the install")

    def test_the_checks_own_pre_release_is_checked_against_its_published_checksum(self):
        self.serve([entry("0.6.12-beta.2"), entry(INSTALLED), entry("0.6.11")])
        self.published("0.6.12-beta.2")
        code, output, asked = self.pick("0.6.12-beta.2", NoStartup=True)
        self.assertEqual(code, 0, output[-2000:])
        self.assertEqual(self.answer_lines(output, "pick: "),
                         ["pick: offered newer,prerelease,kept", "pick: installed 0.6.12-beta.2 standard"])
        self.assertIn("SHA-256 matches the checksum published beside it", output)
        self.assertEqual(self.downloads(asked), ["CodexAutoResume-v0.6.12-beta.2-win-x64.zip",
                                                 "CodexAutoResume-v0.6.12-beta.2-win-x64.zip.sha256"])
        self.assertEqual(self.bound(), {"PluginName": "codex-auto-resume", "SkipStartup": "True"})

    def test_an_edition_change_tells_the_installer_it_was_asked_for(self):
        self.serve([entry(INSTALLED), entry("0.6.11")])
        self.published(INSTALLED, edition="advanced")
        code, output, asked = self.pick(INSTALLED, edition="Advanced", Force=True)
        self.assertEqual(code, 0, output[-2000:])
        self.assertEqual(self.answer_lines(output, "pick: "),
                         ["pick: offered same,prerelease,kept,edition", "pick: installed 0.6.12-beta advanced"])
        self.assertIn("Standard edition -> Advanced edition", output)
        self.assertEqual(self.downloads(asked), ["CodexAutoResume-Advanced-v0.6.12-beta-win-x64.zip",
                                                 "CodexAutoResume-Advanced-v0.6.12-beta-win-x64.zip.sha256"])
        self.assertEqual(self.bound(), {"PluginName": "codex-auto-resume", "AllowEditionChange": "True"})

    def test_an_older_version_is_installed_after_the_state_is_converted(self):
        """After the archive passed and was unpacked, under the install lock, and before its installer ran."""
        self.serve([entry(INSTALLED), entry("0.6.11"), entry("0.6.10", files=assets("0.6.10", ("standard",)))])
        self.published("0.6.10", pin=True)
        code, output, asked = self.pick("0.6.10", Force=True)
        self.assertEqual(code, 0, output[-2000:])
        lines = self.answer_lines(output, "pick: ")
        self.assertEqual(lines, ["pick: offered older,release,convert3", "pick: state converted 30 5 2 1 0",
                                 "pick: installed 0.6.10 standard"])
        self.assertLess(output.index("Archive contents verified"), output.index("pick: state converted"))
        self.assertEqual(self.seen(), [("convert", {"home": str(self.home), "unpacked": True, "installed": False,
                                                    "lock": "held"})])
        self.assertEqual(self.bound(), {"PluginName": "codex-auto-resume"})
        self.assertEqual(sorted(self.temp.glob("codex-auto-resume-*")), [])

    def test_a_state_already_old_enough_is_not_said_to_be_converted(self):
        self.serve(OLDER)
        self.published("0.6.10", pin=True)
        code, output, _ = self.pick("0.6.10", Force=True, convert="nothing")
        self.assertEqual(code, 0, output[-2000:])
        self.assertEqual(self.answer_lines(output, "pick: "), ["pick: offered older,release,convert3",
                                                                "pick: installed 0.6.10 standard"])
        self.assertEqual([word for word, _ in self.seen()], ["convert"])

    def test_an_archive_that_fails_its_checks_converts_nothing(self):
        self.serve(OLDER)
        for published, said in (({"pin": True, "served": "0.6.9"}, "The archive is version 0.6.9, not 0.6.10."),
                                ({"pin": True, "digest": "0" * 64}, "does not match the digest pinned"),
                                ({"digest": "0" * 64}, "does not match its published checksum")):
            with self.subTest(published=published):
                self.published("0.6.10", **published)
                code, output, _ = self.pick("0.6.10", Force=True)
                self.assertEqual(code, 1, output[-2000:])
                self.assertIn(said, output)
                self.assertIn("Nothing was installed.", output)
                self.assertEqual(self.answer_lines(output, "pick: "), ["pick: offered older,release,convert3"])
                self.assertEqual(self.seen(), [], "the state was converted for an archive that did not pass")
                self.assertIsNone(self.bound())
                self.assertEqual(sorted(self.temp.glob("codex-auto-resume-*")), [])

    def test_a_watcher_that_did_not_stop_installs_nothing(self):
        self.serve(OLDER)
        self.published("0.6.10", pin=True)
        code, output, _ = self.pick("0.6.10", Force=True, convert="watcher-running")
        self.assertEqual(code, 15, output[-2000:])
        self.assertEqual(self.answer_lines(output, "pick: "), ["pick: offered older,release,convert3",
                                                                "pick: refused watcher-running"])
        self.assertEqual([word for word, _ in self.seen()], ["convert"], "the watcher was started again")
        self.assertIsNone(self.bound())
        self.assertEqual(sorted(self.temp.glob("codex-auto-resume-*")), [])

    def test_a_conversion_that_failed_installs_nothing_and_starts_the_watcher_again(self):
        self.serve(OLDER)
        self.published("0.6.10", pin=True)
        for convert in ("failed", "", "something else"):
            with self.subTest(convert=convert):
                code, output, _ = self.pick("0.6.10", Force=True, convert=convert, NoStartup=True)
                self.assertEqual(code, 15, output[-2000:])
                self.assertEqual(self.answer_lines(output, "pick: "), ["pick: offered older,release,convert3",
                                                                        "pick: refused state"])
                self.assertEqual([word for word, _ in self.seen()], ["convert", "restart"])
                self.assertEqual(self.seen()[1], ("restart", "True"), "the restart keeps -NoStartup")
                self.assertIsNone(self.bound())

    def test_another_installation_holding_the_lock_installs_and_converts_nothing(self):
        self.serve(OLDER)
        self.published("0.6.10", pin=True)
        holder = subprocess.Popen([sys.executable, "-c", LOCK_HOLDER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            self.assertEqual(holder.stdout.readline().strip(), "held")
            code, output, _ = self.pick("0.6.10", Force=True)
        finally:
            holder.stdin.close()
            holder.wait(timeout=30)
            holder.stdout.close()
        self.assertEqual(code, 15, output[-2000:])
        self.assertEqual(self.answer_lines(output, "pick: "), ["pick: offered older,release,convert3",
                                                                "pick: refused busy"])
        self.assertEqual(self.seen(), [])
        self.assertIsNone(self.bound())
        self.assertEqual(sorted(self.temp.glob("codex-auto-resume-*")), [])

    def test_an_installer_that_fails_says_no_installed_line(self):
        self.serve([entry("0.6.12"), entry(INSTALLED)])
        self.published("0.6.12", pin=True)
        code, output, _ = self.pick("0.6.12", installer_exit=7)
        self.assertEqual(code, 7, output[-2000:])
        self.assertEqual(self.answer_lines(output, "pick: "), ["pick: offered newer,release,kept,latest"])
        self.assertEqual(sorted(self.temp.glob("codex-auto-resume-*")), [])

    # ------------------------------------------------------------- what is refused
    def test_an_older_version_without_force_asks_nothing(self):
        self.serve([entry(INSTALLED), entry("0.6.11")])
        _, asked = self.refused("pick: refused needs-force", version="0.6.11")
        self.assertEqual(asked, [])

    def test_the_other_edition_without_force_asks_nothing(self):
        self.serve([entry("0.6.12"), entry(INSTALLED)])
        _, asked = self.refused("pick: refused needs-force", version="0.6.12", edition="Advanced")
        self.assertEqual(asked, [])

    def test_force_where_it_is_not_needed_asks_nothing(self):
        self.serve([entry("0.6.12"), entry(INSTALLED)])
        _, asked = self.refused("pick: refused force-not-needed", version="0.6.12", Force=True)
        self.assertEqual(asked, [])

    def test_the_installed_version_is_not_installed_again(self):
        _, asked = self.refused("pick: refused installed", version=INSTALLED)
        self.assertEqual(asked, [])

    def test_without_an_installation_it_can_read_nothing_is_asked(self):
        for installed in (None, "0.6.12-gamma"):
            with self.subTest(installed=installed):
                shutil.rmtree(self.home, ignore_errors=True)
                if installed:
                    self.installation(installed)
                _, asked = self.refused("pick: refused unreadable", version="0.6.12")
                self.assertEqual(asked, [])

    def test_a_row_no_longer_offered_as_it_was_shown_installs_nothing(self):
        """The list changed, a policy was set, or the row is one the list never offered."""
        self.published("0.6.10", pin=True)
        for listed, version, force, policy, edition in (
                ([entry(INSTALLED)], "0.6.12", False, None, "Standard"),
                ([entry(INSTALLED), entry("0.6.10", files=assets("0.6.10", sums=False))], "0.6.10", True,
                 {HKLM: ["ForceObserveOnly"]}, "Standard"),
                ([entry("0.6.12-beta.2", files=assets("0.6.12-beta.2", ("standard",))), entry(INSTALLED)],
                 "0.6.12-beta.2", True, None, "Advanced"),
                ([entry(INSTALLED), entry("0.6.11-beta", files=assets("0.6.11-beta", sums=False))], "0.6.11-beta",
                 True, None, "Standard"),
                ([entry(INSTALLED), entry("0.6.10")], "0.6.10", True, None, "Advanced"),
                ([entry(INSTALLED), entry("0.6.6-alpha", files=assets("0.6.6"))], "0.6.6-alpha", True, None,
                 "Standard"),
                ([entry(INSTALLED), entry("0.6.1")], "0.6.1", True, None, "Standard")):
            with self.subTest(version=version, policy=policy, edition=edition):
                self.serve(listed)
                pick = {"version": version, "policy": policy, "edition": edition}
                if force:
                    pick["Force"] = True
                output, asked = self.refused("pick: refused changed", **pick)
                # The list again and the policy keys - the first one alone where it holds a value.
                self.assertEqual([request[0] for request in asked], ["Get"] + ["Registry"] * (1 if policy else 2))

    def test_an_edition_change_never_reaches_an_installer_older_than_editions(self):
        shutil.rmtree(self.home, ignore_errors=True)
        self.installation(INSTALLED, "advanced")
        self.serve(OLDER)
        self.published("0.6.10", pin=True)
        self.refused("pick: refused changed", version="0.6.10", Force=True)

    def test_a_list_that_could_not_be_read_installs_nothing(self):
        self.serve()
        output, asked = self.refused("pick: unavailable", code=12, version="0.6.12")
        self.assertEqual(asked, [["Get", PAGES.replace("{page}", "1")]])

    def test_only_a_version_by_the_rule_and_its_edition(self):
        for version in ("0.6.12-rc1", "v0.6.12", "0.6.012", "0.6.12 ", "0.6.12-beta.1", "latest", "0.6.12;calc"):
            with self.subTest(version=version):
                output, asked = self.refused(None, code=1, version=version)
                self.assertEqual(self.answer_lines(output, "pick: "), [])
                self.assertIn("Not a version this product publishes", output)
                self.assertEqual(asked, [])
        output, asked = self.refused(None, code=1, version="0.6.12", edition=None)
        self.assertIn("-Pick goes with -Edition", output)

    def test_it_goes_with_nothing_else(self):
        for more in ({"CheckOnly": True}, {"Update": True}, {"ArchivePath": str(self.root / "x.zip")},
                     {"Compatibility": True}, {"Version": "0.6.12-beta.2"}):
            with self.subTest(more=more):
                output, asked = self.refused(None, code=1, version="0.6.12", **more)
                self.assertEqual(self.answer_lines(output, "pick: "), [])
                self.assertEqual(asked, [])
        output, asked = self.refused(None, code=12, version="0.6.12", Versions=True)
        self.assertEqual(self.answer_lines(output, "versions: "), ["versions: unavailable"])
        self.assertEqual(asked, [])


class PickSourceTests(unittest.TestCase):
    def setUp(self):
        self.text = BOOTSTRAP.read_text(encoding="utf-8")

    def test_the_state_is_converted_only_after_the_archive_passed_and_before_its_installer(self):
        run = self.text[self.text.index("# " + "-" * 76 + " run"):]
        order = [run.index(marker) for marker in (
            "Test-Archive -Zip $zip", "ExtractToDirectory", "$pickLock.WaitOne(0)",
            "Convert-StateForOlder -Home_ $installHome", "& $installer @arguments")]
        self.assertEqual(order, sorted(order))
        self.assertEqual(run.count("Convert-StateForOlder -Home_"), 1)
        self.assertEqual(run.count("Start-CurrentWatcher -Home_"), 1)

    def test_the_picked_version_is_read_in_one_place_and_rebuilt(self):
        self.assertEqual(re.findall(r"Get-ChosenVersion \$Pick\b", self.text), ["Get-ChosenVersion $Pick"])
        self.assertIn("if ($Pick) { $target = $picked }", self.text)

    def test_nothing_widens_a_pick(self):
        """-Force is required exactly where the row is older or of the other edition, and refused otherwise."""
        self.assertIn("$needsForce = ($order -lt 0) -or $changesEdition", self.text)
        self.assertIn("if ($needsForce -and -not $Force)", self.text)
        self.assertIn("if ($Force -and -not $needsForce)", self.text)


if __name__ == "__main__":
    unittest.main()
