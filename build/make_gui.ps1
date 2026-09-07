<#
    Compile the two small Windows executables the product ships.

    .NET Framework 4.8 ships with every supported version of Windows, so the release
    carries no extra runtime for either of them and there is nothing to install to build
    them. csc.exe lives beside the framework itself.

    Every compiler argument is built as a complete string before the call. In argument
    mode PowerShell does not evaluate a parenthesised expression that is glued to a
    literal prefix - `/win32icon:(Join-Path ...)` is passed through verbatim, and csc
    then reports "Illegal characters in path".
#>
[CmdletBinding()]
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$Out  = (Join-Path (Split-Path -Parent $PSScriptRoot) 'build')
)

$ErrorActionPreference = 'Stop'

$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path $csc)) { throw 'The in-box C# compiler was not found.' }

New-Item -ItemType Directory -Force $Out | Out-Null

$icon     = Join-Path $Root 'assets\codex-auto-resume.ico'
$manifest = Join-Path $Root 'gui\app.manifest'

function Build {
    param(
        [string]$Name,
        [string]$Source,
        [string]$Target,
        [string[]]$References,
        [switch]$WithManifest
    )
    $exe = Join-Path $Out $Name
    $arguments = @('/nologo', ('/target:' + $Target), '/platform:x64', '/optimize+',
                   ('/out:' + $exe))
    foreach ($reference in $References) { $arguments += ('/reference:' + $reference) }
    if (Test-Path $icon) { $arguments += ('/win32icon:' + $icon) }
    # Only the window declares per-monitor DPI awareness; the launcher draws nothing.
    if ($WithManifest -and (Test-Path $manifest)) { $arguments += ('/win32manifest:' + $manifest) }
    $arguments += $Source
    & $csc @arguments
    if ($LASTEXITCODE -ne 0) { throw ($Name + ' failed to compile.') }
    Write-Host ('built ' + $exe + ' (' + (Get-Item $exe).Length + ' bytes)')
}

Build -Name 'CodexAutoResumeSettings.exe' -Target 'winexe' -WithManifest `
      -Source (Join-Path $Root 'gui\SettingsApp.cs') `
      -References @('System.dll', 'System.Drawing.dll', 'System.Windows.Forms.dll')

# A console-subsystem executable on purpose: it inherits Codex's standard streams and
# hands them straight to the MCP server, which is the whole reason it exists.
Build -Name 'codex-auto-resume-mcp.exe' -Target 'exe' `
      -Source (Join-Path $Root 'gui\McpLauncher.cs') `
      -References @('System.dll')
