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

# One installation at a time. There are three routes in - a double-clicked Install.cmd,
# an upgrade, and the Codex plugin's bootstrap - and two of them running together would
# copy over each other's half-written payload and race on the same plugin cache.
#
# The mutex is not released explicitly. This script has many exit points, and Windows
# releases a mutex when the owning process ends, which for an installer is moments after
# the last of them. A previous run that was killed leaves it abandoned rather than held:
# WaitOne then throws instead of returning, and an abandoned lock means the holder is
# gone, so it is taken rather than treated as contention.
$script:InstallLock = New-Object System.Threading.Mutex($false, 'Local\CodexAutoResume.Install')
$held = $false
try { $held = $script:InstallLock.WaitOne(0) }
catch [System.Threading.AbandonedMutexException] { $held = $true }
if (-not $held) {
    Fail 'Another Codex Auto Resume installation is already running.'
    Write-Host '       Wait for it to finish, then run this again.'
    exit 1
}

# The same override the Python side honours. It exists for a machine whose profile is
# not where the state should live, and the two have to agree about it: the installer
# deploying to one home while setup configures another is exactly the split this
# release removes.
$InstallHome = $env:CODEX_AUTO_RESUME_PLUGIN_HOME
if ([string]::IsNullOrWhiteSpace($InstallHome)) {
    $InstallHome = Join-Path $env:USERPROFILE '.codex-auto-resume'
}
$AppDir      = Join-Path $InstallHome 'app'
$RunDir      = Join-Path $InstallHome 'runtime'
$Payload     = Join-Path (Split-Path -Parent $PSScriptRoot) 'payload'
$Python      = Join-Path $RunDir 'python.exe'

function Quote-Argument {
    <#
        Quote one argument the way CommandLineToArgvW will read it back.

        Start-Process joins -ArgumentList with single spaces and quotes nothing, so an
        installation home containing a space - `C:\Users\Example User\...`, or a profile
        under a folder like `OneDrive - Company` - arrives at codex as two arguments, so
        the marketplace path is wrong and the plugin is never registered. The registry
        side has had this exactly right since v0.5.0 (startup.quote_argument, with the
        same backslash rule); this side had not, and warned rather than failing, so the
        run still ended with "Installed and running."

        The backslash rule is the documented one: a run of backslashes matters only
        immediately before a quote, where it has to be doubled.
    #>
    param([string]$Value)
    $quoted = New-Object System.Text.StringBuilder
    [void]$quoted.Append('"')
    $slashes = 0
    foreach ($ch in $Value.ToCharArray()) {
        if ($ch -eq '\') { $slashes++; continue }
        if ($ch -eq '"') {
            [void]$quoted.Append('\' * ($slashes * 2 + 1)).Append('"')
        } else {
            [void]$quoted.Append('\' * $slashes).Append($ch)
        }
        $slashes = 0
    }
    [void]$quoted.Append('\' * ($slashes * 2)).Append('"')
    return $quoted.ToString()
}

function Invoke-Codex {
    # Native stderr must not become a terminating error: PowerShell 5.1 wraps it in an
    # ErrorRecord, and `codex` writes ordinary progress there. Capture to files instead
    # of using 2>&1, and judge the result by the exit code alone.
    param([string]$Exe, [string[]]$Arguments)
    $out = [System.IO.Path]::GetTempFileName()
    $err = [System.IO.Path]::GetTempFileName()
    $line = (($Arguments | ForEach-Object { Quote-Argument $_ }) -join ' ')
    try {
        $p = Start-Process -FilePath $Exe -ArgumentList $line -NoNewWindow -Wait -PassThru `
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
        # Without -Purge this keeps settings and pending recoveries, which is what the
        # message at the end of this branch promises. It used to call plain `uninstall`,
        # which deletes them - so a reinstall silently lost everything that was waiting.
        $setupArgs = @('uninstall')
        if ($Purge) { $setupArgs += '--purge' }
        # The exit code matters. That step fails closed when the watcher is still
        # running or its state cannot be verified, and throwing the code away meant
        # deleting the engine and the interpreter out from under a live watcher and
        # then printing "Removed." over the top of its refusal.
        $code = Invoke-Setup $setupArgs
        if ($code -ne 0) {
            Fail 'The watcher could not be stopped, so nothing was removed.'
            Write-Host '       Close the ChatGPT/Codex app, wait a moment, and run this again.'
            exit 1
        }
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
    # Codex keeps this plugin's MCP server running, and that holds the bundled
    # interpreter's DLLs open; a loaded image cannot be deleted. The install path has
    # been hardened against exactly this since v0.5.1 and the uninstall path had not, so
    # removal half-failed in silence and still reported success. Stopping only our own
    # launchers is enough - nothing else has a reason to run them.
    $ours = @(Get-CimInstance Win32_Process -Filter "Name='codex-auto-resume-mcp.exe'" -ErrorAction SilentlyContinue)
    if ($ours.Count -gt 0) {
        Step 'Releasing the files this installation is holding open'
        foreach ($process in $ours) { Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Milliseconds 800
    }
    foreach ($stale in (Get-ChildItem -Path $InstallHome -Filter '*.old-*' -ErrorAction SilentlyContinue)) {
        Remove-Item -Recurse -Force $stale.FullName -ErrorAction SilentlyContinue
    }
    $stuck = @()
    foreach ($dir in @($AppDir, $RunDir)) {
        if (Test-Path $dir) { Remove-Item -Recurse -Force $dir -ErrorAction SilentlyContinue }
        # -ErrorAction SilentlyContinue swallows a sharing violation, so ask afterwards
        # rather than assuming. A half-deleted installation reported as "Removed." is
        # worse than an honest failure: nothing tells the user to try again.
        if (Test-Path $dir) { $stuck += $dir }
    }
    foreach ($file in @('CodexAutoResumeSettings.exe', 'codex-auto-resume.ico', 'watcher-launcher.py', 'runtime.json')) {
        $path = Join-Path $InstallHome $file
        if (Test-Path $path) { Remove-Item -Force $path -ErrorAction SilentlyContinue }
    }
    if ($stuck.Count -gt 0) {
        Write-Host ''
        Fail 'Some program files are still in use and could not be removed:'
        foreach ($dir in $stuck) { Write-Host ('       ' + $dir) }
        Write-Host '       Close the ChatGPT/Codex app and run this again. The watcher is'
        Write-Host '       already stopped and unregistered, so nothing is running now.'
        exit 1
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

# Sweep up copies moved aside by an earlier upgrade. They are only removable once
# whatever was using them has exited, which is normally by now.
foreach ($stale in (Get-ChildItem -Path $InstallHome -Directory -Filter '*.old-*' -ErrorAction SilentlyContinue)) {
    Remove-Item -Recurse -Force $stale.FullName -ErrorAction SilentlyContinue
}

# Replace only the program directories. Settings, state and logs sit beside them and are
# deliberately not in this list, so an upgrade cannot lose a pending recovery.
#
# Moved aside, never deleted in place. Codex keeps this plugin's MCP server running, and
# that holds the bundled interpreter's DLLs open; a loaded DLL cannot be deleted, so
# `Remove-Item` failed part-way through and left the installation half-replaced. Windows
# does allow renaming the directory that contains an open file - the running process
# keeps working - so the old copy is moved out of the way and swept up next time.
$pairs = @(@{ src = 'app'; dst = $AppDir }, @{ src = 'runtime'; dst = $RunDir })
foreach ($pair in $pairs) {
    if (-not (Test-Path (Join-Path $Payload $pair.src))) { Fail ('Payload is incomplete: ' + $pair.src); exit 1 }
}

# Move everything aside first, copy second, and undo the whole thing on any failure -
# including a failure during the copy. An upgrade that stops half way is worse than one
# that does not happen: the first attempt at this rolled back a failed move but not a
# failed copy, and left the application present and the interpreter missing.
$moved = @()
try {
    foreach ($pair in $pairs) {
        if (-not (Test-Path $pair.dst)) { continue }
        $aside = $pair.dst + '.old-' + (Get-Date -Format 'yyyyMMddHHmmss')
        Move-Item -Path $pair.dst -Destination $aside -ErrorAction Stop
        $moved += @{ from = $aside; to = $pair.dst }
    }
    foreach ($pair in $pairs) {
        New-Item -ItemType Directory -Force -Path $pair.dst | Out-Null
        # Join-Path takes two paths in Windows PowerShell; a third argument is a
        # parameter-binding error, not a longer path.
        Copy-Item -Path (Join-Path (Join-Path $Payload $pair.src) '*') `
                  -Destination $pair.dst -Recurse -Force -ErrorAction Stop
    }
} catch {
    Warn ('Could not replace the installation: ' + $_.Exception.Message)
    foreach ($undo in $moved) {
        if (Test-Path $undo.to) { Remove-Item -Recurse -Force $undo.to -ErrorAction SilentlyContinue }
        Move-Item -Path $undo.from -Destination $undo.to -Force -ErrorAction SilentlyContinue
    }
    Fail 'The existing installation was put back; nothing was changed.'
    Write-Host '       Close the ChatGPT/Codex app and run this installer again.'
    exit 1
}
foreach ($old in $moved) { Remove-Item -Recurse -Force $old.from -ErrorAction SilentlyContinue }

# The settings window and the icon live at the payload root because the window
# resolves runtime\python.exe and app\src relative to its own directory. The window may
# be open right now, so the same move-aside rule applies to it.
foreach ($file in (Get-ChildItem -Path $Payload -File -ErrorAction SilentlyContinue)) {
    $target = Join-Path $InstallHome $file.Name
    try {
        Copy-Item -Path $file.FullName -Destination $target -Force -ErrorAction Stop
    } catch {
        $aside = $target + '.old-' + (Get-Date -Format 'yyyyMMddHHmmss')
        Move-Item -Path $target -Destination $aside -Force -ErrorAction SilentlyContinue
        Copy-Item -Path $file.FullName -Destination $target -Force
    }
}
foreach ($stale in (Get-ChildItem -Path $InstallHome -File -Filter '*.old-*' -ErrorAction SilentlyContinue)) {
    Remove-Item -Force $stale.FullName -ErrorAction SilentlyContinue
}
if (-not (Test-Path $Python)) { Fail 'The bundled Python runtime is missing from the payload.'; exit 1 }
$runtimeVersion = & $Python -c 'import sys;print(str(sys.version_info[0])+chr(46)+str(sys.version_info[1]))'
Ok ('Bundled Python ' + $runtimeVersion + ' (no system Python needed)')

# The payload is itself a valid local marketplace, so the plugin installs from the bytes
# already on disk rather than from GitHub, with no network access. Nothing *here*
# verifies those bytes: on the plugin route the bootstrap checked the archive before
# unpacking it, and a hand-extracted download carries only the assurance whoever
# downloaded it obtained for themselves.
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
if ($installed.Code -ne 0 -and (($installed.Err + $installed.Out) -match 'os error 5|back up plugin cache')) {
    # Codex replaces the plugin by backing up its cache directory, and it cannot while
    # a file inside that directory is open. The open file is ours: Codex starts this
    # plugin's MCP launcher, which lives in the plugin, so the plugin cannot be updated
    # while Codex is using it. Stopping only our own launchers is enough - Codex starts
    # a fresh one the next time it needs the server.
    $ours = @(Get-CimInstance Win32_Process -Filter "Name='codex-auto-resume-mcp.exe'" -ErrorAction SilentlyContinue)
    if ($ours.Count -gt 0) {
        Step 'Releasing the plugin files this installation is holding open'
        foreach ($process in $ours) {
            Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Milliseconds 800
        $installed = Invoke-Codex $codex @('plugin', 'add', ($PluginName + '@' + $MarketplaceName))
    }
}
if ($installed.Code -ne 0) {
    Warn 'Could not update the Codex plugin; the watcher and its settings still work.'
    Write-Host '       Close the ChatGPT/Codex app and run this installer again to finish it.'
} else { Ok 'Codex plugin installed' }

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
