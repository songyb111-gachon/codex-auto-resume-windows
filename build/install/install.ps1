<#
    Installer for codex-auto-resume-windows.

    It deploys a self-contained payload: the application and its own Python runtime.
    There is no system Python requirement, no network requirement and no administrator
    requirement, and it registers nothing outside the current user.

    Re-running it is the upgrade and the repair path. Runtime state - settings, pending
    recoveries, retry budgets and logs - lives beside the installation and is never
    touched here; only the program files are replaced.

    An archive of the other edition from the one installed replaces it only when that was
    asked for: -AllowEditionChange, which Install.cmd passes after a y/N answer and the
    bootstrap only after -Edition and -Force. Without it this says what the change would
    keep and change, and stops with 14 before anything is moved.
#>
[CmdletBinding()]
param(
    [switch]$SkipStartup,        # install, but do not run at Windows sign-in
    [switch]$Uninstall,          # remove the program, keeping settings and pending state
    [switch]$Purge,              # with -Uninstall: also delete settings, state and logs
    [switch]$AllowEditionChange, # replace the installed edition with this archive's other one
    [switch]$Silent,             # for Install.cmd and Uninstall.cmd, which ask nothing and wait for no key with it
    [string]$PluginName      = 'codex-auto-resume',
    [string]$MarketplaceName = 'codex-auto-resume-windows'
)

# Every published bootstrap from v0.5.2 to v0.6.10 passes its -NoStartup in an array splatted
# into this script: `$arguments += '-SkipStartup'; & $installer @arguments`. An array binds by
# position, so the word lands in the first positional parameter, $PluginName, and -SkipStartup
# stays off. Those bootstraps are still installed, and `-Update -NoStartup` makes one of them
# download this release and run this script that way: without this, the update registered the
# sign-in start the person had asked it not to, and gave Codex a plugin named -SkipStartup.
# The word is read back as the switch it meant. Not refused: a refusal here would fail every
# such update outright, for a word whose meaning is not in doubt.
if ($PluginName -ieq '-SkipStartup') {
    $SkipStartup = [switch]$true
    $PluginName = 'codex-auto-resume'
}

$ErrorActionPreference = 'Stop'
$script:Failed = $false
# Text in and out as UTF-8. The setup step's lines are UTF-8 (scripts/plugin_setup.py reconfigures its
# streams), and PowerShell 5.1 decodes a program's output by [Console]::OutputEncoding - the console's code
# page, 949 on a Korean Windows - so its Korean lines arrived as broken characters (issue #33). The Dashboard
# reads this script's output as UTF-8 too. A process with no console to set is no failure.
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch { }

function Step { param([string]$m) Write-Host ('  ' + $m) }
function Ok   { param([string]$m) Write-Host ('  [ok] ' + $m) }
function Warn { param([string]$m) Write-Host ('  [!]  ' + $m) -ForegroundColor Yellow }
function Fail { param([string]$m) Write-Host ('  [x]  ' + $m) -ForegroundColor Red; $script:Failed = $true }

# ----------------------------------------------------------------------- inside another app (v0.6.17)
# A process descended from an MSIX app - the Codex app (OpenAI.Codex), Claude desktop - writes HKCU and %APPDATA%
# into that app's private view, which Windows itself never reads (measured 2026-10-19). Run by an agent inside one
# of them, this installer would put the entry in Settings > Apps, the Run value, the notifications' identity, the
# link handler and the Start menu shortcut where Windows never looks. Nothing in this process tells - not its
# package, token or job - but a live ancestor with package identity does, walked parent by parent with a
# creation-time guard against a reused process id; gui/HostApp.cs makes the same decision for the Dashboard and the
# setup programs. Inside, this script runs again outside through WMI's Win32_Process.Create - the WMI service
# creates the process, with this run's environment and parameters and CODEX_AUTO_RESUME_OUTSIDE=1, which stops a
# second relaunch - passes on what that run prints as it prints it, and ends with its exit code. Where it cannot
# get out, it carries on and says once what will stay inside the app.

# >>> the outside gate: the same text in scripts/bootstrap.ps1, which runs the installation's setup itself in its
# repair branch. Both scripts ship in every archive but neither can find the other from every place it runs (the kept
# uninstaller, Codex's plugin copy), so each carries it, and tests/test_host_app.py holds the two copies equal.
# Opens a process for limited query: its creation time (FILETIME; 0 where it cannot be opened) and its package
# family name (null without package identity).
$script:HostAppSource = @'
using System;
using System.Runtime.InteropServices;
using System.Text;
namespace CodexAutoResumeInstall
{
    public static class HostApp
    {
        [DllImport("kernel32.dll", ExactSpelling = true)]
        static extern IntPtr OpenProcess(uint access, bool inherit, int process);
        [DllImport("kernel32.dll", ExactSpelling = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        static extern bool GetProcessTimes(IntPtr process, out long created, out long exited, out long kernel, out long user);
        [DllImport("kernel32.dll", ExactSpelling = true, CharSet = CharSet.Unicode)]
        static extern int GetPackageFamilyName(IntPtr process, ref uint length, StringBuilder name);
        [DllImport("kernel32.dll", ExactSpelling = true, CharSet = CharSet.Unicode)]
        static extern int GetCurrentPackageFamilyName(ref uint length, StringBuilder name);
        [DllImport("kernel32.dll", ExactSpelling = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        static extern bool CloseHandle(IntPtr handle);

        public static long Open(int id, bool self, out string package)
        {
            package = null;
            IntPtr handle = OpenProcess(0x1000, false, id);
            if (handle == IntPtr.Zero) return 0;
            try
            {
                long created, exited, kernel, user;
                if (!GetProcessTimes(handle, out created, out exited, out kernel, out user)) return 0;
                var name = new StringBuilder(256);
                uint length = (uint)name.Capacity;
                int answer = self ? GetCurrentPackageFamilyName(ref length, name) : GetPackageFamilyName(handle, ref length, name);
                if (answer == 0 && name.Length > 0) package = name.ToString();
                return created;
            }
            finally
            {
                CloseHandle(handle);
            }
        }
    }
}
'@

function Find-PackagedAncestor {
    <#
        The package family name of this process, or of its nearest live ancestor that has one, or $null: the
        decision over a process table, `$Table[pid] = @{ Parent; Created; Package }`. The walk stops - outside -
        where a parent is not in the table or could not be opened (Created 0), where a parent was created after its
        child (its id was reused), on a cycle, and after 32 steps. Pure, so a test can feed it a table of its own.
    #>
    param([hashtable]$Table, [int]$Self)
    $row = $Table[$Self]
    if ($null -eq $row) { return $null }
    if ($row.Package) { return [string]$row.Package }
    $seen = @{ $Self = $true }
    for ($step = 0; $step -lt 32; $step++) {
        $id = [int]$row.Parent
        $parent = $Table[$id]
        if ($null -eq $parent -or -not $parent.Created) { return $null }
        if ($seen.ContainsKey($id)) { return $null }
        $seen[$id] = $true
        if ([long]$parent.Created -gt [long]$row.Created) { return $null }
        if ($parent.Package) { return [string]$parent.Package }
        $row = $parent
    }
    return $null
}

function Get-ProcessTable {
    # This process and its ancestors as far as the walk can go, for Find-PackagedAncestor.
    param([int]$Self)
    Add-Type -TypeDefinition $script:HostAppSource -ErrorAction Stop
    $parents = @{}
    foreach ($process in @(Get-CimInstance Win32_Process -Property ProcessId, ParentProcessId -ErrorAction Stop)) {
        $parents[[int]$process.ProcessId] = [int]$process.ParentProcessId
    }
    $table = @{}
    $id = $Self
    for ($step = 0; $step -le 33 -and $parents.ContainsKey($id) -and -not $table.ContainsKey($id); $step++) {
        $package = $null
        $created = [CodexAutoResumeInstall.HostApp]::Open($id, ($id -eq $Self), [ref]$package)
        $table[$id] = @{ Parent = $parents[$id]; Created = $created; Package = $package }
        if (-not $created) { break }
        $id = $parents[$id]
    }
    return $table
}

function Get-OutsideSource {
    <#
        What the run outside executes: $Script - a script or a program - by its full path with this run's switches
        and values, then $Arguments as they are, everything it prints appended line by line to $Log as it prints it,
        and its exit code written to $CodeFile last.
    #>
    param([string]$Script, [string[]]$Switches, [hashtable]$Values, [string[]]$Arguments, [string]$Log, [string]$CodeFile,
          [hashtable]$Environment)
    # Every character PowerShell ends a single-quoted string at - the ASCII one and U+2018, U+2019, U+201A, U+201B -
    # doubled: with the ASCII one alone, a path holding a curly quote broke the script, and a folder name made for it
    # ran code here (v0.6.18 security review, M3).
    $quotes = '[' + "'" + [char]0x2018 + [char]0x2019 + [char]0x201A + [char]0x201B + ']'
    $literal = { param($text) "'" + (([string]$text) -replace $quotes, '$0$0') + "'" }
    $call = '& ' + (& $literal $Script)
    foreach ($name in $Switches) { $call += ' -' + $name }
    if ($Values) { foreach ($name in @($Values.Keys | Sort-Object)) { $call += ' -' + $name + ' ' + (& $literal $Values[$name]) } }
    foreach ($argument in $Arguments) { $call += ' ' + (& $literal $argument) }
    # Variables the run outside has to see (this process's own do not reach it): one line each, before the call.
    $variables = @()
    if ($Environment) { foreach ($name in @($Environment.Keys | Sort-Object)) { $variables += '$env:' + $name + ' = ' + (& $literal $Environment[$name]) } }
    return @(
        '$ErrorActionPreference = ''Continue'''
        '$log = ' + (& $literal $Log)
        '$utf8 = New-Object System.Text.UTF8Encoding $false'
        '$code = 1'
        $variables
        'try {'
        '    ' + $call + ' *>&1 | ForEach-Object { [IO.File]::AppendAllText($log, [string]$_ + "`r`n", $utf8) }'
        '    $code = $LASTEXITCODE'
        '    if ($null -eq $code) { $code = 0 }'
        '} catch { [IO.File]::AppendAllText($log, [string]$_ + "`r`n", $utf8) }'
        '[IO.File]::WriteAllText(' + (& $literal $CodeFile) + ', [string]$code)'
        'exit $code'
    ) -join "`r`n"
}

function Send-OutsideLines {
    # The whole lines the run outside has added to $Log since byte $From, printed here; where it has got to. -All
    # prints a last line that has no line end too.
    param([string]$Log, [long]$From, [switch]$All)
    if (-not (Test-Path -LiteralPath $Log)) { return $From }
    $stream = $null
    $bytes = $null
    $read = 0
    try {
        $stream = New-Object System.IO.FileStream($Log, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read,
                                                  ([System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete))
        if ($stream.Length -le $From) { return $From }
        $null = $stream.Seek($From, [System.IO.SeekOrigin]::Begin)
        $bytes = New-Object byte[] ([int]($stream.Length - $From))
        $read = $stream.Read($bytes, 0, $bytes.Length)
    } catch {
        return $From
    } finally {
        if ($stream) { $stream.Dispose() }
    }
    $end = $read
    if (-not $All) { $end = [Array]::LastIndexOf($bytes, [byte]10, [Math]::Max(0, $read - 1)) + 1 }
    if ($end -le 0) { return $From }
    $lines = @([System.Text.Encoding]::UTF8.GetString($bytes, 0, $end) -split "`r`n|`n")
    if ($lines.Count -gt 0 -and $lines[$lines.Count - 1] -eq '') { $lines = @($lines | Select-Object -First ($lines.Count - 1)) }
    foreach ($line in $lines) { Write-Host $line }
    return $From + $end
}

function Invoke-Outside {
    <#
        Runs $Source in Windows PowerShell outside every app's private view: created by WMI's Win32_Process.Create,
        with this run's environment and CODEX_AUTO_RESUME_OUTSIDE=1, its console hidden (SW_HIDE: WMI refuses
        CREATE_NO_WINDOW), in this run's folder. Passes on what it writes to $Log as it writes it, and returns its
        exit code once it has ended - or $null where it could not be started.
    #>
    param([string]$Source, [string]$Log, [string]$CodeFile)
    $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $encoded = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($Source))
    $line = '"' + $powershell + '" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand ' + $encoded
    $environment = @(foreach ($variable in [Environment]::GetEnvironmentVariables().GetEnumerator()) {
        if ([string]$variable.Key -ne 'CODEX_AUTO_RESUME_OUTSIDE') { [string]$variable.Key + '=' + [string]$variable.Value }
    }) + 'CODEX_AUTO_RESUME_OUTSIDE=1'
    $startup = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{
        ShowWindow = [uint16]0; EnvironmentVariables = [string[]]$environment }
    $created = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -ErrorAction Stop -Arguments @{
        CommandLine = $line; CurrentDirectory = [Environment]::CurrentDirectory; ProcessStartupInformation = $startup }
    if ($created.ReturnValue -ne 0 -or -not $created.ProcessId) { return $null }
    $id = [int]$created.ProcessId
    $process = $null
    try { $process = [System.Diagnostics.Process]::GetProcessById($id); $null = $process.Handle } catch { $process = $null }
    $position = [long]0
    while ($true) {
        if ($process) { $ended = $process.HasExited }
        else { $ended = (Test-Path -LiteralPath $CodeFile) -or -not (Get-Process -Id $id -ErrorAction SilentlyContinue) }
        $position = Send-OutsideLines -Log $Log -From $position
        if ($ended) { break }
        Start-Sleep -Milliseconds 200
    }
    $null = Send-OutsideLines -Log $Log -From $position -All
    $said = $null
    try { $said = [System.IO.File]::ReadAllText($CodeFile).Trim() } catch { $said = $null }
    $code = 0
    if ([int]::TryParse([string]$said, [ref]$code)) { return $code }
    return 1
}

function Resolve-OutsideRun {
    <#
        Whether this run goes on here: $null, or the exit code of the run outside that did its work instead. A run
        CODEX_AUTO_RESUME_OUTSIDE=1 marks is one: it never relaunches, and the mark goes no further than it.
    #>
    param([string]$Script, [string[]]$Switches, [hashtable]$Values, [string[]]$Arguments, [hashtable]$Environment)
    if ($env:CODEX_AUTO_RESUME_OUTSIDE -eq '1') {
        $env:CODEX_AUTO_RESUME_OUTSIDE = $null
        return $null
    }
    $app = $null
    try { $app = Find-PackagedAncestor -Table (Get-ProcessTable -Self $PID) -Self $PID } catch { $app = $null }
    if (-not $app) { return $null }
    $folder = Join-Path ([System.IO.Path]::GetTempPath()) ('CodexAutoResume-Outside-' + [guid]::NewGuid().ToString('N').Substring(0, 16))
    $code = $null
    try {
        $null = New-Item -ItemType Directory -Path $folder -ErrorAction Stop
        $log = Join-Path $folder 'output.txt'
        $codeFile = Join-Path $folder 'code.txt'
        $source = Get-OutsideSource -Script $Script -Switches $Switches -Values $Values -Arguments $Arguments `
                                    -Log $log -CodeFile $codeFile -Environment $Environment
        $code = Invoke-Outside -Source $source -Log $log -CodeFile $codeFile
    } catch {
        $code = $null
    } finally {
        Remove-Item -LiteralPath $folder -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($null -ne $code) { return $code }
    $name = $app
    if ($app.LastIndexOf('_') -gt 0) { $name = $app.Substring(0, $app.LastIndexOf('_')) }
    Warn ('This may be running inside ' + $name + '. A program started from the Codex app, Claude or another app ' +
          'installed as a package can be, and Windows then keeps what it registers inside that app: the entry in ' +
          'Settings > Apps, the start at sign-in, the notifications'' name, the link handler and the Start menu ' +
          'entry. If Settings > Apps lacks the entry or it does not start at sign-in, open the Dashboard from the ' +
          'Start menu and choose Repair installation.')
    return $null
}
# <<< the outside gate

$outsideSwitches = @(foreach ($name in 'SkipStartup', 'Uninstall', 'Purge', 'AllowEditionChange', 'Silent') {
    if (Get-Variable -Name $name -ValueOnly) { $name }
})
$outsideCode = Resolve-OutsideRun -Script $PSCommandPath -Switches $outsideSwitches `
                                  -Values @{ PluginName = $PluginName; MarketplaceName = $MarketplaceName }
if ($null -ne $outsideCode) { exit $outsideCode }

# The setup window's progress lines (Progress), read once - after the outside gate, so a run outside gets the variable
# with the rest of this run's environment - and then taken out of it: what this run starts that lives on (the watcher,
# the Dashboard it opens again) never inherits it. The setup step and the health check get it back for their own call
# (Invoke-Setup).
$script:ProgressLines = $env:CODEX_AUTO_RESUME_PROGRESS_LINES -ceq '1'
$script:ProgressSaid = @{}
$env:CODEX_AUTO_RESUME_PROGRESS_LINES = $null

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
# What a run that does not finish leaves behind, so the next one can tell a program
# directory that was moved aside from one that was only ever a leftover. It lives at the
# installation root and nowhere else: `config\` and `logs\` hold the user's settings and
# recovery history, and an installer has no business writing its own bookkeeping there.
# The name says whose it is, so whoever finds it knows what they are looking at.
$Journal     = Join-Path $InstallHome '.codex-auto-resume-install-journal.json'

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

function Get-Edition {
    <#
        Which edition the tree whose `src` this is: the advanced one when the advanced
        package is in it, the standard one otherwise. Nothing is stamped anywhere to say
        which. It is the fact the product itself reads (src/codex_auto_resume/edition.py,
        name()), and scripts/bootstrap.ps1 reads it the same way, so the three agree -
        even about an installation whose advanced package would not load.
    #>
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

function Get-AppVersion {
    <#
        The version the program files under Root (an app\ tree) declare: the plugin manifest's own "version", or
        $null where there is no manifest, it cannot be read or it names no version. The one fact that tells a repair
        from an update - this archive's version over the same version already installed - and read the way the
        product reads it (config.version), from the tree itself rather than from a name.
    #>
    param([string]$Root)
    $manifest = Join-Path (Join-Path $Root '.codex-plugin') 'plugin.json'
    try {
        $item = Get-Item -LiteralPath $manifest -Force -ErrorAction Stop
        if ($item.PSIsContainer) { return $null }
        $declared = ([IO.File]::ReadAllText($item.FullName) | ConvertFrom-Json).version
        if ($declared -is [string] -and $declared.Trim()) { return $declared.Trim() }
    } catch { }
    return $null
}

function Get-EditionStatement {
    # What moving from one edition to the other keeps and what it changes, in one line said
    # before anything is done. The bootstrap says the same line (scripts/bootstrap.ps1) before
    # it downloads anything; a test holds the two copies to each other.
    param([string]$From, [string]$To)
    $words = @{ standard = 'Standard edition'; advanced = 'Advanced edition' }
    $line = $words[$From] + ' -> ' + $words[$To] + '; settings and pending recoveries are kept; '
    if ($To -eq 'advanced') { return $line + 'every advanced feature starts off' }
    return $line + 'the advanced features go, and their code with them'
}

function Write-PluginNotUpdated {
    <#
        What a failed `codex plugin add` leaves, said as it is. The watcher, its settings and the
        plugin's tools do not depend on it: the tools' launcher runs this installation's own program
        (gui/McpLauncher.cs runs <home>\app\src), so they are already whatever this archive is. What
        Codex keeps in its own copy of the plugin is the skill's text and that launcher, and it replaces
        the copy only once nothing holds it open. After an edition change that copy is still the old
        edition's - said here, and in the Dashboard's Diagnostics until it is replaced.
    #>
    param([string]$From, [string]$To)
    $words = @{ standard = 'Standard edition'; advanced = 'Advanced edition' }
    if ($From -and $To -and $From -ne $To) {
        Warn ('Could not update the Codex plugin, so Codex still has the ' + $words[$From] + '''s copy of it.')
        Write-Host ('       Its tools already run the ' + $words[$To] + ' installed here; only the skill''s text')
        Write-Host '       is still the old one. Close the ChatGPT/Codex app and run this installer again to'
        Write-Host '       update it. The watcher and its settings work meanwhile.'
        return
    }
    Warn 'Could not update the Codex plugin; the watcher and its settings still work.'
    Write-Host '       Close the ChatGPT/Codex app and run this installer again to finish it.'
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

function Get-OwnedDashboardProcess {
    <#
        This installation's Dashboard windows that are open, found as the MCP launchers are: by their
        executable's path inside the installation, never by name alone. The one that started this update
        (CODEX_AUTO_RESUME_UPDATING_DASHBOARD, its process id) is not among them: it waits for this, and
        opens the new version itself once it is done.
    #>
    $found = @()
    $starter = 0
    [void][int]::TryParse([string]$env:CODEX_AUTO_RESUME_UPDATING_DASHBOARD, [ref]$starter)
    $all = @(Get-CimInstance Win32_Process -Filter "Name='CodexAutoResumeSettings.exe'" -ErrorAction SilentlyContinue)
    foreach ($process in $all) {
        $exe = $process.ExecutablePath
        if ([string]::IsNullOrWhiteSpace($exe) -or $process.ProcessId -eq $starter) { continue }
        if (Test-PathInside $exe $OwnedHome) { $found += $process }
    }
    return ,$found
}

function Get-UpdateEventName {
    <#
        The event an update sets to ask this installation's Dashboard windows to close themselves - the
        window's own close, never anything ended from outside (gui/WindowReopen.cs, WatchForUpdate). Named
        after the installation's folder, so another installation's windows never hear it: the first sixteen
        hex digits of the SHA-256 of its full path in lower case, as UTF-8.
    #>
    param([string]$Root)
    $full = [IO.Path]::GetFullPath($Root).TrimEnd('\').ToLowerInvariant()
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $hash = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($full)) } finally { $sha.Dispose() }
    return 'Local\CodexAutoResume.CloseForUpdate.' + (-join ($hash[0..7] | ForEach-Object { $_.ToString('x2') }))
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

function Get-DashboardPage {
    <#
        The page an older Dashboard window was opened on, read from its command line: the one thing a window that does
        not answer an update's request says about where it is. Only the words its own reopen takes for a page
        (`--page=<name>`, and `--settings`, the older spelling); '' where it says none, and it opens on the Overview.
    #>
    param([string]$CommandLine)
    $page = ''
    foreach ($word in @([regex]::Matches([string]$CommandLine, '"([^"]*)"|(\S+)') |
                        ForEach-Object { if ($_.Groups[1].Success) { $_.Groups[1].Value } else { $_.Groups[2].Value } })) {
        if ($word -cmatch '^--page=(overview|pending|history|statistics|diagnostics|settings)$') { $page = $Matches[1] }
        elseif ($word -ceq '--settings') { $page = 'settings' }
    }
    return $page
}

function Test-DashboardAnswered {
    <#
        Whether a Dashboard window answered an update's request: it wrote where it was and is closing itself
        (reopen-after-update-<its process id>.txt), or it wrote that it keeps unsaved Settings changes and stays open
        (update-unsaved-<its process id>.txt, gui/WindowReopen.cs). A window from before v0.6.16 never writes either.
    #>
    param([int]$ProcessId)
    $config = Join-Path $InstallHome 'config'
    foreach ($name in @('reopen-after-update-', 'update-unsaved-')) {
        if (Test-Path -LiteralPath (Join-Path $config ($name + $ProcessId + '.txt')) -PathType Leaf) { return $true }
    }
    return $false
}

function Test-DashboardUnsaved {
    param([int]$ProcessId)
    return (Test-Path -LiteralPath (Join-Path (Join-Path $InstallHome 'config') ('update-unsaved-' + $ProcessId + '.txt')) -PathType Leaf)
}

function Close-DashboardWindow {
    <#
        The fallback for a window that did not answer: its own close, as a person closes it - WM_CLOSE to its main
        window (Process.CloseMainWindow), which every Dashboard before v0.6.16 answers by closing. Never ended from
        outside. False where it has no window to be asked.
    #>
    param([int]$ProcessId)
    try {
        $process = [System.Diagnostics.Process]::GetProcessById($ProcessId)
        try { return [bool]$process.CloseMainWindow() } finally { $process.Dispose() }
    } catch { return $false }
}

function Close-OwnedDashboard {
    <#
        Asks this installation's open Dashboard windows to close, and says how it went: before an update or a repair
        replaces the files they run, and before an uninstall removes them.

        Each window is asked through its own close (gui/WindowReopen.cs): the event named after the installation
        (Get-UpdateEventName). A window of this version answers at once - it writes where it was and closes, or writes
        that it keeps unsaved Settings changes and stays open. A window of an earlier version does not listen for the
        event and answers nothing: most updates come from v0.6.15, and such a window kept the update waiting a minute
        and was then said to have unsaved changes it never had (v0.6.16 acceptance). So a window that has not answered
        in $AnswerSeconds is closed as a person closes it (Close-DashboardWindow), and opens again on the new version
        (Open-ClosedDashboard) on the page its command line names, else the Overview.

        Nothing is ended by force. Returns Unsaved - the windows that answered that they keep unsaved changes - and
        Stuck - the windows still open that did not say so, which could not be asked or did not close - and
        Fallback, the page of each window closed by the fallback ('' for the Overview), which is also kept for
        Open-ClosedDashboard. Sets $script:DashboardsAskedAt, so the windows open again on every way out.
    #>
    param([int]$AnswerSeconds = 10, [int]$CloseSeconds = 20)
    $result = @{ Unsaved = 0; Stuck = 0; Fallback = @() }
    if ((Get-OwnedDashboardProcess).Count -eq 0) { return $result }
    $config = Join-Path $InstallHome 'config'
    # An answer an earlier run left is no answer to this one.
    foreach ($stale in @(Get-ChildItem -LiteralPath $config -File -Filter 'update-unsaved-*.txt' -ErrorAction SilentlyContinue)) {
        $null = Remove-OwnedItem $stale.FullName
    }
    $script:DashboardsAskedAt = [DateTime]::UtcNow
    $closeEvents = @()
    foreach ($root in @($InstallHome, $OwnedHome) | Select-Object -Unique) {
        try {
            $closeEvent = New-Object System.Threading.EventWaitHandle($false,
                [System.Threading.EventResetMode]::ManualReset, (Get-UpdateEventName $root))
            [void]$closeEvent.Set()
            $closeEvents += $closeEvent
        } catch { }
    }
    $fallback = @()
    # Each list is taken whole before it is read: Get-OwnedDashboardProcess hands back one array (its leading comma),
    # which a pipeline or @() would take as a single item.
    try {
        # The answers: every window closed, or said why it stays.
        $deadline = (Get-Date).AddSeconds($AnswerSeconds)
        while ((Get-Date) -lt $deadline) {
            $windows = Get-OwnedDashboardProcess
            $silent = @($windows | Where-Object { -not (Test-DashboardAnswered $_.ProcessId) })
            if ($silent.Count -eq 0) { break }
            Start-Sleep -Milliseconds 250
        }
        # The fallback, for each window that said nothing.
        $windows = Get-OwnedDashboardProcess
        foreach ($process in $windows) {
            if (Test-DashboardAnswered $process.ProcessId) { continue }
            if (Close-DashboardWindow $process.ProcessId) {
                $fallback += @{ Id = [int]$process.ProcessId; Page = (Get-DashboardPage $process.CommandLine) }
            }
        }
        # Every window but one that keeps unsaved changes closes now, and its bridge with it.
        $deadline = (Get-Date).AddSeconds($CloseSeconds)
        while ((Get-Date) -lt $deadline) {
            $windows = Get-OwnedDashboardProcess
            $open = @($windows | Where-Object { -not (Test-DashboardUnsaved $_.ProcessId) })
            if ($open.Count -eq 0) { break }
            Start-Sleep -Milliseconds 250
        }
    } finally {
        foreach ($closeEvent in $closeEvents) { [void]$closeEvent.Reset(); $closeEvent.Dispose() }
    }
    $still = Get-OwnedDashboardProcess
    $stillIds = @($still | ForEach-Object { [int]$_.ProcessId })
    $result.Unsaved = @($still | Where-Object { Test-DashboardUnsaved $_.ProcessId }).Count
    $result.Stuck = $still.Count - $result.Unsaved
    $result.Fallback = @($fallback | Where-Object { $stillIds -notcontains $_.Id } | ForEach-Object { [string]$_.Page })
    $script:DashboardsFallback = $result.Fallback
    foreach ($answer in @(Get-ChildItem -LiteralPath $config -File -Filter 'update-unsaved-*.txt' -ErrorAction SilentlyContinue)) {
        $null = Remove-OwnedItem $answer.FullName
    }
    return $result
}

function Get-InstallationHolder {
    <#
        What of this installation still runs that an uninstall does not stop itself, and so would hold its files: each
        process whose program is inside the installation - a Dashboard that stayed open, the runtime python.exe one
        started, a command run by hand - but the watcher, which the uninstall's own first step stops, and this
        installation's tool launchers, which it ends before the files go, with whatever each of them started. Waits up
        to $Seconds for what is closing to have closed. Changes nothing.
    #>
    param([int]$Seconds = 10)
    $roots = @($OwnedHome, $InstallHome) | Where-Object { $_ } | Select-Object -Unique
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ($true) {
        $all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
        # Each list taken whole first: the two hand back one array (their leading comma).
        $watchers = Get-OwnedWatcherProcess
        $launchers = Get-OwnedMcpProcess -Roots @($OwnedHome, $PluginCacheRoot)
        $spared = @($watchers | ForEach-Object { [int]$_.ProcessId }) + @($launchers | ForEach-Object { [int]$_.ProcessId })
        # And what each of those started, however deep.
        $grew = $true
        while ($grew) {
            $grew = $false
            foreach ($process in $all) {
                $id = [int]$process.ProcessId
                if ($spared -notcontains $id -and $spared -contains [int]$process.ParentProcessId) { $spared += $id; $grew = $true }
            }
        }
        $held = @()
        foreach ($process in $all) {
            $exe = [string]$process.ExecutablePath
            if (-not $exe -or [int]$process.ProcessId -eq $PID -or $spared -contains [int]$process.ProcessId) { continue }
            $near = $false
            foreach ($root in $roots) { if ($exe.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) { $near = $true } }
            if ($near -and (Test-PathInside $exe $OwnedHome)) { $held += $process }
        }
        if ($held.Count -eq 0 -or (Get-Date) -ge $deadline) { return ,$held }
        Start-Sleep -Milliseconds 500
    }
}

function Test-FileFree {
    # Whether nothing holds a file open: it opens for writing with no sharing, and is closed at once, unchanged. A
    # running program's own file never opens so. A file that may not be written to at all is not held by anything.
    param([string]$Path)
    try {
        $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
        $stream.Dispose()
        return $true
    } catch [System.UnauthorizedAccessException] {
        return $true
    } catch {
        return $false
    }
}

function Get-UninstallBlocker {
    <#
        What would stop an uninstall part way, found before anything is removed. The v0.6.16 acceptance's uninstall
        ran with the Dashboard open: the watcher, the sign-in start, the Start menu entry and the plugin went, and
        then the program files could not - the Dashboard and the runtime python.exe it started held them - and it
        stopped with half a product left. So the Dashboard is asked to close first, as an update asks it
        (Close-OwnedDashboard), and then what still runs here (Get-InstallationHolder) and each program file at the
        root that something holds are named. An empty list: nothing holds the files. Changes nothing but the windows
        asked to close, and the records they wrote.

        A window asked so writes where it was for the installer to open it again (reopen-after-update-<its process
        id>.txt) - as it does for an update, for it cannot tell the two apart. An uninstall opens nothing again, so
        each record is removed here, once the windows have answered: the v0.6.17 acceptance's keep-data uninstall left
        one in config\, which the uninstall keeps, and the reinstall after it, which is no update, never swept it.
    #>
    $blockers = @()
    if ((Get-OwnedDashboardProcess).Count -gt 0) {
        Step 'Closing the Dashboard so its files can be removed'
        $closed = Close-OwnedDashboard
        foreach ($record in @(Get-ChildItem -LiteralPath (Join-Path $InstallHome 'config') -File `
                                            -Filter 'reopen-after-update*.txt' -ErrorAction SilentlyContinue)) {
            $null = Remove-OwnedItem $record.FullName
        }
        if ($closed.Unsaved -gt 0) { $blockers += 'A Dashboard window has unsaved Settings changes: save or undo them, then close it.' }
        if ($closed.Stuck -gt 0) { $blockers += 'A Dashboard window could not be closed: close it.' }
        if ($blockers.Count -eq 0) { Ok 'The Dashboard closed' }
    }
    if ($blockers.Count -eq 0) {
        $holders = Get-InstallationHolder
        foreach ($process in $holders) {
            $blockers += ([string]$process.Name + ' (process ' + $process.ProcessId + ') is running ' + $process.ExecutablePath)
        }
    }
    foreach ($file in @('CodexAutoResumeSettings.exe', 'codex-auto-resume.ico')) {
        $path = Join-Path $OwnedHome $file
        if ((Test-Path -LiteralPath $path -PathType Leaf) -and -not (Test-FileFree $path)) { $blockers += ($path + ' is in use.') }
    }
    return ,$blockers
}

function Invoke-Codex {
    # Native stderr must not become a terminating error: PowerShell 5.1 wraps it in an
    # ErrorRecord, and `codex` writes ordinary progress there. Capture to files instead
    # of using 2>&1, and judge the result by the exit code alone.
    #
    # Telemetry off, as every codex process this product starts (standard C10): the variable and the `-c` overrides the
    # watcher's own calls carry (src/codex_auto_resume/codex/transport.py, Backend._environment and Backend._argv),
    # before this call's own arguments; the variable for this call alone. `codex -c ... plugin ...` measured on
    # codex-cli 0.163.0-alpha.11 against a scratch CODEX_HOME (tests/test_installer_codex_telemetry.py).
    param([string]$Exe, [string[]]$Arguments)
    $telemetryOff = @('-c', 'analytics.enabled=false', '-c', 'otel.exporter="none"', '-c', 'otel.trace_exporter="none"',
                      '-c', 'otel.metrics_exporter="none"', '-c', 'otel.log_user_prompt=false',
                      '-c', 'chatgpt_base_url="https://chatgpt.com/backend-api/"')
    $out = [System.IO.Path]::GetTempFileName()
    $err = [System.IO.Path]::GetTempFileName()
    $line = ((@($telemetryOff) + @($Arguments) | ForEach-Object { Quote-Argument $_ }) -join ' ')
    $otelBefore = $env:OTEL_SDK_DISABLED
    try {
        $env:OTEL_SDK_DISABLED = 'true'
        $p = Start-Process -FilePath $Exe -ArgumentList $line -NoNewWindow -Wait -PassThru `
             -RedirectStandardOutput $out -RedirectStandardError $err
        return @{ Code = $p.ExitCode
                  Out  = (Get-Content -Raw -ErrorAction SilentlyContinue $out)
                  Err  = (Get-Content -Raw -ErrorAction SilentlyContinue $err) }
    } finally {
        $env:OTEL_SDK_DISABLED = $otelBefore
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

# How much of a step is done, for the setup window's bar: `progress: <step> <done>/<total>`, an English line of its own
# that the window reads and keeps out of the log it shows (gui/InstallerFlow.cs, InstallerProgress). Only when the
# window asked for it with CODEX_AUTO_RESUME_PROGRESS_LINES=1 ($script:ProgressLines, read once after the outside
# gate): Install.cmd's console, the CI logs and every other caller see exactly what they always did. Real counts only,
# never a guess, and at most one line per whole percent of the step, so the pipe is not flooded.
function Progress {
    param([string]$Step, [int]$Done, [int]$Total)
    if (-not $script:ProgressLines -or $Total -le 0) { return }
    # Read through Get-Variable: the bootstrap runs this script under Set-StrictMode 2.0, where reading a variable
    # never set throws (v0.6.18's installer audit: every Dashboard update failed and rolled back).
    $said_table = Get-Variable -Name ProgressSaid -Scope Script -ValueOnly -ErrorAction SilentlyContinue
    if ($null -eq $said_table) { $script:ProgressSaid = @{} }
    $count = [Math]::Max(0, [Math]::Min($Done, $Total))
    $percent = [int][Math]::Floor(100 * $count / $Total)
    # Nothing for a share below one percent: the bar stands at the step's milestone already.
    $said = 0
    if ($script:ProgressSaid.ContainsKey($Step)) { $said = $script:ProgressSaid[$Step] }
    if ($percent -le $said) { return }
    $script:ProgressSaid[$Step] = $percent
    Write-Host ('  progress: ' + $Step + ' ' + $count + '/' + $Total)
}

function Get-PayloadTree {
    <#
        Every folder and file under Source, each with where it goes under Destination ({ From; To; Folder }):
        what the copy of the program files copies, one file at a time so the setup window's bar can follow it
        (Progress). Hidden and system ones too, as `Copy-Item -Recurse -Force` took them.
    #>
    param([string]$Source, [string]$Destination)
    $base = (Get-Item -LiteralPath $Source -Force -ErrorAction Stop).FullName.TrimEnd('\')
    foreach ($item in @(Get-ChildItem -LiteralPath $base -Recurse -Force -ErrorAction Stop)) {
        @{ From = $item.FullName
           To = (Join-Path $Destination $item.FullName.Substring($base.Length + 1))
           Folder = [bool]$item.PSIsContainer }
    }
}

function Invoke-Setup {
    # The command's stdout must not leak into the return value: a bare call would make
    # the function return every printed line AND the exit code as an array, and any
    # comparison against 0 would then be true no matter how well setup went.
    param([string[]]$Arguments)
    $setup = Join-Path $AppDir 'scripts\plugin_setup.py'
    # The setup step and the health check count their own steps for the setup window's bar (Progress): the variable
    # is set for those two calls alone, as the other hints to setup are.
    $counted = $script:ProgressLines -and @($Arguments).Count -gt 0 -and
               (@($Arguments)[0] -ceq 'setup' -or @($Arguments)[0] -ceq 'doctor')
    if ($counted) { $env:CODEX_AUTO_RESUME_PROGRESS_LINES = '1' }
    # Setup's exit code decides, never its stderr. Run outside another app, this script's streams are merged
    # (Get-OutsideSource: `*>&1`), and Windows PowerShell then makes each stderr line of a native program a
    # NativeCommandError, which this script's 'Stop' made terminating: setup's `error: ...` line stopped setup half way
    # and failed the install (v0.6.18 installer audit, R1). For this call alone; the bootstrap's Invoke-InstalledSetup
    # does the same.
    $ErrorActionPreference = 'Continue'
    try { & $Python $setup @Arguments | ForEach-Object { Write-Host ('    ' + $_) } }
    finally { if ($counted) { $env:CODEX_AUTO_RESUME_PROGRESS_LINES = $null } }
    return $LASTEXITCODE
}

function Install-KeptUninstaller {
    <#
        Keep a copy of this script in the installation, for the entry in Add or remove programs.

        The archive's own Uninstall.cmd is gone once a setup program has run: it unpacks the
        archive into a temporary folder and removes it. Windows' list of installed programs, and
        `winget uninstall` with it, runs a command line, so there has to be a file for that command
        to name. This script is that file - uninstalling is its -Uninstall branch, which asks the
        installed engine about the installation and needs nothing else from the archive.

        One file, in a folder of the installation's own, written beside its name and moved into
        place so a copy cut short is never the one that runs. A link or a junction where the
        folder should be is not followed and not replaced: the path is refused unless it resolves
        inside the verified root, the confinement every other write in this file keeps.

        Returns $true when the copy is there afterwards.
    #>
    param([string]$Source)
    $folder = Join-Path $OwnedHome 'uninstall'
    $target = Join-Path $folder 'install.ps1'
    if (-not (Test-PathInside $target $OwnedHome)) {
        Warn ('Not keeping an uninstaller: ' + $folder + ' is outside the verified installation.')
        return $false
    }
    $existing = Get-Item -LiteralPath $folder -Force -ErrorAction SilentlyContinue
    if ($existing -and (-not $existing.PSIsContainer -or $existing.LinkType)) {
        Warn ('Not keeping an uninstaller: ' + $folder + ' is not an ordinary folder.')
        return $false
    }
    if ((Resolve-Canonical $Source) -eq (Resolve-Canonical $target)) { return $true }
    $temp = $target + '.writing'
    try {
        if (-not $existing) { New-Item -ItemType Directory -Path $folder -ErrorAction Stop | Out-Null }
        Copy-Item -LiteralPath $Source -Destination $temp -Force -ErrorAction Stop
        Move-Item -LiteralPath $temp -Destination $target -Force -ErrorAction Stop
    } catch {
        Warn ('Could not keep an uninstaller: ' + $_.Exception.Message)
        $null = Remove-OwnedItem $temp
        return $false
    }
    return $true
}

function Test-DefaultHome {
    <#
        True when the installation root $Root is the ordinary one, `.codex-auto-resume` in the profile $Profile.

        The kept uninstaller (Install-KeptUninstaller), and with it the entry in Add or remove programs, is for the
        ordinary home. Whether CODEX_AUTO_RESUME_PLUGIN_HOME is set does not say which home this is: the Dashboard sets
        it to its own root for every update it starts (gui/DashboardMaintenance.cs, StartBootstrap), and that root is
        the ordinary home nearly always. Read as "set means moved", every update from the Dashboard kept no uninstaller,
        so no entry was ever written after one, and Repair could not add it (GitHub #43). So the root this run really
        installed is compared with the ordinary one.

        Both go through Resolve-Canonical, so one place has one spelling: a different case (the compare ignores it), a
        trailing separator, `.` and `..`, forward slashes, a `\\?\` prefix, an 8.3 short name (Windows PowerShell's
        GetFullPath gives the long name of a path that exists, and both exist here) and a junction are all the same
        folder. Environment variables are not expanded, on purpose: $InstallHome takes the variable as it is written, so
        a `%USERPROFILE%` in it names another folder, and $Root is the folder the files went to - which is what decides.
    #>
    param([string]$Root, [string]$Profile)
    if ([string]::IsNullOrWhiteSpace($Root) -or [string]::IsNullOrWhiteSpace($Profile)) { return $false }
    $ordinary = Resolve-Canonical (Join-Path $Profile '.codex-auto-resume')
    $here = Resolve-Canonical $Root
    if (-not $ordinary -or -not $here) { return $false }
    return [string]::Equals($ordinary, $here, [StringComparison]::OrdinalIgnoreCase)
}

function Protect-RelocatedHome {
    <#
        An installation root outside the person's profile $Profile (CODEX_AUTO_RESUME_PLUGIN_HOME) given an access list of
        its own: the person, SYSTEM and Administrators, full control, inherited by everything under it, and nothing
        inherited from above. A folder made under a drive root takes the root's `Authenticated Users: Modify`, and every
        other account on the PC could then replace the launcher, the program or the runtime that run as the person at
        each sign-in (v0.6.18 security review, R2). Inside the profile nothing changes: the profile is the person's own.

        Chosen over refusing such a home: an installation already relocated keeps working and is made private on its next
        update or repair, and nothing the person can do there today is taken away. Where the drive keeps no access list
        (FAT, exFAT) or the list cannot be written, it says so and goes on. Returns 'profile', 'protected' or 'failed'.
    #>
    param([string]$Root, [string]$Profile)
    if (-not [string]::IsNullOrWhiteSpace($Profile) -and (Test-PathInside $Root $Profile)) { return 'profile' }
    try {
        $person = [Security.Principal.WindowsIdentity]::GetCurrent().User
        $system = New-Object Security.Principal.SecurityIdentifier 'S-1-5-18'
        $administrators = New-Object Security.Principal.SecurityIdentifier 'S-1-5-32-544'
        $acl = New-Object Security.AccessControl.DirectorySecurity
        $acl.SetAccessRuleProtection($true, $false)
        $inherit = [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
        foreach ($who in @($person, $system, $administrators)) {
            $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule(
                $who, [Security.AccessControl.FileSystemRights]::FullControl, $inherit,
                [Security.AccessControl.PropagationFlags]::None, [Security.AccessControl.AccessControlType]::Allow)))
        }
        (New-Object IO.DirectoryInfo $Root).SetAccessControl($acl)
        return 'protected'
    } catch {
        Warn ('The installation folder outside your profile could not be made private to you: ' + $_.Exception.Message)
        Write-Host '       Other accounts on this PC may be able to change its files. Install into your profile, or'
        Write-Host '       give the folder an access list that lets only you, SYSTEM and Administrators change it.'
        return 'failed'
    }
}

function Read-UninstallEntry {
    # The two values that say whose an entry in Add or remove programs is, or $null when there is none. The only
    # read of the registry in this file, and one of the two calls into it (Remove-UninstallEntry is the other);
    # tests stand in for both, so none of them reaches the real one.
    param([string]$Name)
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Software\Microsoft\Windows\CurrentVersion\Uninstall\' + $Name)
    if ($null -eq $key) { return $null }
    try {
        return @{ InstallLocation = [string]$key.GetValue('InstallLocation'); UninstallString = [string]$key.GetValue('UninstallString') }
    } finally { $key.Close() }
}

function Remove-UninstallEntry {
    param([string]$Name)
    [Microsoft.Win32.Registry]::CurrentUser.DeleteSubKey('Software\Microsoft\Windows\CurrentVersion\Uninstall\' + $Name, $false)
}

function Remove-OwnUninstallEntry {
    <#
        Take this installation's entry in Add or remove programs away, and nobody else's.

        Called once, after every removal has succeeded: until then a failed uninstall stays listed, and the
        entry's own command is what runs it again. The engine writes the entry (src/codex_auto_resume/
        addremove.py) and would remove it too, early, in its own uninstall step; it is told not to
        (CODEX_AUTO_RESUME_KEEP_ENTRY) so that this is the only place it goes.

        An entry is this installation's when it is installed at this root and its command runs this root's
        kept uninstaller - the engine's own rule, in the same two conditions (addremove.owned): one of the
        command's arguments after the program it starts is the kept script. Both forms the engine writes are
        that: PowerShell's `-File "<root>\uninstall\install.ps1"`, and since v0.6.16 the installation's own
        program, `"<root>\CodexAutoResumeSettings.exe" "--uninstall" "<root>\uninstall\install.ps1"`, which
        the first version of this read only as the first and so left behind after every uninstall. One of the
        two fixed names, which differ by edition and never exist together; an entry that says anything else is
        left as it is.
    #>
    param([string]$Root)
    $kept = Resolve-Canonical (Join-Path (Join-Path $Root 'uninstall') 'install.ps1')
    foreach ($name in @('CodexAutoResume', 'CodexAutoResumeAdvanced')) {
        try {
            $entry = Read-UninstallEntry $name
            if ($null -eq $entry) { continue }
            $here = (Resolve-Canonical $entry.InstallLocation) -eq (Resolve-Canonical $Root)
            $runs = $false
            # The command's words as Windows reads them: a quoted one whole, any other up to a space. The first is
            # the program it starts, and is never the script.
            $words = @([regex]::Matches([string]$entry.UninstallString, '"([^"]*)"|(\S+)') |
                       ForEach-Object { if ($_.Groups[1].Success) { $_.Groups[1].Value } else { $_.Groups[2].Value } })
            foreach ($word in @($words | Select-Object -Skip 1)) {
                if ($kept -and (Resolve-Canonical $word) -eq $kept) { $runs = $true }
            }
            if ($here -and $runs) {
                Step 'Removing the entry in Add or remove programs'
                Remove-UninstallEntry $name
            }
        } catch {
            Warn ('Could not remove the entry in Add or remove programs: ' + $_.Exception.Message)
        }
    }
}

function Write-CopyJournal {
    <#
        Write down what is about to be moved aside, before any of it moves.

        The rollback further down only covers a failure this process survives to catch.
        A power cut between the move and the copy leaves the only complete tree under an
        `*.old-*` name - and the first thing the next run does is sweep every `*.old-*`
        directory away, so the recovery attempt is what destroys the installation. This
        file is the one thing that can tell that run the difference.

        Written atomically, because a half-written journal is worse than none: the text
        goes to a temporary name first and is then moved over the real one, so a crash
        during the write leaves either the previous journal or no journal at all.
        ConvertTo-Json, so whoever finds the file can read what happened to their
        installation without needing this script to explain it.
    #>
    param([string]$Path, [string]$Root, $Entries)
    $moved = @()
    foreach ($entry in $Entries) {
        $moved += @{ name = $entry.src; target = $entry.dst; movedAside = $entry.aside }
    }
    $record = @{ version = 1
                 written = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ssK')
                 home    = $Root
                 moved   = $moved }
    $temp = $Path + '.writing'
    Set-Content -LiteralPath $temp -Value (ConvertTo-Json $record -Depth 4) -Encoding UTF8 -ErrorAction Stop
    Move-Item -LiteralPath $temp -Destination $Path -Force -ErrorAction Stop
}

function Restore-InterruptedCopy {
    <#
        Put back a program directory that an interrupted run left moved aside.

        Read before the sweep, because the sweep is the danger: a tree missing from its
        target and sitting under the aside name the journal records is the installation,
        not a leftover, and deleting it would leave nothing to install over.

        Both ends of every move are re-checked against the root this run already proved
        it owns. The journal is a file on disk like any other, and a path read out of a
        file is not permission to move something.

        Returns the aside paths the journal still accounts for, so the sweep that
        follows leaves them where they are until this run has written a complete copy.
    #>
    param([string]$Path, [string]$Root)
    $claimed = @()
    if (-not (Test-Path -LiteralPath $Path)) { return ,$claimed }
    try {
        $record = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json
    } catch {
        Warn 'An interrupted installation left a journal here that cannot be read.'
        Write-Host ('       ' + $Path)
        # An empty protected set would let the caller sweep every *.old-* tree,
        # including the only complete installation the unreadable journal described.
        # Refuse before the sweep rather than interpreting unknown as nothing to keep.
        throw 'Installation stopped before moving or sweeping anything. Preserve the journal and *.old-* folders for repair.'
    }
    if (-not $record -or -not $record.PSObject.Properties.Match('moved').Count -or
        $null -eq $record.moved -or @($record.moved).Count -eq 0) {
        throw 'The interrupted-installation journal has no usable move records. Nothing was moved or swept.'
    }
    # Validate the entire list before moving its first tree. Skipping a malformed
    # entry would give the sweep permission to delete the tree that entry described.
    foreach ($entry in @($record.moved)) {
        foreach ($field in @('name', 'target', 'movedAside')) {
            if ($null -eq $entry -or -not $entry.PSObject.Properties.Match($field).Count -or
                $entry.$field -isnot [string] -or [string]::IsNullOrWhiteSpace($entry.$field)) {
                throw 'The interrupted-installation journal contains an invalid move record. Nothing was moved or swept.'
            }
        }
    }
    foreach ($entry in @($record.moved)) {
        $target = $entry.target
        $aside  = $entry.movedAside
        if ([string]::IsNullOrWhiteSpace($target) -or [string]::IsNullOrWhiteSpace($aside)) { continue }
        if (-not (Test-PathInside $aside $Root) -or -not (Test-PathInside $target $Root)) {
            Warn ('The journal names a path outside this installation; ignoring it: ' + $aside)
            continue
        }
        $canonical = Resolve-Canonical $aside
        if ($canonical) { $claimed += $canonical }
        # The target being there means the copy got far enough to recreate it, so the
        # aside copy is a leftover this run will replace rather than the only one left.
        if (Test-Path -LiteralPath $target) { continue }
        if (-not (Test-Path -LiteralPath $aside)) { continue }
        Step ('Putting back the ' + $entry.name + ' folder an interrupted installation left aside')
        try {
            Move-Item -LiteralPath $aside -Destination $target -ErrorAction Stop
            Ok ('Restored ' + $target)
            $claimed = @($claimed | Where-Object { $_ -ne $canonical })
        } catch {
            Warn ('Could not put ' + $aside + ' back as ' + $target + ': ' + $_.Exception.Message)
            Write-Host '       It was left exactly where it is and nothing will sweep it up.'
            Write-Host '       Close the ChatGPT/Codex app and run this installer again.'
        }
    }
    return ,$claimed
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
    # Ask the *payload's* copy of the engine, not the installed one.
    #
    # `verify-home` arrived in v0.5.4, and this uninstaller has to work against an
    # installation made by an earlier version - where asking the installed copy gets an
    # argparse error, a non-zero exit, and a refusal to uninstall a perfectly legitimate
    # installation. The payload travels with this script and is always its own version,
    # so it can always answer. Measured, by running exactly that against a v0.5.3 tree.
    $verifier = Join-Path $Payload 'app\scripts\plugin_setup.py'
    if (-not (Test-Path -LiteralPath $verifier)) { $verifier = Join-Path $AppDir 'scripts\plugin_setup.py' }
    $interpreter = $Python
    if (-not (Test-Path -LiteralPath $interpreter)) { $interpreter = Join-Path $Payload 'runtime\python.exe' }
    # Refused only when neither interpreter is there: an uninstall run from the archive (Uninstall.cmd) over an
    # installation whose runtime\ an earlier run already removed still has the payload's to ask (v0.6.18 audit, R3).
    if (-not (Test-Path -LiteralPath $interpreter)) {
        Warn 'No installed runtime found here, so nothing can be verified or removed.'
        Write-Host ('       Looked in ' + $InstallHome)
        exit 1
    }
    # 'Continue' for this call: under 'Stop', Windows PowerShell 5.1 makes a native stderr line a terminating error even
    # with 2>$null, and a traceback then replaced the refusal below with a raw error (v0.6.18 installer audit, M1).
    $ErrorActionPreference = 'Continue'
    $verify = & $interpreter $verifier 'verify-home' 2>$null
    $ErrorActionPreference = 'Stop'
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
    # Before the first removal: the Dashboard asked to close, and nothing else of this installation's left holding
    # its files (Get-UninstallBlocker). An uninstall that stops here has changed nothing, and says what holds them.
    $blockers = Get-UninstallBlocker
    if ($blockers.Count -gt 0) {
        Fail 'Codex Auto Resume is still in use here, so nothing was removed:'
        foreach ($line in $blockers) { Write-Host ('       ' + $line) }
        Write-Host '       Close it, and run this uninstaller again.'
        exit 1
    }
    if (Test-Path -LiteralPath $Python) {
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
        # The engine is asked to leave the entry in Add or remove programs for the end of this branch.
        $env:CODEX_AUTO_RESUME_KEEP_ENTRY = '1'
        try { $code = Invoke-Setup $setupArgs } finally { $env:CODEX_AUTO_RESUME_KEEP_ENTRY = $null }
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
    # Registration failures must leave a runnable uninstaller behind. Deleting the
    # runtime here used to make the requested retry fail at the initial runtime check,
    # while Codex still held a registration pointing at the deleted application.
    if ($script:Failed) {
        Write-Host 'The installed runtime was kept so this uninstall can be retried.'
        exit 1
    }
    # An open settings window locks its executable. Check these files while the
    # runtime still exists, otherwise a sharing violation can leave only that locked
    # window behind and destroy the interpreter the documented retry requires.
    foreach ($file in @('CodexAutoResumeSettings.exe', 'codex-auto-resume.ico')) {
        $path = Join-Path $OwnedHome $file
        if ((Test-Path -LiteralPath $path) -and -not (Remove-OwnedItem $path)) {
            Fail 'A program file is still in use and could not be removed.'
            Write-Host '       Close Codex Auto Resume and run this uninstaller again.'
            Write-Host 'The installed runtime was kept so this uninstall can be retried.'
            exit 1
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
    foreach ($stale in (Get-ChildItem -LiteralPath $OwnedHome -Filter '*.old-*' -ErrorAction SilentlyContinue)) {
        # Its True or False is not a line for the log or the setup window.
        $null = Remove-OwnedItem $stale.FullName
    }
    $stuck = @()
    # What is in the two program folders goes entry by entry, each proved inside the installation again
    # (Remove-OwnedItem), so the setup window's bar follows the removal (Progress); then each folder itself, as before.
    #
    # The retry this branch asks for below needs what it ran on: runtime\python.exe, and app\scripts and app\src for
    # verify-home (the kept uninstaller has no payload to fall back on). So app\ goes first, those two of it last and
    # only while nothing before them stuck, and runtime\ only once app\ is gone: one file held open under app\ used to
    # leave runtime\ deleted anyway, and the retry then stopped at "No installed runtime found" for good (v0.6.18
    # installer audit, R3).
    $retryNeeds = @('scripts', 'src')
    $programDirs = @(@($AppDir, $RunDir) | Where-Object { Test-Path -LiteralPath $_ })
    $programEntries = @{}
    $removeTotal = $programDirs.Count
    foreach ($dir in $programDirs) {
        $inside = @(Get-ChildItem -LiteralPath $dir -Force -ErrorAction SilentlyContinue)
        if ($dir -eq $AppDir) {
            $inside = @($inside | Where-Object { $retryNeeds -notcontains $_.Name }) +
                      @($inside | Where-Object { $retryNeeds -contains $_.Name })
        }
        $programEntries[$dir] = $inside
        $removeTotal += $inside.Count
    }
    $removedCount = 0
    foreach ($dir in $programDirs) {
        foreach ($programEntry in $programEntries[$dir]) {
            if ($stuck.Count -gt 0 -and $retryNeeds -contains $programEntry.Name) { continue }
            # -ErrorAction SilentlyContinue swallows a sharing violation, so Remove-OwnedItem asks afterwards. A
            # half-deleted installation reported as "Removed." is worse than an honest failure.
            if (-not (Remove-OwnedItem $programEntry.FullName)) { $stuck += $programEntry.FullName }
            $removedCount++
            Progress 'remove_files' $removedCount $removeTotal
        }
        if ($stuck.Count -eq 0) {
            $dirGone = Remove-OwnedItem $dir
            $removedCount++
            Progress 'remove_files' $removedCount $removeTotal
            if (-not $dirGone) { $stuck += $dir }
        }
        # Nothing of runtime\ goes while anything of app\ is left.
        if ($stuck.Count -ne 0) { break }
    }
    if ($stuck.Count -gt 0) {
        Write-Host ''
        Fail 'Some program files are still in use and could not be removed:'
        foreach ($dir in $stuck) { Write-Host ('       ' + $dir) }
        Write-Host '       Close the ChatGPT/Codex app and run this again. The watcher is'
        Write-Host '       already stopped and unregistered, so nothing is running now.'
        if (Test-Path -LiteralPath $Python) { Write-Host 'The installed runtime was kept so this uninstall can be retried.' }
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
    # The copy journal is ours too, and an installation being removed has nothing left to
    # put back, so it goes with the rest rather than outliving the thing it described.
    # Every removal that can fail has succeeded: only now does the program leave the list of installed programs.
    Remove-OwnUninstallEntry $OwnedHome
    # This script may be the copy being removed: PowerShell has read all of it, and nothing holds the file.
    $kept = Join-Path $OwnedHome 'uninstall'
    $keptItem = Get-Item -LiteralPath $kept -Force -ErrorAction SilentlyContinue
    if ($keptItem -and $keptItem.PSIsContainer -and -not $keptItem.LinkType) { $null = Remove-OwnedItem $kept }
    foreach ($file in @('CodexAutoResumeSettings.exe', 'codex-auto-resume.ico', 'watcher-launcher.py',
                        'runtime.json', '.owned-by-codex-auto-resume',
                        '.codex-auto-resume-install-journal.json')) {
        $path = Join-Path $OwnedHome $file
        if (Test-Path -LiteralPath $path) { $null = Remove-OwnedItem $path }
    }
    if ($Purge) {
        # Only on an explicit request: this is the user's recovery history.
        # Asked whether it worked: a held log file used to stay while this said it was removed (v0.6.18 audit, M3).
        $kept = @()
        foreach ($dir in @((Join-Path $OwnedHome 'config'), (Join-Path $OwnedHome 'logs'))) {
            if ((Test-Path -LiteralPath $dir) -and -not (Remove-OwnedItem $dir)) { $kept += $dir }
        }
        Write-Host ''
        if ($kept.Count -gt 0) {
            Fail 'Removed, but some settings or recovery history could not be removed:'
            foreach ($dir in $kept) { Write-Host ('       ' + $dir) }
            Write-Host '       The program is gone; close what is using them, then delete them yourself.'
        } else {
            Write-Host 'Removed, including settings and recovery history.'
        }
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
if (-not (Test-Path -LiteralPath $Payload)) { Fail 'This installer is missing its payload folder.'; exit 1 }

# Said before anything is done: which edition this archive installs. Every route in - Install.cmd,
# the bootstrap, an update - passes here, so every install says it.
$edition = Get-Edition -Src (Join-Path $Payload 'app\src')
Write-Host ('edition: ' + $edition)

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
if (-not (Test-Path -LiteralPath $claimPython)) { $claimPython = $Python }
# 'Continue' for this call, as for verify-home above: the exit code decides, never a stderr line (M1).
$ErrorActionPreference = 'Continue'
$claim = & $claimPython $claimer 'claim-home' 2>$null
$ErrorActionPreference = 'Stop'
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
# A root outside the profile is made private to the person before a file of the program goes into it (R2).
if ((Protect-RelocatedHome -Root $OwnedHome -Profile $env:USERPROFILE) -eq 'protected') {
    Ok 'The installation folder, outside your profile, is private to you'
}

# Finish the previous run's move before deciding anything else.
#
# This comes first because everything below it assumes the installation is where it was
# left: `$upgrade` is decided by whether `app\` is there, and the sweep deletes every
# `*.old-*` directory it finds. A run that lost power between moving the old tree aside
# and copying the new one over leaves the only complete copy under exactly that name, so
# the two steps in that order used to answer "not installed" and then delete the proof.
$claimedAside = Restore-InterruptedCopy -Path $Journal -Root $OwnedHome

function Open-ClosedDashboard {
    <#
        Opens again each Dashboard window this update asked to close (the close step below), where it was: the
        arguments it wrote are its own reopen's (WindowReopen.ReopenArguments), taken only in that form, and it
        checks each again. On every way out once the windows were asked - an update that finished, and one that
        stopped or was put back (the `finally` at the end) - so an update that fails never leaves the person's
        Dashboard closed. Each window writes a record of its own, reopen-after-update-<its process id>.txt, so two
        windows open again as two. Only a record written after this run asked is opened, and every record is removed
        once read: none is left behind for a later update to open. Nothing is opened that was not open before. Once.
    #>
    param([switch]$Updated)
    if ($null -eq $script:DashboardsAskedAt -or $script:DashboardsReopened) { return }
    $script:DashboardsReopened = $true
    $dashboard = Join-Path $InstallHome 'CodexAutoResumeSettings.exe'
    # Only the words the window's own ParseArguments takes (gui/WindowReopen.cs): its pages, sections, themes and
    # designs by name, the bounds and the frame as numbers, a generation from 1 to 9 and a place for the keyboard it
    # gives - nothing else, such as the window's --uninstall. The numbers' ranges are the window's to check again.
    $pages = 'overview|pending|history|statistics|diagnostics|settings'
    $sections = 'general|recovery|continuation|appearance|advanced'
    $word = '--settings|--maximized|--page=(' + $pages + ')|--section=(' + $sections + ')' +
            '|--theme=(system|light|dark)|--design=(soft|classic|plain)' +
            '|--bounds=(-[0-9]{1,5}|[0-9]{1,6}),(-[0-9]{1,5}|[0-9]{1,6}),[0-9]{1,6},[0-9]{1,6}' +
            '|--frame=[0-9]{1,2},[0-9]{1,2},[0-9]{1,2},[0-9]{1,2}|--reopened=[1-9]' +
            '|--focus=(save|restore|close|start|page\.(' + $pages + ')|section\.(' + $sections + ')|setting\.[a-z0-9_]{1,64})'
    $rule = '^(' + $word + ')( (' + $word + '))*$'
    $records = @(Get-ChildItem -LiteralPath (Join-Path $InstallHome 'config') -File -Filter 'reopen-after-update*.txt' `
                               -ErrorAction SilentlyContinue)
    foreach ($record in $records) {
        $fresh = $record.LastWriteTimeUtc -ge $script:DashboardsAskedAt
        $line = ([string](Get-Content -LiteralPath $record.FullName -Raw -ErrorAction SilentlyContinue)).Trim()
        $null = Remove-OwnedItem $record.FullName
        if ($record.Name -cnotmatch '^reopen-after-update-[0-9]{1,10}\.txt$') { continue }
        if (-not $fresh -or -not (Test-Path -LiteralPath $dashboard -PathType Leaf)) { continue }
        if ($line -cnotmatch $rule) { continue }
        try {
            # Through the shell, never -NoNewWindow: that hands the window this script's own output and error handles,
            # so whoever reads them - the Dashboard that started an update, `$o = & Setup.exe -Silent` - waited for
            # this Dashboard to close before it saw the end. The Dashboard is a Windows program, built
            # /target:winexe, so the shell opens no console for it.
            Start-Process -FilePath $dashboard -ArgumentList $line -WorkingDirectory $InstallHome
            if ($Updated) { Ok 'The Dashboard was opened again on the new version' }
            else { Ok 'The Dashboard was opened again' }
        } catch {
            Warn 'The Dashboard could not be opened again; open it from the Start menu.'
        }
    }
    # A window of an earlier version, closed by the fallback (Close-OwnedDashboard), wrote no record: it opens on the
    # page its command line named, else the Overview - one for each window closed so.
    foreach ($page in @($script:DashboardsFallback)) {
        if (-not (Test-Path -LiteralPath $dashboard -PathType Leaf)) { break }
        try {
            if ($page -cmatch ('^(' + $pages + ')$')) {
                Start-Process -FilePath $dashboard -ArgumentList ('--page=' + $page) -WorkingDirectory $InstallHome
            } else {
                Start-Process -FilePath $dashboard -WorkingDirectory $InstallHome
            }
            if ($Updated) { Ok 'The Dashboard was opened again on the new version' }
            else { Ok 'The Dashboard was opened again' }
        } catch {
            Warn 'The Dashboard could not be opened again; open it from the Start menu.'
        }
    }
}

function Start-StoppedWatcher {
    <#
        Starts again the watcher this update stopped (the hand-over below), when the update stops before its own setup
        starts the new version's: a copy that was put back, a payload found incomplete, anything that throws. Without
        this the closing line said nothing was changed while recovery stayed off until the next sign-in (v0.6.18
        installer audit, R2). It is the installation's own `setup --keep-state` - whichever version's files are in
        place, the put-back ones after a rollback - which changes no decision a person made, as the bootstrap's repair
        runs it. Where that cannot run or does not confirm the watcher, it says recovery is off and how to start it.
        Once, and only while $script:WatcherStoppedForUpdate says a watcher was stopped and nothing has started one.
    #>
    if (-not $script:WatcherStoppedForUpdate) { return }
    $script:WatcherStoppedForUpdate = $false
    if ((Test-Path -LiteralPath $Python) -and (Test-Path -LiteralPath (Join-Path $AppDir 'scripts\plugin_setup.py'))) {
        Step 'Starting the watcher that was stopped for this update again'
        $restartArgs = @('setup', '--keep-state')
        if ($SkipStartup) { $restartArgs += '--no-startup' }
        if ((Invoke-Setup $restartArgs) -eq 0) {
            Ok 'The watcher was started again'
            return
        }
    }
    Warn 'The watcher that was stopped for this update is not running, so nothing is being recovered now.'
    Write-Host '       Open Start Menu > Codex Auto Resume and use Start watcher, or sign out and back in.'
}

# From here on, the Dashboard windows an update asks to close (below) open again on every way out, through the
# `finally` at the end - an update that finishes, and one that stops, is refused or is put back alike. So does the
# watcher the update stopped, until the update's own setup takes over (Start-StoppedWatcher).
$script:WatcherStoppedForUpdate = $false
$script:DashboardsAskedAt = $null
$script:DashboardsReopened = $false
$script:DashboardsFallback = @()
try {
    $upgrade = Test-Path -LiteralPath $AppDir

    # Which edition is installed, read while the old program files are still where they were.
    # The move-aside below takes the whole app tree away, which is why no advanced package can
    # outlive a move to the standard edition - and why this is the last moment to read it.
    #
    # Moving between editions is a reinstall, never an update, so it happens only when asked for.
    # Refused before the sweep, the handover and the move: a run that stops here has changed
    # nothing, and says what going ahead would keep and change. Install.cmd reads the code as its
    # cue to ask y/N and run this again with -AllowEditionChange; the bootstrap passes that only
    # after -Edition and -Force.
    $EDITION_CHANGE_REFUSED = 14
    $previousEdition = $null
    if ($upgrade) { $previousEdition = Get-Edition -Src (Join-Path $AppDir 'src') }
    $editionChange = $upgrade -and ($previousEdition -ne $edition)
    # A repair is this archive's version over the same version, in the same edition (the setup program's Repair, or
    # Install.cmd run again): the last word says it repaired, not that it updated (v0.6.17, the live acceptance).
    # Read now, while the installed program files are still where they were.
    $repair = $false
    if ($upgrade -and -not $editionChange) {
        $installedVersion = Get-AppVersion -Root $AppDir
        if ($installedVersion -and ($installedVersion -ceq (Get-AppVersion -Root (Join-Path $Payload 'app')))) { $repair = $true }
    }
    if ($editionChange) {
        Write-Host ''
        Write-Host (Get-EditionStatement -From $previousEdition -To $edition)
        if (-not $AllowEditionChange) {
            Fail ('This archive is the ' + $edition + ' edition, and the ' + $previousEdition + ' edition is installed here.')
            Write-Host '       An edition is changed only when that is asked for, so nothing was changed.'
            Write-Host '       Install.cmd asks before it changes it; run by hand, add -AllowEditionChange.'
            exit $EDITION_CHANGE_REFUSED
        }
        Ok ('Replacing the ' + $previousEdition + ' edition with the ' + $edition + ' edition, as asked')
    }

    if ($upgrade) { Step 'Updating program files' } else { Step 'Installing program files' }

    # Sweep up copies moved aside by an earlier upgrade. They are only removable once
    # whatever was using them has exited, which is normally by now - except the ones the
    # journal still accounts for, which are either the tree just put back or the one an
    # interrupted run was replacing and could not.
    foreach ($stale in (Get-ChildItem -LiteralPath $OwnedHome -Directory -Filter '*.old-*' -ErrorAction SilentlyContinue)) {
        $canonical = Resolve-Canonical $stale.FullName
        if ($canonical -and ($claimedAside -contains $canonical)) {
            Step ('Keeping ' + $stale.Name + ' until this installation is complete')
            continue
        }
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
    # Whether a watcher of this installation ran before the update: the setup below starts the new version's again only
    # then, or where it runs at sign-in anyway - never one the person had stopped (--watcher-was-stopped, v0.6.16).
    $watcherWasRunning = (Get-OwnedWatcherProcess).Count -gt 0
    if ($watcherWasRunning) {
        Step 'Stopping the running watcher so the new version takes over'
        if ((Test-Path -LiteralPath $Python) -and (Test-Path -LiteralPath (Join-Path $AppDir 'scripts\plugin_setup.py'))) {
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
            # Started again on every way out before the setup below (the `finally` at the end, Start-StoppedWatcher).
            $script:WatcherStoppedForUpdate = $true
        }
    }

    # The Dashboard, as the watcher (v0.6.16, the owner: after an update everything runs on the new version). An
    # open window of this installation is asked to close itself (Close-OwnedDashboard): a window of this version
    # writes where it was (config\reopen-after-update-<its process id>.txt) and closes - unless it has unsaved
    # Settings changes, which it keeps, and says so, and stays open; a window of an earlier version, which does not
    # listen, is closed as a person closes it. A window that stayed runs the previous version until it is opened
    # again, and is said as what it is. Nothing is ended by force. Each window opens again where it was once setup
    # has run (below) - and on every other way out from here, through the `finally` at the end, so an update that
    # stops or is put back leaves it open as it was. A record an earlier update left, one that stopped before it
    # read it, is never opened: removed before asking.
    if ($upgrade) {
        foreach ($stale in @(Get-ChildItem -LiteralPath (Join-Path $InstallHome 'config') -File `
                                           -Filter 'reopen-after-update*.txt' -ErrorAction SilentlyContinue)) {
            $null = Remove-OwnedItem $stale.FullName
        }
    }
    $dashboardsOpen = $upgrade -and (Get-OwnedDashboardProcess).Count -gt 0
    if ($dashboardsOpen) {
        Step 'Closing the Dashboard so it opens again on the new version'
        $closed = Close-OwnedDashboard
        if ($closed.Fallback.Count -gt 0) {
            Ok 'A Dashboard of an earlier version, which cannot be asked, was closed as a window is closed'
        }
        if ($closed.Unsaved -gt 0) {
            Warn 'A Dashboard window with unsaved changes stayed open; it runs the previous version until it is opened again.'
        }
        if ($closed.Stuck -gt 0) {
            Warn 'A Dashboard window could not be closed; it runs the previous version until it is opened again.'
        }
        if ($closed.Unsaved -eq 0 -and $closed.Stuck -eq 0) { Ok 'The Dashboard closed' }
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
    # The files the payload carries at its root, by name - the settings window and its icon,
    # which is exactly what build/make_release.py puts there. Named rather than enumerated:
    # copying whatever happened to be at the payload root wrote every stray file into the
    # installation home, including names this product reads as proof that the home is ours
    # (`runtime.json`, `.owned-by-codex-auto-resume`) or as state. An installer authors
    # neither. Checked here, before anything is moved, so a payload missing one of them
    # fails while putting it back is still free.
    $rootFiles = @('CodexAutoResumeSettings.exe', 'codex-auto-resume.ico')
    foreach ($pair in $pairs) {
        if (-not (Test-Path -LiteralPath (Join-Path $Payload $pair.src))) { Fail ('Payload is incomplete: ' + $pair.src); exit 1 }
    }
    foreach ($name in $rootFiles) {
        if (-not (Test-Path -LiteralPath (Join-Path $Payload $name))) { Fail ('Payload is incomplete: ' + $name); exit 1 }
    }

    # Move everything aside first, copy second, and undo the whole thing on any failure -
    # including a failure during the copy. An upgrade that stops half way is worse than one
    # that does not happen: the first attempt at this rolled back a failed move but not a
    # failed copy, and left the application present and the interpreter missing.
    #
    # The names every tree will be moved to are decided before the first move and written to
    # the journal, because the undo below cannot run at all if the power goes. One stamp for
    # the whole run: the two trees have different base names, so they cannot collide.
    $stamp = Get-Date -Format 'yyyyMMddHHmmss'
    $plan = @()
    foreach ($pair in $pairs) {
        if (-not (Test-Path -LiteralPath $pair.dst)) { continue }
        $aside = $pair.dst + '.old-' + $stamp
        $plan += @{ src = $pair.src; dst = $pair.dst; aside = $aside }
    }
    $moved = @()
    # Its own line, so the installer window's step follows the copy rather than staying on what came before it.
    Step 'Copying the program files into place'
    try {
        if ($plan.Count -gt 0) { Write-CopyJournal -Path $Journal -Root $OwnedHome -Entries $plan }
        foreach ($pair in $plan) {
            $aside = $pair.aside
            Move-Item -LiteralPath $pair.dst -Destination $aside -ErrorAction Stop
            $moved += @{ from = $aside; to = $pair.dst }
        }
        # File by file, so the setup window's bar follows the copy as it goes (Progress): every folder first, then
        # every file, of both trees - hidden ones too, as the copy of each whole tree took them.
        $copying = @()
        foreach ($pair in $pairs) {
            New-Item -ItemType Directory -Force -Path $pair.dst | Out-Null
            # Join-Path takes two paths in Windows PowerShell; a third argument is a
            # parameter-binding error, not a longer path.
            $copying += @(Get-PayloadTree -Source (Join-Path $Payload $pair.src) -Destination $pair.dst)
        }
        $copyFiles = @($copying | Where-Object { -not $_.Folder }).Count
        $copied = 0
        foreach ($payloadItem in @($copying | Where-Object { $_.Folder })) {
            New-Item -ItemType Directory -Force -Path $payloadItem.To | Out-Null
        }
        foreach ($payloadItem in @($copying | Where-Object { -not $_.Folder })) {
            [IO.File]::Copy($payloadItem.From, $payloadItem.To, $true)
            $copied++
            Progress 'files' $copied $copyFiles
        }
    } catch {
        Warn ('Could not replace the installation: ' + $_.Exception.Message)
        $notBack = @()
        foreach ($undo in $moved) {
            if (Test-Path -LiteralPath $undo.to) { $null = Remove-OwnedItem $undo.to }
            # Moved back only where the half-copied tree is gone: moved onto a folder that is still there, it went INTO
            # it (apppp.old-<stamp>), and a later run swept it with the rest (v0.6.18 installer audit, M5). Left
            # aside under its own name, the journal below keeps it from every sweep.
            if (Test-Path -LiteralPath $undo.to) { $notBack += $undo; continue }
            Move-Item -LiteralPath $undo.from -Destination $undo.to -Force -ErrorAction SilentlyContinue
            if (-not (Test-Path -LiteralPath $undo.to)) { $notBack += $undo }
        }
        # The journal is deliberately left where it is. The undo above is best-effort, and if
        # any part of it did not take, that file is the only record of where the tree went.
        if ($notBack.Count -gt 0) {
            Fail 'The existing installation could not be put back completely:'
            foreach ($undo in $notBack) { Write-Host ('       ' + $undo.from + ' could not be put back at ' + $undo.to) }
            Write-Host '       It is kept under that name until an installation completes.'
            Write-Host '       Close the ChatGPT/Codex app and run this installer again.'
            exit 1
        }
        Fail 'The existing installation was put back; nothing was changed.'
        Write-Host '       Close the ChatGPT/Codex app and run this installer again.'
        exit 1
    }
    # Both trees are in place, so nothing is waiting to be put back and the copies moved
    # aside are leftovers again rather than the last good ones.
    if (Test-Path -LiteralPath $Journal) { $null = Remove-OwnedItem $Journal }
    foreach ($old in $moved) { $null = Remove-OwnedItem $old.from }

    # The settings window and the icon live at the payload root because the window
    # resolves runtime\python.exe and app\src relative to its own directory. The window may
    # be open right now, so the same move-aside rule applies to it. By name, from the list
    # checked above - never everything the payload root happens to hold.
    foreach ($name in $rootFiles) {
        $source = Join-Path $Payload $name
        $target = Join-Path $InstallHome $name
        try {
            Copy-Item -LiteralPath $source -Destination $target -Force -ErrorAction Stop
        } catch {
            $aside = $target + '.old-' + (Get-Date -Format 'yyyyMMddHHmmss')
            Move-Item -LiteralPath $target -Destination $aside -Force -ErrorAction SilentlyContinue
            # A second failure is said, and the run goes on to its setup: thrown here, it ended the update after the
            # program trees were replaced and before the watcher was set up, with no last word (v0.6.18 audit, M6).
            try { Copy-Item -LiteralPath $source -Destination $target -Force -ErrorAction Stop }
            catch {
                Fail ($name + ' could not be replaced: ' + $_.Exception.Message)
                Write-Host '       Close the Dashboard and run this installer again; the rest of the update goes on.'
            }
        }
    }
    foreach ($stale in (Get-ChildItem -LiteralPath $OwnedHome -File -Filter '*.old-*' -ErrorAction SilentlyContinue)) {
        $null = Remove-OwnedItem $stale.FullName
    }
    if (-not (Test-Path -LiteralPath $Python)) { Fail 'The bundled Python runtime is missing from the payload.'; exit 1 }
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
    # Three commands to Codex - add the marketplace, upgrade it, add the plugin - each counted once done (Progress).
    Progress 'plugin' 1 3
    # Ours, by name - never the no-name form. Without a name, Codex refreshes every Git
    # marketplace the user has configured and reinstalls those vendors' plugins: an action on
    # other people's software that nobody asked this installer to take, and a network fetch on
    # the route that promises none. Measured in an isolated CODEX_HOME: for the local
    # marketplace registered above, the named form is a no-op ("not configured as a Git
    # marketplace"); it only does anything when a GitHub registration survived the repoint.
    $null = Invoke-Codex $codex @('plugin', 'marketplace', 'upgrade', $MarketplaceName)
    Progress 'plugin' 2 3
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
        # After an edition change, what is and is not the new edition yet (Write-PluginNotUpdated).
        if ($editionChange) { Write-PluginNotUpdated -From $previousEdition -To $edition }
        else { Write-PluginNotUpdated }
    } else { Ok 'Codex plugin installed' }
    Progress 'plugin' 3 3

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

    # The entry in Add or remove programs is written by the engine's setup below, and only where this has
    # left an uninstaller for it to name. Only for the ordinary home: an installation somewhere the person
    # chose through CODEX_AUTO_RESUME_PLUGIN_HOME would need the uninstaller told where it is, and gets none.
    # The ordinary home named by that variable is still the ordinary home (Test-DefaultHome): every update the
    # Dashboard starts names it so, and kept nothing until v0.6.17 - which this puts back, update by update.
    if ([string]::IsNullOrWhiteSpace($env:CODEX_AUTO_RESUME_PLUGIN_HOME) -or
        (Test-DefaultHome -Root $OwnedHome -Profile $env:USERPROFILE)) {
        $null = Install-KeptUninstaller -Source $PSCommandPath
    }

    Step 'Setting up the watcher'
    # From here the new version's setup starts the watcher, and nothing else does.
    $script:WatcherStoppedForUpdate = $false
    $setupArgs = @('setup')
    # An upgrade repairs an installation; it does not get to decide anything for its owner.
    # Plain `setup` runs the engine's `enable` and registers the sign-in entry, so upgrading
    # over an installation whose owner had paused recovery switched it back on, and put back
    # a sign-in entry they had removed - silently, under the name of an update. `--keep-state`
    # leaves the pause switch alone and only re-registers an autostart that is already ours,
    # which still repairs a stale path after the runtime moves.
    #
    # Only on the upgrade branch. A first install has no decision to preserve, and has to end
    # up enabled and registered or nothing is being watched.
    if ($upgrade) { $setupArgs += '--keep-state' }
    # An edition change is the new edition's to act on, and only it knows what that means for it:
    # entering the advanced edition starts every advanced feature off, whatever an earlier advanced
    # installation left on. Setup carries the edition it replaced across to `install --edition-from`.
    #
    # A home with no program in it but advanced state in config\advanced is the other way in. An
    # uninstall keeps config\ unless it purges, so the state of an advanced installation that was
    # armed, moved to the standard edition and then uninstalled is still there, and nothing says
    # which edition ran here last. The advanced archive installed over it enters from standard as
    # far as setup is told, so every advanced feature starts off rather than coming back on.
    # Unless the uninstall said it took the advanced edition away (config\edition-left.txt, v0.6.16): then this is the
    # same edition coming back, and its choices stay as an update keeps them (K2, amended by the owner on 2026-10-18).
    $advancedLeft = Test-Path -LiteralPath (Join-Path (Join-Path $InstallHome 'config') 'advanced')
    $leftFile = Join-Path (Join-Path $InstallHome 'config') 'edition-left.txt'
    $leftBy = $null
    $leftItem = Get-Item -LiteralPath $leftFile -Force -ErrorAction SilentlyContinue
    if ($leftItem -and -not $leftItem.PSIsContainer -and -not ($leftItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        try { $leftBy = ([IO.File]::ReadAllText($leftItem.FullName)).Trim() } catch { $leftBy = $null }
    }
    if ($editionChange) { $setupArgs += @('--edition-from', $previousEdition) }
    elseif (-not $upgrade -and $edition -eq 'advanced' -and $advancedLeft -and $leftBy -cne 'advanced') {
        $setupArgs += @('--edition-from', 'standard')
    }
    if ($SkipStartup) { $setupArgs += '--no-startup' }
    if ($upgrade -and -not $watcherWasRunning) { $setupArgs += '--watcher-was-stopped' }
    # 2 means everything was done but the watcher was not seen running - a real outcome that
    # is neither success nor failure. Treating it as failure would roll back a good install;
    # treating it as success is how this script came to end with "Installed and running."
    # about a watcher nobody had looked at.
    $SETUP_UNCONFIRMED = 2
    # This run looks at the watcher again after the health check (watcher-running, below) and says the last word, so a
    # watcher setup could not confirm within its wait is "not confirmed yet" in setup's own line, not a verdict
    # the last word then contradicts (v0.6.17, the live acceptance's second round). Said as a variable for this one
    # call, the way the bootstrap says it to an installed setup that may be older.
    $env:CODEX_AUTO_RESUME_SETUP_WILL_LOOK_AGAIN = '1'
    try { $code = Invoke-Setup $setupArgs } finally { $env:CODEX_AUTO_RESUME_SETUP_WILL_LOOK_AGAIN = $null }
    $watcherUnconfirmed = $code -eq $SETUP_UNCONFIRMED
    if ($code -ne 0 -and -not $watcherUnconfirmed) {
        Fail 'Setup did not complete. Nothing was removed; read the message above.'
        # A watcher stopped for this update that the failed setup did not start again is said, not left unsaid.
        if ($watcherWasRunning -and (Invoke-Setup @('watcher-running')) -ne 0) {
            Warn 'The watcher that was stopped for this update is not running, so nothing is being recovered now.'
            Write-Host '       Open Start Menu > Codex Auto Resume and use Start watcher, or run this again.'
        }
        exit 1
    }

    Step 'Checking the installation'
    $null = Invoke-Setup @('doctor')
    if ($LASTEXITCODE -ne 0) { Warn 'The health check reported a problem. Recovery is installed but may not be ready.' }
    # Setup waits for the watcher it started for a few seconds and no longer. On a busy PC, right after every file
    # was written fresh, a watcher can take longer than that to take its mutex (v0.6.17 live acceptance: 6 to 9
    # seconds), and this run then ended "could not be confirmed" under a health check that had just seen the mutex
    # held. So it is looked at once more, now, before the last word: a watcher running now is a watcher running.
    # The look's one line is said in English, for this English log, whatever Interface language the PC stores.
    if ($watcherUnconfirmed) {
        $env:CODEX_AUTO_RESUME_SETUP_ENGLISH = '1'
        try { if ((Invoke-Setup @('watcher-running')) -eq 0) { $watcherUnconfirmed = $false } }
        finally { $env:CODEX_AUTO_RESUME_SETUP_ENGLISH = $null }
    }

    # The Dashboard that closed for this update opens again on the new version, where it was (Open-ClosedDashboard).
    Open-ClosedDashboard -Updated

    Write-Host ''
    if ($script:Failed) { Write-Host 'Finished with problems. See the messages above.'; exit 1 }
    # What was done to an installation that was there: repaired (this version over itself) or updated.
    $keptLine = if ($repair) { 'Repaired. Your settings and pending recoveries were kept.' }
                else { 'Updated. Your settings and pending recoveries were kept.' }
    if ($watcherUnconfirmed) {
        if ($upgrade) { Write-Host $keptLine }
        else { Write-Host 'Installed.' }
        Write-Host 'The watcher could not be confirmed running, so nothing is being watched yet.'
        Write-Host 'Open Start Menu > Codex Auto Resume and use Start watcher, or run this again.'
    } elseif ($previousWatcherStillRunning) {
        Write-Host $keptLine
        Write-Host 'The previous version of the watcher was asked to stop and is still finishing'
        Write-Host 'what it was doing; nothing was ended by force. Once it has stopped, open'
        Write-Host 'Start Menu > Codex Auto Resume and use Start watcher - or sign out and back in.'
    } else {
        if ($upgrade) { Write-Host $keptLine }
        else { Write-Host 'Installed and running.' }
        Write-Host 'Recommended settings are already on. Nothing else to do.'
    }
    Write-Host ''
    Write-Host 'To change anything: open Codex and ask "open auto resume settings",'
    Write-Host 'or use Start Menu > Codex Auto Resume.'
    exit 0
} finally {
    # Every way out before the setup step - a put-back installation, a stop, an error - starts the stopped watcher again.
    try { Start-StoppedWatcher } catch { }
    # Every way out once the Dashboard was asked to close - a stop, a put-back installation, an error - opens it again.
    try { Open-ClosedDashboard } catch { }
}
