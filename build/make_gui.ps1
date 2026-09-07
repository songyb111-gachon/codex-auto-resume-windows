<#
    Compile the standalone settings window with the in-box C# compiler.

    .NET Framework 4.8 ships with every supported version of Windows, so the release
    carries no extra runtime for the interface and there is nothing to install to build
    it. csc.exe lives beside the framework itself.

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

$exe      = Join-Path $Out  'CodexAutoResumeSettings.exe'
$source   = Join-Path $Root 'gui\SettingsApp.cs'
$icon     = Join-Path $Root 'assets\codex-auto-resume.ico'
$manifest = Join-Path $Root 'gui\app.manifest'

$arguments = @('/nologo', '/target:winexe', '/platform:x64', '/optimize+',
               '/reference:System.dll', '/reference:System.Drawing.dll',
               '/reference:System.Windows.Forms.dll',
               ('/out:' + $exe))
if (Test-Path $icon)     { $arguments += ('/win32icon:' + $icon) }
if (Test-Path $manifest) { $arguments += ('/win32manifest:' + $manifest) }
$arguments += $source

& $csc @arguments
if ($LASTEXITCODE -ne 0) { throw 'The settings window failed to compile.' }

Write-Host ('built ' + $exe + ' (' + (Get-Item $exe).Length + ' bytes)')
