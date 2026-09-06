<#
    Bootstrap installer for codex-auto-resume-windows.

    This is not a runtime. It automates the same commands the README documents and
    then hands over to the plugin's own setup, which owns everything afterwards.

    It requires no administrator rights, installs no service and no scheduled task,
    writes only under HKCU, and never deletes runtime state: re-running it upgrades
    in place and keeps pending recoveries.
#>
[CmdletBinding()]
param(
    [switch]$SkipStartup,      # set up, but do not register the sign-in autostart
    [switch]$Uninstall,        # remove the watcher, then the plugin
    [string]$Marketplace = 'songyb111-gachon/codex-auto-resume-windows',
    [string]$PluginName  = 'codex-auto-resume'
)

$ErrorActionPreference = 'Stop'
$script:Failed = $false

function Step { param([string]$Message) Write-Host ("  " + $Message) }
function Ok   { param([string]$Message) Write-Host ("  [ok] " + $Message) }
function Warn { param([string]$Message) Write-Host ("  [!]  " + $Message) -ForegroundColor Yellow }
function Fail {
    param([string]$Message)
    Write-Host ("  [x]  " + $Message) -ForegroundColor Red
    $script:Failed = $true
}

function Get-CodexCli {
    # The desktop app keeps its engine in a content-addressed directory; take the
    # newest one that actually contains codex.exe.
    $root = Join-Path $env:LOCALAPPDATA 'OpenAI\Codex\bin'
    if (-not (Test-Path $root)) { return $null }
    # @() matters: a single result would otherwise be a bare string, and indexing a
    # string returns its first character rather than the path.
    $found = @(Get-ChildItem -Path $root -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { Join-Path $_.FullName 'codex.exe' } |
        Where-Object { Test-Path $_ } |
        Sort-Object { (Get-Item $_).LastWriteTime } -Descending)
    if ($found.Count -eq 0) { return $null }
    return $found[0]
}

function Get-Python {
    # Order matters: the py launcher picks a sane default even when several
    # interpreters are installed. Nothing is ever downloaded or installed here.
    $candidates = @(
        @{ File = 'py';      Args = @('-3') },
        @{ File = 'python';  Args = @() },
        @{ File = 'python3'; Args = @() }
    )
    foreach ($candidate in $candidates) {
        $command = Get-Command $candidate.File -ErrorAction SilentlyContinue
        if ($null -eq $command) { continue }
        $probe = @($candidate.Args) + @('-c', 'import sys;print(sys.version_info[0]*100+sys.version_info[1])')
        $version = (& $candidate.File @probe) 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $version) { continue }
        $encoded = 0
        if (-not [int]::TryParse(("$version".Trim()), [ref]$encoded)) { continue }
        $major = [math]::Floor($encoded / 100); $minor = $encoded % 100
        if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 10)) {
            return @{ File = $candidate.File; Args = $candidate.Args; Version = "$major.$minor" }
        }
    }
    return $null
}

function Get-PluginRoot {
    param([string]$CodexHome)
    $cache = Join-Path $CodexHome 'plugins\cache'
    if (-not (Test-Path $cache)) { return $null }
    $found = @(Get-ChildItem -Path $cache -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { Join-Path $_.FullName $PluginName } |
        Where-Object { Test-Path $_ } |
        ForEach-Object { Get-ChildItem -Path $_ -Directory -ErrorAction SilentlyContinue } |
        Where-Object { Test-Path (Join-Path $_.FullName 'scripts\plugin_setup.py') } |
        Sort-Object LastWriteTime -Descending)
    if ($found.Count -eq 0) { return $null }
    return $found[0].FullName
}

Write-Host ''
Write-Host 'Codex Auto Resume - installer'
Write-Host ''

# 1. Windows only.
if ($env:OS -ne 'Windows_NT') { Fail 'This tool targets Windows only.'; exit 1 }
Ok 'Windows'

# 2. The official Codex engine.
$codex = Get-CodexCli
if ($null -eq $codex) {
    Fail 'Codex desktop app not found. Install the ChatGPT/Codex desktop app first, run it once, then run this again.'
    exit 1
}
Ok ("Codex engine: " + $codex)

# 3. Plugin support in this engine build.
& $codex plugin --help > $null 2>&1
if ($LASTEXITCODE -ne 0) {
    Fail 'This Codex build has no plugin support. Update the Codex desktop app and try again.'
    exit 1
}
Ok 'Plugin support'

$codexHome = $env:CODEX_HOME
if (-not $codexHome) { $codexHome = Join-Path $env:USERPROFILE '.codex' }

if ($Uninstall) {
    # Remove the watcher FIRST, while the plugin (and therefore the engine) still
    # exists; removing the plugin first would leave the registrations behind.
    $root = Get-PluginRoot -CodexHome $codexHome
    $python = Get-Python
    if ($null -ne $root -and $null -ne $python) {
        Step 'Removing the watcher, autostart and notification handler'
        $setup = Join-Path $root 'scripts\plugin_setup.py'
        $argv = @($python.Args) + @($setup, 'uninstall')
        & $python.File @argv
        if ($LASTEXITCODE -ne 0) { Warn 'The watcher reported a problem; the plugin will still be removed.' }
    } else {
        Warn 'No installed plugin runtime found; skipping watcher removal.'
    }
    Step 'Removing the plugin'
    & $codex plugin remove ("$PluginName@" + (Split-Path $Marketplace -Leaf)) 2>$null | Out-Null
    Write-Host ''
    Write-Host 'Removed. Your Codex conversations were not touched.'
    exit 0
}

# 4-5. Marketplace registration. `marketplace add` is idempotent for the same source.
Step 'Registering the marketplace'
& $codex plugin marketplace add $Marketplace 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Fail 'Could not register the marketplace. Check your network connection and try again.'
    exit 1
}
Ok 'Marketplace registered'

Step 'Refreshing the marketplace'
& $codex plugin marketplace upgrade 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Warn 'Could not refresh the marketplace; an already-cached version will be used.' }

# 6. Install or update the plugin.
$marketplaceName = Split-Path $Marketplace -Leaf
Step 'Installing the plugin'
& $codex plugin add ("$PluginName@" + $marketplaceName) 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Fail 'Could not install the plugin.'
    exit 1
}
$root = Get-PluginRoot -CodexHome $codexHome
if ($null -eq $root) { Fail 'The plugin installed but its files could not be located.'; exit 1 }
Ok ("Plugin installed: " + (Split-Path $root -Leaf))

# 7. Python. Never downloaded or installed automatically: that is a supply-chain
#    decision for the user to make, not for an installer to make silently.
$python = Get-Python
if ($null -eq $python) {
    Fail 'Python 3.10 or newer is required and was not found.'
    Write-Host '       Install it from https://www.python.org/downloads/windows/ (tick "Add python.exe to PATH"),'
    Write-Host '       then run this installer again. Nothing has been left running.'
    exit 1
}
Ok ("Python " + $python.Version)

# 8-11. Hand over to the plugin's own setup: it owns the runtime home, the watcher,
#       the sign-in autostart and the notification handler, and refuses to create a
#       second installation alongside an existing one.
Step 'Setting up the watcher'
$setup = Join-Path $root 'scripts\plugin_setup.py'
$argv = @($python.Args) + @($setup, 'setup')
if ($SkipStartup) { $argv = $argv + @('--no-startup') }
& $python.File @argv
if ($LASTEXITCODE -ne 0) {
    Fail 'Setup did not complete. Nothing was removed; read the message above and re-run when resolved.'
    exit 1
}

# 12. Read-only health check.
Step 'Checking the installation'
$argv = @($python.Args) + @($setup, 'doctor')
& $python.File @argv
if ($LASTEXITCODE -ne 0) { Warn 'The health check reported a problem. Auto recovery is installed but may not be ready yet.' }

# 13. Summary.
Write-Host ''
if ($script:Failed) {
    Write-Host 'Finished with problems. See the messages above.'
    exit 1
}
Write-Host 'Done. Codex Auto Resume is installed and running.'
Write-Host 'Ask Codex "show auto resume status" in a new conversation to check on it.'
exit 0
