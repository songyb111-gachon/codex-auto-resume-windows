<#
    Turn a Codex plugin into a working installation.

    The Codex plugin is a source tree: skills, Python and a manifest. It is what a user
    gets from `codex plugin add`, and on its own it cannot recover anything, because the
    parts that do the work are a bundled Python runtime, a settings window and an MCP
    launcher - a runtime and two compiled binaries that have no business in a source
    repository. Codex has no install hook to put them there either; the plugin system
    offers skills, MCP servers, hosted app connectors and lifecycle hooks, and not one
    of them runs a command when a plugin is installed.

    So the plugin fetches its own release and installs it. That is a download and an
    execution, which means the interesting part of this script is what it refuses.

    What it will fetch
      * Exactly one URL shape, built from constants in scripts/release.json and a
        version this script chose. An ordinary run fetches the version in the plugin's
        own manifest and nothing else. -Update fetches the version it read out of a
        redirect under this exact repository, as three integers. -Version fetches a
        pre-release the update check would offer, which is how a person's yes to that offer
        reaches it, and what was typed never reaches the URL as typed: only a pre-release in
        this product's own grammar is accepted, and it is rebuilt from its integers and one of
        two words. -Pick fetches a version the list of releases offers, rebuilt the same way.
      * Over HTTPS, with TLS 1.2 at minimum, from github.com - and the final response
        URI has to be one of the three hosts in $AllowedHosts below, because a release
        download redirects to GitHub's object storage and nowhere else.

    What it verifies, before anything is executed
      * SHA-256. Against the digest pinned in scripts/release.json when there is one,
        and otherwise against the .sha256 published beside the archive. The pinned case
        is the strong one; the sidecar case is trust-on-first-use over TLS to GitHub.
        There is a third case, and it is the reason this paragraph is longer than it
        looks like it should be: a file handed to -ArchivePath has no sidecar to fetch,
        so with no pinned digest for that version nothing is compared at all and only
        the contents checks below stand behind it. This script prints which of the
        three it did rather than letting a reader assume the strongest one.
      * That the archive is a coherent build of this exact product and version: the
        files the release is defined to contain are all present, and the manifest
        inside it declares the same version as the plugin doing the fetching.
      * That no entry escapes the extraction directory.
      A failure at any point deletes what was downloaded and stops. Nothing is executed
      from an archive that did not pass.

    What it never does
      No administrator rights, no change to any Windows security setting, no execution
      policy change beyond this one process, nothing piped from the network into a
      shell, and no code from the archive is run before the archive has been verified.

    Asking whether there is a newer release
      -CheckOnly asks and answers. -Update asks, and installs the answer when it is
      newer. Neither happens unless a person asks for it: nothing here polls, and a
      watcher nobody has asked makes no request to github.com at all.

      The question is answered without parsing anything github.com sends. The request
      is a HEAD to the releases/latest URL in scripts/release.json, so no body is
      transferred, and the answer is read out of the URL the request ended at: the path
      has to begin with the exact owner and repository this product is published from,
      and what follows has to be a tag named vMAJOR.MINOR.PATCH. The version is rebuilt
      from those three integers, so the only thing that crosses from the network into a
      download URL is arithmetic.

      An update is refused unless it is strictly newer, compared as numbers and never as
      text. A local build ahead of everything published is reported as that and left
      alone. Everything an ordinary install verifies - the checksum, the contents, the
      version inside the archive - is verified for an update too, and it goes through the
      same installer, which keeps the state and the decisions already on the machine.

    Offering a pre-release
      releases/latest never names a pre-release, so -CheckOnly asks one more question once
      github.com has answered the first: one GET to GitHub's list of this repository's
      releases (`releases` in scripts/release.json, api.github.com, unauthenticated, the
      ten newest). It looks for the newest one that is published, not a draft, marked a
      pre-release, tagged vMAJOR.MINOR.PATCH-alpha or -beta with a stage's number, and
      newer than both the installed version and the newest release. It says so on a line
      of its own, `prerelease: v<version>`, and nothing else in the answer changes: a list
      that cannot be read, is too large or is malformed offers nothing, and the `update:`
      line and the exit code are the ones the first question gave. A redirect is not
      followed, so this request goes to api.github.com and nowhere else.

      Nothing installs a pre-release unless a person says yes to it: the settings window
      asks, and its yes runs -Version with the version offered. -Version asks both questions
      again first, because a release may have been published while the question was open, and
      installs only what the check would still offer: a pre-release the list names as
      published, newer than what is installed and newer than the newest release, over an
      installation, in its edition and keeping its state. A release newer than it is answered
      as the check answers it, `update: available`, and nothing is downloaded. A pre-release
      is never pinned, so it is verified against the .sha256 published beside it.

      Both of the check's later requests - this list and the compatibility data - are given a
      deadline of wall-clock time, not only -TimeoutSec: under Windows PowerShell 5.1 that
      bounds the wait for a response to begin, and a body that arrives slowly is read for as
      long as it keeps coming (Invoke-BoundedWebRequest).

    Listing the versions a person may pick
      -Versions is what the Dashboard's Install another version... asks when a person presses it,
      and at no other time. It reads the same list of this repository's releases through the one
      other address api.github.com is allowed for (`release_pages` in scripts/release.json): the
      same host and path, one page of thirty at a time, at most five pages, whose page number is
      the one thing put into it. Each page is checked as the update check's page is (Read-ReleasesPage),
      and a page that cannot be read, or a fifth as full as the rest, lists nothing at all:
      `versions: unavailable`, exit 12. It downloads nothing, installs nothing and does not refresh
      the compatibility data.

      -Pick installs one row of it, the version and edition a person confirmed, and asks for the
      list again first: a row no longer offered as it was shown installs nothing (`pick: refused
      changed`). -Force comes exactly with an older row or one of the other edition and is refused
      with any other. The archive is fetched, checked and unpacked as every install's is; only then,
      under the install lock, is the state converted for a version on schema 3 - the installed
      version's own downgrade-state, which asks the watcher to stop and waits for it a minute, and
      never kills it - and only then does the archive's installer run. Each answer is a `pick:` line.

      Each version, in each edition, is offered or refused with its reason on a line of its own:
      nothing older than v0.6.2, no archive or no checksum to check it by, an edition change to an
      installer older than editions, a policy an administrator set that the version would stop
      applying (the policy key is read, never written), and - while I12 says so - a pre-release the
      update check would not offer. The list's versions are rebuilt from their integers like every
      other version here (Get-ChosenVersion), and only the names of the assets are read.

    Which edition it installs
      There are two, and an installation is one or the other: the advanced edition is the
      standard one plus one package in app\src. Nothing is stamped anywhere to say which; the
      package being there is the fact, for the product and for this script alike. A run
      installs the edition -Edition names; without it, the edition already installed, so a
      repair or an update never leaves it; with nothing installed, this plugin tree's own -
      the standard edition for a plugin added from GitHub, whose tree has no advanced package.
      The edition only ever chooses between the two constant archive names in release.json.

      Moving between editions is a reinstall, never an update. -Update refuses -Edition. A run
      that would replace one edition with the other needs -Edition and -Force: without -Force
      it downloads nothing and exits 14; with both, it says what the change keeps and changes
      before it fetches anything, and tells the installer the change was asked for. An archive
      of the other edition is refused like an archive of another version.

    Refreshing the Codex compatibility data
      Only on request, at exactly two moments: -Compatibility (the Diagnostics page's
      refresh button), and an update check that reached github.com (-CheckOnly or -Update).
      Nothing here polls, and the watcher never asks.

      One GET to one constant URL with no query string - the registry file on the main
      branch of this repository, at raw.githubusercontent.com and at no other host. Nothing
      about this machine is in the request; in particular the local Codex version is not,
      which is why the whole document is fetched and matched locally. The body lands in a
      temporary file this script deletes, and it is never parsed or run here: it is handed
      to the installation's own Python validator (`controlcli compat-import`), which is the
      only thing that writes it anywhere, and refuses anything malformed, older than what
      is already in force, or meant for a newer product. The data can only ever restrict
      what the watcher does. A refresh that fails leaves everything as it was, and it never
      changes what the update check answers.

      It says so before it asks: the host is named on the output, update check or not, so a
      second address is never contacted silently. And when it rides on an update check it
      gets only what is left of the time the settings window waits for that check
      ($CheckBudgetSeconds below), as a deadline its download cannot overrun however slowly
      the bytes arrive, so it can make the check neither late nor "running" - with too little
      left it is not attempted, and the data already in force still applies.

    Run: powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
         Add -Force to reinstall a version that is already present.
         Add -ArchivePath <zip> to install a file you already have. It is checked
         against the pinned digest when this version has one; otherwise only the
         contents checks apply, because there is no sidecar to fetch for a local file.
         Add -CheckOnly to ask whether a newer release exists and install nothing.
         Add -Update to install one if there is.
         Add -Version <pre-release> to install the pre-release -CheckOnly offered.
         Add -Compatibility to refresh the Codex compatibility data and nothing else.
         Add -Versions to list the versions the Dashboard may install instead, and install nothing.
         Add -Pick <version> -Edition <edition> to install one of them (with -Force when it is older
         or of the other edition).
         Add -Edition Standard or -Edition Advanced to choose the edition; over the other
         edition, add -Force as well, which is what replacing it takes.
#>
[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$NoStartup,
    [string]$ArchivePath,
    [switch]$CheckOnly,
    [switch]$Update,
    [switch]$Compatibility,
    # A closed word, not a value: it only chooses which of two constant archive names is
    # fetched, and nothing of what was typed reaches a URL.
    [ValidateSet('Standard', 'Advanced')]
    [string]$Edition,
    # The pre-release a person said yes to when the update check offered it. Never spliced as
    # typed: Get-PrereleaseVersion accepts a pre-release in this product's grammar alone and
    # rebuilds it from its integers and one of two words.
    [string]$Version,
    # Lists every version a person may pick in the Dashboard's Install another version..., and why
    # each of the others cannot be. It installs nothing and takes no value.
    [switch]$Versions,
    # The version a person picked there and confirmed, with -Edition the edition of its row and -Force
    # exactly when that row is older or of the other edition. Never spliced as typed: Get-ChosenVersion
    # rebuilds it from its integers, and it is installed only if the list still offers it.
    [string]$Pick
)

# Started before anything else runs, so an update check can tell how much of its caller's
# patience is left for the compatibility refresh that rides on it ($CheckBudgetSeconds).
$ScriptClock = [Diagnostics.Stopwatch]::StartNew()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$PluginRoot = Split-Path -Parent $PSScriptRoot
$AllowedHosts = @('github.com', 'objects.githubusercontent.com', 'release-assets.githubusercontent.com')

# The Codex compatibility data's one address: a constant, with no query string and nothing
# about this machine in it. It is the bundled registry file, as it stands on main, where
# every change is a reviewed commit the tests validated before it could be served. Its host
# is allowed for this fetch alone - the archive's list above does not grow.
$CompatibilityUrl = 'https://raw.githubusercontent.com/songyb111-gachon/codex-auto-resume-windows/main/src/codex_auto_resume/data/codex_compat.json'
$CompatibilityHosts = @('raw.githubusercontent.com')
# The validator's own cap. A larger download is refused before Python is started.
$CompatibilityMaxBytes = 262144

# The refresh that rides on an update check shares that check's time. The settings window
# waits 120 s for -CheckOnly (gui/DashboardMaintenance.cs, CheckMilliseconds) and calls anything slower
# "running", and the update answer is printed after the refresh - so the refresh must be
# over, or never started, well inside that, whatever the network does. The HEAD to
# github.com alone can take its 60 s plus a name lookup, which -TimeoutSec does not count.
# The refresh gets what is left of $CheckBudgetSeconds after allowing for a lookup of its
# own and the validator's start, at most $CompatibilityCheckTimeoutMax, and is not attempted
# when that is under $CompatibilityCheckTimeoutMin. -Compatibility alone keeps 60 s.
$CheckBudgetSeconds = 90
$LookupAllowanceSeconds = 15
$ValidatorAllowanceSeconds = 10
$CompatibilityCheckTimeoutMax = 30
$CompatibilityCheckTimeoutMin = 5

# The update check's question about pre-releases: GitHub's list of this repository's releases,
# on its API host, which is allowed for that list alone - the update check's one page of it and the
# picker's pages of it (-Versions, below), and nothing else; the archive's list above does not
# grow. The list is the one body this script parses, so a larger one is refused before it is,
# and a malformed one offers nothing. It shares the check's time too, after the refresh, so it
# can make the check neither late nor "running": what is left of $CheckBudgetSeconds after a
# name lookup, at most $ReleasesTimeoutMax, and not attempted under $ReleasesTimeoutMin - a
# deadline for the whole request, body and all (Invoke-BoundedWebRequest). -Version, which the
# window waits far longer for, gives the same request $ReleasesVersionTimeout.
$ReleasesHosts = @('api.github.com')
$ReleasesMaxChars = 2097152
$ReleasesTimeoutMax = 15
$ReleasesTimeoutMin = 5
$ReleasesVersionTimeout = 60

# What -CheckOnly and -Update answer with. Four codes, because there are four answers and
# a caller that has to tell them apart should not have to read prose to do it. "Could not
# ask" is its own answer and never borrows the one for "up to date": a machine with no
# network would otherwise be told it is current, which is the one wrong thing an update
# check can say. An update that goes ahead exits with the installer's own code instead.
$ExitCurrent     = 0
$ExitAvailable   = 10
$ExitLocalNewer  = 11
$ExitUnavailable = 12
# -Compatibility answers with its own line, `compatibility: refreshed <sequence>`,
# `compatibility: refused <reason>` or `compatibility: unavailable`, and exits 0, 13 or 12.
# Refused is its own answer: the data arrived and the validator would not have it.
$ExitCompatibilityRefused = 13
# The other edition is installed and nothing said to replace it: nothing was downloaded and
# nothing changed. The installer refuses the same way with the same code, and Install.cmd
# reads it as its cue to ask.
$ExitOtherEdition = 14

# Install another version... (v0.6.12): which versions a person may pick, and which not.
# Nothing older than $PickFloor is offered: v0.6.0 and v0.6.1 verify with a cmdlet that did not
# resolve in the process the Dashboard starts, so from them the Dashboard could not bring a person
# back, and v0.5.x's installer has no --keep-state. The advanced edition begins at $EditionsSince,
# and an installer below it cannot be told an edition change was asked for, so a change of edition
# needs a target at least that new. The policy keys an administrator sets are read from
# $PolicySince on; while any of $PolicyValues is set, an older version would stop applying it, so
# none is offered. $PolicyValues are the values a version below $PolicySince would drop
# (src/codex_auto_resume/managed.py, VALUES): a value that guards a feature no older version has
# is not among them, since no older version could do what it holds back.
$PickFloor = '0.6.2'
$EditionsSince = '0.6.11-alpha'
$PolicySince = '0.6.11-beta'
$PolicyKeys = @('HKEY_LOCAL_MACHINE', 'HKEY_CURRENT_USER')
$PolicyPath = 'Software\Policies\CodexAutoResume'
$PolicyValues = @('DisableAutoResume', 'ForceObserveOnly', 'DisableUpdateCheck', 'DisableStatusFile',
                  'MaxRecoveryAttempts', 'QuietHours')
# The state's schema from each version on, newest first; the first row is this version's own. A
# target on the schema before it is offered with the state converted first (downgrade-state --to 3);
# a target on any other is not offered at all.
$StateSchemaSince = @(@('0.6.11-beta', 4), @('0.6.0', 3))
# The advanced settings' form from each version on, newest first; the first row is this version's
# own. An advanced target on an older form cannot read them: every advanced feature is off there.
$AdvancedStateSince = @(@('0.6.11-beta.2', 2), @('0.6.11-alpha', 1))
# The list is read page by page, $PickPageSize to a page (release_pages in release.json), at most
# $PickMaxPages of them - a page with fewer ends it, and a full last one is no answer - and all of it
# within $PickBudgetSeconds, each page within $PickPageTimeoutMax. The window waits longer than that
# for the answer.
$PickPageSize = 30
$PickMaxPages = 5
$PickBudgetSeconds = 150
$PickPageTimeoutMax = 30
# I12 as the owner amended it on 2026-10-03: its two pre-release clauses bind the update check's offer,
# and a version picked by name and confirmed - a pre-release too, older or newer - follows "older only
# with -Force", the confirmation being the yes. Both $false is I12 as it was written before: a
# pre-release only where the update check would offer that same one, the others greyed.
$PickNewerPrereleases = $true
$PickOlderPrereleases = $true
# -Pick refused to go ahead, and said why on its `pick: refused <reason>` line. Nothing was changed -
# except for `state`, which started the watcher again. Its own code: no answer to the update
# question, and not the other edition's refusal either.
$ExitPickRefused = 15

function Step { param([string]$Text) Write-Host ('  ' + $Text) }
function Ok   { param([string]$Text) Write-Host ('  [ok] ' + $Text) }
function Fail { param([string]$Text) Write-Host ('  [!] ' + $Text) -ForegroundColor Red }

function Get-Sha256 {
    <#
        The digest of a downloaded archive, computed with .NET rather than `Get-FileHash`.

        This is the one number that decides whether anything is installed, so it must not
        depend on a cmdlet resolving. `Get-FileHash` has now failed to resolve twice while
        every other cmdlet in the same script still worked: once under the release runner's
        PSModulePath, where `build/make_gui.ps1` moved off it for the same reason, and once
        in the process the Dashboard's update button starts on a user's machine, where the
        archive downloaded and then could not be verified. The second one is why this
        exists: the update refused to install, which was right, but the feature was
        unusable and the message named a cmdlet rather than anything a person could act on.

        `[Security.Cryptography.SHA256]` is part of the runtime PowerShell is already
        hosted in. There is nothing left to autoload.
    #>
    param([string]$Path)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $stream = [IO.File]::OpenRead((Resolve-Path $Path))
        try { return [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '').ToLower() }
        finally { $stream.Dispose() }
    } finally { $sha.Dispose() }
}

function Read-Json {
    param([string]$Path)
    if (-not (Test-Path $Path)) { throw ('This plugin is incomplete: ' + $Path + ' is missing.') }
    return Get-Content -Path $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Get-PluginVersion {
    $manifest = Read-Json (Join-Path $PluginRoot '.codex-plugin\plugin.json')
    # Under StrictMode a missing property throws before the check below can report it,
    # so ask whether it is there rather than reading it and hoping.
    if (-not $manifest.PSObject.Properties.Match('version').Count) {
        throw 'The plugin manifest has no version, so there is nothing to fetch.'
    }
    $version = $manifest.version
    # Strict semver, because the version is spliced into a URL. Anything else stops here
    # rather than reaching the network. The two suffixes are the literal -alpha and -beta of a
    # planned pre-release (v0.6.9-alpha, v0.6.11-beta), each naming its own tag and archive -
    # in lower case, as tags are: -cnotmatch, because -notmatch ignores case. A stage's later
    # pre-releases number it from .2 to .999 with no leading zero (v0.6.11-beta.2): the plain
    # word is its first, so there is no .0 or .1. \z, not $, which .NET also matches before a
    # final line break; [0-9], not \d, which takes any script's digits.
    # The same rule as every other check of this product's version (tests/test_version_rule.py).
    if ($version -cnotmatch '^[0-9]+\.[0-9]+\.[0-9]+(-(alpha|beta)(\.([2-9]|[1-9][0-9]{1,2}))?)?\z') {
        throw ('The plugin manifest declares an unusable version: ' + $version)
    }
    return $version
}

function Get-PinnedDigest {
    param($Release, [string]$Version)
    if (-not $Release.PSObject.Properties.Match('sha256').Count) { return $null }
    $table = $Release.sha256
    if ($null -eq $table) { return $null }
    if (-not $table.PSObject.Properties.Match($Version).Count) { return $null }
    $digest = $table.$Version
    if ([string]::IsNullOrWhiteSpace($digest)) { return $null }
    if ($digest -notmatch '^[0-9a-fA-F]{64}$') {
        throw ('scripts/release.json has a malformed digest for ' + $Version + '.')
    }
    return $digest.ToLower()
}

function Get-EditionRelease {
    <#
        The part of scripts/release.json that names and pins one edition's archive: an object
        with `archive` and `sha256`, which is how Get-PinnedDigest reads it.

        The top-level keys are the standard edition's and stay so, because every published
        bootstrap reads them from its own copy and has to go on finding the standard archive
        under the name it always built. The advanced edition's are a second constant under
        `advanced`. So an edition only ever chooses between two fixed templates.
    #>
    param($Release, [string]$Edition)
    if ($Edition -ne 'advanced') { return $Release }
    if (-not $Release.PSObject.Properties.Match('advanced').Count -or $null -eq $Release.advanced) {
        throw 'scripts/release.json names no advanced edition, so there is none to fetch.'
    }
    return $Release.advanced
}

function Get-FinalUri {
    param($Response)
    # Where the bytes actually came from, after redirects. Windows PowerShell 5.1 hands
    # back an HttpWebResponse, which spells it ResponseUri; PowerShell 7 hands back an
    # HttpResponseMessage, which does not have that property at all and spells it
    # RequestMessage.RequestUri. Reading only the 5.1 name would throw under StrictMode
    # on pwsh - fail closed, but fail closed on every download, which is not a check so
    # much as an outage. Neither present means we cannot tell, and the caller treats
    # cannot tell as a refusal.
    $base = $Response.BaseResponse
    if ($base.PSObject.Properties.Match('ResponseUri').Count) { return $base.ResponseUri }
    if ($base.PSObject.Properties.Match('RequestMessage').Count -and $base.RequestMessage) {
        return $base.RequestMessage.RequestUri
    }
    return $null
}

function Assert-TrustedHost {
    # The hosts a download may have come from are the caller's: the archive's three by
    # default, and the compatibility data's one for that fetch alone, so allowing a host for
    # one download never widens what may serve another.
    param($Response, [string]$What, [string[]]$Hosts = $AllowedHosts)
    $final = Get-FinalUri -Response $Response
    if ($null -eq $final) {
        throw ($What + ': this PowerShell does not report where the download came from, so it was refused.')
    }
    if ($final.Scheme -ne 'https' -or ($Hosts -notcontains $final.Host)) {
        throw ($What + ' was redirected to a host this installer does not trust: ' + $final.Host)
    }
}

function Invoke-BoundedWebRequest {
    <#
        Invoke-WebRequest with $Parameters, answered within $Seconds of being asked - lookup,
        response and body - or a throw.

        Under Windows PowerShell 5.1, which the settings window starts, -TimeoutSec bounds only
        the wait for a response to begin. The body is read after that for as long as bytes keep
        arriving: a list sent one byte a second kept a -TimeoutSec 5 request going for 29 s, and
        a 300 KB list over a very slow link does the same without anyone meaning it to. The window
        waits a fixed time for -CheckOnly and calls anything slower "running", so a request that
        rides on the check needs a deadline it cannot overrun. The request therefore runs in a
        runspace of its own, and this waits for it at most $Seconds; one still going then is
        stopped - Invoke-WebRequest aborts its connection when it is - and this throws.

        What runs there is what this session would run under the name: the cmdlet, or a function
        standing in for it, carried over by its text - which is how the tests replace the network,
        so a stand-in is never passed over for the real one. Anything else under the name is
        refused rather than guessed at.
    #>
    param([hashtable]$Parameters, [int]$Seconds, [string]$What)
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $command = Get-Command -Name Invoke-WebRequest -ErrorAction Stop
    $state = [Management.Automation.Runspaces.InitialSessionState]::CreateDefault()
    if ($command.CommandType -eq 'Function') {
        $state.Commands.Add((New-Object Management.Automation.Runspaces.SessionStateFunctionEntry `
                                        -ArgumentList 'Invoke-WebRequest', $command.Definition))
    } elseif ($command.CommandType -ne 'Cmdlet') {
        throw ('Invoke-WebRequest is a ' + $command.CommandType + ' here, which this script does not run.')
    }
    $runspace = [Management.Automation.Runspaces.RunspaceFactory]::CreateRunspace($state)
    $shell = [PowerShell]::Create()
    $finished = $false
    try {
        $runspace.Open()
        $shell.Runspace = $runspace
        [void]$shell.AddCommand('Invoke-WebRequest')
        foreach ($name in $Parameters.Keys) { [void]$shell.AddParameter($name, $Parameters[$name]) }
        [void]$shell.AddParameter('ErrorAction', 'Stop')
        $pending = $shell.BeginInvoke()
        $left = [int][Math]::Max(0, $Seconds * 1000 - $clock.ElapsedMilliseconds)
        if (-not $pending.AsyncWaitHandle.WaitOne($left)) {
            # A moment for it to let go of a file it was writing, so the caller can remove it.
            $finished = $shell.BeginStop($null, $null).AsyncWaitHandle.WaitOne(2000)
            throw ($What + ' did not arrive within ' + $Seconds + ' s.')
        }
        $finished = $true
        try { $answer = @($shell.EndInvoke($pending)) }
        catch {
            $inner = $_.Exception
            while ($null -ne $inner.InnerException) { $inner = $inner.InnerException }
            throw ($What + ' could not be fetched: ' + $inner.Message)
        }
        if ($answer.Count -eq 0) { return $null }
        return $answer[0]
    } finally {
        # One that would not stop ends with this process; disposing it here would wait for it.
        if ($finished) { $shell.Dispose(); $runspace.Dispose() }
    }
}

function Get-VersionParts {
    param([string]$Version)
    # Get-PluginVersion's rule, with a ceiling on each number so it stays an integer.
    if ($Version -cnotmatch '^([0-9]{1,6})\.([0-9]{1,6})\.([0-9]{1,6})(?:-(alpha|beta)(?:\.([2-9]|[1-9][0-9]{1,2}))?)?\z') {
        throw ('Not a version this product uses: ' + $Version)
    }
    # A fourth and a fifth part order the pre-releases just before their own release - the
    # stage, then its number, where the plain word is the stage's first:
    # 0.6.11-alpha < 0.6.11-alpha.2 < 0.6.11-beta < 0.6.11-beta.2 < 0.6.11.
    $stage = 2
    $number = 0
    if ($Matches[4] -ceq 'alpha') { $stage = 0 }
    elseif ($Matches[4] -ceq 'beta') { $stage = 1 }
    if ($stage -lt 2) {
        $number = 1
        if ($Matches[5]) { $number = [int]$Matches[5] }
    }
    return @([int]$Matches[1], [int]$Matches[2], [int]$Matches[3], $stage, $number)
}

function Format-UnreadVersion {
    # An installed manifest's version this copy could not read, as it may be printed: printable
    # ASCII and not much of it. It is shown so a person can tell a newer build from a broken one,
    # and a line break in it must never print a line that reads like one of this script's answers.
    param($Version)
    $shown = ([string]$Version) -replace '[^\x20-\x7E]', '?'
    if ($shown.Length -gt 40) { $shown = $shown.Substring(0, 40) + '...' }
    return $shown
}

function Compare-ProductVersion {
    param([string]$Left, [string]$Right)
    # -1, 0 or 1, as integers. Compared as text, '0.10.0' sorts before '0.9.0' and the tenth
    # minor release of a line would look like a downgrade.
    $a = Get-VersionParts $Left
    $b = Get-VersionParts $Right
    for ($i = 0; $i -lt 5; $i++) {
        if ($a[$i] -lt $b[$i]) { return -1 }
        if ($a[$i] -gt $b[$i]) { return 1 }
    }
    return 0
}

function Get-NewestPublishedVersion {
    param($Release)
    foreach ($name in @('owner', 'repo', 'latest')) {
        if (-not $Release.PSObject.Properties.Match($name).Count) {
            throw ('scripts/release.json has no "' + $name + '", so there is nothing to ask.')
        }
    }
    # HEAD, so the tag page's body is never transferred - and therefore never available
    # to be parsed by a later change to this script. The answer is the URL, not the page.
    $response = Invoke-WebRequest -Uri $Release.latest -UseBasicParsing -Method Head `
                                  -MaximumRedirection 5 -TimeoutSec 60
    Assert-TrustedHost -Response $response -What 'The release page'
    $final = Get-FinalUri -Response $response
    # Asked again rather than assumed. Assert-TrustedHost refuses a response that will
    # not say where it came from, so this is unreachable today; it is here because every
    # line below reads a property of $final, and "the check above would have caught it"
    # is the shape of reasoning that stops being true when the check above is edited.
    if ($null -eq $final) { throw 'The release page did not say where it came from.' }
    if ($final.Host -ne 'github.com') {
        throw ('The release page ended on ' + $final.Host + ', which does not answer for this project.')
    }
    # The literal owner and repository, not a pattern. A redirect to a fork, or to
    # another repository of the same owner, is a different project's release, and a
    # release page that answers for a different project answers nothing here.
    $expected = '/' + $Release.owner + '/' + $Release.repo + '/releases/tag/'
    if (-not $final.AbsolutePath.StartsWith($expected, [StringComparison]::Ordinal)) {
        throw ('The release page redirected outside this repository: ' + $final.AbsolutePath)
    }
    $tag = $final.AbsolutePath.Substring($expected.Length)
    if ($tag -notmatch '^v[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}\z') {
        throw ('The newest release is not tagged the way this product tags releases: ' + $tag)
    }
    # Rebuilt from the three numbers rather than reused as text: what reaches the URL
    # below is arithmetic, and a leading zero or an unexpected character cannot survive
    # being turned into an integer and back.
    $parts = $tag.Substring(1).Split('.')
    return ([string][int]$parts[0]) + '.' + ([string][int]$parts[1]) + '.' + ([string][int]$parts[2])
}

function Get-PrereleaseVersion {
    <#
        A pre-release's version as this product writes it, rebuilt, or a throw: MAJOR.MINOR.PATCH,
        then -alpha or -beta, then a stage's later number .2 to .999 - the rule every check of this
        product's version applies (tests/test_version_rule.py), less the release, which is not a
        pre-release. What comes back is made of integers and one of two literal words, and it has to
        be exactly what came in: a leading zero is a tag this product never makes, and rebuilding it
        would name a different tag from the one that was read or offered.
    #>
    param([string]$Text)
    if ($Text -cnotmatch '^([0-9]{1,6})\.([0-9]{1,6})\.([0-9]{1,6})-(alpha|beta)(?:\.([2-9]|[1-9][0-9]{1,2}))?\z') {
        throw ('Not a pre-release this product publishes: ' + (Format-UnreadVersion $Text))
    }
    $word = 'beta'
    if ($Matches[4] -ceq 'alpha') { $word = 'alpha' }
    $rebuilt = ([string][int]$Matches[1]) + '.' + ([string][int]$Matches[2]) + '.' + ([string][int]$Matches[3]) + '-' + $word
    if ($Matches[5]) { $rebuilt += '.' + ([string][int]$Matches[5]) }
    if ($rebuilt -cne $Text) { throw ('Not a pre-release this product publishes: ' + (Format-UnreadVersion $Text)) }
    return $rebuilt
}

function Get-ChosenVersion {
    <#
        Any version this product publishes, rebuilt, or a throw: a release, MAJOR.MINOR.PATCH, from
        its three integers, or a pre-release by Get-PrereleaseVersion - the rule every check of this
        product's version applies (tests/test_version_rule.py). What comes back has to be exactly
        what came in, for the reason Get-PrereleaseVersion gives. It is what -Pick and a tag in the
        list of releases are read through, so what reaches a URL from either is arithmetic.
    #>
    param([string]$Text)
    if ($Text -cmatch '^([0-9]{1,6})\.([0-9]{1,6})\.([0-9]{1,6})\z') {
        $rebuilt = ([string][int]$Matches[1]) + '.' + ([string][int]$Matches[2]) + '.' + ([string][int]$Matches[3])
        if ($rebuilt -cne $Text) { throw ('Not a version this product publishes: ' + (Format-UnreadVersion $Text)) }
        return $rebuilt
    }
    try { return Get-PrereleaseVersion $Text }
    catch { throw ('Not a version this product publishes: ' + (Format-UnreadVersion $Text)) }
}

function Read-ReleasesPage {
    <#
        One page of GitHub's list of this repository's releases, as a list, or a throw where it
        cannot be read. Both readers of the list - the update check's (Get-PublishedPrereleases) and
        the picker's (Get-ReleasePages) - come through here, so neither checks less than the other.

        One GET, unauthenticated, to $Uri, a constant of scripts/release.json, with a deadline of
        $TimeoutSec for all of it (Invoke-BoundedWebRequest). No redirect is followed, the answer
        has to come from api.github.com for this exact owner and repository, a body over
        $ReleasesMaxChars is refused before it is parsed, and a body that is not a JSON list is no
        list. What the entries hold is the caller's to read.
    #>
    param($Release, [string]$Uri, [int]$TimeoutSec)
    $response = Invoke-BoundedWebRequest -What 'The list of releases' -Seconds $TimeoutSec -Parameters @{
        Uri = $Uri; UseBasicParsing = $true; Method = 'Get'; MaximumRedirection = 0
        TimeoutSec = $TimeoutSec }
    if ($null -eq $response) { throw 'The list of releases was empty.' }
    Assert-TrustedHost -Response $response -What 'The list of releases' -Hosts $ReleasesHosts
    $final = Get-FinalUri -Response $response
    # The literal owner and repository, as the release page's are: another repository's list says
    # nothing about this one.
    $expected = '/repos/' + $Release.owner + '/' + $Release.repo + '/releases'
    if ($final.AbsolutePath -cne $expected) {
        throw ('The list of releases came from outside this repository: ' + $final.AbsolutePath)
    }
    if (-not $response.PSObject.Properties.Match('Content').Count) { throw 'The list of releases was empty.' }
    $body = [string]$response.Content
    if ($body.Length -gt $ReleasesMaxChars) { throw 'The list of releases is larger than this script reads.' }
    if (-not $body.TrimStart().StartsWith('[', [StringComparison]::Ordinal)) {
        throw 'The list of releases is not a list.'
    }
    # Windows PowerShell hands a JSON list back as one array and PowerShell 7 as its items, so
    # both are made into the same list here.
    $list = @(ConvertFrom-Json -InputObject $body)
    if ($list.Count -eq 1 -and $list[0] -is [array]) { $list = @($list[0]) }
    return ,$list
}

function Get-PublishedPrereleases {
    <#
        Every pre-release GitHub's list of this repository's releases names as published, by this
        product's version rule - or a throw where the list cannot be read.

        One page: the constant `releases` in scripts/release.json, read by Read-ReleasesPage with a
        deadline of $TimeoutSec. An entry counts only when it is published (`draft` false), a
        pre-release (`prerelease` true) and tagged `v` and a version Get-PrereleaseVersion accepts;
        anything else in the list, or about an entry, is passed over.
    #>
    param($Release, [int]$TimeoutSec = 15)
    foreach ($name in @('owner', 'repo', 'releases')) {
        if (-not $Release.PSObject.Properties.Match($name).Count) {
            throw ('scripts/release.json has no "' + $name + '", so there is no list to read.')
        }
    }
    $list = Read-ReleasesPage -Release $Release -Uri $Release.releases -TimeoutSec $TimeoutSec
    $found = @()
    foreach ($entry in $list) {
        if ($entry -isnot [Management.Automation.PSCustomObject]) { continue }
        $fields = $entry.PSObject.Properties
        if (-not $fields.Match('draft').Count -or -not $fields.Match('prerelease').Count -or
            -not $fields.Match('tag_name').Count) { continue }
        if ($entry.draft -isnot [bool] -or $entry.draft) { continue }
        if ($entry.prerelease -isnot [bool] -or -not $entry.prerelease) { continue }
        $tag = $entry.tag_name
        if ($tag -isnot [string] -or -not $tag.StartsWith('v', [StringComparison]::Ordinal)) { continue }
        try { $found += ,(Get-PrereleaseVersion $tag.Substring(1)) } catch { continue }
    }
    return ,$found
}

function Get-NewerPrerelease {
    <#
        The newest pre-release this repository has published (Get-PublishedPrereleases) that is newer
        than both $Installed and $Stable, the newest release - or $null where there is none. It throws
        where the list cannot be read, and the caller takes that as nothing to offer, never as an
        answer about the release.
    #>
    param($Release, [string]$Installed, [string]$Stable, [int]$TimeoutSec = 15)
    $best = $null
    foreach ($candidate in (Get-PublishedPrereleases -Release $Release -TimeoutSec $TimeoutSec)) {
        if ((Compare-ProductVersion -Left $candidate -Right $Installed) -le 0) { continue }
        if ((Compare-ProductVersion -Left $candidate -Right $Stable) -le 0) { continue }
        if ($null -eq $best -or (Compare-ProductVersion -Left $candidate -Right $best) -gt 0) { $best = $candidate }
    }
    return $best
}

function Get-ReleasePages {
    <#
        Every release GitHub's list of this repository's releases names as published, read page by
        page for the picker - or a throw where any page cannot be read, so the answer is never a
        part of the list taken for all of it.

        Page 1, 2, ... of the constant `release_pages` in scripts/release.json, whose `{page}` is the
        one thing put into it, each read by Read-ReleasesPage within what is left of
        $PickBudgetSeconds, at most $PickPageTimeoutMax. A page with fewer than $PickPageSize entries
        is the last; no more than $PickMaxPages are asked for, newest first, which is many times what
        is published above $PickFloor - and a last one asked for that is as full as the rest is a
        throw too, since more may follow it, and the oldest would be left out unsaid. An entry
        counts only when it is published (`draft` false), tagged `v` and a version
        Get-ChosenVersion accepts, marked a pre-release exactly when its version is one, and has a
        list of assets; of the assets only their names are kept, and only names that are text. A version the list names twice is taken where it is named first.
        Each comes back as Version, Prerelease and Assets.
    #>
    param($Release)
    foreach ($name in @('owner', 'repo', 'release_pages')) {
        if (-not $Release.PSObject.Properties.Match($name).Count) {
            throw ('scripts/release.json has no "' + $name + '", so there is no list to read.')
        }
    }
    $template = [string]$Release.release_pages
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $found = @()
    $seen = @{}
    $ended = $false
    for ($page = 1; $page -le $PickMaxPages; $page++) {
        $left = $PickBudgetSeconds - $clock.Elapsed.TotalSeconds
        $seconds = [int][Math]::Floor([Math]::Min([double]$PickPageTimeoutMax, $left))
        if ($seconds -lt $ReleasesTimeoutMin) { throw 'Too little time was left to read the rest of the list of releases.' }
        $list = Read-ReleasesPage -Release $Release -Uri $template.Replace('{page}', [string]$page) -TimeoutSec $seconds
        foreach ($entry in $list) {
            if ($entry -isnot [Management.Automation.PSCustomObject]) { continue }
            $fields = $entry.PSObject.Properties
            if (-not $fields.Match('draft').Count -or -not $fields.Match('prerelease').Count -or
                -not $fields.Match('tag_name').Count -or -not $fields.Match('assets').Count) { continue }
            if ($entry.draft -isnot [bool] -or $entry.draft) { continue }
            if ($entry.prerelease -isnot [bool]) { continue }
            $tag = $entry.tag_name
            if ($tag -isnot [string] -or -not $tag.StartsWith('v', [StringComparison]::Ordinal)) { continue }
            $number = $null
            try { $number = Get-ChosenVersion $tag.Substring(1) } catch { continue }
            if ($entry.prerelease -ne $number.Contains('-')) { continue }
            if ($null -eq $entry.assets -or $entry.assets -isnot [array]) { continue }
            $names = @()
            foreach ($asset in $entry.assets) {
                if ($asset -isnot [Management.Automation.PSCustomObject]) { continue }
                if (-not $asset.PSObject.Properties.Match('name').Count -or $asset.name -isnot [string]) { continue }
                $names += ,$asset.name
            }
            if ($seen.ContainsKey($number)) { continue }
            $seen[$number] = $true
            $found += ,([pscustomobject]@{ Version = $number; Prerelease = $entry.prerelease; Assets = $names })
        }
        if ($list.Count -lt $PickPageSize) { $ended = $true; break }
    }
    if (-not $ended) {
        throw ('The list of releases goes on past the ' + $PickMaxPages + ' pages read, so none of it is shown.')
    }
    return ,$found
}

function Get-PolicyInForce {
    <#
        Whether an administrator's policy key holds anything a version below $PolicySince would stop
        applying: any of $PolicyValues by name, under either of $PolicyKeys - or a key that is there
        and cannot be read, which may hold any of them. No network, and read only: the key is opened
        and its value names listed, nothing is written, and no value is parsed. So a value managed.py
        would ignore as malformed still counts here: it can only make the picker offer less.
    #>
    foreach ($root in $PolicyKeys) {
        $names = @()
        try {
            $key = Get-Item -LiteralPath ('Registry::' + $root + '\' + $PolicyPath) -ErrorAction Stop
            $names = @($key.GetValueNames())
        } catch [Management.Automation.ItemNotFoundException] {
            continue
        } catch {
            return $true
        }
        foreach ($name in $names) {
            if ($PolicyValues -contains [string]$name) { return $true }
        }
    }
    return $false
}

function Get-SinceValue {
    # The value a table of (version, value) rows, newest first, gives $Version: the first row whose
    # version it is at or past - or $null where it is older than all of them.
    param([string]$Version, $Table)
    foreach ($row in $Table) {
        if ((Compare-ProductVersion -Left $Version -Right $row[0]) -ge 0) { return $row[1] }
    }
    return $null
}

function Get-VersionVerdict {
    <#
        What the picker says of one version in one edition, from the list's $Entry, the installed
        $Installed and $InstalledEdition, scripts/release.json's $Release, whether a policy is in
        force ($Policy, Get-PolicyInForce), the update check's own offer of a pre-release ($Offer)
        and the newest release ($Latest). $null where the row is not shown at all: below
        $PickFloor, or advanced below $EditionsSince. Otherwise Version, Edition, Answer and Detail,
        the first that applies:
          installed -            the version and edition installed
          refused no-archive     no archive of this edition was published under this number
          refused no-checksum    neither a pinned digest nor a published .sha256 to check it by
          refused edition-first  another edition, and its installer predates editions
          refused managed-policy a policy is in force, and this version would stop applying it
          refused older-prerelease  a pre-release older than what is installed
          refused not-offered    a pre-release, not older than what is installed, that is not the
                                 update check's own offer (the version installed, in the other
                                 edition, never is)
          offered <words>        newer|older|same, release|prerelease, kept|convert3, and any of
                                 latest, edition, advanced-off - comma-joined, in that order
    #>
    param($Entry, [string]$Edition, [string]$Installed, [string]$InstalledEdition, $Release,
          [bool]$Policy, $Offer, $Latest)
    $number = [string]$Entry.Version
    if ((Compare-ProductVersion -Left $number -Right $PickFloor) -lt 0) { return $null }
    if ($Edition -eq 'advanced' -and (Compare-ProductVersion -Left $number -Right $EditionsSince) -lt 0) { return $null }
    $schema = Get-SinceValue -Version $number -Table $StateSchemaSince
    if ($schema -ne $StateSchemaSince[0][1] -and $schema -ne 3) { return $null }
    $order = Compare-ProductVersion -Left $number -Right $Installed
    $other = $Edition -ne $InstalledEdition
    $row = [pscustomobject]@{ Version = $number; Edition = $Edition; Answer = 'refused'; Detail = '' }
    if ($order -eq 0 -and -not $other) { $row.Answer = 'installed'; $row.Detail = '-'; return $row }
    $template = Get-EditionRelease -Release $Release -Edition $Edition
    $archive = $template.archive.Replace('{version}', $number)
    $assets = @($Entry.Assets)
    if ($assets -cnotcontains $archive) { $row.Detail = 'no-archive'; return $row }
    if (-not (Get-PinnedDigest -Release $template -Version $number) -and $assets -cnotcontains ($archive + '.sha256')) {
        $row.Detail = 'no-checksum'; return $row
    }
    if ($other -and (Compare-ProductVersion -Left $number -Right $EditionsSince) -lt 0) { $row.Detail = 'edition-first'; return $row }
    if ($Policy -and (Compare-ProductVersion -Left $number -Right $PolicySince) -lt 0) { $row.Detail = 'managed-policy'; return $row }
    if ($Entry.Prerelease -and $order -lt 0 -and -not $PickOlderPrereleases) { $row.Detail = 'older-prerelease'; return $row }
    # The check offers its pre-release over the installation, in its edition: a pre-release of the
    # other edition is no offer the check makes, and neither is the one installed, in either.
    if ($Entry.Prerelease -and $order -ge 0 -and -not $PickNewerPrereleases -and ($other -or $number -cne [string]$Offer)) {
        $row.Detail = 'not-offered'; return $row
    }
    $words = @()
    if ($order -gt 0) { $words += 'newer' } elseif ($order -lt 0) { $words += 'older' } else { $words += 'same' }
    if ($Entry.Prerelease) { $words += 'prerelease' } else { $words += 'release' }
    if ($schema -eq $StateSchemaSince[0][1]) { $words += 'kept' } else { $words += 'convert3' }
    if (-not $Entry.Prerelease -and $number -ceq [string]$Latest) { $words += 'latest' }
    if ($other) { $words += 'edition' }
    if ($Edition -eq 'advanced' -and (Get-SinceValue -Version $number -Table $AdvancedStateSince) -ne $AdvancedStateSince[0][1]) {
        $words += 'advanced-off'
    }
    $row.Answer = 'offered'
    $row.Detail = $words -join ','
    return $row
}

function Get-VersionTable {
    <#
        Every row the picker shows, newest first and, at one version, the installed edition first -
        from the list Get-ReleasePages read - with the newest release ($null where the list names
        none) and the update check's own offer: the rule of Get-NewerPrerelease applied to this list,
        the newest pre-release newer than both what is installed and the newest release.
    #>
    param($Listed, [string]$Installed, [string]$InstalledEdition, $Release, [bool]$Policy)
    $latest = $null
    foreach ($entry in $Listed) {
        if ($entry.Prerelease) { continue }
        if ($null -eq $latest -or (Compare-ProductVersion -Left $entry.Version -Right $latest) -gt 0) { $latest = $entry.Version }
    }
    $offer = $null
    foreach ($entry in $Listed) {
        if (-not $entry.Prerelease) { continue }
        if ((Compare-ProductVersion -Left $entry.Version -Right $Installed) -le 0) { continue }
        if ($null -ne $latest -and (Compare-ProductVersion -Left $entry.Version -Right $latest) -le 0) { continue }
        if ($null -eq $offer -or (Compare-ProductVersion -Left $entry.Version -Right $offer) -gt 0) { $offer = $entry.Version }
    }
    # Sorted by the five numbers Compare-ProductVersion compares, written to sort as text.
    $sorted = @($Listed | Sort-Object -Descending -Property @{ Expression = {
        (Get-VersionParts $_.Version | ForEach-Object { '{0:D6}' -f $_ }) -join '.' } })
    $otherEdition = 'advanced'
    if ($InstalledEdition -eq 'advanced') { $otherEdition = 'standard' }
    $editions = @($InstalledEdition, $otherEdition)
    $rows = @()
    foreach ($entry in $sorted) {
        foreach ($edition in $editions) {
            $row = Get-VersionVerdict -Entry $entry -Edition $edition -Installed $Installed -InstalledEdition $InstalledEdition `
                                      -Release $Release -Policy $Policy -Offer $offer -Latest $latest
            if ($null -ne $row) { $rows += ,$row }
        }
    }
    return [pscustomobject]@{ Rows = $rows; Latest = $latest; Offer = $offer }
}

function Get-Remote {
    # -Deadline makes -TimeoutSec a deadline for the whole download (Invoke-BoundedWebRequest): what
    # rides on an update check takes it. An archive never does - on a slow link it simply takes long.
    param([string]$Uri, [string]$OutFile, [string]$What, [string[]]$Hosts = $AllowedHosts,
          [int]$TimeoutSec = 300, [switch]$Deadline)
    # -UseBasicParsing keeps this working on a Windows with no Internet Explorer engine,
    # which is every current one.
    if ($Deadline) {
        $response = Invoke-BoundedWebRequest -What $What -Seconds $TimeoutSec -Parameters @{
            Uri = $Uri; OutFile = $OutFile; UseBasicParsing = $true; PassThru = $true; MaximumRedirection = 5
            TimeoutSec = $TimeoutSec }
    } else {
        $response = Invoke-WebRequest -Uri $Uri -OutFile $OutFile -UseBasicParsing -PassThru `
                                     -MaximumRedirection 5 -TimeoutSec $TimeoutSec
    }
    Assert-TrustedHost -Response $response -What $What -Hosts $Hosts
}

function Get-CompatibilityTimeout {
    <#
        The seconds the refresh that rides on an update check may wait for its download,
        given how long this script has already run: what is left of $CheckBudgetSeconds
        after a name lookup and the validator's start, at most $CompatibilityCheckTimeoutMax
        - and 0, meaning do not try, when that is under $CompatibilityCheckTimeoutMin.
    #>
    param([double]$Elapsed)
    $left = $CheckBudgetSeconds - $Elapsed - $LookupAllowanceSeconds - $ValidatorAllowanceSeconds
    $seconds = [int][Math]::Floor([Math]::Min([double]$CompatibilityCheckTimeoutMax, $left))
    if ($seconds -lt $CompatibilityCheckTimeoutMin) { return 0 }
    return $seconds
}

function Get-ReleasesListTimeout {
    # The seconds the update check's question about pre-releases may wait, given how long this
    # script has already run: what is left of $CheckBudgetSeconds after a name lookup, at most
    # $ReleasesTimeoutMax - and 0, meaning do not ask, when that is under $ReleasesTimeoutMin.
    param([double]$Elapsed)
    $left = $CheckBudgetSeconds - $Elapsed - $LookupAllowanceSeconds
    $seconds = [int][Math]::Floor([Math]::Min([double]$ReleasesTimeoutMax, $left))
    if ($seconds -lt $ReleasesTimeoutMin) { return 0 }
    return $seconds
}

function Update-CompatibilityData {
    <#
        Fetch the Codex compatibility data from its one address and hand it to the
        installation's Python validator - the only thing that writes it anywhere.

        Returns the answer for the `compatibility:` line - 'refreshed <sequence>',
        'refused <reason>' or 'unavailable' - and never throws: a refresh that could not
        happen is an answer, and it must never change what an update check answers.
        Nothing is downloaded where there is no installation to validate it with, or with
        -TimeoutSec 0 (no time left), and the host is named on the output before it is asked.
    #>
    param([string]$Home_, [string]$Python, [string]$Source, [int]$TimeoutSec = 60)
    if (-not $Python) { $Python = Join-Path $Home_ 'runtime\python.exe' }
    if (-not $Source) { $Source = Join-Path $Home_ 'app\src' }
    if (-not (Test-Path -LiteralPath $Python) -or
        -not (Test-Path -LiteralPath (Join-Path $Source 'codex_auto_resume\controlcli.py'))) {
        Step 'There is no installation here to check the Codex compatibility data with, so it was not asked for.'
        return 'unavailable'
    }
    if ($TimeoutSec -le 0) {
        Step 'Too little of the update check''s time is left to ask for the Codex compatibility data;'
        Step 'it was not asked for, and the data already in force still applies.'
        return 'unavailable'
    }
    Step 'Asking raw.githubusercontent.com for the Codex compatibility data. Nothing is uploaded,'
    Step 'and nothing is kept unless this installation''s validator accepts it.'
    $folder = Join-Path ([IO.Path]::GetTempPath()) ('codex-auto-resume-compat-' + [Guid]::NewGuid().ToString('N'))
    try {
        try {
            [Net.ServicePointManager]::SecurityProtocol =
                [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13
        } catch {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        }
        New-Item -ItemType Directory -Force -Path $folder | Out-Null
        $file = Join-Path $folder 'codex_compat.json'
        try {
            Get-Remote -Uri $CompatibilityUrl -OutFile $file -What 'The compatibility data' `
                       -Hosts $CompatibilityHosts -TimeoutSec $TimeoutSec -Deadline
        } catch { return 'unavailable' }
        if (-not (Test-Path -LiteralPath $file)) { return 'unavailable' }
        if ((Get-Item -LiteralPath $file).Length -gt $CompatibilityMaxBytes) { return 'refused too_large' }
        # The bridge's own entry, as the settings window starts it; the path travels as its
        # own argument, which survives a non-ASCII profile directory.
        $code = 'import sys;sys.path.insert(0,sys.argv[1]);from codex_auto_resume.controlcli import main;sys.exit(main(sys.argv[2:]))'
        $ErrorActionPreference = 'Continue'
        $printed = @(& $Python -c $code $Source --home $Home_ compat-import --file $file --origin main)
        $line = @($printed | Where-Object { $_ -and ([string]$_).Trim() }) | Select-Object -Last 1
        if (-not $line) { return 'unavailable' }
        $reply = ([string]$line) | ConvertFrom-Json
        if ($reply.ok -ne $true) { return 'unavailable' }
        $result = $reply.result
        if ($result.imported -eq $true) { return ('refreshed ' + [string][int]$result.sequence) }
        $reason = [string]$result.reason
        if ($reason -notmatch '^[a-z_]{1,40}$') { $reason = 'invalid_field' }
        return ('refused ' + $reason)
    } catch {
        return 'unavailable'
    } finally {
        Remove-Item -Recurse -Force -LiteralPath $folder -ErrorAction SilentlyContinue
    }
}

function Get-CompatibilityExit {
    param([string]$Answer)
    if ($Answer -like 'refreshed *') { return 0 }
    if ($Answer -like 'refused *') { return $ExitCompatibilityRefused }
    return $ExitUnavailable
}

function Test-Archive {
    # An archive nothing asks an edition of is held to the standard one: what every archive
    # was before there were two.
    param([string]$Zip, [string]$Version, [string]$Edition = 'standard')
    # Everything the release is defined to contain. The same list the release workflow
    # checks before publishing, so "it built" and "it downloaded" mean the same thing.
    $required = @('payload/runtime/python.exe',
                  'payload/app/src/codex_auto_resume/mcpserver.py',
                  'payload/app/mcp/codex-auto-resume-mcp.exe',
                  'payload/app/.mcp.json',
                  'payload/app/.codex-plugin/plugin.json',
                  'payload/app/scripts/plugin_setup.py',
                  'payload/CodexAutoResumeSettings.exe',
                  'install/install.ps1',
                  'Install.cmd')
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead((Resolve-Path $Zip))
    try {
        $names = @($archive.Entries.FullName)
        foreach ($entry in $required) {
            if ($names -notcontains $entry) { throw ('The archive is missing ' + $entry + '.') }
        }
        # The payload root, exactly: the settings window and its icon, and nothing else.
        # The installer copies those two by name into the installation home, so a file
        # that should not be there is a sign this is not the build it claims to be - and
        # it used to be worse than a sign, because the root was copied by wildcard and
        # any name at all landed in the home, ownership markers and state included.
        $rootFiles = @('CodexAutoResumeSettings.exe', 'codex-auto-resume.ico')
        $atRoot = @($names | Where-Object { $_ -match '^payload/[^/]+$' })
        foreach ($name in $rootFiles) {
            if ($atRoot -notcontains ('payload/' + $name)) {
                throw ('The archive is missing payload/' + $name + '.')
            }
        }
        foreach ($name in $atRoot) {
            if ($rootFiles -notcontains $name.Substring('payload/'.Length)) {
                throw ('The archive carries an unexpected file at the payload root: ' + $name + '.')
            }
        }
        # No entry may escape the directory it is extracted into.
        foreach ($name in $names) {
            if ($name -match '(^|[\\/])\.\.([\\/]|$)' -or $name -match '^([\\/]|[A-Za-z]:)') {
                throw ('The archive contains an unsafe path: ' + $name)
            }
        }
        # And it has to be this product at this version, not merely a well-formed zip.
        $entry = $archive.GetEntry('payload/app/.codex-plugin/plugin.json')
        # GetEntry is ordinal while -notcontains above is not, so an entry differing only
        # in case satisfies the presence check and returns $null here. Say so instead of
        # dereferencing nothing.
        if ($null -eq $entry) { throw 'The archive names its manifest with unexpected casing.' }
        $reader = New-Object IO.StreamReader($entry.Open())
        try { $manifest = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
        if ($manifest.name -ne 'codex-auto-resume') {
            throw ('The archive contains a different product: ' + $manifest.name)
        }
        if ($manifest.version -ne $Version) {
            throw ('The archive is version ' + $manifest.version + ', not ' + $Version + '.')
        }
        # And the edition this run asked for. The advanced package in app\src is what makes an
        # installation advanced (Get-Edition below), so an advanced archive has to carry it, and a
        # standard one may carry nothing of that edition: not the package, and not its skill,
        # which Codex would read from the plugin tree. Names are compared as the extraction will
        # write them: either separator, no '.' or empty segment, and no '.' or ' ' at the end of
        # a segment, which Windows drops - the extraction below puts 'src/./x', 'src//x' and
        # 'src/x./y' into src\x, which the raw name hid from this check. A standard
        # archive holds nothing there in any case; an advanced one holds the package in exactly
        # its case, which is the one Python imports (Get-Edition). An archive named for one
        # edition and holding the other is refused here, before anything of it is unpacked.
        $package = 'payload/app/src/codex_auto_resume_advanced/'
        $skill = 'payload/app/skills/codex-auto-resume-advanced/'
        $written = @($names | ForEach-Object { @($_ -split '[\\/]' | ForEach-Object { $_.TrimEnd('.', ' ') } | Where-Object { $_ -ne '' }) -join '/' })
        if ($Edition -eq 'advanced') {
            if ($written -cnotcontains ($package + '__init__.py')) {
                throw ('The archive is not the advanced edition: it has no ' + $package + '__init__.py.')
            }
        } else {
            for ($index = 0; $index -lt $written.Count; $index++) {
                $path = $written[$index] + '/'
                if ($path.StartsWith($package, [StringComparison]::OrdinalIgnoreCase) -or
                    $path.StartsWith($skill, [StringComparison]::OrdinalIgnoreCase)) {
                    throw ('The archive holds the advanced edition (' + $names[$index] + '), and the standard edition was asked for.')
                }
            }
        }
    } finally { $archive.Dispose() }
}

# Which edition the tree whose `src` this is: the advanced one when the advanced package is in it,
# the standard one otherwise. Nothing is stamped anywhere to say which. It is the fact the product
# itself reads (src/codex_auto_resume/edition.py, name()) and the installer reads the same way, so
# the three agree about an installation - even one whose advanced package would not load.
function Get-Edition {
    param([string]$Src)
    # The package's directory in exactly this case. Python's import finds a package by its
    # directory's own name, case and all, so a tree that spells it otherwise is the standard
    # edition to the product; Test-Path, which ignores case, called it advanced. Its __init__.py
    # may be in any case, as it may for Python, which asks the file system for that file.
    $package = @(Get-ChildItem -LiteralPath $Src -Directory -Force -ErrorAction SilentlyContinue |
                 Where-Object { $_.Name -ceq 'codex_auto_resume_advanced' })
    if ($package.Count -and (Test-Path -LiteralPath (Join-Path $package[0].FullName '__init__.py') -PathType Leaf)) {
        return 'advanced'
    }
    return 'standard'
}

function Get-InstalledVersion {
    param([string]$Home_)
    $manifest = Join-Path $Home_ 'app\.codex-plugin\plugin.json'
    if (-not (Test-Path (Join-Path $Home_ 'runtime\python.exe'))) { return $null }
    if (-not (Test-Path $manifest)) { return $null }
    try { return (Get-Content $manifest -Raw -Encoding UTF8 | ConvertFrom-Json).version }
    catch { return $null }
}

function Get-InstalledEdition {
    # The edition installed at $Home_, or $null where nothing is - by the rule the installer
    # applies before it replaces anything (build/install/install.ps1): an `app` folder there,
    # and the edition of its `src`. So the two always agree about whether a run changes the
    # edition, and the installer's own refusal is never where anyone first hears of it.
    param([string]$Home_)
    $app = Join-Path $Home_ 'app'
    if (-not (Test-Path -LiteralPath $app)) { return $null }
    return Get-Edition -Src (Join-Path $app 'src')
}

function Get-TreeEdition {
    # The edition of the plugin tree this script came in. Main's tree on GitHub has no advanced
    # package in `src`, so a plugin added from there is the standard edition; the copy inside
    # an advanced installation, which its settings window runs, is the advanced one.
    param([string]$Root)
    return Get-Edition -Src (Join-Path $Root 'src')
}

function Resolve-Edition {
    <#
        The edition this run installs, and what that means for the installation already here.

        The edition -Edition names, where it names one; otherwise the installed one, so that a
        repair or an update stays in the edition a person chose; otherwise the plugin tree's own.
        The answer carries one of three words: 'same' - nothing is installed, or this edition
        is; 'change' - the other edition is installed and -Force says to replace it; 'refused' -
        the other edition is installed and nothing said to replace it. Only a named edition can
        differ from the installed one, so a change always takes -Edition and -Force together.
    #>
    param([string]$Asked, [string]$Installed, [string]$Tree, [switch]$Force)
    $chosen = $Tree
    if ($Installed) { $chosen = $Installed }
    if ($Asked) { $chosen = $Asked.ToLowerInvariant() }
    $verdict = 'same'
    if ($Installed -and $Installed -ne $chosen) {
        $verdict = 'refused'
        if ($Force) { $verdict = 'change' }
    }
    return [pscustomobject]@{ Edition = $chosen; Verdict = $verdict }
}

function Get-EditionStatement {
    # What moving from one edition to the other keeps and what it changes, in one line said
    # before anything is done. The installer says the same line (build/install/install.ps1) as
    # it replaces the program files; a test holds the two copies to each other.
    param([string]$From, [string]$To)
    $words = @{ standard = 'Standard edition'; advanced = 'Advanced edition' }
    $line = $words[$From] + ' -> ' + $words[$To] + '; settings and pending recoveries are kept; '
    if ($To -eq 'advanced') { return $line + 'every advanced feature starts off' }
    return $line + 'the advanced features go, and their code with them'
}

function Invoke-InstalledSetup {
    <#
        The installation's own plugin_setup.py with $Arguments, run by its own runtime\python.exe:
        the version that is installed now, whatever this run is about to install. Returns what it
        printed and its exit code. A console program, by the call operator, in this console.
    #>
    param([string]$Home_, [string[]]$Arguments)
    $python = Join-Path $Home_ 'runtime\python.exe'
    $setup = Join-Path $Home_ 'app\scripts\plugin_setup.py'
    $ErrorActionPreference = 'Continue'
    $printed = @(& $python $setup @Arguments)
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 1 }
    return [pscustomobject]@{ Printed = @($printed | ForEach-Object { [string]$_ }); Code = $code }
}

function Convert-StateForOlder {
    <#
        The state converted for a version on schema 3, before that version's installer runs: the
        installed version's own `downgrade-state --to 3 --stop-watcher`, which asks the watcher to
        stop, waits for it a minute at most and never kills it. Its one `downgrade:` line has to
        agree with its exit code, and the answer is that line's: 'converted <rows> <made_final>
        <conversations_off> <unfollowed_off> <0|1>', 'nothing', 'watcher-running' - or 'failed',
        which is also what a line and a code that disagree, no line, or two lines are.
    #>
    param([string]$Home_)
    $done = Invoke-InstalledSetup -Home_ $Home_ -Arguments @('downgrade-state', '--to', '3', '--stop-watcher')
    $lines = @($done.Printed | Where-Object { $_.StartsWith('downgrade: ', [StringComparison]::Ordinal) })
    if ($lines.Count -ne 1) { return 'failed' }
    $line = $lines[0]
    if ($done.Code -eq 0 -and $line -cmatch '^downgrade: converted ([0-9]{1,9}) ([0-9]{1,9}) ([0-9]{1,9}) ([0-9]{1,9}) ([01])\z') {
        $numbers = @($Matches[1], $Matches[2], $Matches[3], $Matches[4], $Matches[5])
        return ('converted ' + (@($numbers | ForEach-Object { [string][int]$_ }) -join ' '))
    }
    if ($done.Code -eq 0 -and $line -ceq 'downgrade: nothing') { return 'nothing' }
    if ($done.Code -eq 3 -and $line -ceq 'downgrade: watcher-running') { return 'watcher-running' }
    return 'failed'
}

function Start-CurrentWatcher {
    # The installed version's watcher started again, after a conversion that failed: `setup
    # --keep-state`, the repair branch's own run, which changes no decision a person made.
    param([string]$Home_, [switch]$NoStartup)
    $arguments = @('setup', '--keep-state')
    if ($NoStartup) { $arguments += '--no-startup' }
    $null = Invoke-InstalledSetup -Home_ $Home_ -Arguments $arguments
}

# ---------------------------------------------------------------------------- run

Write-Host ''
Write-Host 'Codex Auto Resume - setting up'
Write-Host ''

# Not $version: PowerShell's names ignore case, and that one would overwrite -Version.
$pluginVersion = Get-PluginVersion
$release = Read-Json (Join-Path $PSScriptRoot 'release.json')
$installHome = $env:CODEX_AUTO_RESUME_PLUGIN_HOME
if ([string]::IsNullOrWhiteSpace($installHome)) {
    $installHome = Join-Path $env:USERPROFILE '.codex-auto-resume'
}

$installed = Get-InstalledVersion -Home_ $installHome

# ------------------------------------------------------ the versions a person may pick
# Its own run, which installs nothing and asks one thing: the list of this repository's releases,
# every page of it. Each row is a version and an edition, offered or refused with its reason, and
# the last line says what they were judged against. A list that could not be read lists nothing:
# `versions: unavailable`, never a part of it, and never the Codex compatibility data either.
if ($Versions) {
    if ($CheckOnly -or $Update -or $ArchivePath -or $Compatibility -or $Version -or $Pick -or $Edition -or $Force) {
        Fail '-Versions lists the versions there are to pick from, and goes with nothing else.'
        Write-Host 'versions: unavailable'
        exit $ExitUnavailable
    }
    $installedEdition = Get-InstalledEdition -Home_ $installHome
    $readable = $false
    if ($installed -and $installedEdition) {
        try { $null = Get-VersionParts ([string]$installed); $readable = $true } catch { $readable = $false }
    }
    if (-not $readable) {
        Fail ('There is no installation at ' + $installHome + ' whose version this copy can read, so there is nothing to pick another version for.')
        Write-Host 'versions: unavailable'
        exit $ExitUnavailable
    }
    Step 'Asking api.github.com for this repository''s whole list of releases, page by page. Nothing is uploaded.'
    $listed = $null
    try { $listed = Get-ReleasePages -Release $release }
    catch {
        Fail ('The list of releases could not be read (' + $_.Exception.Message + ').')
        Write-Host 'versions: unavailable'
        Step 'Nothing was changed.'
        exit $ExitUnavailable
    }
    $table = Get-VersionTable -Listed $listed -Installed $installed -InstalledEdition $installedEdition `
                              -Release $release -Policy (Get-PolicyInForce)
    foreach ($row in $table.Rows) {
        Write-Host ('version: ' + $row.Version + ' ' + $row.Edition + ' ' + $row.Answer + ' ' + $row.Detail)
    }
    $newestShown = '-'
    if ($table.Latest) { $newestShown = $table.Latest }
    Write-Host ('versions: listed ' + $installed + ' ' + $installedEdition + ' ' + $newestShown + ' v' + $PickFloor +
                ' v' + $EditionsSince)
    exit $ExitCurrent
}

# ---------------------------------------------------------- the version a person picked
# Its own run: the version and edition of a row -Versions offered, which a person confirmed. -Force
# comes exactly when the row is older or of the other edition, so a stray one never widens a pick.
# The list is read again, because it may have changed since it was shown, and the row has to be
# offered still, as it was; then the archive is fetched and checked as every install's is, and only
# after it passed - under the install lock - is the state converted, where the row says so. Nothing
# from the archive runs before that.
$pickConvert = $false
if ($Pick) {
    if ($CheckOnly -or $Update -or $ArchivePath -or $Compatibility -or $Version) {
        Fail '-Pick installs the version picked in Install another version..., and goes with -Edition, -Force and -NoStartup alone.'
        Step 'Nothing was downloaded, and nothing was changed.'
        exit 1
    }
    $picked = $null
    try { $picked = Get-ChosenVersion $Pick }
    catch {
        Fail $_.Exception.Message
        Step 'Nothing was downloaded, and nothing was changed.'
        exit 1
    }
    if (-not $Edition) {
        Fail '-Pick goes with -Edition: the edition of the row that was picked.'
        Step 'Nothing was downloaded, and nothing was changed.'
        exit 1
    }
    $pickEdition = $Edition.ToLowerInvariant()
    $installedEdition = Get-InstalledEdition -Home_ $installHome
    $order = $null
    if ($installed -and $installedEdition) {
        try { $order = Compare-ProductVersion -Left $picked -Right ([string]$installed) } catch { $order = $null }
    }
    if ($null -eq $order) {
        Fail ('There is no installation at ' + $installHome + ' whose version this copy can read.')
        Write-Host 'pick: refused unreadable'
        Step 'Nothing was downloaded, and nothing was changed.'
        exit $ExitPickRefused
    }
    $changesEdition = $pickEdition -ne $installedEdition
    if ($order -eq 0 -and -not $changesEdition) {
        Ok ('v' + $picked + ' is the version installed at ' + $installHome + '.')
        Write-Host 'pick: refused installed'
        exit $ExitPickRefused
    }
    $needsForce = ($order -lt 0) -or $changesEdition
    if ($needsForce -and -not $Force) {
        Fail ('v' + $picked + ' (' + $pickEdition + ') is older or of the other edition, and -Force did not say it was confirmed.')
        Write-Host 'pick: refused needs-force'
        Step 'Nothing was downloaded, and nothing was changed.'
        exit $ExitPickRefused
    }
    if ($Force -and -not $needsForce) {
        Fail ('v' + $picked + ' (' + $pickEdition + ') is newer and of this edition, which -Force is not for.')
        Write-Host 'pick: refused force-not-needed'
        Step 'Nothing was downloaded, and nothing was changed.'
        exit $ExitPickRefused
    }
    Step 'Asking api.github.com for this repository''s whole list of releases again, page by page. Nothing is uploaded.'
    $listed = $null
    try { $listed = Get-ReleasePages -Release $release }
    catch {
        Fail ('The list of releases could not be read (' + $_.Exception.Message + ').')
        Write-Host 'pick: unavailable'
        Step 'Nothing was downloaded, and nothing was changed.'
        exit $ExitUnavailable
    }
    $table = Get-VersionTable -Listed $listed -Installed ([string]$installed) -InstalledEdition $installedEdition `
                              -Release $release -Policy (Get-PolicyInForce)
    $rows = @($table.Rows | Where-Object { $_.Version -ceq $picked -and $_.Edition -ceq $pickEdition })
    $words = @()
    if ($rows.Count -eq 1 -and $rows[0].Answer -ceq 'offered') { $words = @($rows[0].Detail.Split(',')) }
    if ($words.Count -eq 0 -or (($words -ccontains 'older') -ne ($order -lt 0)) -or
        (($words -ccontains 'edition') -ne $changesEdition)) {
        Fail ('v' + $picked + ' (' + $pickEdition + ') is not offered now as it was when the list was shown.')
        Write-Host 'pick: refused changed'
        Step 'Nothing was downloaded, and nothing was changed.'
        exit $ExitPickRefused
    }
    Write-Host ('pick: offered ' + $rows[0].Detail)
    $pickConvert = $words -ccontains 'convert3'
}

# ------------------------------------------------- the Codex compatibility data only
if ($Compatibility) {
    if ($CheckOnly -or $Update -or $ArchivePath -or $Force -or $Edition -or $Version) {
        Fail 'Use -Compatibility on its own: it refreshes data and installs nothing.'
        Write-Host 'compatibility: unavailable'
        exit $ExitUnavailable
    }
    $answer = Update-CompatibilityData -Home_ $installHome
    Write-Host ('compatibility: ' + $answer)
    if ($answer -like 'refreshed *') { Ok 'The compatibility data is up to date.' }
    elseif ($answer -like 'refused *') { Step 'The data was refused; what was in force before still is.' }
    else { Step 'Nothing was changed. The data already in force still applies.' }
    exit (Get-CompatibilityExit $answer)
}

# ------------------------------------------------------- is there a newer release?
if ($CheckOnly -and $Update) {
    Fail 'Use -CheckOnly or -Update, not both.'
    exit $ExitUnavailable
}
if (($CheckOnly -or $Update) -and $ArchivePath) {
    Fail 'A file you already have is not an update: -ArchivePath and -Update ask different questions.'
    exit $ExitUnavailable
}

# ------------------------------------------------ the pre-release a person said yes to
# Its own run, and a narrow one: the version a check offered, over the installation that asked,
# in that installation's edition. So it takes nothing that would widen it - not a second
# question, not a file, not another edition, and not -Force, because a pre-release is never
# installed over a version as new as itself or newer.
if ($Version -and ($CheckOnly -or $Update -or $ArchivePath -or $Edition -or $Force)) {
    Fail '-Version installs the pre-release an update check offered, and goes with -NoStartup alone.'
    Step 'Nothing was downloaded, and nothing was changed.'
    exit 1
}

# ------------------------------------------------------ which edition this run installs
# Settled before anything is asked or fetched, so a run that may not go ahead has touched
# nothing. An update never crosses editions: it installs a newer release of the edition that
# is installed, and a move to the other one is a reinstall a person asks for by name.
if ($Edition -and ($CheckOnly -or $Update)) {
    Fail 'An update stays in the edition that is installed, so -Edition does not go with -CheckOnly or -Update.'
    Step ('Moving to the other edition is a reinstall: run this again with -Edition ' + $Edition + ' -Force.')
    exit $ExitUnavailable
}
$installedEdition = Get-InstalledEdition -Home_ $installHome
$plan = Resolve-Edition -Asked $Edition -Installed $installedEdition -Tree (Get-TreeEdition -Root $PluginRoot) -Force:$Force
$targetEdition = $plan.Edition
if ($plan.Verdict -eq 'refused') {
    Write-Host ('edition: ' + $installedEdition)
    Fail ('The ' + $installedEdition + ' edition is installed here, and this run asked for the ' + $targetEdition + ' edition.')
    Step 'Moving between editions is a reinstall, never an update, so nothing was downloaded'
    Step 'and nothing was changed.'
    Step ('To replace it, run this again with -Edition ' + $Edition + ' -Force.')
    exit $ExitOtherEdition
}
# A change says what it keeps and what it changes before anything is fetched. The installer says
# it again as it replaces the program files, and is told the change was asked for.
if ($plan.Verdict -eq 'change') { Write-Host (Get-EditionStatement -From $installedEdition -To $targetEdition) }
Write-Host ('edition: ' + $targetEdition)

# What gets installed. It is the plugin's own version for every ordinary run, and only
# -Update, -Version and -Pick ever move it.
$target = $pluginVersion
if ($Pick) { $target = $picked }
if ($Version) {
    try { $target = Get-PrereleaseVersion $Version }
    catch {
        Fail $_.Exception.Message
        Step 'Nothing was downloaded, and nothing was changed.'
        exit 1
    }
    # An update of an installation that asked, never a first install: a pre-release is installed
    # only over a version it is newer than, which there has to be one of to compare.
    $order = $null
    if ($installed) {
        try { $order = Compare-ProductVersion -Left $target -Right $installed } catch { $order = $null }
    }
    if ($null -eq $order) {
        Fail ('There is no installation at ' + $installHome + ' whose version this copy can read, so v' + $target +
              ' would not be an update of one.')
        Step 'Nothing was downloaded, and nothing was changed.'
        exit 1
    }
    if ($order -le 0) {
        Fail ('v' + $installed + ' is installed at ' + $installHome + ', and the pre-release v' + $target +
              ' is not newer than it.')
        Step 'Nothing was downloaded, and nothing was replaced with an older or the same version.'
        exit 1
    }
    # The check's two questions again, now that a person said yes: a release may have been published
    # while the question was open, and what is installed is only what the check would still offer - a
    # pre-release the list names as published, newer than the newest release. A release newer than it
    # is answered as the check answers it, and a question that could not be asked as "unavailable".
    Step 'Asking github.com which release is newest. Nothing is uploaded, and no page is read.'
    $newest = $null
    try { $newest = Get-NewestPublishedVersion -Release $release }
    catch {
        Fail $_.Exception.Message
        Write-Host 'update: unavailable'
        Step ('Nothing was downloaded, and nothing was changed: whether a release newer than v' + $target +
              ' has been published could not be told.')
        exit $ExitUnavailable
    }
    if ((Compare-ProductVersion -Left $target -Right $newest) -le 0) {
        Fail ('v' + $newest + ' has been published, and the pre-release v' + $target + ' is not newer than it.')
        Write-Host ('update: available ' + $installed + ' ' + $newest)
        Step 'Nothing was downloaded, and nothing was changed. Check for updates again to install the release.'
        exit $ExitAvailable
    }
    Step 'Asking api.github.com for this repository''s list of releases, for the pre-release.'
    $listed = $null
    try { $listed = Get-PublishedPrereleases -Release $release -TimeoutSec $ReleasesVersionTimeout }
    catch {
        Fail ('The list of releases could not be read (' + $_.Exception.Message + ').')
        Write-Host 'update: unavailable'
        Step ('Nothing was downloaded, and nothing was changed: whether v' + $target +
              ' is a published pre-release could not be told.')
        exit $ExitUnavailable
    }
    if ($listed -cnotcontains $target) {
        Fail ('v' + $target + ' is not a published pre-release among this repository''s newest releases.')
        Step 'Nothing was downloaded, and nothing was changed.'
        exit 1
    }
    Ok ('v' + $target + ' is a pre-release, tested less than a release, and newer than the newest release, v' +
        $newest + '. This machine has v' + $installed + '.')
    Write-Host ('update: available ' + $installed + ' ' + $target)
}
if ($CheckOnly -or $Update) {
    # "Up to date" is a question about the version that would run, which is the installed
    # one wherever there is one. A plugin tree sitting at a version the machine has not
    # installed yet is an install that has not happened, not an answer to this.
    $current = $pluginVersion
    if ($installed) { $current = $installed }
    Step 'Asking github.com which release is newest. Nothing is uploaded, and no page is read.'
    $newest = $null
    try { $newest = Get-NewestPublishedVersion -Release $release }
    catch {
        Fail $_.Exception.Message
        Write-Host 'update: unavailable'
        Step 'Nothing was changed. This says nothing about whether an update exists.'
        exit $ExitUnavailable
    }
    # The installed version is compared only once it has been read. One this copy cannot read -
    # a later build with a word after its version that did not exist when this copy was
    # published - is neither older nor newer as far as this copy can tell, so there is no
    # answer to give but "unavailable", and nothing is installed over it.
    $order = $null
    try { $order = Compare-ProductVersion -Left $newest -Right $current }
    catch {
        Fail ('The installation at ' + $installHome + ' says it is version ' + (Format-UnreadVersion $current) +
              ', which this copy of the plugin cannot read, so it cannot tell whether v' + $newest + ' is newer.')
        Write-Host 'update: unavailable'
        Step 'Nothing was changed. This says nothing about whether an update exists.'
        exit $ExitUnavailable
    }
    # The second of the two moments the Codex compatibility data is refreshed: a person
    # asked, and github.com answered. Its own line, never a different update answer - and
    # never a late one: it gets only what is left of the time the window waits for this.
    $compatibilityTimeout = Get-CompatibilityTimeout -Elapsed $ScriptClock.Elapsed.TotalSeconds
    Write-Host ('compatibility: ' + (Update-CompatibilityData -Home_ $installHome -TimeoutSec $compatibilityTimeout))
    # The check's own second question, asked by -CheckOnly alone: is there a pre-release newer than
    # both? Its own line, `prerelease: v<version>`, and only when there is one. It never changes the
    # answer below, and a list that could not be read offers nothing rather than claiming anything.
    if ($CheckOnly) {
        $listTimeout = Get-ReleasesListTimeout -Elapsed $ScriptClock.Elapsed.TotalSeconds
        $prerelease = $null
        if ($listTimeout -le 0) {
            Step 'Too little of the update check''s time is left to look for a pre-release; none is offered.'
        } else {
            Step 'Asking api.github.com for this repository''s list of releases, for a newer pre-release.'
            try {
                $prerelease = Get-NewerPrerelease -Release $release -Installed $current -Stable $newest -TimeoutSec $listTimeout
            } catch {
                Step 'The list of releases could not be read, so no pre-release is offered. The answer below does not depend on it.'
            }
        }
        if ($prerelease) {
            Ok ('v' + $prerelease + ' is a pre-release, newer than this machine''s v' + $current +
                ' and the newest release, v' + $newest + ', and tested less than a release.')
            Write-Host ('prerelease: v' + $prerelease)
        }
    }
    if ($order -lt 0) {
        Ok ('This is v' + $current + ', which is ahead of the newest published release, v' + $newest + '.')
        Write-Host ('update: newer-local ' + $current + ' ' + $newest)
        Step 'Nothing was changed. An update would be a downgrade.'
        exit $ExitLocalNewer
    }
    if ($order -eq 0) {
        Ok ('v' + $current + ' is the newest published release.')
        Write-Host ('update: current ' + $current)
        exit $ExitCurrent
    }
    Ok ('v' + $newest + ' has been published. This machine has v' + $current + '.')
    Write-Host ('update: available ' + $current + ' ' + $newest)
    if ($CheckOnly) {
        Step 'Nothing was installed. Run this again with -Update to install it.'
        exit $ExitAvailable
    }
    $target = $newest
}

# Whether what is installed is older than, the same as, or newer than what would be
# installed. Null where there is no installation, or one whose manifest cannot be read.
#
# A manifest that reads and declares a version this copy cannot read is not "no installation".
# A copy of this script knows the version words of the day it was published and no later one:
# the published v0.6.10 and v0.6.11-alpha bootstraps knew -alpha and not -beta, took an installed
# 0.6.11-beta for nothing installed, and installed their own older release over it. Those copies
# cannot be changed; this one refuses instead, until -Force says to replace what it cannot read.
# Every copy published before the numbered pre-releases (-beta.2) cannot read those either.
#
# The "newer" case is the one -Update creates and nothing else did: an update leaves the
# machine ahead of the plugin tree it was started from, because Codex's copy of the plugin
# is still whatever version it fetched. Without this, the next ordinary run of this script
# would see a version it does not have and install it - over a newer one, silently. An
# installation is only ever replaced by an older one on purpose, which is what -Force is.
#
# Only an installation of the edition this run installs can be "already installed". The other
# edition at the same version is a different installation, and replacing it is what this run
# was asked to do - so it is never checked over in its place.
$standing = $null
$unread = $false
if ($installed -and $plan.Verdict -eq 'same') {
    try { $standing = Compare-ProductVersion -Left $installed -Right $target }
    catch { $standing = $null; $unread = $true }
}

if ($unread -and -not $Force) {
    Fail ('The installation at ' + $installHome + ' says it is version ' + (Format-UnreadVersion $installed) +
          ', which this copy of the plugin cannot read.')
    Step ('It may be newer than the v' + $target + ' this copy carries, so nothing was downloaded')
    Step 'and nothing was replaced.'
    Step ('Add -Force to install v' + $target + ' over it.')
    exit 1
}

if ($null -ne $standing -and $standing -ge 0 -and -not $Force) {
    if ($standing -eq 0) {
        Ok ('v' + $target + ' is already installed at ' + $installHome)
    } else {
        Ok ('v' + $installed + ' is installed at ' + $installHome + ', which is newer than the v' +
            $target + ' this copy of the plugin carries.')
        Step 'Nothing was downloaded, and nothing was replaced with an older version.'
        Step 'Add -Force to install this version over it.'
    }
    # Still converge. Re-running setup is the repair path: it re-registers the sign-in
    # entry and the notification handler against the installed runtime and starts the
    # watcher if it is not running. All of that is cheap, and any of it can be missing
    # on a machine where the last install was interrupted.
    Step 'Checking it over'
    Write-Host ''
    # This branch writes to the installation without going through install.ps1, so it
    # has to take install.ps1's lock itself. It used to take none at all, which meant a
    # repair and a running installer could rewrite the same registrations at once - the
    # one case the lock exists for. Windows releases it when this process ends, moments
    # from now; an abandoned lock means the previous holder died, so it is taken rather
    # than treated as contention.
    $lock = New-Object System.Threading.Mutex($false, 'Local\CodexAutoResume.Install')
    $held = $false
    try { $held = $lock.WaitOne(0) }
    catch [System.Threading.AbandonedMutexException] { $held = $true }
    if (-not $held) {
        Fail 'Another Codex Auto Resume installation is already running.'
        Step 'Wait for it to finish, then try again.'
        exit 1
    }
    $python = Join-Path $installHome 'runtime\python.exe'
    $setup = Join-Path $installHome 'app\scripts\plugin_setup.py'
    # `--keep-state`, always: this branch is reached only when the installation is already
    # at this version or past it, so it is a repair and never a first install. Plain
    # `setup` runs the engine's `enable` and re-registers the sign-in entry, which would
    # switch recovery back on for someone who paused it and put back a sign-in entry they
    # removed - a decision, taken while claiming to check the installation over.
    $arguments = @($setup, 'setup', '--keep-state')
    if ($NoStartup) { $arguments += '--no-startup' }
    & $python @arguments
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 0 }
    exit $code
}

# No lock is taken around the download. Fetching and verifying touch nothing shared -
# the working directory is unique to this run - and the step that does, the install
# itself, takes the lock inside install.ps1. A second bootstrap is therefore refused at
# the moment it would actually collide rather than at the moment it starts. The repair
# branch above is the exception: it skips install.ps1, so it takes the lock itself.
$started = $false
$work = Join-Path ([IO.Path]::GetTempPath()) ('codex-auto-resume-' + [Guid]::NewGuid().ToString('N'))
try {
    [Net.ServicePointManager]::SecurityProtocol =
        [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13
} catch {
    # Tls13 is not a member on older builds. Tls12 alone is still acceptable.
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
}

try {
    New-Item -ItemType Directory -Force -Path $work | Out-Null
    # The edition's own template, so an advanced installation updates to the advanced archive
    # and a standard one to the name every published bootstrap has always built.
    $name = (Get-EditionRelease -Release $release -Edition $targetEdition).archive.Replace('{version}', $target)
    $zip = Join-Path $work $name

    if ($ArchivePath) {
        if (-not (Test-Path $ArchivePath)) { Fail ('No such file: ' + $ArchivePath); exit 1 }
        Step ('Using the archive you provided: ' + $ArchivePath)
        Copy-Item -Path $ArchivePath -Destination $zip -Force
    } else {
        $base = $release.download.Replace('{version}', $target)
        Step ('Downloading v' + $target + ' from github.com over HTTPS.')
        Step ('Nothing is uploaded, and nothing runs until the download is verified.')
        Get-Remote -Uri ($base + $name) -OutFile $zip -What 'The archive'
    }

    $actual = Get-Sha256 -Path $zip
    $pinned = Get-PinnedDigest -Release (Get-EditionRelease -Release $release -Edition $targetEdition) -Version $target
    if ($pinned) {
        if ($actual -ne $pinned) { throw 'The download does not match the digest pinned in this plugin.' }
        Ok 'SHA-256 matches the digest pinned in this plugin'
    } elseif ($ArchivePath) {
        # Nothing to check a local file against. Say so; the layout and version checks
        # below still run, and they are the reason this is not simply unchecked.
        # Deliberately not an [ok]: nothing was compared. Printing a hash-shaped string
        # beside a tick is how an unverified file comes to look like a verified one.
        Step ('SHA-256 ' + $actual.Substring(0, 16) + '... - NOT checked against anything.')
        Step ('This version has no pinned digest, and a local file has no published')
        Step ('checksum to fetch. Only the contents checks below apply.')
    } else {
        $sidecar = $zip + '.sha256'
        Get-Remote -Uri ($base + $name + '.sha256') -OutFile $sidecar -What 'The checksum'
        $recorded = ((Get-Content $sidecar -Raw) -split '\s+')[0].Trim().ToLower()
        if ($recorded -notmatch '^[0-9a-f]{64}$') { throw 'The published checksum file is not a SHA-256.' }
        if ($actual -ne $recorded) { throw 'The download does not match its published checksum.' }
        Ok 'SHA-256 matches the checksum published beside it (no pinned digest for this version)'
    }

    Test-Archive -Zip $zip -Version $target -Edition $targetEdition
    Ok ('Archive contents verified as Codex Auto Resume v' + $target)

    $unpacked = Join-Path $work 'unpacked'
    [IO.Compression.ZipFile]::ExtractToDirectory((Resolve-Path $zip), $unpacked)

    if ($Pick) {
        # The install lock, from before the state is converted until this process ends: the
        # installer below runs on this thread and takes it again, which a Mutex allows its owner. A
        # repair or another install cannot come between the conversion and the installer.
        $pickLock = New-Object System.Threading.Mutex($false, 'Local\CodexAutoResume.Install')
        $pickHeld = $false
        try { $pickHeld = $pickLock.WaitOne(0) }
        catch [System.Threading.AbandonedMutexException] { $pickHeld = $true }
        if (-not $pickHeld) {
            Fail 'Another Codex Auto Resume installation is already running.'
            Write-Host 'pick: refused busy'
            Step 'Nothing was installed, and nothing was changed.'
            exit $ExitPickRefused
        }
        if ($pickConvert) {
            Step 'Converting the state for the older version, after asking the watcher to stop. A copy of it'
            Step 'as it is now is kept beside it.'
            $converted = Convert-StateForOlder -Home_ $installHome
            if ($converted -ceq 'watcher-running') {
                Fail 'The watcher did not stop within a minute; it was asked to, and was not stopped any other way.'
                Write-Host 'pick: refused watcher-running'
                Step 'Nothing was installed, and the state was not converted.'
                exit $ExitPickRefused
            }
            if ($converted -cnotlike 'converted *' -and $converted -cne 'nothing') {
                Fail 'The state could not be converted for that version, so it is as it was.'
                Start-CurrentWatcher -Home_ $installHome -NoStartup:$NoStartup
                Write-Host 'pick: refused state'
                Step 'Nothing was installed, and the watcher was started again.'
                exit $ExitPickRefused
            }
            if ($converted -clike 'converted *') { Write-Host ('pick: state ' + $converted) }
        }
    }

    Step 'Installing'
    Write-Host ''
    $installer = Join-Path $unpacked 'install\install.ps1'
    # By name, never as a list. A list is bound by position, so '-SkipStartup' in one reached
    # the installer as the plugin's name, and the switch it meant stayed off.
    $arguments = @{}
    if ($NoStartup) { $arguments['SkipStartup'] = $true }
    # Only a change this run was asked for, with -Edition and -Force. The installer refuses an
    # edition change nobody told it about.
    if ($plan.Verdict -eq 'change') { $arguments['AllowEditionChange'] = $true }
    # From here on "nothing was installed" would be a lie: the installer moves the old
    # payload aside before it copies, so a failure inside it leaves a machine that has
    # been touched. It reports and rolls back its own work; this script must not claim
    # otherwise on its way out.
    $started = $true
    & $installer @arguments
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 0 }
    if ($Pick -and $code -eq 0) { Write-Host ('pick: installed ' + $target + ' ' + $targetEdition) }
    exit $code
} catch {
    Write-Host ''
    Fail $_.Exception.Message
    if ($started) { Step 'The installer had already started; read its messages above.' }
    else { Step 'Nothing was installed.' }
    exit 1
} finally {
    # The download is deleted whether it was used or not: a rejected archive should not
    # be left on disk where someone could run it by hand.
    Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
}
