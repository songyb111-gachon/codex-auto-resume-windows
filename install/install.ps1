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
# Where Codex keeps its copy of this plugin. The MCP launcher runs from there rather than
# from the installation, so recognising our own process needs both roots.
$codexHomeDir = $env:CODEX_HOME
if ([string]::IsNullOrWhiteSpace($codexHomeDir)) { $codexHomeDir = Join-Path $env:USERPROFILE '.codex' }
$PluginCacheRoot = Join-Path (Join-Path (Join-Path $codexHomeDir 'plugins') 'cache') $MarketplaceName
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

function Resolve-Canonical {
    <#
        One spelling for one location, with every reparse point followed.

        Ownership is decided by comparing paths, so the comparison has to survive the
        several names Windows will hand out for the same directory: an 8.3 short name, a
        different case, a junction, a `\\?\` extended-length prefix (which `codex plugin
        list --json` returns and `marketplace list --json` does not). `GetFullPath` alone
        normalises separators and nothing else, so a junction pointing out of the
        installation would still read as inside it.

        Returns $null when the path cannot be resolved. Callers treat that as "not ours".
    #>
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return $null }
    $text = $Path
    if ($text.StartsWith('\\?\UNC\')) { $text = '\\' + $text.Substring(8) }
    elseif ($text.StartsWith('\\?\')) { $text = $text.Substring(4) }
    try { $text = [IO.Path]::GetFullPath($text) } catch { return $null }

    # Resolve component by component, from the root down. Resolving only the leaf is not
    # enough: `<home>\escape\keep.txt` has no reparse point at `keep.txt`, so a leaf-only
    # resolver reports it as living under `<home>` while it actually lives wherever
    # `escape` points. A directory in the middle of the path is exactly where a junction
    # is useful to whoever placed it.
    $root = [IO.Path]::GetPathRoot($text)
    $rest = $text.Substring($root.Length)
    $current = $root.TrimEnd('\')
    if ($current -eq '') { $current = $root }
    foreach ($part in $rest.Split([char]'\', [StringSplitOptions]::RemoveEmptyEntries)) {
        $current = Join-Path $current $part
        try {
            $item = Get-Item -LiteralPath $current -Force -ErrorAction Stop
        } catch {
            continue        # not on disk yet; the remaining components are literal
        }
        $guard = 0
        while ($item.LinkType -and $item.Target -and $guard -lt 16) {
            $target = @($item.Target)[0]
            try { $item = Get-Item -LiteralPath $target -Force -ErrorAction Stop } catch { break }
            $guard++
        }
        $current = $item.FullName
    }
    return $current.TrimEnd('\')
}

function Test-PathInside {
    <#
        True when Child is Parent, or lives under it, after both are canonicalised.

        Used for every destructive decision in this file: which directories may be
        deleted, which running processes may be stopped, which marketplace may be
        removed. One implementation, so there is one thing to be right about.
    #>
    param([string]$Child, [string]$Parent)
    $c = Resolve-Canonical $Child
    $p = Resolve-Canonical $Parent
    if (-not $c -or -not $p) { return $false }
    if ($c -eq $p) { return $true }
    return $c.StartsWith($p + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
}

function Get-OwnedMcpProcess {
    <#
        Running MCP launchers that belong to an installation we are managing.

        A process name is not ownership. This used to match `Name='codex-auto-resume-mcp.exe'`
        and force-stop every hit, so a build, a test fixture or a second installation
        running an executable with the same filename was killed by an unrelated install.

        The launcher normally runs from the Codex plugin cache rather than from the
        installation, so both roots count - and the cache path has to name *this* plugin,
        not merely be somewhere under the cache.

        A process whose ExecutablePath cannot be read is skipped: not being able to tell
        is not permission to kill.
    #>
    param([string[]]$Roots)
    $found = @()
    $all = @(Get-CimInstance Win32_Process -Filter "Name='codex-auto-resume-mcp.exe'" -ErrorAction SilentlyContinue)
    foreach ($process in $all) {
        $exe = $process.ExecutablePath
        if ([string]::IsNullOrWhiteSpace($exe)) { continue }
        foreach ($root in $Roots) {
            if ($root -and (Test-PathInside $exe $root)) { $found += $process; break }
        }
    }
    return ,$found
}

function Get-OwnedWatcherProcess {
    <#
        The watcher belonging to this installation, if one is running.

        Found by what it is, not by what it is called: the bundled interpreter of *this*
        installation, running this installation's watcher launcher. Any other Python on
        the machine - another project, a second installation - is not ours to wait for.

        An upgrade has to know, because renaming the program directories under a running
        watcher succeeds and leaves the old code executing from the renamed copy. v0.5.7
        is a security fix; an upgrade that left the vulnerable watcher running until the
        next sign-in would not have fixed anything yet.
    #>
    $found = @()
    $all = @(Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue)
    foreach ($process in $all) {
        $exe = $process.ExecutablePath
        $line = $process.CommandLine
        if ([string]::IsNullOrWhiteSpace($exe) -or [string]::IsNullOrWhiteSpace($line)) { continue }
        if (-not (Test-PathInside $exe $RunDir)) { continue }
        if ($line -notmatch 'watcher-launcher\.py') { continue }
        $found += $process
    }
    # The leading comma keeps an empty or one-element result an array. Callers read
    # (Get-OwnedWatcherProcess).Count; wrapping the call in @() instead would make a
    # one-element array of the array, whose Count is always 1 - which is exactly how
    # the first version of the upgrade handover waited sixty seconds for a watcher
    # that had exited in under one.
    return ,$found
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

function Get-MarketplaceRoot {
    <#
        Where a configured marketplace currently points, or $null if unknown.

        `codex plugin marketplace list --json` is a supported interface and returns
        `{"marketplaces":[{"name","root"}]}` - verified against codex-cli 0.153.4. No
        text scraping, and if the shape is not what we expect we return $null and the
        caller leaves the marketplace alone.
    #>
    param([string]$Exe, [string]$Name)
    $result = Invoke-Codex $Exe @('plugin', 'marketplace', 'list', '--json')
    if ($result.Code -ne 0 -or [string]::IsNullOrWhiteSpace($result.Out)) { return $null }
    try { $parsed = $result.Out | ConvertFrom-Json } catch { return $null }
    if (-not $parsed.PSObject.Properties.Match('marketplaces').Count) { return $null }
    foreach ($entry in $parsed.marketplaces) {
        if ($entry.name -eq $Name) { return $entry.root }
    }
    return $null            # not configured at all: nothing to remove
}

function Get-InstalledPluginSource {
    <#
        Where the installed plugin was installed from, or $null if it cannot be told.

        `codex plugin list --json` returns installed entries carrying `source.path`.
        Note that the sibling `marketplaceSource.source` arrives with a `\\?\` prefix;
        Resolve-Canonical strips it, but `source.path` is the field this reads.
    #>
    param([string]$Exe, [string]$Plugin, [string]$Marketplace)
    $result = Invoke-Codex $Exe @('plugin', 'list', '--json')
    if ($result.Code -ne 0 -or [string]::IsNullOrWhiteSpace($result.Out)) { return $null }
    try { $parsed = $result.Out | ConvertFrom-Json } catch { return $null }
    if (-not $parsed.PSObject.Properties.Match('installed').Count) { return $null }
    foreach ($entry in $parsed.installed) {
        if ($entry.name -eq $Plugin -and $entry.marketplaceName -eq $Marketplace) {
            if ($entry.PSObject.Properties.Match('source').Count -and $entry.source) {
                return $entry.source.path
            }
            return $null
        }
    }
    return ''               # configured marketplace, but this plugin is not installed
}

function Remove-OwnedItem {
    <#
        Delete one path, but only after re-proving it lies inside the verified root.

        $OwnedHome is set once, from the engine's own provenance check, and is the
        canonical path - so this is not a second ownership rule, it is the confinement
        half of the same one. Re-checking each target rather than trusting the loop that
        produced it is what stops a junction inside the installation from redirecting a
        recursive delete somewhere else between the check and the deletion.

        Returns $true when the path is gone afterwards.
    #>
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($OwnedHome)) {
        Warn ('Refusing to delete ' + $Path + ': the installation root was never verified.')
        return $false
    }
    if (-not (Test-PathInside $Path $OwnedHome)) {
        Warn ('Refusing to delete ' + $Path + ': it is outside the verified installation.')
        return $false
    }
    Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue
    return (-not (Test-Path -LiteralPath $Path))
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
    # Nothing is deleted until this installation can prove the root belongs to it.
    #
    # $InstallHome comes from an environment variable, so it can point anywhere, and
    # this branch used to delete `app`, `runtime`, every `*.old-*`, and - with -Purge -
    # `config` and `logs` beneath it, with no check at all. A directory that happened to
    # contain folders with those names was indistinguishable from an installation.
    #
    # The question is answered by the engine rather than re-implemented here: `verify-home`
    # applies the same provenance rule the Python uninstall has always applied, and prints
    # the canonical root. Every deletion below is confined to that canonical path, not to
    # the string this script started from - so a junction cannot widen the target after
    # the check has passed.
    if (-not (Test-Path $Python)) {
        Warn 'No installed runtime found here, so nothing can be verified or removed.'
        Write-Host ('       Looked in ' + $InstallHome)
        exit 1
    }
    # Ask the *payload's* copy of the engine, not the installed one.
    #
    # `verify-home` arrived in v0.5.4, and this uninstaller has to work against an
    # installation made by an earlier version - where asking the installed copy gets an
    # argparse error, a non-zero exit, and a refusal to uninstall a perfectly legitimate
    # installation. The payload travels with this script and is always its own version,
    # so it can always answer. Measured, by running exactly that against a v0.5.3 tree.
    $verifier = Join-Path $Payload 'app\scripts\plugin_setup.py'
    if (-not (Test-Path $verifier)) { $verifier = Join-Path $AppDir 'scripts\plugin_setup.py' }
    $interpreter = $Python
    if (-not (Test-Path $interpreter)) { $interpreter = Join-Path $Payload 'runtime\python.exe' }
    $verify = & $interpreter $verifier 'verify-home' 2>$null
    if ($LASTEXITCODE -ne 0) {
        Fail 'This directory is not a Codex Auto Resume installation, so nothing was removed.'
        Write-Host ('       ' + $InstallHome)
        Write-Host '       Refusing to delete anything here: no installation of ours has ever'
        Write-Host '       claimed this directory. If you meant a different location, set'
        Write-Host '       CODEX_AUTO_RESUME_PLUGIN_HOME to it and run this again.'
        exit 1
    }
    $OwnedHome = Resolve-Canonical (@($verify)[-1])
    if (-not $OwnedHome -or -not (Test-PathInside $AppDir $OwnedHome)) {
        Fail 'The installation root could not be resolved; nothing was removed.'
        exit 1
    }
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
        # Remove the plugin and the marketplace only while they still point at this
        # installation. A user may repoint the same marketplace name at a fork of their
        # own; removing it by name would take their configuration with ours.
        $pluginSource = Get-InstalledPluginSource $codex $PluginName $MarketplaceName
        if ($null -eq $pluginSource) {
            Warn 'Could not tell where the installed Codex plugin came from; leaving it alone.'
        } elseif ($pluginSource -eq '') {
            Step 'The Codex plugin is not installed; nothing to remove'
        } elseif (Test-PathInside $pluginSource $AppDir) {
            Step 'Removing the Codex plugin'
            # Not `$null =`. Codex refuses this while it holds the plugin cache open - the
            # same os error 5 the install path handles by name - and throwing the code away
            # printed "Removed." over the top of a plugin that is still registered and now
            # points at a directory being deleted.
            $gone = Invoke-Codex $codex @('plugin', 'remove', ($PluginName + '@' + $MarketplaceName))
            if ($gone.Code -ne 0) {
                Fail ("Codex could not remove the plugin '" + $PluginName + "'.")
                Write-Host '       Close the ChatGPT/Codex app and run this again.'
            }
        } else {
            Warn ("The installed plugin '" + $PluginName + "' now comes from a different source;")
            Write-Host ('       leaving it installed. Source: ' + $pluginSource)
        }

        $marketplaceRoot = Get-MarketplaceRoot $codex $MarketplaceName
        if ($null -eq $marketplaceRoot) {
            Step ("Marketplace '" + $MarketplaceName + "' is not configured; nothing to remove")
        } elseif (Test-PathInside $marketplaceRoot $AppDir) {
            Step 'Removing the marketplace this installation registered'
            $gone = Invoke-Codex $codex @('plugin', 'marketplace', 'remove', $MarketplaceName)
            if ($gone.Code -ne 0) {
                Fail ("Codex could not remove the marketplace '" + $MarketplaceName + "'.")
                Write-Host '       Close the ChatGPT/Codex app and run this again.'
            }
        } else {
            Warn ("Marketplace '" + $MarketplaceName + "' now points to a different source.")
            Write-Host '       Leaving it configured because this installation no longer owns it.'
            Write-Host ('       Source: ' + $marketplaceRoot)
        }
    }
    Step 'Removing program files'
    # Codex keeps this plugin's MCP server running, and that holds the bundled
    # interpreter's DLLs open; a loaded image cannot be deleted. The install path has
    # been hardened against exactly this since v0.5.1 and the uninstall path had not, so
    # removal half-failed in silence and still reported success. Stopping only our own
    # launchers is enough - nothing else has a reason to run them.
    $ours = Get-OwnedMcpProcess -Roots @($OwnedHome, $PluginCacheRoot)
    if ($ours.Count -gt 0) {
        Step 'Releasing the files this installation is holding open'
        foreach ($process in $ours) { Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Milliseconds 800
    }
    foreach ($stale in (Get-ChildItem -Path $OwnedHome -Filter '*.old-*' -ErrorAction SilentlyContinue)) {
        Remove-OwnedItem $stale.FullName
    }
    $stuck = @()
    foreach ($dir in @($AppDir, $RunDir)) {
        if (-not (Test-Path $dir)) { continue }
        if (-not (Remove-OwnedItem $dir)) { $stuck += $dir; continue }
        # -ErrorAction SilentlyContinue swallows a sharing violation, so ask afterwards
        # rather than assuming. A half-deleted installation reported as "Removed." is
        # worse than an honest failure: nothing tells the user to try again.
        if (Test-Path $dir) { $stuck += $dir }
    }
    if ($stuck.Count -gt 0) {
        Write-Host ''
        Fail 'Some program files are still in use and could not be removed:'
        foreach ($dir in $stuck) { Write-Host ('       ' + $dir) }
        Write-Host '       Close the ChatGPT/Codex app and run this again. The watcher is'
        Write-Host '       already stopped and unregistered, so nothing is running now.'
        exit 1
    }
    # The last thing to go is the proof that any of this was ours.
    #
    # A purge has already taken the other two: the Python step deletes `config/`'s marker
    # and always unlinks `runtime.json`, so the root marker is the only route left through
    # `owns_home()`. Deleting it before the check below - which can still stop the run and
    # ask the user to close Codex and try again - made that retry impossible: the second
    # run finds no proof and refuses to remove the half-deleted installation, permanently.
    # So the check comes first, and the proof only goes when there is nothing left to do.
    foreach ($file in @('CodexAutoResumeSettings.exe', 'codex-auto-resume.ico', 'watcher-launcher.py',
                        'runtime.json', '.owned-by-codex-auto-resume')) {
        $path = Join-Path $OwnedHome $file
        if (Test-Path $path) { $null = Remove-OwnedItem $path }
    }
    if ($Purge) {
        # Only on an explicit request: this is the user's recovery history.
        foreach ($dir in @((Join-Path $OwnedHome 'config'), (Join-Path $OwnedHome 'logs'))) {
            if (Test-Path $dir) { $null = Remove-OwnedItem $dir }
        }
        Write-Host ''
        Write-Host 'Removed, including settings and recovery history.'
    } else {
        Write-Host ''
        Write-Host 'Removed. Settings and pending recoveries were kept.'
        Write-Host ('They are in ' + $InstallHome + ' - re-installing picks them up again.')
    }
    Write-Host 'Your Codex conversations were not touched.'
    # `Fail` records rather than exits, so a step that could not finish - a plugin Codex
    # would not let go of, a file it could not delete - has to be answered for here. The
    # install path has read $script:Failed at the end since v0.1; this branch exited 0
    # regardless, which is how a refused removal came to be reported as a removal.
    if ($script:Failed) {
        Write-Host ''
        Write-Host 'Finished with problems. See the messages above.'
        exit 1
    }
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

# Nothing under this root is destroyed unless the installation can claim it.
#
# `$InstallHome` comes from an environment variable, and three deletions below act on
# whatever is beneath it: the `*.old-*` sweep, the move-aside of `app` and `runtime`, and
# the removal of the copies moved aside. The uninstall branch above already refuses a
# directory no installation of ours has claimed - and an install into that same directory
# used to delete inside it and finish with "Installed and running."
#
# `claim-home` answers the install-side half of the question, in the same engine and by
# the same rule: ours already, or empty of anything of ours - in which case it is claimed
# now, before a byte is written. That ordering is the whole point. A marker written after
# the deletions would authorise them backwards, which is not authorisation.
$claimer = Join-Path $Payload 'app\scripts\plugin_setup.py'
$claimPython = Join-Path $Payload 'runtime\python.exe'
if (-not (Test-Path $claimPython)) { $claimPython = $Python }
$claim = & $claimPython $claimer 'claim-home' 2>$null
if ($LASTEXITCODE -ne 0) {
    Fail 'This directory holds files no installation of ours has claimed; nothing was installed.'
    Write-Host ('       ' + $InstallHome)
    foreach ($line in @($claim | Select-Object -Skip 2)) { Write-Host ('         ' + $line) }
    Write-Host '       Installing here would move those aside and then delete them. Point'
    Write-Host '       CODEX_AUTO_RESUME_PLUGIN_HOME at an empty location, or remove them'
    Write-Host '       yourself first if they really are a broken installation of ours.'
    exit 1
}
$OwnedHome = Resolve-Canonical (@($claim)[1])
if (-not $OwnedHome -or -not (Test-PathInside $AppDir $OwnedHome)) {
    Fail 'The installation root could not be resolved; nothing was installed.'
    exit 1
}

$upgrade = Test-Path $AppDir
if ($upgrade) { Step 'Updating program files' } else { Step 'Installing program files' }

# Sweep up copies moved aside by an earlier upgrade. They are only removable once
# whatever was using them has exited, which is normally by now.
foreach ($stale in (Get-ChildItem -Path $OwnedHome -Directory -Filter '*.old-*' -ErrorAction SilentlyContinue)) {
    $null = Remove-OwnedItem $stale.FullName
}

# Hand over from a running watcher before its files are replaced.
#
# Renaming app\ and runtime\ under a live watcher succeeds - Windows allows it - and the
# old process carries on running the old code from the renamed copy, while setup below
# sees the watcher mutex held, reports it already running and starts nothing. For an
# ordinary upgrade that only delays the new version until the next sign-in. For a
# security fix it means the fix is installed and not in effect. So the running watcher
# is asked to stop through its own stop event - the same request "stop" and uninstall
# make - and waited for.
#
# It is asked, never killed. A watcher stopped mid-submission would leave that recovery
# unable to prove whether it was sent, and the product then refuses to send it again.
# If it does not finish within the wait, the upgrade still completes and says plainly
# that the old version is still running and how to replace it.
$previousWatcherStillRunning = $false
if ((Get-OwnedWatcherProcess).Count -gt 0) {
    Step 'Stopping the running watcher so the new version takes over'
    if ((Test-Path $Python) -and (Test-Path (Join-Path $AppDir 'scripts\plugin_setup.py'))) {
        $null = Invoke-Setup @('stop')
    }
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline -and (Get-OwnedWatcherProcess).Count -gt 0) {
        Start-Sleep -Milliseconds 500
    }
    if ((Get-OwnedWatcherProcess).Count -gt 0) {
        $previousWatcherStillRunning = $true
        Warn 'The previous watcher is still finishing and was left running.'
    } else {
        Ok 'The previous watcher stopped'
    }
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
        if (Test-Path $undo.to) { $null = Remove-OwnedItem $undo.to }
        Move-Item -Path $undo.from -Destination $undo.to -Force -ErrorAction SilentlyContinue
    }
    Fail 'The existing installation was put back; nothing was changed.'
    Write-Host '       Close the ChatGPT/Codex app and run this installer again.'
    exit 1
}
foreach ($old in $moved) { $null = Remove-OwnedItem $old.from }

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
foreach ($stale in (Get-ChildItem -Path $OwnedHome -File -Filter '*.old-*' -ErrorAction SilentlyContinue)) {
    $null = Remove-OwnedItem $stale.FullName
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
# Ours, by name - never the no-name form. Without a name, Codex refreshes every Git
# marketplace the user has configured and reinstalls those vendors' plugins: an action on
# other people's software that nobody asked this installer to take, and a network fetch on
# the route that promises none. Measured in an isolated CODEX_HOME: for the local
# marketplace registered above, the named form is a no-op ("not configured as a Git
# marketplace"); it only does anything when a GitHub registration survived the repoint.
$null = Invoke-Codex $codex @('plugin', 'marketplace', 'upgrade', $MarketplaceName)
$installed = Invoke-Codex $codex @('plugin', 'add', ($PluginName + '@' + $MarketplaceName))
if ($installed.Code -ne 0 -and (($installed.Err + $installed.Out) -match 'os error 5|back up plugin cache')) {
    # Codex replaces the plugin by backing up its cache directory, and it cannot while
    # a file inside that directory is open. The open file is ours: Codex starts this
    # plugin's MCP launcher, which lives in the plugin, so the plugin cannot be updated
    # while Codex is using it. Stopping only our own launchers is enough - Codex starts
    # a fresh one the next time it needs the server.
    $ours = Get-OwnedMcpProcess -Roots @($InstallHome, $PluginCacheRoot)
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

# Every run, not only when a locked file forced it: a tool server Codex started before the
# files were replaced is still running the previous version's code, and that code may not
# read the state the new version writes. It holds no state of its own, so ending it only
# costs a restart - Codex starts a fresh one, from the new files, when it next needs the
# tools. Only this installation's own launchers are touched, found by path, never by name.
$stale = Get-OwnedMcpProcess -Roots @($InstallHome, $PluginCacheRoot)
if ($stale.Count -gt 0) {
    Step 'Restarting the plugin tools on the new version'
    foreach ($process in $stale) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

Step 'Setting up the watcher'
$setupArgs = @('setup')
if ($SkipStartup) { $setupArgs += '--no-startup' }
# 2 means everything was done but the watcher was not seen running - a real outcome that
# is neither success nor failure. Treating it as failure would roll back a good install;
# treating it as success is how this script came to end with "Installed and running."
# about a watcher nobody had looked at.
$SETUP_UNCONFIRMED = 2
$code = Invoke-Setup $setupArgs
$watcherUnconfirmed = $code -eq $SETUP_UNCONFIRMED
if ($code -ne 0 -and -not $watcherUnconfirmed) {
    Fail 'Setup did not complete. Nothing was removed; read the message above.'
    exit 1
}

Step 'Checking the installation'
$null = Invoke-Setup @('doctor')
if ($LASTEXITCODE -ne 0) { Warn 'The health check reported a problem. Recovery is installed but may not be ready.' }

Write-Host ''
if ($script:Failed) { Write-Host 'Finished with problems. See the messages above.'; exit 1 }
if ($watcherUnconfirmed) {
    if ($upgrade) { Write-Host 'Updated. Your settings and pending recoveries were kept.' }
    else { Write-Host 'Installed.' }
    Write-Host 'The watcher could not be confirmed running, so nothing is being watched yet.'
    Write-Host 'Open Start Menu > Codex Auto Resume and use Start watcher, or run this again.'
} elseif ($previousWatcherStillRunning) {
    Write-Host 'Updated. Your settings and pending recoveries were kept.'
    Write-Host 'The previous version of the watcher was asked to stop and is still finishing'
    Write-Host 'what it was doing; nothing was ended by force. Once it has stopped, open'
    Write-Host 'Start Menu > Codex Auto Resume and use Start watcher - or sign out and back in.'
} else {
    if ($upgrade) { Write-Host 'Updated. Your settings and pending recoveries were kept.' }
    else { Write-Host 'Installed and running.' }
    Write-Host 'Recommended settings are already on. Nothing else to do.'
}
Write-Host ''
Write-Host 'To change anything: open Codex and ask "open auto resume settings",'
Write-Host 'or use Start Menu > Codex Auto Resume.'
exit 0
