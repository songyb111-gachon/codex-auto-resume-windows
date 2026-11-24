
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$target = $shell.CreateShortcut($env:CODEX_AUTO_RESUME_ARG_LNK).TargetPath
if ([string]::IsNullOrEmpty($target)) { exit 4 }
$root = [IO.Path]::GetFullPath($env:CODEX_AUTO_RESUME_ARG_ROOT).TrimEnd('\') + '\'
if ([IO.Path]::GetFullPath($target).StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) { exit 0 }
exit 3
