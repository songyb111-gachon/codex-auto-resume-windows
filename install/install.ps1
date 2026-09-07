<#
    Installer for codex-auto-resume-windows.

    It deploys a self-contained payload: the application and its own Python runtime.
    There is no system Python requirement, no network requirement and no administrator
    requirement, and it registers nothing outside the current user.

    Re-running it is the upgrade and the repair path. Runtime state - settings, pending
    recoveries, retry budgets and logs - lives beside the installation and is never
    touched here; only the program files are replaced.
#>
[CmdletBinding()]
param(
    [switch]$SkipStartup,        # install, but do not run at Windows sign-in
    [switch]$Uninstall,          # remove the program, keeping settings and pending state
    [switch]$Purge,              # with -Uninstall: also delete settings, state and logs
    [string]$PluginName      = 'codex-auto-resume',
    [string]$MarketplaceName = 'codex-auto-resume-windows'
)

$ErrorActionPreference = 'Stop'
$script:Failed = $false

function Step { param([string]$m) Write-Host ('  ' + $m) }
function Ok   { param([string]$m) Write-Host ('  [ok] ' + $m) }
function Warn { param([string]$m) Write-Host ('  [!]  ' + $m) -ForegroundColor Yellow }
function Fail { param([string]$m) Write-Host ('  [x]  ' + $m) -ForegroundColor Red; $script:Failed = $true }

$InstallHome = Join-Path $env:USERPROFILE '.codex-auto-resume'
$AppDir      = Join-Path $InstallHome 'app'
$RunDir      = Join-Path $InstallHome 'runtime'
$Payload     = Join-Path (Split-Path -Parent $PSScriptRoot) 'payload'
$Python      = Join-Path $RunDir 'python.exe'

function Invoke-Codex {
    # Native stderr must not become a terminating error: PowerShell 5.1 wraps it in an
    # ErrorRecord, and `codex` writes ordinary progress there. Capture to files instead
    # of using 2>&1, and judge the result by the exit code alone.
    param([string]$Exe, [string[]]$Arguments)
    $out = [System.IO.Path]::GetTempFileName()
    $err = [System.IO.Path]::GetTempFileName()
    try {
        $p = Start-Process -FilePath $Exe -ArgumentList $Arguments -NoNewWindow -Wait -PassThru `
             -RedirectStandardOutput $out -RedirectStandardError $err
        return @{ Code = $p.ExitCode
                  Out  = (Get-Content -Raw -ErrorAction SilentlyContinue $out)
                  Err  = (Get-Content -Raw -ErrorAction SilentlyContinue $err) }
    } finally {
        Remove-Item -Force -ErrorAction SilentlyContinue $out, $err
    }
}

function Get-CodexCli {
    # The desktop app keeps its engine in a content-addressed directory and does not put
    # it on PATH, so look there rather than relying on the environment.
    $root = Join-Path $env:LOCALAPPDATA 'OpenAI\Codex\bin'
    if (-not (Test-Path $root)) { return $null }
    $found = @(Get-ChildItem -Path $root -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { Join-Path $_.FullName 'codex.exe' } |
        Where-Object { Test-Path $_ } |
        Sort-Object { (Get-Item $_).LastWriteTime } -Descending)
    if ($found.Count -eq 0) { return $null }
    return $found[0]
}

function Invoke-Setup {
    # The command's stdout must not leak into the return value: a bare call would make
    # the function return every printed line AND the exit code as an array, and any
    # comparison against 0 would then be true no matter how well setup went.
    param([string[]]$Arguments)
    $setup = Join-Path $AppDir 'scripts\plugin_setup.py'
    & $Python $setup @Arguments | ForEach-Object { Write-Host ('    ' + $_) }
    return $LASTEXITCODE
}

Write-Host ''
Write-Host 'Codex Auto Resume'
Write-Host ''

if ($env:OS -ne 'Windows_NT') { Fail 'This tool targets Windows only.'; exit 1 }

# ----------------------------------------------------------------------- uninstall
if ($Uninstall) {
    if (Test-Path $Python) {
        Step 'Removing the watcher, autostart, notification identity and Start Menu entry'
        $null = Invoke-Setup @('uninstall')
    } else {
        Warn 'No installed runtime found; skipping watcher removal.'
    }
    $codex = Get-CodexCli
    if ($codex) {
        Step 'Removing the Codex plugin'
        $null = Invoke-Codex $codex @('plugin', 'remove', ($PluginName + '@' + $MarketplaceName))
        $null = Invoke-Codex $codex @('plugin', 'marketplace', 'remove', $MarketplaceName)
    }
    Step 'Removing program files'
    foreach ($dir in @($AppDir, $RunDir)) {
        if (Test-Path $dir) { Remove-Item -Recurse -Force $dir -ErrorAction SilentlyContinue }
    }
    foreach ($file in @('CodexAutoResumeSettings.exe', 'codex-auto-resume.ico', 'watcher-launcher.py', 'runtime.json')) {
        $path = Join-Path $InstallHome $file
        if (Test-Path $path) { Remove-Item -Force $path -ErrorAction SilentlyContinue }
    }
    if ($Purge) {
        # Only on an explicit request: this is the user's recovery history.
        foreach ($dir in @((Join-Path $InstallHome 'config'), (Join-Path $InstallHome 'logs'))) {
            if (Test-Path $dir) { Remove-Item -Recurse -Force $dir -ErrorAction SilentlyContinue }
        }
        Write-Host ''
        Write-Host 'Removed, including settings and recovery history.'
    } else {
        Write-Host ''
        Write-Host 'Removed. Settings and pending recoveries were kept.'
        Write-Host ('They are in ' + $InstallHome + ' - re-installing picks them up again.')
    }
    Write-Host 'Your Codex conversations were not touched.'
    exit 0
}

# -------------------------------------------------------------------------- install
if (-not (Test-Path $Payload)) { Fail 'This installer is missing its payload folder.'; exit 1 }

$codex = Get-CodexCli
if ($null -eq $codex) {
    Fail 'The ChatGPT/Codex desktop app was not found.'
    Write-Host '       Install it and run it once, then run this installer again.'
    exit 1
}
Ok 'Found Codex'

if ((Invoke-Codex $codex @('plugin', '--help')).Code -ne 0) {
    Fail 'This Codex build has no plugin support. Update Codex and try again.'; exit 1
}

$upgrade = Test-Path $AppDir
if ($upgrade) { Step 'Updating program files' } else { Step 'Installing program files' }
# Replace only the program directories. Settings, state and logs sit beside them and are
# deliberately not in this list, so an upgrade cannot lose a pending recovery.
foreach ($pair in @(@{ src = 'app'; dst = $AppDir }, @{ src = 'runtime'; dst = $RunDir })) {
    $source = Join-Path $Payload $pair.src
    if (-not (Test-Path $source)) { Fail ('Payload is incomplete: ' + $pair.src); exit 1 }
    if (Test-Path $pair.dst) { Remove-Item -Recurse -Force $pair.dst }
    New-Item -ItemType Directory -Force -Path $pair.dst | Out-Null
    Copy-Item -Path (Join-Path $source '*') -Destination $pair.dst -Recurse -Force
}
# The settings window and the icon live at the payload root because the window
# resolves runtime\python.exe and app\src relative to its own directory.
foreach ($file in (Get-ChildItem -Path $Payload -File -ErrorAction SilentlyContinue)) {
    Copy-Item -Path $file.FullName -Destination (Join-Path $InstallHome $file.Name) -Force
}
if (-not (Test-Path $Python)) { Fail 'The bundled Python runtime is missing from the payload.'; exit 1 }
$runtimeVersion = & $Python -c 'import sys;print(str(sys.version_info[0])+chr(46)+str(sys.version_info[1]))'
Ok ('Bundled Python ' + $runtimeVersion + ' (no system Python needed)')

# The payload is itself a valid local marketplace, so the plugin installs from the same
# bytes that were just verified, with no network access.
Step 'Registering the Codex plugin'
$added = Invoke-Codex $codex @('plugin', 'marketplace', 'add', $AppDir)
if ($added.Code -ne 0) {
    # A previous install may have registered the same marketplace name from GitHub.
    # Repointing it at the payload is the upgrade path, so replace rather than fail.
    if (($added.Err + $added.Out) -match 'already added from a different source') {
        Step 'Repointing the existing marketplace at this installation'
        $null = Invoke-Codex $codex @('plugin', 'marketplace', 'remove', $MarketplaceName)
        $added = Invoke-Codex $codex @('plugin', 'marketplace', 'add', $AppDir)
    }
}
if ($added.Code -ne 0) { Warn 'Could not register the local marketplace; the Codex skill may be unavailable.' }
$null = Invoke-Codex $codex @('plugin', 'marketplace', 'upgrade')
$installed = Invoke-Codex $codex @('plugin', 'add', ($PluginName + '@' + $MarketplaceName))
if ($installed.Code -ne 0) { Warn 'Could not install the Codex plugin; the watcher will still run.' }
else { Ok 'Codex plugin installed' }

Step 'Setting up the watcher'
$setupArgs = @('setup')
if ($SkipStartup) { $setupArgs += '--no-startup' }
$code = Invoke-Setup $setupArgs
if ($code -ne 0) {
    Fail 'Setup did not complete. Nothing was removed; read the message above.'
    exit 1
}

Step 'Checking the installation'
$null = Invoke-Setup @('doctor')
if ($LASTEXITCODE -ne 0) { Warn 'The health check reported a problem. Recovery is installed but may not be ready.' }

Write-Host ''
if ($script:Failed) { Write-Host 'Finished with problems. See the messages above.'; exit 1 }
if ($upgrade) { Write-Host 'Updated. Your settings and pending recoveries were kept.' }
else { Write-Host 'Installed and running.' }
Write-Host 'Recommended settings are already on. Nothing else to do.'
Write-Host ''
Write-Host 'To change anything: open Codex and ask "open auto resume settings",'
Write-Host 'or use Start Menu > Codex Auto Resume.'
exit 0
