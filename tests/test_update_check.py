r"""What the update check accepts as an answer to "is there a newer release?".

The check is the one place where a version number crosses from the network into a
download URL, so the question is not whether it works but what it refuses. It asks
github.com with HEAD - no body is transferred, so there is nothing to parse - and reads
the answer out of the URL the request ended at. Everything that matters is therefore in
how that URL is judged: a fork, a repository of the same owner with a different name, an
owner whose name merely starts with ours, a tag that is not a version, a host that is
allowed for downloads but does not answer for releases.

Reading the script would show the rules are written. These tests run them. The real
function definitions are lifted out of `scripts/bootstrap.ps1` by the PowerShell parser
and defined in a session where `Invoke-WebRequest` is a stub, so what is exercised is the
shipped code with the network replaced - and no test here reaches the internet.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts" / "bootstrap.ps1"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")

OWNER = "songyb111-gachon"
REPO = "codex-auto-resume-windows"
TAG = "https://github.com/%s/%s/releases/tag/" % (OWNER, REPO)

# Each case is a final URL - where the request ended up after redirects - and what the
# resolver must make of it. `None` means it must refuse.
REDIRECTS = {
    "plain": (TAG + "v1.2.3", "1.2.3"),
    "two_digits": (TAG + "v0.10.0", "0.10.0"),
    "leading_zero": (TAG + "v0.06.0", "0.6.0"),
    "another_owner": ("https://github.com/someone-else/%s/releases/tag/v9.9.9" % REPO, None),
    "another_repo": ("https://github.com/%s/some-fork/releases/tag/v9.9.9" % OWNER, None),
    # The owner name is a prefix of this one. A `StartsWith` on the wrong string, or a
    # regex without an anchor, takes this for ours.
    "owner_prefix": ("https://github.com/%s-mirror/%s/releases/tag/v9.9.9" % (OWNER, REPO), None),
    "repo_prefix": ("https://github.com/%s/%s-fork/releases/tag/v9.9.9" % (OWNER, REPO), None),
    "foreign_host": ("https://example.invalid/%s/%s/releases/tag/v9.9.9" % (OWNER, REPO), None),
    # Allowed to serve a download, because a release asset redirects there. It does not
    # answer the question of which release is newest.
    "asset_host": ("https://objects.githubusercontent.com/%s/%s/releases/tag/v9.9.9"
                   % (OWNER, REPO), None),
    "not_https": ("http://github.com/%s/%s/releases/tag/v9.9.9" % (OWNER, REPO), None),
    "not_a_tag_page": ("https://github.com/%s/%s/releases" % (OWNER, REPO), None),
    "tag_is_not_a_version": (TAG + "nightly", None),
    "four_parts": (TAG + "v1.2.3.4", None),
    "prerelease_suffix": (TAG + "v1.2.3-rc1", None),
    "no_v": (TAG + "1.2.3", None),
    "trailing_slash": (TAG + "v1.2.3/", None),
    # Normalised by Uri before the path is read; it must not climb out either way.
    "traversal": ("https://github.com/%s/%s/releases/tag/../../../evil/repo/releases/tag/v9.9.9"
                  % (OWNER, REPO), None),
    "enormous": (TAG + "v1234567.0.0", None),
}

# Ordered pairs and the sign the comparison must give.
ORDERING = [
    ("1.2.3", "1.2.3", 0),
    ("0.10.0", "0.9.0", 1),
    ("0.9.0", "0.10.0", -1),
    ("1.0.0", "0.99.99", 1),
    ("0.6.0", "0.5.7", 1),
    ("0.5.7", "0.6.0", -1),
    ("0.6.1", "0.6.0", 1),
    ("10.0.0", "9.0.0", 1),
]

MALFORMED = ["1.2", "1.2.3.4", "v1.2.3", "1.2.3-rc1", "", "1.2.x", "1234567.0.0"]

PROBE = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

# The real functions, lifted out of the shipped script. Running the script itself would
# install something; this defines exactly the parts under test and nothing else.
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:CAR_BOOTSTRAP, [ref]$null, [ref]$errors)
if ($errors -and $errors.Count) { throw 'bootstrap.ps1 does not parse' }
$wanted = @('Get-FinalUri', 'Assert-TrustedHost', 'Get-VersionParts',
            'Compare-ProductVersion', 'Get-NewestPublishedVersion')
$found = @()
foreach ($node in $ast.FindAll({ param($n)
        $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    if ($wanted -contains $node.Name) {
        $found += $node.Name
        Invoke-Expression $node.Extent.Text
    }
}
foreach ($name in $wanted) {
    if ($found -notcontains $name) { throw ('bootstrap.ps1 has no ' + $name) }
}

# The one constant those functions close over.
$allowedAst = $ast.FindAll({ param($n)
        $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and
        $n.Left.Extent.Text -eq '$AllowedHosts' }, $true)
if (-not $allowedAst) { throw 'bootstrap.ps1 has no $AllowedHosts' }
Invoke-Expression $allowedAst[0].Extent.Text

$Release = [pscustomobject]@{
    owner  = $env:CAR_OWNER
    repo   = $env:CAR_REPO
    latest = 'https://github.com/' + $env:CAR_OWNER + '/' + $env:CAR_REPO + '/releases/latest'
}

# Where the network was. Every case says what the request ended up at, and nothing here
# opens a socket.
$script:NextFinal = $null
$script:Shape = 'five'
$script:Calls = 0
function Invoke-WebRequest {
    param([string]$Uri, [switch]$UseBasicParsing, [string]$Method,
          [int]$MaximumRedirection, [int]$TimeoutSec, [string]$OutFile, [switch]$PassThru)
    $script:Calls += 1
    $script:Method = $Method
    $script:Asked = $Uri
    if ($script:NextFinal -eq 'throw') { throw 'the network is not there' }
    $base = New-Object psobject
    if ($script:NextFinal) {
        if ($script:Shape -eq 'five') {
            $base | Add-Member -MemberType NoteProperty -Name ResponseUri -Value ([Uri]$script:NextFinal)
        } else {
            $message = New-Object psobject
            $message | Add-Member -MemberType NoteProperty -Name RequestUri -Value ([Uri]$script:NextFinal)
            $base | Add-Member -MemberType NoteProperty -Name RequestMessage -Value $message
        }
    }
    $response = New-Object psobject
    $response | Add-Member -MemberType NoteProperty -Name BaseResponse -Value $base
    return $response
}

$out = @{ redirects = @{}; ordering = @{}; malformed = @{}; probe = @{} }

foreach ($pair in (ConvertFrom-Json $env:CAR_REDIRECTS).PSObject.Properties) {
    $script:NextFinal = $pair.Value
    $script:Shape = 'five'
    try { $out.redirects[$pair.Name] = (Get-NewestPublishedVersion -Release $Release) }
    catch { $out.redirects[$pair.Name] = 'REFUSED' }
}

foreach ($row in (ConvertFrom-Json $env:CAR_ORDERING)) {
    try { $out.ordering[$row[0] + ' ' + $row[1]] = (Compare-ProductVersion -Left $row[0] -Right $row[1]) }
    catch { $out.ordering[$row[0] + ' ' + $row[1]] = 'REFUSED' }
}

foreach ($bad in (ConvertFrom-Json $env:CAR_MALFORMED)) {
    try { $null = Get-VersionParts $bad; $out.malformed[[string]$bad] = 'ACCEPTED' }
    catch { $out.malformed[[string]$bad] = 'REFUSED' }
}

# The request itself: no body, and the URL asked for is the constant, not a value.
$script:NextFinal = 'https://github.com/' + $env:CAR_OWNER + '/' + $env:CAR_REPO + '/releases/tag/v1.2.3'
$script:Calls = 0
$null = Get-NewestPublishedVersion -Release $Release
$out.probe['method'] = $script:Method
$out.probe['asked'] = $script:Asked
$out.probe['calls'] = $script:Calls

# PowerShell 7 reports the final URL under a different name; the resolver reads both.
$script:Shape = 'seven'
$out.probe['pwsh7'] = Get-NewestPublishedVersion -Release $Release

# A response that says nothing about where it came from is a refusal, not a guess.
$script:NextFinal = $null
$script:Shape = 'five'
try { $null = Get-NewestPublishedVersion -Release $Release; $out.probe['silent'] = 'ACCEPTED' }
catch { $out.probe['silent'] = 'REFUSED' }

# The same guard on its own, because every download goes through it and only the update
# check goes through the resolver above. A silent pass here would accept an archive from
# wherever a redirect chain happened to end.
function New-Response {
    param([string]$Final)
    $base = New-Object psobject
    if ($Final) { $base | Add-Member -MemberType NoteProperty -Name ResponseUri -Value ([Uri]$Final) }
    $response = New-Object psobject
    $response | Add-Member -MemberType NoteProperty -Name BaseResponse -Value $base
    return $response
}
$out.trust = @{}
$trust = @{
    'nothing'      = $null
    'foreign'      = 'https://example.invalid/x.zip'
    'plain_http'   = 'http://github.com/x.zip'
    'lookalike'    = 'https://github.com.example.invalid/x.zip'
    'subdomain'    = 'https://evil.github.com.invalid/x.zip'
    'github'       = 'https://github.com/x.zip'
    'objects'      = 'https://objects.githubusercontent.com/x.zip'
    'assets'       = 'https://release-assets.githubusercontent.com/x.zip'
}
foreach ($pair in $trust.GetEnumerator()) {
    try {
        Assert-TrustedHost -Response (New-Response -Final $pair.Value) -What 'The archive'
        $out.trust[$pair.Key] = 'ACCEPTED'
    } catch { $out.trust[$pair.Key] = 'REFUSED' }
}

# So is a release.json with nothing to ask.
try {
    $null = Get-NewestPublishedVersion -Release ([pscustomobject]@{ owner = 'x' })
    $out.probe['incomplete'] = 'ACCEPTED'
} catch { $out.probe['incomplete'] = 'REFUSED' }

$out | ConvertTo-Json -Depth 6 -Compress
"""


@unittest.skipUnless(POWERSHELL.is_file(), "the bootstrap is PowerShell on Windows")
class ResolverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        environment = dict(
            os.environ,
            CAR_BOOTSTRAP=str(BOOTSTRAP),
            CAR_OWNER=OWNER,
            CAR_REPO=REPO,
            CAR_REDIRECTS=json.dumps({name: final for name, (final, _) in REDIRECTS.items()}),
            CAR_ORDERING=json.dumps([[left, right] for left, right, _ in ORDERING]),
            CAR_MALFORMED=json.dumps(MALFORMED),
        )
        result = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", PROBE],
                                capture_output=True, text=True, timeout=300, env=environment)
        cls.result = result
        cls.answer = json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else {}

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-2000:])

    def test_a_tag_under_this_repository_is_read_as_its_three_numbers(self):
        for name, (_, expected) in sorted(REDIRECTS.items()):
            if expected is None:
                continue
            with self.subTest(name):
                self.assertEqual(self.answer["redirects"][name], expected)

    def test_everything_else_is_refused(self):
        """Each of these is a way an answer could come from somewhere that is not this
        project, or could be a version that is not a version."""
        for name, (_, expected) in sorted(REDIRECTS.items()):
            if expected is not None:
                continue
            with self.subTest(name):
                self.assertEqual(self.answer["redirects"][name], "REFUSED")

    def test_versions_are_ordered_as_numbers(self):
        for left, right, expected in ORDERING:
            with self.subTest("%s vs %s" % (left, right)):
                self.assertEqual(self.answer["ordering"]["%s %s" % (left, right)], expected)

    def test_a_version_that_is_not_one_is_refused(self):
        for bad in MALFORMED:
            with self.subTest(bad):
                self.assertEqual(self.answer["malformed"][str(bad)], "REFUSED")

    def test_it_asks_for_no_body_and_asks_only_the_constant(self):
        probe = self.answer["probe"]
        self.assertEqual(probe["method"], "Head", "a body that is never parsed is a body "
                                                  "that should not have been transferred")
        self.assertEqual(probe["asked"],
                         "https://github.com/%s/%s/releases/latest" % (OWNER, REPO))
        self.assertEqual(probe["calls"], 1, "one question, one request")

    def test_it_reads_the_final_url_on_powershell_7_too(self):
        self.assertEqual(self.answer["probe"]["pwsh7"], "1.2.3")

    def test_a_response_that_hides_where_it_came_from_is_refused(self):
        self.assertEqual(self.answer["probe"]["silent"], "REFUSED")

    def test_a_release_file_with_nothing_to_ask_is_refused(self):
        self.assertEqual(self.answer["probe"]["incomplete"], "REFUSED")

    def test_only_the_three_github_hosts_may_have_served_a_download(self):
        """`Assert-TrustedHost` guards every download, not only the update check, and a
        host that merely contains `github.com` is not one of them."""
        self.assertEqual(
            {name: verdict for name, verdict in sorted(self.answer["trust"].items())},
            {"assets": "ACCEPTED", "foreign": "REFUSED", "github": "ACCEPTED",
             "lookalike": "REFUSED", "nothing": "REFUSED", "objects": "ACCEPTED",
             "plain_http": "REFUSED", "subdomain": "REFUSED"})


@unittest.skipUnless(POWERSHELL.is_file(), "the bootstrap is PowerShell on Windows")
class EndToEndTests(unittest.TestCase):
    """The whole script, run, with nowhere to ask.

    The resolver tests above replace the network; these replace the answer. A copy of the
    plugin is pointed at a port nothing is listening on, which is what an offline machine,
    a blocked proxy and a GitHub outage all look like from here. What matters is that the
    script says so - a machine that could not ask must never be told it is up to date -
    and that it exits with a code of its own, distinct from the one for "current".
    """

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        root = Path(cls.folder.name) / "plugin"
        (root / "scripts").mkdir(parents=True)
        (root / ".codex-plugin").mkdir(parents=True)
        shutil.copyfile(BOOTSTRAP, root / "scripts" / "bootstrap.ps1")
        shutil.copyfile(ROOT / ".codex-plugin" / "plugin.json",
                        root / ".codex-plugin" / "plugin.json")
        release = json.loads((ROOT / "scripts" / "release.json").read_text(encoding="utf-8"))
        # Refused at once, with no name to look up and no packet leaving the machine.
        release["latest"] = "https://127.0.0.1:1/releases/latest"
        (root / "scripts" / "release.json").write_text(
            json.dumps(release, indent=2), encoding="utf-8")
        cls.script = root / "scripts" / "bootstrap.ps1"
        # An empty home, so the plugin's own version is the one it compares.
        cls.home = Path(cls.folder.name) / "home"
        cls.home.mkdir()

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def run_it(self, *arguments):
        """Both streams, always as text, and never None - a message that reads a stream
        which is not there hides the failure it was written to explain."""
        return subprocess.run(
            [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(self.script), *arguments],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300,
            # Decoded as UTF-8 rather than by the machine's locale: PowerShell's own error
            # messages are localised, and where they are not in the console's code page the
            # default reader raises inside its thread and hands back no output at all -
            # which reads as a product bug and is not one.
            text=True, encoding="utf-8", errors="replace",
            env=dict(os.environ, CODEX_AUTO_RESUME_PLUGIN_HOME=str(self.home)))

    def test_a_machine_that_cannot_ask_is_told_so(self):
        result = self.run_it("-CheckOnly")
        self.assertEqual(result.returncode, 12, (result.stdout or "")[-1500:])
        self.assertIn("update: unavailable", result.stdout)
        self.assertNotIn("update: current", result.stdout)
        self.assertIn("This says nothing about whether an update exists", result.stdout)

    def test_it_installs_nothing_when_it_cannot_ask(self):
        result = self.run_it("-Update")
        self.assertEqual(result.returncode, 12, (result.stdout or "")[-1500:])
        self.assertIn("update: unavailable", result.stdout)
        self.assertEqual(sorted(p.name for p in self.home.iterdir()), [])

    def test_the_two_questions_are_not_asked_together(self):
        result = self.run_it("-CheckOnly", "-Update")
        self.assertEqual(result.returncode, 12)
        self.assertIn("not both", result.stdout)

    def test_a_local_file_is_not_an_update(self):
        result = self.run_it("-Update", "-ArchivePath", str(self.script))
        self.assertEqual(result.returncode, 12)
        self.assertIn("different questions", result.stdout)

    def test_asking_reaches_the_network_and_nothing_else(self):
        """It refuses before it writes: no working directory, no partial install."""
        before = sorted(p.name for p in Path(self.folder.name).iterdir())
        self.run_it("-CheckOnly")
        self.assertEqual(sorted(p.name for p in Path(self.folder.name).iterdir()), before)


@unittest.skipUnless(POWERSHELL.is_file(), "the bootstrap is PowerShell on Windows")
class NeverGoesBackwardsTests(unittest.TestCase):
    """An installation is replaced by an older one only on purpose.

    `-Update` leaves the machine ahead of the plugin tree it was started from: Codex's copy
    of the plugin is still whatever version it fetched, and the installation is now newer.
    The next ordinary run of this script then sees a version it does not have. Before this
    guard, that run downloaded it and installed it over the newer one - silently, under the
    name of setting the plugin up, which Codex may do on its own.

    The installation here is a directory laid out the way `Get-InstalledVersion` reads it,
    with no network reachable, so a run that decides to download fails loudly instead of
    quietly succeeding.
    """

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.root = Path(cls.folder.name) / "plugin"
        (cls.root / "scripts").mkdir(parents=True)
        (cls.root / ".codex-plugin").mkdir(parents=True)
        shutil.copyfile(BOOTSTRAP, cls.root / "scripts" / "bootstrap.ps1")
        cls.manifest = json.loads(
            (ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        release = json.loads((ROOT / "scripts" / "release.json").read_text(encoding="utf-8"))
        # Nothing is listening, so any download attempt is an unmistakable failure.
        release["download"] = "https://127.0.0.1:1/releases/download/v{version}/"
        release["latest"] = "https://127.0.0.1:1/releases/latest"
        (cls.root / "scripts" / "release.json").write_text(
            json.dumps(release, indent=2), encoding="utf-8")
        cls.script = cls.root / "scripts" / "bootstrap.ps1"

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def plugin_at(self, version):
        manifest = dict(self.manifest, version=version)
        (self.root / ".codex-plugin" / "plugin.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8")

    def installation_at(self, version):
        """The three things `Get-InstalledVersion` looks at, and nothing else."""
        home = Path(self.folder.name) / ("home-" + version)
        (home / "runtime").mkdir(parents=True, exist_ok=True)
        (home / "runtime" / "python.exe").write_bytes(b"not a real interpreter")
        (home / "app" / ".codex-plugin").mkdir(parents=True, exist_ok=True)
        (home / "app" / ".codex-plugin" / "plugin.json").write_text(
            json.dumps({"name": "codex-auto-resume", "version": version}), encoding="utf-8")
        (home / "app" / "scripts").mkdir(parents=True, exist_ok=True)
        return home

    def run_it(self, home, *arguments):
        return subprocess.run(
            [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(self.script), *arguments],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300,
            text=True, encoding="utf-8", errors="replace",
            env=dict(os.environ, CODEX_AUTO_RESUME_PLUGIN_HOME=str(home)))

    def test_a_newer_installation_is_not_replaced_by_an_older_plugin(self):
        self.plugin_at("0.5.7")
        result = self.run_it(self.installation_at("0.6.0"))
        self.assertIn("0.6.0 is installed", result.stdout)
        self.assertIn("newer than", result.stdout)
        self.assertNotIn("Downloading", result.stdout)

    def test_the_same_version_still_reads_as_already_installed(self):
        self.plugin_at("0.6.0")
        result = self.run_it(self.installation_at("0.6.0"))
        self.assertIn("already installed", result.stdout)
        self.assertNotIn("newer than", result.stdout)
        self.assertNotIn("Downloading", result.stdout)

    def test_an_older_installation_is_still_upgraded(self):
        """The guard must not stop the case it was never about."""
        self.plugin_at("0.6.0")
        result = self.run_it(self.installation_at("0.5.7"))
        self.assertIn("Downloading v0.6.0", result.stdout)
        self.assertNotIn("already installed", result.stdout)

    def test_force_still_installs_over_a_newer_one(self):
        """Going back is allowed; it just has to be asked for."""
        self.plugin_at("0.5.7")
        result = self.run_it(self.installation_at("0.6.0"), "-Force")
        self.assertIn("Downloading v0.5.7", result.stdout)

    def test_an_installation_whose_version_cannot_be_read_is_not_treated_as_newer(self):
        home = self.installation_at("0.6.0")
        (home / "app" / ".codex-plugin" / "plugin.json").write_text("{ not json",
                                                                    encoding="utf-8")
        self.plugin_at("0.6.0")
        result = self.run_it(home)
        self.assertIn("Downloading v0.6.0", result.stdout)



if __name__ == "__main__":
    unittest.main()
