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
        version this script chose. No input becomes part of a URL. An ordinary run
        fetches the version in the plugin's own manifest and nothing else; -Update is
        the single exception, and the version it fetches is not an input either - it is
        three integers read out of a redirect under this exact repository.
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

      An update is refused unless it is strictly newer, compared as three integers and
      never as text. A local build ahead of everything published is reported as that and
      left alone. Everything an ordinary install verifies - the checksum, the contents,
      the version inside the archive - is verified for an update too, and it goes through
      the same installer, which keeps the state and the decisions already on the machine.

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
      ($CheckBudgetSeconds below), so it can make the check neither late nor "running" -
      with too little left it is not attempted, and the data already in force still applies.

    Run: powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
         Add -Force to reinstall a version that is already present.
         Add -ArchivePath <zip> to install a file you already have. It is checked
         against the pinned digest when this version has one; otherwise only the
         contents checks apply, because there is no sidecar to fetch for a local file.
         Add -CheckOnly to ask whether a newer release exists and install nothing.
         Add -Update to install one if there is.
         Add -Compatibility to refresh the Codex compatibility data and nothing else.
#>
[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$NoStartup,
    [string]$ArchivePath,
    [switch]$CheckOnly,
    [switch]$Update,
    [switch]$Compatibility
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
    # rather than reaching the network. The one suffix is the literal -alpha of a planned
    # pre-release (v0.6.9-alpha), which names its own tag and archive.
    if ($version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+(-alpha)?$') {
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

function Get-VersionParts {
    param([string]$Version)
    if ($Version -notmatch '^([0-9]{1,6})\.([0-9]{1,6})\.([0-9]{1,6})(-alpha)?$') {
        throw ('Not a version this product uses: ' + $Version)
    }
    # A fourth part orders a pre-release just before its own release: 0.6.9-alpha < 0.6.9.
    $stage = 1
    if ($Matches[4]) { $stage = 0 }
    return @([int]$Matches[1], [int]$Matches[2], [int]$Matches[3], $stage)
}

function Compare-ProductVersion {
    param([string]$Left, [string]$Right)
    # -1, 0 or 1, as integers. Compared as text, '0.10.0' sorts before '0.9.0' and the tenth
    # minor release of a line would look like a downgrade.
    $a = Get-VersionParts $Left
    $b = Get-VersionParts $Right
    for ($i = 0; $i -lt 4; $i++) {
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
    if ($tag -notmatch '^v[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}$') {
        throw ('The newest release is not tagged the way this product tags releases: ' + $tag)
    }
    # Rebuilt from the three numbers rather than reused as text: what reaches the URL
    # below is arithmetic, and a leading zero or an unexpected character cannot survive
    # being turned into an integer and back.
    $parts = $tag.Substring(1).Split('.')
    return ([string][int]$parts[0]) + '.' + ([string][int]$parts[1]) + '.' + ([string][int]$parts[2])
}

function Get-Remote {
    param([string]$Uri, [string]$OutFile, [string]$What, [string[]]$Hosts = $AllowedHosts,
          [int]$TimeoutSec = 300)
    # -UseBasicParsing keeps this working on a Windows with no Internet Explorer engine,
    # which is every current one.
    $response = Invoke-WebRequest -Uri $Uri -OutFile $OutFile -UseBasicParsing -PassThru `
                                 -MaximumRedirection 5 -TimeoutSec $TimeoutSec
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
                       -Hosts $CompatibilityHosts -TimeoutSec $TimeoutSec
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
    param([string]$Zip, [string]$Version)
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
    } finally { $archive.Dispose() }
}

function Get-InstalledVersion {
    param([string]$Home_)
    $manifest = Join-Path $Home_ 'app\.codex-plugin\plugin.json'
    if (-not (Test-Path (Join-Path $Home_ 'runtime\python.exe'))) { return $null }
    if (-not (Test-Path $manifest)) { return $null }
    try { return (Get-Content $manifest -Raw -Encoding UTF8 | ConvertFrom-Json).version }
    catch { return $null }
}

# ---------------------------------------------------------------------------- run

Write-Host ''
Write-Host 'Codex Auto Resume - setting up'
Write-Host ''

$version = Get-PluginVersion
$release = Read-Json (Join-Path $PSScriptRoot 'release.json')
$installHome = $env:CODEX_AUTO_RESUME_PLUGIN_HOME
if ([string]::IsNullOrWhiteSpace($installHome)) {
    $installHome = Join-Path $env:USERPROFILE '.codex-auto-resume'
}

$installed = Get-InstalledVersion -Home_ $installHome

# ------------------------------------------------- the Codex compatibility data only
if ($Compatibility) {
    if ($CheckOnly -or $Update -or $ArchivePath -or $Force) {
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

# What gets installed. It is the plugin's own version for every ordinary run, and only
# -Update ever moves it.
$target = $version
if ($CheckOnly -or $Update) {
    # "Up to date" is a question about the version that would run, which is the installed
    # one wherever there is one. A plugin tree sitting at a version the machine has not
    # installed yet is an install that has not happened, not an answer to this.
    $current = $version
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
    $order = Compare-ProductVersion -Left $newest -Right $current
    # The second of the two moments the Codex compatibility data is refreshed: a person
    # asked, and github.com answered. Its own line, never a different update answer - and
    # never a late one: it gets only what is left of the time the window waits for this.
    $compatibilityTimeout = Get-CompatibilityTimeout -Elapsed $ScriptClock.Elapsed.TotalSeconds
    Write-Host ('compatibility: ' + (Update-CompatibilityData -Home_ $installHome -TimeoutSec $compatibilityTimeout))
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
# installed. Null where there is no installation, or one whose version cannot be read.
#
# The "newer" case is the one -Update creates and nothing else did: an update leaves the
# machine ahead of the plugin tree it was started from, because Codex's copy of the plugin
# is still whatever version it fetched. Without this, the next ordinary run of this script
# would see a version it does not have and install it - over a newer one, silently. An
# installation is only ever replaced by an older one on purpose, which is what -Force is.
$standing = $null
if ($installed) {
    try { $standing = Compare-ProductVersion -Left $installed -Right $target }
    catch { $standing = $null }
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
    $name = $release.archive.Replace('{version}', $target)
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
    $pinned = Get-PinnedDigest -Release $release -Version $target
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

    Test-Archive -Zip $zip -Version $target
    Ok ('Archive contents verified as Codex Auto Resume v' + $target)

    $unpacked = Join-Path $work 'unpacked'
    [IO.Compression.ZipFile]::ExtractToDirectory((Resolve-Path $zip), $unpacked)

    Step 'Installing'
    Write-Host ''
    $installer = Join-Path $unpacked 'install\install.ps1'
    $arguments = @()
    if ($NoStartup) { $arguments += '-SkipStartup' }
    # From here on "nothing was installed" would be a lie: the installer moves the old
    # payload aside before it copies, so a failure inside it leaves a machine that has
    # been touched. It reports and rolls back its own work; this script must not claim
    # otherwise on its way out.
    $started = $true
    & $installer @arguments
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 0 }
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
