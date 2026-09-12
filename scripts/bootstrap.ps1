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

    Run: powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
         Add -Force to reinstall a version that is already present.
         Add -ArchivePath <zip> to install a file you already have. It is checked
         against the pinned digest when this version has one; otherwise only the
         contents checks apply, because there is no sidecar to fetch for a local file.
         Add -CheckOnly to ask whether a newer release exists and install nothing.
         Add -Update to install one if there is.
#>
[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$NoStartup,
    [string]$ArchivePath,
    [switch]$CheckOnly,
    [switch]$Update
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$PluginRoot = Split-Path -Parent $PSScriptRoot
$AllowedHosts = @('github.com', 'objects.githubusercontent.com', 'release-assets.githubusercontent.com')

# What -CheckOnly and -Update answer with. Four codes, because there are four answers and
# a caller that has to tell them apart should not have to read prose to do it. "Could not
# ask" is its own answer and never borrows the one for "up to date": a machine with no
# network would otherwise be told it is current, which is the one wrong thing an update
# check can say. An update that goes ahead exits with the installer's own code instead.
$ExitCurrent     = 0
$ExitAvailable   = 10
$ExitLocalNewer  = 11
$ExitUnavailable = 12

function Step { param([string]$Text) Write-Host ('  ' + $Text) }
function Ok   { param([string]$Text) Write-Host ('  [ok] ' + $Text) }
function Fail { param([string]$Text) Write-Host ('  [!] ' + $Text) -ForegroundColor Red }

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
    # rather than reaching the network.
    if ($version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+$') {
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
    param($Response, [string]$What)
    $final = Get-FinalUri -Response $Response
    if ($null -eq $final) {
        throw ($What + ': this PowerShell does not report where the download came from, so it was refused.')
    }
    if ($final.Scheme -ne 'https' -or ($AllowedHosts -notcontains $final.Host)) {
        throw ($What + ' was redirected to a host this installer does not trust: ' + $final.Host)
    }
}

function Get-VersionParts {
    param([string]$Version)
    if ($Version -notmatch '^[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}$') {
        throw ('Not a version this product uses: ' + $Version)
    }
    $parts = $Version.Split('.')
    return @([int]$parts[0], [int]$parts[1], [int]$parts[2])
}

function Compare-ProductVersion {
    param([string]$Left, [string]$Right)
    # -1, 0 or 1, as three integers. Compared as text, '0.10.0' sorts before '0.9.0' and
    # the tenth minor release of a line would look like a downgrade.
    $a = Get-VersionParts $Left
    $b = Get-VersionParts $Right
    for ($i = 0; $i -lt 3; $i++) {
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
    param([string]$Uri, [string]$OutFile, [string]$What)
    # -UseBasicParsing keeps this working on a Windows with no Internet Explorer engine,
    # which is every current one.
    $response = Invoke-WebRequest -Uri $Uri -OutFile $OutFile -UseBasicParsing -PassThru `
                                 -MaximumRedirection 5 -TimeoutSec 300
    Assert-TrustedHost -Response $response -What $What
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

    $actual = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
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
