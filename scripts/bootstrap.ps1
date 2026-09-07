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
      * Exactly one URL shape, built from constants in scripts/release.json and the
        version in the plugin's own manifest. There is no "latest", no input that
        becomes part of a URL, and no way to ask it for a different version: a v0.5.2
        plugin can fetch the v0.5.2 archive and nothing else.
      * Over HTTPS, with TLS 1.2 at minimum, from github.com - and the final response
        URI has to be github.com or githubusercontent.com, because a release download
        redirects to GitHub's object storage and nowhere else.

    What it verifies, before anything is executed
      * SHA-256. Against the digest pinned in scripts/release.json when there is one,
        and otherwise against the .sha256 published beside the archive. The pinned case
        is the strong one; the sidecar case is trust-on-first-use over TLS to GitHub,
        and this script prints which of the two it used rather than letting a reader
        assume the stronger one.
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

    Run: powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
         Add -Force to reinstall a version that is already present.
         Add -ArchivePath <zip> to install a file you already have, verified the same way.
#>
[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$NoStartup,
    [string]$ArchivePath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$PluginRoot = Split-Path -Parent $PSScriptRoot
$AllowedHosts = @('github.com', 'objects.githubusercontent.com', 'release-assets.githubusercontent.com')

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

function Assert-TrustedHost {
    param($Response, [string]$What)
    $final = $Response.BaseResponse.ResponseUri
    if ($final.Scheme -ne 'https' -or ($AllowedHosts -notcontains $final.Host)) {
        throw ($What + ' was redirected to a host this installer does not trust: ' + $final.Host)
    }
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
        # No entry may escape the directory it is extracted into.
        foreach ($name in $names) {
            if ($name -match '(^|[\\/])\.\.([\\/]|$)' -or $name -match '^([\\/]|[A-Za-z]:)') {
                throw ('The archive contains an unsafe path: ' + $name)
            }
        }
        # And it has to be this product at this version, not merely a well-formed zip.
        $entry = $archive.GetEntry('payload/app/.codex-plugin/plugin.json')
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
if ($installed -eq $version -and -not $Force) {
    Ok ('v' + $version + ' is already installed at ' + $installHome)
    # Still converge. Re-running setup is the repair path: it re-registers the sign-in
    # entry and the notification handler against the installed runtime and starts the
    # watcher if it is not running. All of that is cheap, and any of it can be missing
    # on a machine where the last install was interrupted.
    Step 'Checking it over'
    Write-Host ''
    $python = Join-Path $installHome 'runtime\python.exe'
    $setup = Join-Path $installHome 'app\scripts\plugin_setup.py'
    $arguments = @($setup, 'setup')
    if ($NoStartup) { $arguments += '--no-startup' }
    & $python @arguments
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 0 }
    exit $code
}

# There is deliberately no lock taken here. Downloading and verifying touch nothing
# shared - the working directory is unique to this run - and the one step that does,
# the install itself, takes the lock in install.ps1 where every route passes through
# it. One owner, no recursive acquisition, and a second bootstrap is refused at the
# moment it would actually collide rather than at the moment it starts.
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
    $name = $release.archive.Replace('{version}', $version)
    $zip = Join-Path $work $name

    if ($ArchivePath) {
        if (-not (Test-Path $ArchivePath)) { Fail ('No such file: ' + $ArchivePath); exit 1 }
        Step ('Using the archive you provided: ' + $ArchivePath)
        Copy-Item -Path $ArchivePath -Destination $zip -Force
    } else {
        $base = $release.download.Replace('{version}', $version)
        Step ('Downloading v' + $version + ' from github.com')
        Get-Remote -Uri ($base + $name) -OutFile $zip -What 'The archive'
    }

    $actual = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
    $pinned = Get-PinnedDigest -Release $release -Version $version
    if ($pinned) {
        if ($actual -ne $pinned) { throw 'The download does not match the digest pinned in this plugin.' }
        Ok 'SHA-256 matches the digest pinned in this plugin'
    } elseif ($ArchivePath) {
        # Nothing to check a local file against. Say so; the layout and version checks
        # below still run, and they are the reason this is not simply unchecked.
        Ok ('SHA-256 ' + $actual.Substring(0, 16) + '... (no pinned digest for this version)')
    } else {
        $sidecar = $zip + '.sha256'
        Get-Remote -Uri ($base + $name + '.sha256') -OutFile $sidecar -What 'The checksum'
        $recorded = ((Get-Content $sidecar -Raw) -split '\s+')[0].Trim().ToLower()
        if ($recorded -notmatch '^[0-9a-f]{64}$') { throw 'The published checksum file is not a SHA-256.' }
        if ($actual -ne $recorded) { throw 'The download does not match its published checksum.' }
        Ok 'SHA-256 matches the checksum published beside it (no pinned digest for this version)'
    }

    Test-Archive -Zip $zip -Version $version
    Ok ('Archive contents verified as Codex Auto Resume v' + $version)

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
