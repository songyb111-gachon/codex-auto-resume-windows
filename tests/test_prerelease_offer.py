r"""The update check's offer of a pre-release, and the one way it is installed (v0.6.11).

`releases/latest` never names a pre-release, so `-CheckOnly` asks one more question once github.com
has answered the first: GitHub's list of this repository's releases, for the newest pre-release that
is published, not a draft, tagged by this product's rule and newer than both the installed version
and the newest release. It says so on a line of its own, `prerelease: v<version>`, and nothing else
in the answer changes: the `update:` line and the exit code are the first question's, and a list
that cannot be read offers nothing - nor one that arrives too slowly, since the list has a deadline
of wall-clock time and not only `-TimeoutSec`. Only a person's yes installs one, through `-Version`,
which asks both questions again and takes only what the check would still offer: a pre-release the
list names as published, newer than what is installed and than the newest release, over an
installation, in its edition, verified against the `.sha256` published beside it - a pre-release is
never pinned.

The reader is lifted out of scripts/bootstrap.ps1 by the PowerShell parser and run with
`Invoke-WebRequest` replaced, as tests/test_update_check.py does. The stand-in keeps what it is told
and what it was asked in the environment and in files, because the reader asks it from a runspace of
its own (Invoke-BoundedWebRequest), which carries the stand-in over by its text and nothing else of
this session. The deadline itself is held with the real cmdlet against a server on 127.0.0.1 that
sends its body one byte a second - loopback only. The whole-script runs start a
scratch copy of the plugin with a scratch installation home and a scratch TEMP, never the real
installation, in a session where `Invoke-WebRequest` writes down what it was asked and answers from
files this test wrote; the copy's addresses point at a port nothing listens on in case the stub were
ever bypassed. An archive that passes every check is unpacked and its installer run, and that
installer is the stub tests/test_edition_bootstrap.py uses: the real one's parameters, and a record
of how it was bound.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from test_edition_bootstrap import archive, stub_installer  # noqa: E402
import editions  # noqa: E402
import languages  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts" / "bootstrap.ps1"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
RELEASE = json.loads((ROOT / "scripts" / "release.json").read_text(encoding="utf-8"))
OWNER, REPO = RELEASE["owner"], RELEASE["repo"]
TAG = "https://github.com/%s/%s/releases/tag/" % (OWNER, REPO)
LIST = "https://api.github.com/repos/%s/%s/releases" % (OWNER, REPO)
# Nothing listens here, so a request that got past the stub would fail rather than leave.
NOWHERE = "https://127.0.0.1:1/releases"


def entry(tag, prerelease=True, draft=False, **more):
    """One release as GitHub's list gives it, with the three fields the reader looks at."""
    return dict({"tag_name": tag, "prerelease": prerelease, "draft": draft,
                 "html_url": TAG + str(tag), "assets": []}, **more)


# name -> (the list's body, or a failure; installed; newest release; what the reader must answer).
# None means no pre-release to offer, and "THROWS" a list that could not be read - which the
# script takes as nothing to offer, and never as an answer about the release.
READING = {
    "none": ([entry("v1.2.3", prerelease=False), entry("v1.2.2", prerelease=False)],
             "1.2.3", "1.2.3", None),
    "empty": ([], "1.2.3", "1.2.3", None),
    "one": ([entry("v1.2.4-alpha"), entry("v1.2.3", prerelease=False)], "1.2.3", "1.2.3", "1.2.4-alpha"),
    "older": ([entry("v1.2.3-beta"), entry("v1.2.2-alpha")], "1.2.3", "1.2.3", None),
    "the_installed_one": ([entry("v1.2.4-beta")], "1.2.4-beta", "1.2.3", None),
    "installed_ahead": ([entry("v1.2.4-beta")], "1.2.4-beta.2", "1.2.3", None),
    "draft": ([entry("v1.2.4-beta", draft=True)], "1.2.3", "1.2.3", None),
    "a_draft_is_passed_over": ([entry("v1.2.5-alpha", draft=True), entry("v1.2.4-beta")],
                               "1.2.3", "1.2.3", "1.2.4-beta"),
    "stable_newer": ([entry("v1.2.4-beta"), entry("v1.2.4", prerelease=False)], "1.2.3", "1.2.4", None),
    "stable_same_line_newer": ([entry("v1.2.5-alpha"), entry("v1.2.5", prerelease=False)],
                               "1.2.3", "1.2.5", None),
    "newest_of_several": ([entry("v1.2.4-alpha"), entry("v1.2.4-beta.9"), entry("v1.2.4-beta"),
                           entry("v1.2.4-beta.10"), entry("v1.2.4-alpha.2")], "1.2.3", "1.2.3", "1.2.4-beta.10"),
    "past_a_newer_release": ([entry("v1.3.0-alpha"), entry("v1.2.9", prerelease=False)],
                             "1.2.3", "1.2.9", "1.3.0-alpha"),
    "malformed_tags": ([entry(tag) for tag in ("v1.2.4-rc1", "v1.2.4-Beta", "v1.2.4-beta.1", "v1.2.4-beta.0",
                                               "v01.2.4-alpha", "v1.02.4-alpha", "1.2.4-alpha", "V1.2.4-alpha",
                                               "v1.2.4-alpha\n", "v1.2.4-alpha ", "v1.2.4-alpha.2.1",
                                               "v1.2.4", "v1.2.4-gamma", "v1.2.\uff14-alpha", "")]
                       + [entry(5), entry(None), entry(["v1.2.4-alpha"])], "1.2.3", "1.2.3", None),
    "a_release_marked_pre": ([entry("v1.2.4", prerelease=True)], "1.2.3", "1.2.3", None),
    "a_pre_release_not_marked": ([entry("v1.2.4-beta", prerelease=False)], "1.2.3", "1.2.3", None),
    "fields_of_the_wrong_kind": ([entry("v1.2.4-alpha", draft="false"), entry("v1.2.4-beta", prerelease="true"),
                                  entry("v1.2.4-beta.2", draft=0), entry("v1.2.4-beta.3", prerelease=1)],
                                 "1.2.3", "1.2.3", None),
    "fields_missing": ([{"tag_name": "v1.2.4-alpha", "prerelease": True},
                        {"tag_name": "v1.2.4-beta", "draft": False},
                        {"prerelease": True, "draft": False}, "v1.2.4-alpha", 7, None, [1, 2]],
                       "1.2.3", "1.2.3", None),
    "unreachable": ("throw", "1.2.3", "1.2.3", "THROWS"),
    "not_a_list": ({"message": "API rate limit exceeded"}, "1.2.3", "1.2.3", "THROWS"),
    "not_json": ("<html>", "1.2.3", "1.2.3", "THROWS"),
    "too_large": ("large", "1.2.3", "1.2.3", "THROWS"),
    "no_body": ("nobody", "1.2.3", "1.2.3", "THROWS"),
}
# Where the list said it came from, and whether that may answer for this repository.
PLACES = {
    "this_repository": (LIST + "?per_page=10", "1.2.4-alpha"),
    "another_repository": ("https://api.github.com/repos/%s/some-fork/releases" % OWNER, "THROWS"),
    "another_owner": ("https://api.github.com/repos/someone-else/%s/releases" % REPO, "THROWS"),
    "a_repository_named_like_it": ("https://api.github.com/repos/%s/%s-fork/releases" % (OWNER, REPO), "THROWS"),
    "another_list": ("https://api.github.com/repos/%s/%s/tags" % (OWNER, REPO), "THROWS"),
    "the_download_host": ("https://github.com/repos/%s/%s/releases" % (OWNER, REPO), "THROWS"),
    "a_lookalike_host": ("https://api.github.com.example.invalid/repos/%s/%s/releases" % (OWNER, REPO), "THROWS"),
    "plain_http": ("http://api.github.com/repos/%s/%s/releases" % (OWNER, REPO), "THROWS"),
    "nowhere_said": (None, "THROWS"),
}

READER = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:CAR_BOOTSTRAP, [ref]$null, [ref]$errors)
if ($errors -and $errors.Count) { throw 'bootstrap.ps1 does not parse' }
$wanted = @('Get-FinalUri', 'Assert-TrustedHost', 'Invoke-BoundedWebRequest', 'Get-VersionParts',
            'Compare-ProductVersion', 'Format-UnreadVersion', 'Get-PrereleaseVersion', 'Read-ReleasesPage',
            'Get-PublishedPrereleases', 'Get-NewerPrerelease', 'Get-ReleasesListTimeout')
foreach ($node in $ast.FindAll({ param($n)
        $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    if ($wanted -contains $node.Name) { Invoke-Expression $node.Extent.Text }
}
foreach ($name in $wanted) {
    if (-not (Get-Command $name -CommandType Function -ErrorAction SilentlyContinue)) { throw ('bootstrap.ps1 has no ' + $name) }
}
$constants = @{}
foreach ($name in @('$ReleasesHosts', '$ReleasesMaxChars', '$ReleasesTimeoutMax', '$ReleasesTimeoutMin',
                    '$CheckBudgetSeconds', '$LookupAllowanceSeconds')) {
    $found = $ast.FindAll({ param($n)
        $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -eq $name }, $true)
    if (-not $found) { throw ('bootstrap.ps1 has no ' + $name) }
    Invoke-Expression $found[0].Extent.Text
    $constants[$name.Substring(1)] = (Get-Variable -Name $name.Substring(1)).Value
}

$Release = [pscustomobject]@{ owner = $env:CAR_OWNER; repo = $env:CAR_REPO; releases = $env:CAR_ASKED_URL }
# What the stand-in answers, and where it writes down what it was asked: the environment and files,
# which the reader's own runspace shares with this one.
$env:CAR_STUB_BODY = Join-Path $env:CAR_WORK 'body.txt'
$env:CAR_STUB_CALLS = Join-Path $env:CAR_WORK 'calls.txt'
$env:CAR_STUB_LARGE = [string]$ReleasesMaxChars
function Invoke-WebRequest {
    param([string]$Uri, [switch]$UseBasicParsing, [string]$Method, [int]$MaximumRedirection,
          [int]$TimeoutSec, [string]$OutFile, [switch]$PassThru)
    $call = ConvertTo-Json -Compress @([string]$Method, $Uri, $MaximumRedirection, $TimeoutSec, [bool]$OutFile)
    [IO.File]::AppendAllText($env:CAR_STUB_CALLS, $call + "`n")
    $mode = $env:CAR_STUB_MODE
    if ($mode -eq 'throw') { throw 'the network is not there' }
    $base = New-Object psobject
    if ($env:CAR_STUB_FINAL) { $base | Add-Member -MemberType NoteProperty -Name ResponseUri -Value ([Uri]$env:CAR_STUB_FINAL) }
    $response = New-Object psobject
    $response | Add-Member -MemberType NoteProperty -Name BaseResponse -Value $base
    if ($mode -eq 'large') {
        $response | Add-Member -MemberType NoteProperty -Name Content -Value ('[' + (' ' * [int]$env:CAR_STUB_LARGE) + ']')
    } elseif ($mode -ne 'nobody') {
        $response | Add-Member -MemberType NoteProperty -Name Content -Value ([IO.File]::ReadAllText($env:CAR_STUB_BODY))
    }
    return $response
}
function Read-It($body, $final, $installed, $stable) {
    $env:CAR_STUB_MODE = ''
    if (@('throw', 'large', 'nobody') -contains $body) { $env:CAR_STUB_MODE = $body }
    else { [IO.File]::WriteAllText($env:CAR_STUB_BODY, [string]$body) }
    $env:CAR_STUB_FINAL = [string]$final
    try {
        $found = Get-NewerPrerelease -Release $Release -Installed $installed -Stable $stable -TimeoutSec 11
        if ($null -eq $found) { return $null }
        return [string]$found
    } catch { return 'THROWS' }
}

$out = @{ reading = @{}; places = @{}; constants = $constants; timeouts = @{} }
$cases = Get-Content -LiteralPath $env:CAR_CASES -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($case in $cases.reading.PSObject.Properties) {
    $out.reading[$case.Name] = Read-It $case.Value[0] $cases.final $case.Value[1] $case.Value[2]
}
foreach ($case in $cases.places.PSObject.Properties) {
    $out.places[$case.Name] = Read-It $cases.one $case.Value '1.2.3' '1.2.3'
}
# The request itself: one GET to the constant, no redirect followed, the time it was given.
[IO.File]::WriteAllText($env:CAR_STUB_CALLS, '')
$null = Read-It $cases.one $cases.final '1.2.3' '1.2.3'
$out.calls = @([IO.File]::ReadAllLines($env:CAR_STUB_CALLS) | Where-Object { $_ })
# A release.json that names no list has nothing to ask.
$Release = [pscustomobject]@{ owner = $env:CAR_OWNER; repo = $env:CAR_REPO }
$out.incomplete = Read-It $cases.one $cases.final '1.2.3' '1.2.3'
foreach ($elapsed in 0..130) { $out.timeouts[[string]$elapsed] = Get-ReleasesListTimeout -Elapsed $elapsed }
$out | ConvertTo-Json -Depth 8 -Compress
"""


def body(value):
    if value in ("throw", "large", "nobody", "<html>"):
        return value
    return json.dumps(value)


@unittest.skipUnless(POWERSHELL.is_file(), "the bootstrap is PowerShell on Windows")
class ListReadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cases = {"reading": {name: [body(listed), installed, stable]
                             for name, (listed, installed, stable, _) in READING.items()},
                 "places": {name: final for name, (final, _) in PLACES.items()},
                 "final": LIST + "?per_page=10",
                 "one": body(READING["one"][0])}
        with tempfile.TemporaryDirectory() as folder:
            written = Path(folder) / "cases.json"
            written.write_text(json.dumps(cases), encoding="utf-8")
            done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", READER],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
                                  env=dict(os.environ, CAR_BOOTSTRAP=str(BOOTSTRAP), CAR_CASES=str(written),
                                           CAR_WORK=folder, CAR_OWNER=OWNER, CAR_REPO=REPO,
                                           CAR_ASKED_URL=RELEASE["releases"]))
        cls.done = done
        cls.answer = json.loads(done.stdout) if done.returncode == 0 and done.stdout.strip() else None

    def setUp(self):
        if self.answer is None:
            self.fail("the probe did not run: " + (self.done.stderr or self.done.stdout)[-2000:])

    def test_the_newest_pre_release_newer_than_both_or_none(self):
        """None, one, older, the one installed, a draft, a release newer than the pre-release,
        several - and every way a tag or an entry can fail to be one of this product's."""
        for name, (_, _, _, expected) in sorted(READING.items()):
            with self.subTest(name):
                self.assertEqual(self.answer["reading"][name], expected)

    def test_only_this_repositorys_list_on_the_api_host_answers(self):
        for name, (_, expected) in sorted(PLACES.items()):
            with self.subTest(name):
                self.assertEqual(self.answer["places"][name], expected)

    def test_it_is_one_get_to_the_constant_with_no_redirect_followed(self):
        calls = self.answer["calls"]
        calls = [json.loads(call) for call in ([calls] if isinstance(calls, str) else calls)]
        self.assertEqual(calls, [["Get", RELEASE["releases"], 0, 11, False]],
                         "one request, to the one address, into memory rather than a file")

    def test_a_release_file_with_no_list_asks_nothing(self):
        self.assertEqual(self.answer["incomplete"], "THROWS")

    def test_its_host_is_allowed_for_it_alone(self):
        hosts = self.answer["constants"]["ReleasesHosts"]
        self.assertEqual([hosts] if isinstance(hosts, str) else hosts, ["api.github.com"])
        text = BOOTSTRAP.read_text(encoding="utf-8")
        allowed = re.search(r"\$AllowedHosts\s*=\s*@\(([^)]*)\)", text).group(1)
        self.assertNotIn("api.github.com", allowed, "the archive's hosts do not grow")
        # One reader of a page of the list, which the update check and the picker (v0.6.12) both read through.
        self.assertEqual(len(re.findall(r"-Hosts \$ReleasesHosts", text)), 1)
        self.assertIn("-Hosts $ReleasesHosts", text[text.index("function Read-ReleasesPage"):
                                                      text.index("function Get-PublishedPrereleases")])

    def test_it_asks_inside_what_is_left_of_the_checks_time(self):
        """The window waits a fixed time for -CheckOnly, so the list gets only what is left of the
        check's budget after a name lookup - and is not asked for at all with too little left."""
        c = self.answer["constants"]
        for elapsed, seconds in self.answer["timeouts"].items():
            with self.subTest(elapsed=elapsed):
                self.assertLessEqual(seconds, c["ReleasesTimeoutMax"])
                if seconds:
                    self.assertGreaterEqual(seconds, c["ReleasesTimeoutMin"])
                    self.assertLessEqual(int(elapsed) + seconds + c["LookupAllowanceSeconds"], c["CheckBudgetSeconds"])
        self.assertEqual(self.answer["timeouts"]["0"], c["ReleasesTimeoutMax"])
        self.assertEqual(self.answer["timeouts"]["90"], 0)


class SlowServer:
    """HTTP on 127.0.0.1 alone: the status line and headers at once, then the body one byte a second - the
    list GitHub would send over a very slow link, or a server that means to hold the check up."""

    def __init__(self, seconds: int):
        self.body = b"[" + b" " * (seconds - 2) + b"]"
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(5)
        self.listener.settimeout(1)
        self.port = self.listener.getsockname()[1]
        self.asked = 0
        self.stopped = threading.Event()
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while not self.stopped.is_set():
            try:
                connection, _ = self.listener.accept()
            except (socket.timeout, OSError):
                continue
            self.asked += 1
            threading.Thread(target=self.drip, args=(connection,), daemon=True).start()

    def drip(self, connection):
        try:
            connection.recv(65536)
            connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n"
                               b"Connection: close\r\n\r\n" % len(self.body))
            for byte in self.body:
                if self.stopped.is_set():
                    break
                connection.sendall(bytes([byte]))
                time.sleep(1)
        except OSError:
            pass
        finally:
            connection.close()

    def close(self):
        self.stopped.set()
        self.listener.close()


DEADLINE = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:CAR_BOOTSTRAP, [ref]$null, [ref]$errors)
if ($errors -and $errors.Count) { throw 'bootstrap.ps1 does not parse' }
$wanted = @('Get-FinalUri', 'Assert-TrustedHost', 'Invoke-BoundedWebRequest', 'Get-VersionParts',
            'Compare-ProductVersion', 'Format-UnreadVersion', 'Get-PrereleaseVersion', 'Read-ReleasesPage',
            'Get-PublishedPrereleases', 'Get-NewerPrerelease')
foreach ($node in $ast.FindAll({ param($n)
        $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    if ($wanted -contains $node.Name) { Invoke-Expression $node.Extent.Text }
}
foreach ($name in @('$ReleasesHosts', '$ReleasesMaxChars')) {
    $found = $ast.FindAll({ param($n)
        $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -eq $name }, $true)
    Invoke-Expression $found[0].Extent.Text
}
# The real cmdlet, and a list address on this machine alone.
if ((Get-Command Invoke-WebRequest).CommandType -ne 'Cmdlet') { throw 'Invoke-WebRequest is not the cmdlet here' }
$Release = [pscustomobject]@{ owner = 'o'; repo = 'r'; releases = $env:CAR_SLOW_URL }
$clock = [Diagnostics.Stopwatch]::StartNew()
$answer = 'NOTHING'
try { $found = Get-NewerPrerelease -Release $Release -Installed '1.2.3' -Stable '1.2.3' -TimeoutSec 5; $answer = [string]$found }
catch { $answer = 'THROWS ' + $_.Exception.Message }
@{ answer = $answer; seconds = $clock.Elapsed.TotalSeconds } | ConvertTo-Json -Compress
"""


@unittest.skipUnless(POWERSHELL.is_file(), "the bootstrap is PowerShell on Windows")
class DeadlineTests(unittest.TestCase):
    """Under Windows PowerShell 5.1 -TimeoutSec bounds only the wait for a response to begin, and a body that
    arrives slowly is read for as long as it keeps coming. The window waits a fixed time for -CheckOnly and
    calls anything slower "running", so the list gets a deadline for all of it - held here with the real
    cmdlet, against a server on 127.0.0.1 that takes 40 s to send a list of 40 bytes."""

    def test_a_list_that_arrives_slowly_is_given_up_at_its_deadline(self):
        server = SlowServer(40)
        self.addCleanup(server.close)
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", DEADLINE],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
                              env=dict(os.environ, CAR_BOOTSTRAP=str(BOOTSTRAP),
                                       CAR_SLOW_URL="http://127.0.0.1:%d/repos/o/r/releases" % server.port))
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        answer = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertEqual(server.asked, 1, "the request reached the slow server")
        self.assertTrue(answer["answer"].startswith("THROWS"), answer)
        self.assertIn("did not arrive within 5 s", answer["answer"])
        # Five seconds, a runspace to start and two to let a stopped request go: nowhere near the forty the
        # body takes.
        self.assertLess(answer["seconds"], 12, answer)


# ------------------------------------------------------------------------------ the whole script
RUN = r"""
# Where the network was: every request is written down, and none leaves this process. HEAD - the
# update question - is answered with the redirect a case names; GET without a file, the list of
# releases, with the body a case wrote; a download with the archive and the checksum a case wrote.
function global:Invoke-WebRequest {
    param([string]$Uri, [string]$OutFile, [switch]$UseBasicParsing, [switch]$PassThru,
          [int]$MaximumRedirection, [int]$TimeoutSec, [string]$Method)
    Add-Content -LiteralPath $env:CAR_REQUESTS -Value (([string]$Method) + ' ' + $Uri) -Encoding UTF8
    $base = New-Object psobject
    $response = New-Object psobject
    if ($Method -eq 'Head' -and $env:CAR_LATEST) {
        $base | Add-Member -MemberType NoteProperty -Name ResponseUri -Value ([Uri]$env:CAR_LATEST)
    } elseif ($Method -eq 'Get' -and $env:CAR_LIST) {
        # A list that takes this long to arrive, as a slow link or a slow server makes one.
        if ($env:CAR_LIST_SECONDS) { Start-Sleep -Seconds ([int]$env:CAR_LIST_SECONDS) }
        $base | Add-Member -MemberType NoteProperty -Name ResponseUri -Value ([Uri]$env:CAR_LIST_FINAL)
        $response | Add-Member -MemberType NoteProperty -Name Content -Value ([IO.File]::ReadAllText($env:CAR_LIST))
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
$arguments = @{}
foreach ($pair in (ConvertFrom-Json $env:CAR_ARGUMENTS).PSObject.Properties) {
    $arguments[$pair.Name] = $pair.Value
}
& $env:CAR_SCRIPT @arguments
exit $LASTEXITCODE
"""


class ScriptRun(unittest.TestCase):
    """A scratch plugin at 1.2.3, a scratch home, and the stubbed network."""

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
            json.dumps(dict(manifest, version="1.2.3")), encoding="utf-8")
        release = dict(RELEASE, download=NOWHERE + "/download/v{version}/", latest=NOWHERE + "/latest",
                       releases=NOWHERE + "/list")
        (self.plugin / "scripts" / "release.json").write_text(json.dumps(release), encoding="utf-8")
        self.home = self.root / "home"
        self.temp = self.root / "temp"
        self.temp.mkdir()
        self.requests = self.root / "requests.txt"
        self.installed = self.root / "installed.json"
        self.listed = self.root / "list.json"
        self.zip = None
        self.sum = None

    def installation(self, version, edition="standard"):
        """What Get-InstalledVersion and Get-InstalledEdition read, and nothing else."""
        (self.home / "runtime").mkdir(parents=True)
        (self.home / "runtime" / "python.exe").write_bytes(b"not a real interpreter")
        (self.home / "app" / ".codex-plugin").mkdir(parents=True)
        (self.home / "app" / ".codex-plugin" / "plugin.json").write_text(
            json.dumps({"name": "codex-auto-resume", "version": version}), encoding="utf-8")
        (self.home / "app" / "scripts").mkdir()
        (self.home / "app" / "src" / "codex_auto_resume").mkdir(parents=True)
        if edition == "advanced":
            (self.home / "app" / "src" / editions.PACKAGE).mkdir()
            (self.home / "app" / "src" / editions.PACKAGE / "__init__.py").write_text("", encoding="utf-8")

    def listing(self) -> list:
        found = [path for folder in (self.home, self.plugin) for path in folder.rglob("*")]
        found += sorted(self.temp.glob("codex-auto-resume-*"))
        return sorted(str(path.relative_to(self.root)) for path in found)

    def run_it(self, latest=None, listed=None, list_seconds=0, **arguments):
        self.requests.unlink(missing_ok=True)
        environment = dict(os.environ, CODEX_AUTO_RESUME_PLUGIN_HOME=str(self.home),
                           TEMP=str(self.temp), TMP=str(self.temp),
                           CAR_SCRIPT=str(self.plugin / "scripts" / "bootstrap.ps1"),
                           CAR_ARGUMENTS=json.dumps(arguments), CAR_REQUESTS=str(self.requests),
                           CAR_INSTALLED=str(self.installed), CAR_LATEST=TAG + latest if latest else "",
                           CAR_LIST="", CAR_LIST_FINAL=LIST + "?per_page=10", CAR_LIST_SECONDS=str(list_seconds or ""),
                           CAR_ZIP=str(self.zip or ""), CAR_SUM=str(self.sum or ""))
        if listed is not None:
            self.listed.write_text(json.dumps(listed), encoding="utf-8")
            environment["CAR_LIST"] = str(self.listed)
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                               "Bypass", "-Command", RUN],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                              errors="replace", timeout=300, env=environment)
        asked = []
        if self.requests.is_file():
            asked = [line.split(" ", 1) for line in
                     self.requests.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
        return done.returncode, done.stdout, asked


@unittest.skipUnless(POWERSHELL.is_file(), "the bootstrap is PowerShell on Windows")
class CheckOnlyTests(ScriptRun):
    """-CheckOnly, the whole script: the first question's answer and exit code are what they were,
    and a pre-release newer than both is said on a line of its own."""

    ONE = [entry("v1.2.5-alpha"), entry("v1.2.4", prerelease=False), entry("v1.2.4-beta")]

    def check(self, latest, listed, expected_code, expected_line):
        code, output, asked = self.run_it(latest=latest, listed=listed, CheckOnly=True)
        self.assertEqual(code, expected_code, output[-1500:])
        self.assertIn(expected_line, output)
        self.assertEqual(asked, [["Head", NOWHERE + "/latest"], ["Get", NOWHERE + "/list"]], output[-1500:])
        return output

    def test_current_with_a_pre_release_says_both(self):
        self.installation("1.2.4")
        output = self.check("v1.2.4", self.ONE, 0, "update: current 1.2.4")
        self.assertIn("prerelease: v1.2.5-alpha", output)
        self.assertLess(output.index("prerelease: "), output.index("update: "))
        self.assertIn("tested less than a release", output)

    def test_ahead_of_the_release_with_a_newer_pre_release_says_both(self):
        """A machine on a pre-release is ahead of the newest release, and is offered the next one."""
        self.installation("1.2.5-alpha")
        output = self.check("v1.2.4", self.ONE + [entry("v1.2.5-alpha.2")], 11, "update: newer-local 1.2.5-alpha 1.2.4")
        self.assertIn("prerelease: v1.2.5-alpha.2", output)

    def test_a_release_to_install_and_a_newer_pre_release_says_both(self):
        self.installation("1.2.3")
        output = self.check("v1.2.4", self.ONE, 10, "update: available 1.2.3 1.2.4")
        self.assertIn("prerelease: v1.2.5-alpha", output)

    def test_none_says_nothing_of_it(self):
        self.installation("1.2.4")
        output = self.check("v1.2.4", [entry("v1.2.4", prerelease=False), entry("v1.2.4-beta")], 0,
                            "update: current 1.2.4")
        self.assertNotIn("prerelease:", output)

    def test_a_release_newer_than_the_pre_release_offers_none(self):
        self.installation("1.2.3")
        output = self.check("v1.2.6", self.ONE, 10, "update: available 1.2.3 1.2.6")
        self.assertNotIn("prerelease:", output)

    def test_a_list_that_cannot_be_read_offers_nothing_and_changes_nothing(self):
        for listed in (None, {"message": "API rate limit exceeded"}):
            with self.subTest(listed=listed):
                shutil.rmtree(self.home, ignore_errors=True)
                self.installation("1.2.4")
                code, output, asked = self.run_it(latest="v1.2.4", listed=listed, CheckOnly=True)
                self.assertEqual(code, 0, output[-1500:])
                self.assertIn("update: current 1.2.4", output)
                self.assertNotIn("prerelease:", output)
                self.assertIn("The list of releases could not be read", output)
                self.assertEqual([request[0] for request in asked], ["Head", "Get"])

    def test_a_list_that_arrives_too_slowly_offers_nothing_and_the_answer_comes_in_time(self):
        """The window waits 120 s for -CheckOnly and calls anything slower "running". A list that takes 200 s
        to arrive is given up at the list's deadline, and the answer is the one github.com gave."""
        self.installation("1.2.4")
        started = time.monotonic()
        code, output, asked = self.run_it(latest="v1.2.4", listed=self.ONE, list_seconds=200, CheckOnly=True)
        seconds = time.monotonic() - started
        self.assertEqual(code, 0, output[-1500:])
        self.assertIn("update: current 1.2.4", output)
        self.assertNotIn("prerelease:", output)
        self.assertIn("The list of releases could not be read", output)
        self.assertEqual([request[0] for request in asked], ["Head", "Get"])
        self.assertLess(seconds, 60, "the check waited for the list: " + output[-1500:])

    def test_a_check_that_could_not_ask_asks_nothing_else(self):
        self.installation("1.2.4")
        code, output, asked = self.run_it(listed=self.ONE, CheckOnly=True)
        self.assertEqual(code, 12, output[-1500:])
        self.assertIn("update: unavailable", output)
        self.assertNotIn("prerelease:", output)
        self.assertEqual(asked, [["Head", NOWHERE + "/latest"]])

    def test_an_update_never_reads_the_list_or_installs_a_pre_release(self):
        self.installation("1.2.3")
        code, output, asked = self.run_it(latest="v1.2.4", listed=self.ONE, Update=True)
        self.assertEqual(code, 1, "the stub network refuses the download: " + output[-1500:])
        self.assertIn("update: available 1.2.3 1.2.4", output)
        self.assertNotIn("prerelease:", output)
        self.assertEqual(asked, [["Head", NOWHERE + "/latest"],
                                 ["", NOWHERE + "/download/v1.2.4/CodexAutoResume-v1.2.4-win-x64.zip"]])


@unittest.skipUnless(POWERSHELL.is_file(), "the bootstrap is PowerShell on Windows")
class VersionTests(ScriptRun):
    """-Version: the pre-release a person said yes to, and nothing wider. It asks both of the check's questions
    again, because a release may have been published while the question was open: it installs only what the
    check would still offer - a pre-release the list names as published, newer than the newest release."""

    ASKED = [["Head", NOWHERE + "/latest"], ["Get", NOWHERE + "/list"]]

    def published(self, version, digest=None, edition="standard"):
        """The archive and the checksum GitHub would serve for `version`."""
        extra = ["payload/app/src/%s/__init__.py" % editions.PACKAGE] if edition == "advanced" else []
        self.zip = archive(self.root / "served.zip", version=version, extra=extra, installer=stub_installer())
        self.sum = self.root / "served.sha256"
        digest = digest or hashlib.sha256(self.zip.read_bytes()).hexdigest()
        self.sum.write_text("%s  CodexAutoResume-v%s-win-x64.zip\n" % (digest, version), encoding="utf-8")

    def test_it_installs_that_pre_release_verified_by_its_published_checksum(self):
        self.installation("1.2.3")
        self.published("1.2.4-beta.2")
        code, output, asked = self.run_it(latest="v1.2.3", listed=[entry("v1.2.4-beta.2"), entry("v1.2.4-beta")],
                                          Version="1.2.4-beta.2", NoStartup=True)
        self.assertEqual(code, 0, output[-2000:])
        self.assertIn("update: available 1.2.3 1.2.4-beta.2", output)
        self.assertIn("tested less than a release", output)
        self.assertIn("SHA-256 matches the checksum published beside it", output)
        self.assertIn("Archive contents verified as Codex Auto Resume v1.2.4-beta.2", output)
        name = NOWHERE + "/download/v1.2.4-beta.2/CodexAutoResume-v1.2.4-beta.2-win-x64.zip"
        self.assertEqual(asked, self.ASKED + [["", name], ["", name + ".sha256"]],
                         "the two questions, then the archive and its checksum, and nothing else")
        # Over the installation, in its edition: the installer is told of no edition change, and
        # its own upgrade branch is what keeps the state (tests/test_installer.py).
        self.assertEqual(json.loads(self.installed.read_text(encoding="utf-8-sig")),
                         {"PluginName": "codex-auto-resume", "SkipStartup": "True"})
        self.assertEqual(sorted(self.temp.glob("codex-auto-resume-*")), [], "the download outlived the install")

    def test_it_stays_in_the_installed_edition(self):
        self.installation("1.2.3", "advanced")
        code, output, asked = self.run_it(latest="v1.2.3", listed=[entry("v1.2.4-alpha")], Version="1.2.4-alpha")
        self.assertEqual(code, 1, "the stub network refuses the download: " + output[-1500:])
        self.assertIn("edition: advanced", output)
        self.assertEqual(asked, self.ASKED + [
            ["", NOWHERE + "/download/v1.2.4-alpha/CodexAutoResume-Advanced-v1.2.4-alpha-win-x64.zip"]])

    def test_a_checksum_that_does_not_match_installs_nothing(self):
        self.installation("1.2.3")
        self.published("1.2.4-beta", digest="0" * 64)
        code, output, _ = self.run_it(latest="v1.2.3", listed=[entry("v1.2.4-beta")], Version="1.2.4-beta")
        self.assertEqual(code, 1, output[-1500:])
        self.assertIn("does not match its published checksum", output)
        self.assertIn("Nothing was installed.", output)
        self.assertFalse(self.installed.exists(), "its installer ran")
        self.assertEqual(sorted(self.temp.glob("codex-auto-resume-*")), [])

    def test_an_archive_of_another_version_installs_nothing(self):
        self.installation("1.2.3")
        self.published("1.2.4-beta.3")
        code, output, _ = self.run_it(latest="v1.2.3", listed=[entry("v1.2.4-beta.2")], Version="1.2.4-beta.2")
        self.assertEqual(code, 1, output[-1500:])
        self.assertIn("The archive is version 1.2.4-beta.3, not 1.2.4-beta.2.", output)
        self.assertFalse(self.installed.exists(), "its installer ran")

    def test_a_release_published_since_is_answered_and_nothing_is_downloaded(self):
        """The offer was made, and before the yes a release as new or newer came out: the answer is the check's
        own, `update: available` with that release and its exit code, and nothing is fetched."""
        for latest, asked in (("v1.2.4", "1.2.4-beta"), ("v1.2.5", "1.2.4-beta.2"), ("v1.3.0", "1.2.9-alpha")):
            with self.subTest(latest=latest, asked=asked):
                shutil.rmtree(self.home, ignore_errors=True)
                self.installation("1.2.3")
                self.published(asked)
                code, output, requests = self.run_it(latest=latest, listed=[entry("v" + asked)], Version=asked)
                self.assertEqual(code, 10, output[-1500:])
                self.assertIn("update: available 1.2.3 " + latest[1:], output)
                self.assertNotIn("update: available 1.2.3 " + asked, output)
                self.assertEqual(requests, self.ASKED[:1], "it asked for more than the newest release")
                self.assertNotIn("Downloading", output)
                self.assertFalse(self.installed.exists(), "its installer ran")

    def test_only_a_pre_release_the_list_names_as_published(self):
        self.installation("1.2.3")
        self.published("1.2.4-beta")
        for listed in ([], [entry("v1.2.4-beta.2")], [entry("v1.2.4-beta", draft=True)],
                       [entry("v1.2.4-beta", prerelease=False)], [entry("v1.2.4-Beta")]):
            with self.subTest(listed=listed):
                code, output, requests = self.run_it(latest="v1.2.3", listed=listed, Version="1.2.4-beta")
                self.assertEqual(code, 1, output[-1500:])
                self.assertIn("is not a published pre-release", output)
                self.assertEqual(requests, self.ASKED)
                self.assertNotIn("update: available", output)
                self.assertFalse(self.installed.exists(), "its installer ran")

    def test_a_question_that_could_not_be_asked_installs_nothing(self):
        """Could not ask is its own answer here too, and never a yes."""
        self.installation("1.2.3")
        self.published("1.2.4-beta")
        for latest, listed, asked in ((None, [entry("v1.2.4-beta")], self.ASKED[:1]),
                                      ("v1.2.3", None, self.ASKED),
                                      ("v1.2.3", {"message": "API rate limit exceeded"}, self.ASKED)):
            with self.subTest(latest=latest, listed=listed):
                code, output, requests = self.run_it(latest=latest, listed=listed, Version="1.2.4-beta")
                self.assertEqual(code, 12, output[-1500:])
                self.assertIn("update: unavailable", output)
                self.assertNotIn("update: available", output)
                self.assertEqual(requests, asked)
                self.assertFalse(self.installed.exists(), "its installer ran")

    def refused(self, arguments, reason, code=1):
        before = self.listing()
        done, output, asked = self.run_it(**arguments)
        self.assertEqual(done, code, output[-1500:])
        self.assertIn(reason, output)
        self.assertEqual(asked, [], "it asked the network: " + output[-1500:])
        self.assertNotIn("Downloading", output)
        self.assertNotIn("update: available", output)
        self.assertEqual(self.listing(), before, "the run left something behind")

    def test_never_the_installed_version_or_an_older_one(self):
        for installed, asked in (("1.2.4-beta", "1.2.4-beta"), ("1.2.4-beta.2", "1.2.4-beta"),
                                 ("1.2.4", "1.2.4-beta.9"), ("1.3.0", "1.2.4-alpha")):
            with self.subTest(installed=installed, asked=asked):
                shutil.rmtree(self.home, ignore_errors=True)
                self.installation(installed)
                self.refused({"Version": asked}, "is not newer than it")

    def test_never_without_an_installation_it_can_read(self):
        self.refused({"Version": "1.2.4-beta"}, "would not be an update of one")
        self.installation("1.2.3-gamma")
        self.refused({"Version": "1.2.4-beta"}, "would not be an update of one")

    def test_only_a_pre_release_by_the_rule(self):
        self.installation("1.2.3")
        for asked in ("1.2.4", "1.2.4-rc1", "1.2.4-Beta", "1.2.4-beta.1", "01.2.4-alpha", "1.2.4-alpha.02",
                      "1.2.4-alpha ", "1.2.4-alpha/../../x", "1.2.4-alpha;calc", "v1.2.4-alpha", "latest"):
            with self.subTest(asked=asked):
                self.refused({"Version": asked}, "Not a pre-release this product publishes")

    def test_nothing_widens_it(self):
        """Not a second question, not a file, not another edition, and not -Force: a pre-release is
        never installed over a version as new as itself or newer."""
        self.installation("1.2.3")
        for more in ({"CheckOnly": True}, {"Update": True}, {"Force": True}, {"Edition": "Advanced"},
                     {"ArchivePath": str(self.root / "x.zip")}):
            with self.subTest(more=more):
                self.refused(dict(more, Version="1.2.4-beta"), "goes with -NoStartup alone")
        self.refused({"Version": "1.2.4-beta", "Compatibility": True}, "compatibility: unavailable", code=12)


class DocsTests(unittest.TestCase):
    """What the pages about privacy and security say the window does with what the list holds."""

    def test_every_page_says_a_pre_release_is_offered_only_where_no_release_is_offered_first(self):
        """The window offers the pre-release only where the answer is current or newer-local: where a release is
        available it offers that, and a release declined offers nothing more. The guide said so; the privacy and
        security pages said the window asks whenever the list holds one."""
        window = (ROOT / "gui" / "DashboardMaintenance.cs").read_text(encoding="utf-8")
        self.assertIn('if (answer == "available") OfferUpdate(root, script, current, latest);', window)
        self.assertIn('else if ((answer == "current" || answer == "newer-local") && prerelease != null)', window)
        english, korean = "no release to offer first", "먼저 제안할 릴리스가 없"
        pages = ["docs/PRIVACY.md", "docs/SECURITY.md", "docs/GUIDE.md"]
        if languages.both_languages():
            pages += ["docs/PRIVACY.ko.md", "docs/SECURITY.ko.md", "docs/GUIDE.ko.md"]
        for name in pages:
            with self.subTest(name):
                text = " ".join((ROOT / name).read_text(encoding="utf-8").split())
                korean_text = name.endswith(".ko.md") or languages.generated_ko_branch()
                self.assertIn(korean if korean_text else english, text)


if __name__ == "__main__":
    unittest.main()
