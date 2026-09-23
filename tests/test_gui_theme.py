r"""The window's theme, its reopening, and its two kinds of true-or-false control (v0.6.4).

* THEME. The Theme setting is "system", "light" or "dark". The window resolves it once, as it opens:
  "system" follows Windows' app mode (AppsUseLightTheme: 0 is dark, anything else or nothing is
  light), and High Contrast wins over every choice. Every colour and shadow is then drawn from that
  one theme - brand.DARK and the dark elevation recipes in dark, which is what the panel in Codex
  draws in dark.
* REOPEN. A window speaks one language and draws one theme, so a change of either - saved here,
  made elsewhere, or Windows' app mode flipping under "system" - closes it and opens it again where
  it was, never under unsaved edits and never in a loop.
* KINDS. A switch turns something that runs on or off; a check box picks which items of a list apply
  (recover_<category>, notify_<event>). The check box is the neumorphic one brand.CHECKBOX defines.

The real compiled window is loaded and its own methods are called through reflection, as the other
window tests do. Nothing is shown and no input is sent anywhere: the window is built unshown, the
check box is drawn into a bitmap, and every rule about reopening is a pure function it calls - or, for the
handover itself, the window's own ending of it, called with the answer a new process would have given.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import unittest
import guiscan

from codex_auto_resume import brand, l10n, settings

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "gui"
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")

# Palette's fields, and the brand token each one is in light and dark.
TOKENS = {"Ink": "ink", "Muted": "muted", "Secondary": "muted", "Line": "line", "Surface": "surface",
          "Canvas": "canvas", "Raised": "raised", "Inset": "inset", "Accent": "accent",
          "AccentHover": "accent_hover", "AccentPressed": "accent_pressed", "OnAccent": "on_accent",
          "AccentSoft": "accent_soft", "Focus": "focus", "Active": "active", "Idle": "idle",
          "Attention": "attention", "Success": "success", "Waiting": "waiting", "Warning": "warning",
          "Danger": "danger", "Paused": "paused", "Card": None}
# And in High Contrast, the system colour.
SYSTEM = {"Ink": "WindowText", "Muted": "GrayText", "Secondary": "WindowText", "Line": "WindowFrame",
          "Surface": "Window", "Canvas": "Control", "Raised": "Window", "Inset": "Window", "Accent": "Highlight",
          "AccentHover": "Highlight", "AccentPressed": "Highlight", "OnAccent": "HighlightText",
          "AccentSoft": "Highlight", "Focus": "WindowText", "Active": "Highlight", "Idle": "GrayText",
          "Attention": "WindowText", "Success": "WindowText", "Waiting": "WindowText", "Warning": "WindowText",
          "Danger": "WindowText", "Paused": "GrayText", "Card": "Window"}

PREFERENCES = ("system", "light", "dark", None, "", "Dark", "LIGHT", "bogus")
APP_MODES = (-1, 0, 1, 2)

# name -> raw settings.json bytes, or None for no file at all. Each is an installation's config\settings.json,
# which the window must read exactly as settings.load reads it for the bridge.
STORED = {
    "missing": None,
    "dark": b'{"theme": "dark"}',
    "light": b'{"theme": "light", "interface_language": "ko"}',
    "system": b'{"theme": "system"}',
    "no_theme": b'{"interface_language": "ko"}',
    "other_case": b'{"theme": "Dark"}',
    "not_a_string": b'{"theme": 1}',
    "damaged": b'{"theme": "dark"',
    "not_an_object": b'["dark"]',
    "whitespace": b' \r\n\t{"theme": "light"}\r\n',
    "versioned": b'{"config_version": 3, "theme": "dark"}',
    # A byte order mark, as PowerShell 5.1's Set-Content -Encoding utf8 and older Notepad write one.
    "bom": b'\xef\xbb\xbf{"theme": "dark"}',
    # Saved in the Korean ANSI code page rather than UTF-8.
    "not_utf8": b'{"theme": "dark", "custom_message": "\xb0\xe8\xbc\xd3"}',
    "trailing": b'{"theme": "dark"} {"theme": "light"}',
    "too_large": b'{"theme": "dark", "custom_message": "' + b"a" * (256 * 1024) + b'"}',
}
# The widths, in logical pixels of client area, the reopen note is measured at: the opening width, and the
# narrowest the window goes - 800 wide, less a sizable frame's 8 px on each side.
NOTE_WIDTHS = (1000, 784)

# (argument list) -> what ParseArguments makes of it
ARGUMENTS = [
    ([], {}),
    (["C:\\app\\CodexAutoResumeSettings.exe"], {}),
    (["--settings"], {"page": "settings"}),
    (["--page=pending", "--section=appearance"], {"page": "pending", "section": "appearance"}),
    (["--page=nowhere", "--section=../../x"], {}),
    (["--page=Settings", "--section=General"], {}),
    (["--theme=dark"], {"theme": "dark"}),
    (["--theme=system", "--theme=light"], {"theme": "light"}),
    (["--theme=contrast", "--theme=Dark", "--theme="], {}),
    (["--bounds=10,20,1000,600"], {"bounds": [10, 20, 1000, 600]}),
    (["--bounds=-1920,-8,1500,900", "--maximized"], {"bounds": [-1920, -8, 1500, 900], "maximized": True}),
    (["--bounds=10,20,1000"], {}),
    (["--bounds=10,20,0,600"], {}),
    (["--bounds=10,20,1000,600,5"], {}),
    (["--bounds=1e3,20,1000,600"], {}),
    (["--bounds= 10,20,1000,600"], {}),
    (["--bounds=10,20,+1000,600"], {}),
    (["--bounds=99999,20,1000,600"], {}),
    (["--bounds=10,20,1000,40000"], {}),
    (["--bounds=--10,20,1000,600"], {}),
    (["--reopened=1"], {"generation": 1}),
    (["--reopened=9"], {"generation": 9}),
    (["--reopened=0"], {}),
    (["--reopened=10"], {}),
    (["--reopened=x"], {}),
    (["--Maximized", "maximized", "-maximized"], {}),
    (["--page=history --theme=dark"], {}),
    (["--frame=7,0,7,7"], {"frame": [7, 0, 7, 7]}),
    (["--frame=11,0,11,11", "--frame=bogus"], {"frame": [11, 0, 11, 11]}),
    (["--frame=0,0,0,0"], {}),
    (["--frame=-1,0,7,7"], {}),
    (["--frame=100,0,7,7"], {}),
    (["--frame=7,0,7"], {}),
    (["--frame=7, 0,7,7"], {}),
    (["--focus=save"], {"focus": "save"}),
    (["--focus=page.history", "--focus=section.appearance"], {"focus": "section.appearance"}),
    (["--focus=setting.theme"], {"focus": "setting.theme"}),
    (["--focus=setting.__startup"], {"focus": "setting.__startup"}),
    (["--focus=start", "--focus=close"], {"focus": "close"}),
    (["--focus=Save", "--focus=page.nowhere", "--focus=section.", "--focus=setting.", "--focus=setting.Theme",
      "--focus=setting.a-b", "--focus=setting." + "a" * 65, "--focus=", "--focus=save "], {}),
]

# (openedLanguage, openedTheme, language, theme, dirty, firstRead, generation) -> decision
KEEP, REOPEN, ONCE_SAVED, ADOPT = 0, 1, 2, 3
DECISIONS = [
    (("en", "light", "en", "light", False, False, 0), KEEP),
    (("en", "light", "en", "light", True, True, 5), KEEP),
    (("en", "light", "ko", "light", False, False, 0), REOPEN),
    (("en", "light", "en", "dark", False, False, 0), REOPEN),
    (("en", "light", "en", "contrast", False, False, 0), REOPEN),
    (("en", "contrast", "en", "light", False, False, 0), REOPEN),
    (("system", "dark", "en", "dark", False, False, 0), REOPEN),
    (("en", "light", "ko", "dark", True, False, 0), ONCE_SAVED),
    (("en", "light", "en", "dark", True, True, 0), ONCE_SAVED),
    (("en", "light", "en", "dark", False, True, 0), REOPEN),
    (("en", "light", "en", "dark", False, True, 1), REOPEN),
    (("en", "light", "en", "dark", False, True, 2), ADOPT),
    (("en", "light", "en", "dark", False, True, 9), ADOPT),
    (("en", "light", "en", "dark", False, False, 9), REOPEN),
    ((None, "light", "ko", "light", False, False, 0), KEEP),
    (("en", None, "en", "dark", False, False, 0), KEEP),
    (("en", "light", None, None, False, False, 0), KEEP),
]


def argb(value: str) -> int:
    r, g, b = brand.rgb(value)
    return ((0xFF << 24) | (r << 16) | (g << 8) | b) - (1 << 32)


def channels(pixel: int) -> tuple:
    pixel &= 0xFFFFFFFF
    return ((pixel >> 16) & 255, (pixel >> 8) & 255, pixel & 255)


def hex_of(pixel: int) -> str:
    return "#%02X%02X%02X" % channels(pixel)


def system_high_contrast() -> bool:
    """Whether High Contrast is on, asked of Windows directly."""
    import ctypes
    from ctypes import wintypes

    class HighContrast(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwFlags", wintypes.DWORD), ("lpszDefaultScheme", wintypes.LPWSTR)]

    info = HighContrast()
    info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.SystemParametersInfoW(0x0042, info.cbSize, ctypes.byref(info), 0):
        raise OSError("SPI_GETHIGHCONTRAST failed")
    return bool(info.dwFlags & 1)


def compile_window(work: Path) -> Path:
    exe = work / "CodexAutoResumeSettings.exe"
    subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                    "/reference:System.dll", "/reference:System.Drawing.dll", "/reference:System.Windows.Forms.dll",
                    *[str(path) for path in guiscan.sources()]],
                   check=True, capture_output=True, timeout=300)
    return exe


PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$static = [Reflection.BindingFlags]'Static,NonPublic,Public'
$instance = [Reflection.BindingFlags]'Instance,NonPublic,Public'
$work = [string]$env:CAR_WORK
$utf8 = New-Object Text.UTF8Encoding $false
$themeType = $assembly.GetType('CodexAutoResume.Theme', $true)
$paletteType = $assembly.GetType('CodexAutoResume.Palette', $true)
$tokensType = $assembly.GetType('CodexAutoResume.Tokens', $true)
$formType = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$elevation = $assembly.GetType('CodexAutoResume.Elevation', $true)
$checkType = $assembly.GetType('CodexAutoResume.SoftCheck', $true)
$jsonType = $assembly.GetType('CodexAutoResume.Json', $true)
$parse = $jsonType.GetMethod('Parse', $static)
$adopt = $paletteType.GetMethod('Adopt', $static)
# An answer for the window's input from Windows' High Contrast (Theme.HighContrastOn), compiled, so it holds on any thread.
Add-Type -TypeDefinition @'
public static class Said {
    public static bool Yes() { return true; }
    public static bool No() { return false; }
    public static System.Func<bool> Answer(bool yes) { return yes ? new System.Func<bool>(Yes) : new System.Func<bool>(No); }
}
'@
$out = @{}

# ------------------------------------------------------------------ resolution
$resolve = $themeType.GetMethod('Resolve', $static)
$out.resolve = @()
foreach ($case in (ConvertFrom-Json $env:CAR_RESOLVE)) {
    $out.resolve += [string]$resolve.Invoke($null, [object[]]@($case[0], [int]$case[1], [bool]$case[2]))
}
$out.apps = [int]$themeType.GetMethod('AppsUseLightTheme', $static).Invoke($null, $null)
$stored = $themeType.GetMethod('Stored', $static)
$out.stored = @{}
foreach ($name in (ConvertFrom-Json $env:CAR_STORED)) {
    # Written by the test, as settings.load will read them.
    $out.stored[[string]$name] = [string]$stored.Invoke($null, [object[]]@([string](Join-Path $work ('stored-' + $name))))
}

# ------------------------------------------------------------------ the palette in each theme
$names = ConvertFrom-Json $env:CAR_NAMES
$out.palette = @{}
foreach ($theme in @('dark', 'contrast', 'bogus', 'light')) {
    $null = $adopt.Invoke($null, [object[]]@([string]$theme))
    $entry = @{ theme = [string]$paletteType.GetField('Theme', $static).GetValue($null)
                contrast = [bool]$paletteType.GetField('Contrast', $static).GetValue($null)
                dark = [bool]$paletteType.GetProperty('Dark', $static).GetValue($null)
                tokensDark = [bool]$tokensType.GetField('Dark', $static).GetValue($null)
                colours = @{} }
    foreach ($name in $names) {
        $colour = $paletteType.GetField([string]$name, $static).GetValue($null)
        $entry.colours[[string]$name] = @([int]$colour.ToArgb(), [string]$colour.Name, [bool]$colour.IsSystemColor)
    }
    $out.palette[$theme] = $entry
}

# ------------------------------------------------------------------ the dark elevation
$profile = $elevation.GetMethod('Profile', $static)
$render = $elevation.GetMethod('Render', $static)
$reach = $elevation.GetMethod('Reach', $static, $null, [Type[]]@([string], [double]), $null)
$bodies = ConvertFrom-Json $env:CAR_BODIES
$out.elevation = @{}
foreach ($theme in @('dark', 'light')) {
    $null = $adopt.Invoke($null, [object[]]@([string]$theme))
    $out.elevation[$theme] = @{}
    foreach ($scale in (ConvertFrom-Json $env:CAR_SCALES)) {
        $key = ([double]$scale).ToString('0.0', [Globalization.CultureInfo]::InvariantCulture)
        $out.elevation[$theme][$key] = @{}
        foreach ($recipe in @('card', 'control', 'inset')) {
            $body = $bodies.$recipe
            $width = [int][Math]::Round($body[0] * $scale)
            $height = [int][Math]::Round($body[1] * $scale)
            $margin = [int][Math]::Round($body[2] * $scale)
            $pixels = [int[]]$render.Invoke($null, [object[]]@([string]$recipe, [double]$scale, $width, $height, $margin))
            $across = $width + 2 * $margin
            $down = $height + 2 * $margin
            $row = [int[]]::new($across)
            [Array]::Copy($pixels, ($margin + [int][Math]::Floor($height / 2)) * $across, $row, 0, $across)
            $column = [int[]]::new($down)
            $centre = $margin + [int][Math]::Floor($width / 2)
            for ($y = 0; $y -lt $down; $y++) { $column[$y] = $pixels[$y * $across + $centre] }
            $padding = $reach.Invoke($null, [object[]]@([string]$recipe, [double]$scale))
            $out.elevation[$theme][$key][$recipe] = @{
                profile = @($profile.Invoke($null, [object[]]@([string]$recipe, [double]$scale)) | ForEach-Object { [double]$_ })
                reach = @($padding.Left, $padding.Top, $padding.Right, $padding.Bottom)
                width = $width; height = $height; margin = $margin; row = $row; column = $column }
        }
    }
}

# ------------------------------------------------------------------ the check box, drawn
$dpi = $formType.GetField('dpiScale', $static)
$systemScale = [double]$formType.GetField('SystemScale', $static).GetValue($null)
$drawBox = $checkType.GetMethod('DrawBox', $static)
$dpi.SetValue($null, [double]2.0)
$out.box = @{}
foreach ($theme in @('light', 'dark', 'contrast')) {
    $null = $adopt.Invoke($null, [object[]]@([string]$theme))
    $ground = $paletteType.GetField('Card', $static).GetValue($null)
    $out.box[$theme] = @{ ground = [int]$ground.ToArgb(); states = @{} }
    foreach ($state in @('off', 'on', 'off_disabled', 'on_disabled')) {
        $on = $state.StartsWith('on')
        $enabled = -not $state.EndsWith('disabled')
        $bitmap = [Drawing.Bitmap]::new(60, 60)
        $g = [Drawing.Graphics]::FromImage($bitmap)
        $g.Clear($ground)
        $face = [Drawing.Rectangle]::new(10, 10, 36, 36)
        $null = $drawBox.Invoke($null, [object[]]@($g, $face, [bool]$on, [bool]$enabled))
        $g.Dispose()
        $pick = @{}
        foreach ($point in (ConvertFrom-Json $env:CAR_BOX_POINTS).PSObject.Properties) {
            $pick[$point.Name] = [int]$bitmap.GetPixel([int]$point.Value[0], [int]$point.Value[1]).ToArgb()
        }
        $bitmap.Dispose()
        $out.box[$theme].states[$state] = $pick
    }
}
$out.boxSystem = @{ Window = [Drawing.SystemColors]::Window.ToArgb(); WindowText = [Drawing.SystemColors]::WindowText.ToArgb()
                    Highlight = [Drawing.SystemColors]::Highlight.ToArgb(); HighlightText = [Drawing.SystemColors]::HighlightText.ToArgb()
                    GrayText = [Drawing.SystemColors]::GrayText.ToArgb() }
$dpi.SetValue($null, $systemScale)

# ------------------------------------------------------------------ the reopening rules
$decide = $formType.GetMethod('ReopenDecision', $static)
$out.decisions = @()
foreach ($case in (ConvertFrom-Json $env:CAR_DECISIONS)) {
    $out.decisions += [int]$decide.Invoke($null, [object[]]@($case[0], $case[1], $case[2], $case[3], [bool]$case[4], [bool]$case[5], [int]$case[6]))
}
$next = $formType.GetMethod('NextGeneration', $static)
$out.next = @()
foreach ($case in @(@($true, 0), @($true, 1), @($true, 2), @($true, 9), @($false, 0), @($false, 2), @($false, 9))) {
    $out.next += [int]$next.Invoke($null, [object[]]@([bool]$case[0], [int]$case[1]))
}
$out.maxGeneration = [int]$formType.GetField('MaxGeneration', $static).GetValue($null)
$parseArguments = $formType.GetMethod('ParseArguments', $static)
function Request-Of($request) {
    $result = @{}
    if ($null -ne $request.GetType().GetField('Page', $instance).GetValue($request)) { $result.page = [string]$request.GetType().GetField('Page', $instance).GetValue($request) }
    if ($null -ne $request.GetType().GetField('Section', $instance).GetValue($request)) { $result.section = [string]$request.GetType().GetField('Section', $instance).GetValue($request) }
    if ($null -ne $request.GetType().GetField('Theme', $instance).GetValue($request)) { $result.theme = [string]$request.GetType().GetField('Theme', $instance).GetValue($request) }
    if ([bool]$request.GetType().GetField('HasBounds', $instance).GetValue($request)) {
        $bounds = $request.GetType().GetField('Bounds', $instance).GetValue($request)
        $result.bounds = @($bounds.X, $bounds.Y, $bounds.Width, $bounds.Height)
    }
    if ([bool]$request.GetType().GetField('Maximized', $instance).GetValue($request)) { $result.maximized = $true }
    $generation = [int]$request.GetType().GetField('Generation', $instance).GetValue($request)
    if ($generation -ne 0) { $result.generation = $generation }
    $frameField = $request.GetType().GetField('Frame', $instance)
    if ($null -ne $frameField) {
        $frame = $frameField.GetValue($request)
        if ($frame -ne [Windows.Forms.Padding]::Empty) { $result.frame = @($frame.Left, $frame.Top, $frame.Right, $frame.Bottom) }
    }
    $focusField = $request.GetType().GetField('Focus', $instance)
    if ($null -ne $focusField -and $null -ne $focusField.GetValue($request)) { $result.focus = [string]$focusField.GetValue($request) }
    return $result
}
$out.arguments = @()
foreach ($case in (ConvertFrom-Json $env:CAR_ARGUMENTS)) {
    $list = [string[]]@($case | ForEach-Object { [string]$_ })
    $out.arguments += ,(Request-Of ($parseArguments.Invoke($null, [object[]]@(,$list))))
}
$reopenArguments = $formType.GetMethod('ReopenArguments', $static)
$out.roundTrip = @()
try {
    foreach ($case in (ConvertFrom-Json $env:CAR_ROUND_TRIPS)) {
        $bounds = [Drawing.Rectangle]::new([int]$case[2], [int]$case[3], [int]$case[4], [int]$case[5])
        $frame = [Windows.Forms.Padding]::new([int]$case[9][0], [int]$case[9][1], [int]$case[9][2], [int]$case[9][3])
        $line = [string]$reopenArguments.Invoke($null, [object[]]@($case[0], $case[1], $bounds, [bool]$case[6], $case[7], [int]$case[8], $frame, $case[10]))
        $split = [string[]]@($line.Split(' '))
        $out.roundTrip += ,@{ line = $line; parsed = (Request-Of ($parseArguments.Invoke($null, [object[]]@(,$split)))) }
    }
} catch { $out.roundTripError = [string]$_ }
$place = $formType.GetMethod('PlaceOnScreen', $static)
$out.place = @()
try {
    foreach ($case in (ConvertFrom-Json $env:CAR_PLACES)) {
        $wanted = [Drawing.Rectangle]::new([int]$case[0], [int]$case[1], [int]$case[2], [int]$case[3])
        $area = [Drawing.Rectangle]::new([int]$case[4], [int]$case[5], [int]$case[6], [int]$case[7])
        $minimum = [Drawing.Size]::new([int]$case[8], [int]$case[9])
        $frame = [Windows.Forms.Padding]::new([int]$case[10], [int]$case[11], [int]$case[12], [int]$case[13])
        $placed = $place.Invoke($null, [object[]]@($wanted, $area, $minimum, $frame))
        $out.place += ,@($placed.X, $placed.Y, $placed.Width, $placed.Height)
    }
} catch { $out.placeError = [string]$_ }
$isListItem = $formType.GetMethod('IsListItem', $static)
$out.kinds = @{}
foreach ($name in (ConvertFrom-Json $env:CAR_BOOLEANS)) { $out.kinds[[string]$name] = [bool]$isListItem.Invoke($null, [object[]]@([string]$name)) }

# ------------------------------------------------------------------ the window, built and never shown
$english = $parse.Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $work 'strings-en.json'), $utf8)))
$schema = $parse.Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $work 'schema.json'), $utf8)))
$current = $parse.Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $work 'settings.json'), $utf8)))
$snapshot = $parse.Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $work 'snapshot.json'), $utf8)))
$nowhere = [string](Join-Path $work 'nowhere')
$bridgeType = $assembly.GetType('CodexAutoResume.Bridge', $true)
$persistentType = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
$three = @($formType.GetConstructors($instance) | Where-Object { $_.GetParameters().Count -eq 3 })[0]
function Invoke-Window($target, [string]$name, [object[]]$arguments) {
    $method = @($formType.GetMethods($instance) | Where-Object { $_.Name -eq $name -and $_.GetParameters().Count -eq $arguments.Count })[0]
    return $method.Invoke($target, $arguments)
}
function Get-Field($target, [string]$name) { return $formType.GetField($name, $instance).GetValue($target) }
function New-Window {
    $once = $bridgeType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere))
    $bridge = $persistentType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere, $once))
    $window = $three.Invoke([object[]]@($bridge, $english, [Drawing.SystemFonts]::MessageBoxFont))
    $formType.GetField('auditing', $instance).SetValue($window, $true)
    $window.TopLevel = $false
    $window.MinimumSize = [Drawing.Size]::Empty
    # The opening size, read from the window: 1000 by 664 since v0.6.5 (632 in v0.6.4, 600 before).
    $window.ClientSize = [Drawing.Size]::new([int]$formType.GetField('OpeningWidth', $static).GetValue($null), [int]$formType.GetField('OpeningHeight', $static).GetValue($null))
    return $window
}
function Walk($control, [string]$path, $seen) {
    foreach ($child in $control.Controls) {
        $name = $child.GetType().Name
        $here = $path + '/' + $name
        $back = $child.BackColor
        $fore = $child.ForeColor
        if ($back.A -eq 255) { $seen[$name + '|back|' + $back.ToArgb()] = $here }
        if ($fore.A -eq 255) { $seen[$name + '|fore|' + $fore.ToArgb()] = $here }
        Walk $child $here $seen
    }
}
$out.window = @{}
foreach ($theme in @('light', 'dark')) {
    $null = $adopt.Invoke($null, [object[]]@([string]$theme))
    $window = New-Window
    $null = Invoke-Window $window 'BuildEditors' @($schema, $current)
    $null = Invoke-Window $window 'ApplySnapshot' @($snapshot)
    $pages = @('overview', 'pending', 'history', 'statistics', 'diagnostics', 'settings')
    foreach ($page in $pages) { $null = Invoke-Window $window 'ShowPage' @([string]$page) }
    $seen = @{}
    $seen[$window.GetType().Name + '|back|' + $window.BackColor.ToArgb()] = 'form'
    $seen[$window.GetType().Name + '|fore|' + $window.ForeColor.ToArgb()] = 'form'
    Walk $window 'form' $seen
    $entry = @{ colours = $seen; editors = @{} }
    $editors = Get-Field $window 'editors'
    foreach ($pair in $editors.GetEnumerator()) {
        $control = $pair.Value
        $record = @{ type = $control.GetType().Name }
        if ($control.GetType().Name -eq 'SoftCheck') {
            $record.box = [bool]$checkType.GetProperty('Box', $instance).GetValue($control, $null)
            $record.role = [string]$control.AccessibleRole
            $record.glyphX = [int]$checkType.GetProperty('Glyph', $instance).GetValue($control, $null).X
        }
        if ($control.GetType().Name -eq 'SoftCombo') {
            $record.items = @($control.Items | ForEach-Object { ,@([string]$_.GetType().GetField('Value', $instance).GetValue($_), [string]$_.ToString()) })
            $record.width = $control.Width
        }
        $entry.editors[[string]$pair.Key] = $record
    }
    # The Appearance section: how many rows are the Theme's, and whether the old "Light" label is there.
    $sections = Get-Field $window 'sections'
    $appearance = $sections['appearance']
    $labels = New-Object Collections.Generic.List[string]
    function Collect($control) { foreach ($child in $control.Controls) { if ($child -is [Windows.Forms.Label]) { $labels.Add([string]$child.Text) }; Collect $child } }
    Collect $appearance
    $entry.appearanceLabels = @($labels)
    # Unsaved edits, and what a Save sends.
    $entry.dirty = @()
    $entry.dirty += [bool](Invoke-Window $window 'Dirty' @())
    $box = $editors['recover_timeout']
    $box.Checked = -not $box.Checked
    $entry.dirty += [bool](Invoke-Window $window 'Dirty' @())
    $box.Checked = -not $box.Checked
    $entry.dirty += [bool](Invoke-Window $window 'Dirty' @())
    $values = Invoke-Window $window 'EditorValues' @()
    $entry.untouched = [string](Invoke-Window $window 'ChangesJson' @($values))
    $themeCombo = $editors['theme']
    $themeCombo.SelectedIndex = ($themeCombo.SelectedIndex + 1) % $themeCombo.Items.Count
    $entry.dirty += [bool](Invoke-Window $window 'Dirty' @())
    $values = Invoke-Window $window 'EditorValues' @()
    $entry.touched = [string](Invoke-Window $window 'ChangesJson' @($values))
    # The panel's own theme (v0.6.6): sent when changed here, left out when put back, followed in place
    # when it changes elsewhere, and left alone while it holds an edit of its own not saved yet.
    $panelCombo = $editors['panel_theme']
    function PanelChoice() { $c = $panelCombo.SelectedItem; if ($c -eq $null) { return '' }; return [string]$c.GetType().GetField('Value', $instance).GetValue($c) }
    function PanelIndex([string]$value) { for ($i = 0; $i -lt $panelCombo.Items.Count; $i++) { $c = $panelCombo.Items[$i]; if ([string]$c.GetType().GetField('Value', $instance).GetValue($c) -eq $value) { return $i } }; return -1 }
    $panel = @{ built = PanelChoice }
    $panelCombo.SelectedIndex = PanelIndex 'dark'
    $panel.sentWhenChanged = [string](Invoke-Window $window 'ChangesJson' @((Invoke-Window $window 'EditorValues' @())))
    $panelCombo.SelectedIndex = PanelIndex $panel.built
    $panel.sentWhenPutBack = [string](Invoke-Window $window 'ChangesJson' @((Invoke-Window $window 'EditorValues' @())))
    # Changed in the panel or by Codex, while the window is open.
    $null = Invoke-Window $window 'FollowPanelTheme' @($parse.Invoke($null, [object[]]@('{"panel_theme": "light"}')))
    $panel.followed = PanelChoice
    $panel.baselineAfter = [string]((Get-Field $window 'baseline')['panel_theme'])
    # And the person puts it back to what the window used to show - which a stale baseline would have dropped.
    $panelCombo.SelectedIndex = PanelIndex $panel.built
    $panel.sentWhenChosenBack = [string](Invoke-Window $window 'ChangesJson' @((Invoke-Window $window 'EditorValues' @())))
    # An unsaved choice of the person's own is not moved by a change elsewhere.
    $null = Invoke-Window $window 'FollowPanelTheme' @($parse.Invoke($null, [object[]]@('{"panel_theme": "system"}')))
    $panel.kept = PanelChoice
    $entry.panel = $panel
    $entry.openedTheme = [string](Get-Field $window 'openedTheme')
    $versionText = Get-Field $window 'versionText'
    $entry.version = @{ fore = [int]$versionText.ForeColor.ToArgb()
                        card = [int]$paletteType.GetField('Card', $static).GetValue($null).ToArgb() }
    $out.window[$theme] = $entry
    $window.Dispose()
}

# ------------------------------------------------------------------ High Contrast, as the window reads it
# Theme.HighContrastOn: Windows' own answer as the window ships, and the probe's own answer from here on - "off", so the
# steps below change the theme on every machine; with High Contrast on here, every one read "contrast" and was skipped.
$contrastInput = $themeType.GetField('HighContrastOn', $static)
$currentOf = $themeType.GetMethod('Current', $static)
$out.contrastInput = @{ default = [string]$contrastInput.GetValue($null).Method.Name }
$contrastInput.SetValue($null, [Said]::Answer($true))
$out.contrastInput.on = @([string]$currentOf.Invoke($null, [object[]]@('light')), [string]$currentOf.Invoke($null, [object[]]@('dark')),
                          [string]$currentOf.Invoke($null, [object[]]@('system')))
$contrastInput.SetValue($null, [Said]::Answer($false))
$out.contrastInput.off = @([string]$currentOf.Invoke($null, [object[]]@('light')), [string]$currentOf.Invoke($null, [object[]]@('dark')))

# ------------------------------------------------------------------ the reopen check, while an action is on its way
# Not audited, so CheckReopen decides for real. An action is on its way (busy), so where it would reopen it waits,
# as it does while minimized or under a dialog, and never starts a new process - every step checks that first.
$null = $adopt.Invoke($null, [object[]]@('light'))
$window = New-Window
$formType.GetField('auditing', $instance).SetValue($window, $false)
$null = Invoke-Window $window 'BuildEditors' @($schema, $current)
$formType.GetField('settingsRead', $instance).SetValue($window, $true)
$formType.GetField('busy', $instance).SetValue($window, 1)
$formType.GetField('openedLanguage', $instance).SetValue($window, 'en')
$formType.GetField('openedTheme', $instance).SetValue($window, 'light')
$note = Get-Field $window 'reopenNote'
$ownState = [Windows.Forms.Control].GetMethod('GetState', $instance)
function Step([string]$what) {
    if ([int](Get-Field $window 'busy') -ne 1) { throw 'nothing is on its way; a reopen would start a process' }
    return @{ step = $what; recheck = [bool](Get-Field $window 'recheck'); reopening = [bool](Get-Field $window 'reopening')
              note = [bool]$ownState.Invoke($note, [object[]]@(2)); text = [string]$note.Text
              openedTheme = [string](Get-Field $window 'openedTheme'); openedLanguage = [string](Get-Field $window 'openedLanguage') }
}
function Stored([string]$language, [string]$theme) {
    return $parse.Invoke($null, [object[]]@('{"interface_language": "' + $language + '", "theme": "' + $theme + '"}'))
}
$steps = @()
$steps += ,(Step 'opened')
$null = Invoke-Window $window 'Observe' @((Stored 'en' 'light'), $false)
$steps += ,(Step 'unchanged')
$null = Invoke-Window $window 'Observe' @((Stored 'en' 'dark'), $false)
$steps += ,(Step 'theme changed, nothing unsaved')
$editors = Get-Field $window 'editors'
$box = $editors['recover_timeout']
$box.Checked = -not $box.Checked
$null = Invoke-Window $window 'CheckReopen' @($false)
$steps += ,(Step 'an edit')
$box.Checked = -not $box.Checked
$null = Invoke-Window $window 'CheckReopen' @($false)
$steps += ,(Step 'the edit put back')
$null = Invoke-Window $window 'Observe' @((Stored 'en' 'light'), $false)
$steps += ,(Step 'theme changed back')
$box.Checked = -not $box.Checked
$null = Invoke-Window $window 'Observe' @((Stored 'ko' 'light'), $false)
$steps += ,(Step 'language changed under an edit')
$box.Checked = -not $box.Checked
$null = Invoke-Window $window 'Observe' @((Stored 'en' 'light'), $false)
$steps += ,(Step 'all back')
$request = Get-Field $window 'request'
$request.GetType().GetField('Generation', $instance).SetValue($request, 2)
$null = Invoke-Window $window 'Observe' @((Stored 'en' 'dark'), $true)
$steps += ,(Step 'first read of a second reopen in a row')
$null = Invoke-Window $window 'Observe' @((Stored 'en' 'dark'), $false)
$steps += ,(Step 'read again')
$out.checks = $steps
$out.highContrast = [bool]$themeType.GetMethod('ContrastOn', $static).Invoke($null, $null)
$window.Dispose()

# ------------------------------------------------------------------ the handover's two endings
# How the wait for the new window ends, with stand-ins for its process; and what this window does with each ending.
# No process is started: a reopen is never begun here, only ended.
$out.handover = @{}
try {
    $await = $formType.GetMethod('AwaitWindow', $static)
    function Await-With([int]$windowAt, [int]$exitAt, [int]$milliseconds) {
        $count = @{ polls = 0 }
        $hasWindow = [Func[bool]]({ $count.polls++; ($windowAt -gt 0) -and ($count.polls -ge $windowAt) }.GetNewClosure())
        $hasExited = [Func[bool]]({ ($exitAt -gt 0) -and ($count.polls -ge $exitAt) }.GetNewClosure())
        $watch = [Diagnostics.Stopwatch]::StartNew()
        $shown = [bool]$await.Invoke($null, [object[]]@($hasWindow, $hasExited, $milliseconds, 5))
        return @{ shown = $shown; polls = [int]$count.polls; ms = [int]$watch.ElapsedMilliseconds }
    }
    $out.handover.await = @{ window = (Await-With 3 0 5000); exited = (Await-With 0 2 5000)
                             both = (Await-With 1 1 5000); neither = (Await-With 0 0 150) }

    $null = $adopt.Invoke($null, [object[]]@('light'))
    $stay = New-Window
    $formType.GetField('auditing', $instance).SetValue($stay, $false)
    $null = Invoke-Window $stay 'BuildEditors' @($schema, $current)
    $formType.GetField('settingsRead', $instance).SetValue($stay, $true)
    # An action on its way, so a decision to reopen waits (recheck) rather than starting anything.
    $formType.GetField('busy', $instance).SetValue($stay, 1)
    $formType.GetField('openedLanguage', $instance).SetValue($stay, 'en')
    $formType.GetField('openedTheme', $instance).SetValue($stay, 'light')
    $held = @{ runs = 0 }
    $work1 = [Windows.Forms.MethodInvoker]({ $held.runs++ }.GetNewClosure())
    $null = Invoke-Window $stay 'HoldForReopen' @($work1)
    $out.handover.heldWhileStaying = [int]$held.runs
    # As Reopen leaves it once the new process has started: for English and dark.
    $formType.GetField('reopening', $instance).SetValue($stay, $true)
    $formType.GetField('reopenLanguage', $instance).SetValue($stay, 'en')
    $formType.GetField('reopenTheme', $instance).SetValue($stay, 'dark')
    $null = Invoke-Window $stay 'HoldForReopen' @($work1)
    $null = Invoke-Window $stay 'HoldForReopen' @($work1)
    $out.handover.heldWhileReopening = [int]$held.runs
    # The new process ended before it showed a window.
    $null = Invoke-Window $stay 'FinishReopen' @($false)
    $clock = Get-Field $stay 'clock'
    $out.handover.gone = @{ disposed = [bool]$stay.IsDisposed; reopening = [bool](Get-Field $stay 'reopening')
                            held = [int]$held.runs; heldLeft = ($null -ne (Get-Field $stay 'heldForReopen'))
                            clock = (($null -ne $clock) -and [bool]$clock.Enabled) }
    $after = @()
    foreach ($case in @(@('what it could not reopen in', 'en', 'dark'), @('something else', 'ko', 'dark'),
                        @('what it shows', 'en', 'light'), @('what it could not reopen in, again', 'en', 'dark'))) {
        $null = Invoke-Window $stay 'Observe' @((Stored $case[1] $case[2]), $false)
        $after += ,@{ step = [string]$case[0]; recheck = [bool](Get-Field $stay 'recheck'); reopening = [bool](Get-Field $stay 'reopening')
                      note = [bool]$ownState.Invoke((Get-Field $stay 'reopenNote'), [object[]]@(2)) }
    }
    $out.handover.after = $after
    if ($null -ne $clock) { $clock.Stop() }
    $stay.Dispose()
    # The new window came up.
    $go = New-Window
    $formType.GetField('auditing', $instance).SetValue($go, $false)
    $formType.GetField('reopening', $instance).SetValue($go, $true)
    $null = Invoke-Window $go 'FinishReopen' @($true)
    $out.handover.shown = @{ disposed = [bool]$go.IsDisposed }
} catch { $out.handover.error = [string]$_ + ' ' + [string]$_.ScriptStackTrace }

# ------------------------------------------------------------------ where the keyboard was, and is again
$out.focus = @{}
try {
    $null = $adopt.Invoke($null, [object[]]@('light'))
    $window = New-Window
    $null = Invoke-Window $window 'BuildEditors' @($schema, $current)
    $null = Invoke-Window $window 'ShowPage' @('settings')
    $null = Invoke-Window $window 'ShowSection' @('appearance')
    $editors = Get-Field $window 'editors'
    $nav = Get-Field $window 'navButtons'
    $tabs = Get-Field $window 'sectionButtons'
    $spinName = [string]@($editors.Keys | Where-Object { $editors[$_] -is [Windows.Forms.NumericUpDown] } | Sort-Object)[0]
    $spin = $editors[$spinName]
    $edit = @($spin.Controls | Where-Object { $_ -is [Windows.Forms.TextBoxBase] })[0]
    $cases = @(
        @('save', (Get-Field $window 'saveButton'), (Get-Field $window 'saveButton')),
        @('restore', (Get-Field $window 'restoreButton'), (Get-Field $window 'restoreButton')),
        @('close', (Get-Field $window 'closeButton'), (Get-Field $window 'closeButton')),
        @('page.history', $nav['history'], $nav['history']),
        @('section.appearance', $tabs['appearance'], $tabs['appearance']),
        @('setting.theme', $editors['theme'], $editors['theme']),
        @('setting.recover_timeout', $editors['recover_timeout'], $editors['recover_timeout']),
        @('setting.__startup', $editors['__startup'], $editors['__startup']),
        @(('setting.' + $spinName), $edit, $spin)
    )
    $out.focus.names = @()
    foreach ($case in $cases) {
        $window.ActiveControl = $case[1]
        $name = [string](Invoke-Window $window 'FocusName' @())
        $target = Invoke-Window $window 'FocusTarget' @($name)
        $out.focus.names += ,@{ expected = [string]$case[0]; name = $name; target = [object]::ReferenceEquals($target, $case[2]) }
    }
    $window.ActiveControl = $null
    $out.focus.nothingOnSettings = [string](Invoke-Window $window 'FocusName' @())
    $null = Invoke-Window $window 'ShowPage' @('pending')
    $window.ActiveControl = $null
    $out.focus.nothingOnPending = [string](Invoke-Window $window 'FocusName' @())
    $window.Dispose()
    function Restore-Focus([string]$page, [string]$section, $name, [bool]$moved) {
        $w = New-Window
        $request = Get-Field $w 'request'
        $request.GetType().GetField('Focus', $instance).SetValue($request, $name)
        $formType.GetField('currentSection', $instance).SetValue($w, $section)
        $null = Invoke-Window $w 'ShowPage' @($page)
        $null = Invoke-Window $w 'FocusInterim' @()
        $interim = if ($null -eq $w.ActiveControl) { '' } else { [string](Invoke-Window $w 'FocusName' @()) }
        if ($moved) { $w.ActiveControl = (Get-Field $w 'navButtons')['overview'] }
        $null = Invoke-Window $w 'BuildEditors' @($schema, $current)
        $null = Invoke-Window $w 'FocusPending' @()
        $final = if ($null -eq $w.ActiveControl) { '' } else { [string](Invoke-Window $w 'FocusName' @()) }
        $w.Dispose()
        return @{ interim = $interim; final = $final }
    }
    $out.focus.restored = @{
        theme = (Restore-Focus 'settings' 'appearance' 'setting.theme' $false)
        save = (Restore-Focus 'settings' 'appearance' 'save' $false)
        moved = (Restore-Focus 'settings' 'appearance' 'setting.theme' $true)
        pending = (Restore-Focus 'pending' 'general' 'page.pending' $false)
        missing = (Restore-Focus 'settings' 'general' 'setting.nowhere' $false)
        hiddenSave = (Restore-Focus 'history' 'general' 'save' $false)
        otherSection = (Restore-Focus 'settings' 'recovery' 'setting.theme' $false)
        none = (Restore-Focus 'settings' 'appearance' $null $false)
    }
} catch { $out.focus.error = [string]$_ + ' ' + [string]$_.ScriptStackTrace }

# ------------------------------------------------------------------ the reopen note, whole in every language
$out.note = @{}
try {
    $null = $adopt.Invoke($null, [object[]]@('light'))
    $materialise = $formType.GetMethod('Materialise', $static)
    $flags = [Windows.Forms.TextFormatFlags]'WordBreak, TextBoxControl, NoPrefix'
    foreach ($locale in (ConvertFrom-Json $env:CAR_LOCALES)) {
        $catalog = $parse.Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $work ('strings-' + $locale + '.json')), $utf8)))
        $out.note[[string]$locale] = @{}
        foreach ($width in (ConvertFrom-Json $env:CAR_NOTE_WIDTHS)) {
            $once = $bridgeType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere))
            $bridge = $persistentType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere, $once))
            $w = $three.Invoke([object[]]@($bridge, $catalog, [Drawing.SystemFonts]::MessageBoxFont))
            $formType.GetField('auditing', $instance).SetValue($w, $true)
            $w.TopLevel = $false
            $w.MinimumSize = [Drawing.Size]::Empty
            $w.ClientSize = [Drawing.Size]::new([int][Math]::Round($width * $systemScale), [int][Math]::Round([int]$formType.GetField('OpeningHeight', $static).GetValue($null) * $systemScale))
            $null = Invoke-Window $w 'BuildEditors' @($schema, $current)
            $null = Invoke-Window $w 'ShowPage' @('settings')
            $null = Invoke-Window $w 'ShowReopenNote' @($true)
            $null = $materialise.Invoke($null, [object[]]@($w))
            $w.PerformLayout()
            $note = Get-Field $w 'reopenNote'
            $card = Get-Field $w 'savebar'
            $row = (Get-Field $w 'saveButton').Parent
            $needed = [Windows.Forms.TextRenderer]::MeasureText($note.Text, $note.Font, [Drawing.Size]::new($note.ClientSize.Width, [int]::MaxValue), $flags)
            $out.note[[string]$locale][[string]$width] = @{
                text = [string]$note.Text; width = $note.ClientSize.Width; height = $note.ClientSize.Height; needed = $needed.Height
                noteRight = $note.Right; rowLeft = $row.Left; rowTop = $row.Top; rowBottom = $row.Bottom
                cardHeight = $card.ClientSize.Height; cardTop = $card.Padding.Top; cardBottom = $card.Padding.Bottom }
            $w.Dispose()
        }
    }
} catch { $out.note.error = [string]$_ + ' ' + [string]$_.ScriptStackTrace }

# ------------------------------------------------------------------ High Contrast, as a change's own message finds it
# .NET keeps SystemInformation.HighContrast from its first read until its hidden window has handled the change, which
# is after a window's own WM_SETTINGCHANGE has been. Stood in for by leaving the opposite answer in that cache: the
# theme is still what Windows says now.
$out.staleCache = @{}
# Windows' own answer again - its own method, whatever the input held - for this is about what Windows says.
$contrastInput.SetValue($null, [Delegate]::CreateDelegate([Func[bool]], $themeType.GetMethod('HighContrast', $static)))
try {
    $info = [Windows.Forms.SystemInformation]
    $cached = $info.GetField('highContrast', $static)
    $dirty = $info.GetField('systemEventsDirty', $static)
    $real = [bool][Windows.Forms.SystemInformation]::HighContrast
    $out.staleCache.found = ($null -ne $cached) -and ($null -ne $dirty)
    if ($out.staleCache.found) {
        $cached.SetValue($null, -not $real)
        $dirty.SetValue($null, $false)
        $out.staleCache.cached = [bool][Windows.Forms.SystemInformation]::HighContrast
        $currentOf = $themeType.GetMethod('Current', $static)
        $out.staleCache.light = [string]$currentOf.Invoke($null, [object[]]@('light'))
        $out.staleCache.dark = [string]$currentOf.Invoke($null, [object[]]@('dark'))
        $dirty.SetValue($null, $true)
    }
} catch { $out.staleCache.error = [string]$_ }
[IO.File]::WriteAllText((Join-Path $work 'result.json'), ($out | ConvertTo-Json -Depth 12 -Compress), $utf8)
"""

SCALES = (1.0, 1.5, 2.0)
BODIES = {"card": (240, 160, 40), "control": (160, 34, 16), "inset": (280, 35, 0)}
# Points in the 60 x 60 bitmap: the box's outer corner is at (10, 10), 36 px square at scale 2.
BOX_POINTS = {
    "edge": (28, 10),         # the middle of the top hairline, 2 px thick
    "fill": (40, 40),         # inside, away from the mark and the edges (a checked box's fill)
    "centre": (28, 28),       # the middle of the well
    "near_top": (28, 12),     # just inside the top hairline, where the well's shadow falls
    "mark": (31, 27),         # on the long arm of the mark, fully covered by its 4 px stroke
    "outside": (5, 5),        # the ground around the box
}
# (page, section, x, y, width, height, maximized, theme, generation, invisible frame, focus)
ROUND_TRIPS = [
    ("settings", "appearance", 120, 80, 1500, 900, False, "dark", 1, (7, 0, 7, 7), "save"),
    ("pending", "general", -1920, -8, 1000, 600, True, "system", 2, (11, 0, 11, 11), "page.pending"),
    ("overview", "nowhere", 0, 0, 1000, 600, False, "Dark", 0, (0, 0, 0, 0), "setting.theme"),
    ("nowhere", "continuation", 99999, 0, 1000, 600, False, "light", 12, (100, 0, 7, 7), "Save"),
]
# (wanted x, y, w, h, area x, y, w, h, minimum w, h, invisible frame left, top, right, bottom) -> placed
PLACES = [
    ((100, 100, 1000, 600, 0, 0, 1920, 1040, 800, 420, 0, 0, 0, 0), (100, 100, 1000, 600)),
    ((1500, 800, 1000, 600, 0, 0, 1920, 1040, 800, 420, 0, 0, 0, 0), (920, 440, 1000, 600)),
    ((-500, -50, 1000, 600, 0, 0, 1920, 1040, 800, 420, 0, 0, 0, 0), (0, 0, 1000, 600)),
    ((100, 100, 3000, 2000, 0, 0, 1920, 1040, 800, 420, 0, 0, 0, 0), (0, 0, 1920, 1040)),
    ((100, 100, 300, 200, 0, 0, 1920, 1040, 800, 420, 0, 0, 0, 0), (100, 100, 800, 420)),
    ((-1800, 50, 1000, 600, -1920, 0, 1920, 1080, 800, 420, 0, 0, 0, 0), (-1800, 50, 1000, 600)),
    # Snapped to the left half at 100%: the frame one sees is flush with the work area, and the bounds reach 7 px
    # past it on the left, right and bottom. It stays exactly where it was.
    ((-7, 0, 974, 1047, 0, 0, 1920, 1040, 800, 420, 7, 0, 7, 7), (-7, 0, 974, 1047)),
    # A wider border, snapped to the right half.
    ((949, 0, 982, 1051, 0, 0, 1920, 1040, 800, 420, 11, 0, 11, 11), (949, 0, 982, 1051)),
    # As measured live at 150% on a 3840 by 2088 work area: a 9 px border, flush left, top and bottom.
    ((-9, 0, 1522, 2097, 0, 0, 3840, 2088, 1200, 630, 9, 0, 9, 9), (-9, 0, 1522, 2097)),
    # Dragged flush against the left edge and the bottom.
    ((-7, 433, 1014, 614, 0, 0, 1920, 1040, 800, 420, 7, 0, 7, 7), (-7, 433, 1014, 614)),
    # Larger than the area even as seen: the frame one sees becomes the area.
    ((-7, -7, 1934, 1054, 0, 0, 1920, 1040, 800, 420, 7, 0, 7, 7), (-7, 0, 1934, 1047)),
    # Past the edge by more than the invisible border: back until the frame one sees is on the screen.
    ((-300, 0, 974, 600, 0, 0, 1920, 1040, 800, 420, 7, 0, 7, 7), (-7, 0, 974, 600)),
    # Smaller than the minimum, which is the bounds', frame and all.
    ((100, 100, 300, 200, 0, 0, 1920, 1040, 800, 420, 7, 0, 7, 7), (100, 100, 800, 420)),
]


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class WindowThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_gui_layout import fullest_snapshot
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = compile_window(work)
        reply = {"ok": True, "language": "en", "strings": l10n.catalog("en"), "endonyms": dict(l10n.ENDONYMS),
                 "preference": "en", "system_language": "en"}
        (work / "strings-en.json").write_text(json.dumps(reply, ensure_ascii=False), encoding="utf-8")
        for locale in l10n.LOCALES:
            (work / ("strings-%s.json" % locale)).write_text(json.dumps(
                dict(reply, language=locale, strings=l10n.catalog(locale), preference=locale, system_language=locale),
                ensure_ascii=False), encoding="utf-8")
        cls.work = work
        for name, raw in STORED.items():
            config = work / ("stored-" + name) / "config"
            config.mkdir(parents=True)
            if raw is not None:
                (config / "settings.json").write_bytes(raw)
        (work / "schema.json").write_text(json.dumps(settings.describe(), ensure_ascii=False), encoding="utf-8")
        (work / "settings.json").write_text(json.dumps(settings.defaults(), ensure_ascii=False), encoding="utf-8")
        (work / "snapshot.json").write_text(json.dumps(fullest_snapshot(time.time()), ensure_ascii=False), encoding="utf-8")
        probe = work / "probe.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        cls.booleans = [entry["name"] for entry in settings.describe() if entry["type"] == "boolean"] + ["__startup"]
        resolve = [[preference, mode, contrast] for preference in PREFERENCES for mode in APP_MODES
                   for contrast in (False, True)]
        cls.resolve_cases = resolve
        cls.result = subprocess.run(
            [str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
            env=dict(os.environ, CAR_EXE=str(exe), CAR_WORK=str(work), CAR_RESOLVE=json.dumps(resolve),
                     CAR_STORED=json.dumps(list(STORED)), CAR_LOCALES=json.dumps(list(l10n.LOCALES)),
                     CAR_NOTE_WIDTHS=json.dumps(NOTE_WIDTHS),
                     CAR_NAMES=json.dumps(list(TOKENS)), CAR_SCALES=json.dumps(SCALES), CAR_BODIES=json.dumps(BODIES),
                     CAR_BOX_POINTS=json.dumps(BOX_POINTS),
                     CAR_DECISIONS=json.dumps([list(case) for case, _ in DECISIONS]),
                     CAR_ARGUMENTS=json.dumps([case for case, _ in ARGUMENTS]),
                     CAR_ROUND_TRIPS=json.dumps([list(case) for case in ROUND_TRIPS]),
                     CAR_PLACES=json.dumps([list(case) for case, _ in PLACES]),
                     CAR_BOOLEANS=json.dumps(cls.booleans)))
        answer = work / "result.json"
        cls.answer = (json.loads(answer.read_text(encoding="utf-8-sig"))
                      if cls.result.returncode == 0 and answer.is_file() else {})

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-3000:])

    # ------------------------------------------------------------------ resolution

    def test_the_theme_is_the_setting_then_windows_app_mode_and_high_contrast_wins(self):
        for (preference, mode, contrast), got in zip(self.resolve_cases, self.answer["resolve"]):
            if contrast:
                expected = "contrast"
            elif preference in ("light", "dark"):
                expected = preference
            else:
                # "system", and anything that is not exactly light or dark, which the settings layer
                # reads as "system": dark only when Windows' AppsUseLightTheme is 0.
                expected = "dark" if mode == 0 else "light"
            with self.subTest(preference=preference, app_mode=mode, high_contrast=contrast):
                self.assertEqual(got, expected)

    def test_the_app_mode_is_read_where_windows_keeps_it(self):
        try:
            import winreg
        except ImportError:
            self.skipTest("not Windows")
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                value, kind = winreg.QueryValueEx(key, "AppsUseLightTheme")
                expected = value if kind == winreg.REG_DWORD else -1
        except OSError:
            expected = -1
        self.assertEqual(self.answer["apps"], expected)

    def test_the_stored_theme_is_read_as_the_settings_layer_reads_it(self):
        """Before the first control exists, from the settings file, as settings.load reads the same file for
        the bridge. A file the two read differently opened the window in one theme and had its first settings
        read reopen it in the other, every time it was opened."""
        for name in STORED:
            path = self.work / ("stored-" + name) / "config" / "settings.json"
            expected = settings.theme_preference(settings.load(path))
            with self.subTest(name):
                self.assertEqual(self.answer["stored"][name], expected)
        # Spelled out: a file the settings layer does not read is its defaults, "system", even where it says dark.
        for name in ("bom", "not_utf8", "trailing", "too_large", "damaged", "missing"):
            with self.subTest(refused=name):
                self.assertEqual(self.answer["stored"][name], "system")
        for name, theme in (("dark", "dark"), ("light", "light"), ("whitespace", "light"), ("versioned", "dark")):
            with self.subTest(read=name):
                self.assertEqual(self.answer["stored"][name], theme)

    def test_high_contrast_as_the_window_reads_it_wins_over_every_preference(self):
        """What Theme.HighContrastOn answers - Windows' own answer as the window ships (ThemeSourceRuleTests), the
        probe's here - wins over every preference."""
        contrast = self.answer["contrastInput"]
        self.assertEqual(contrast["on"], ["contrast", "contrast", "contrast"])
        self.assertEqual(contrast["off"], ["light", "dark"])

    def test_high_contrast_is_asked_of_windows_not_of_a_cache_the_change_has_not_reached(self):
        """Turning High Contrast on reaches the window's WM_SETTINGCHANGE before .NET's own copy of the setting
        is refreshed, so a theme read from SystemInformation.HighContrast there was the old one, and the window
        kept its colours under High Contrast."""
        stale = self.answer["staleCache"]
        self.assertNotIn("error", stale)
        if not stale.get("found"):
            self.skipTest("this .NET keeps no High Contrast cache to stand a stale value in")
        real = system_high_contrast()
        self.assertEqual(stale["cached"], not real, "the stale value did not take, so this proves nothing")
        self.assertEqual(stale["light"], "contrast" if real else "light")
        self.assertEqual(stale["dark"], "contrast" if real else "dark")

    # ------------------------------------------------------------------ the palette

    def test_each_theme_draws_from_its_own_palette(self):
        for theme, tokens in (("light", brand.LIGHT), ("dark", brand.DARK), ("bogus", brand.LIGHT)):
            entry = self.answer["palette"][theme]
            name = "light" if theme == "bogus" else theme
            with self.subTest(theme):
                self.assertEqual(entry["theme"], name)
                self.assertFalse(entry["contrast"])
                self.assertEqual(entry["dark"], name == "dark")
                for field, token in TOKENS.items():
                    expected = brand.card_ground(name) if token is None else tokens[token]
                    self.assertEqual(entry["colours"][field][0], argb(expected), field)
                    self.assertFalse(entry["colours"][field][2], field + " is a system colour outside High Contrast")

    def test_the_dark_card_is_lifted_off_its_surface_as_the_panels_is(self):
        dark = self.answer["palette"]["dark"]["colours"]
        self.assertEqual(dark["Card"][0], argb(brand.card_ground("dark")))
        self.assertNotEqual(dark["Card"][0], dark["Surface"][0])
        light = self.answer["palette"]["light"]["colours"]
        self.assertEqual(light["Card"][0], light["Surface"][0])

    def test_high_contrast_is_system_colours_whatever_the_theme(self):
        entry = self.answer["palette"]["contrast"]
        self.assertEqual(entry["theme"], "contrast")
        self.assertTrue(entry["contrast"])
        self.assertFalse(entry["dark"])
        for field, system in SYSTEM.items():
            with self.subTest(field):
                self.assertTrue(entry["colours"][field][2])
                self.assertEqual(entry["colours"][field][1], system)

    # ------------------------------------------------------------------ the dark elevation

    def test_the_dark_shadows_are_the_panels_recipes(self):
        for scale in SCALES:
            for recipe in ("card", "control", "inset"):
                drawn = self.answer["elevation"]["dark"]["%.1f" % scale][recipe]
                values = drawn["profile"]
                shadows = brand.SHADOWS["dark"][recipe]
                self.assertEqual(len(values) % (4 * len(shadows)), 0)
                samples = len(values) // (4 * len(shadows))
                for index, shadow in enumerate(shadows):
                    for side_index, side in enumerate(("left", "top", "right", "bottom")):
                        for i in range(samples):
                            expected = brand.shadow_alpha(shadow, i + 0.5, side, scale)
                            got = values[(index * 4 + side_index) * samples + i]
                            with self.subTest(scale=scale, recipe=recipe, shadow=index, side=side, d=i + 0.5):
                                self.assertLessEqual(abs(got - expected), 3 / 255, "%.4f against %.4f" % (got, expected))
                with self.subTest(scale=scale, recipe=recipe, what="reach"):
                    self.assertEqual(tuple(drawn["reach"]), brand.reach(recipe, "dark", scale))

    def test_a_dark_body_is_composited_as_the_panel_model_has_it(self):
        """A card on the dark canvas with its one-pixel top light inside, a control on a card, a well."""
        ground = brand.card_ground("dark")
        for scale in SCALES:
            hairline = max(1, int(scale + 1e-6))
            for recipe in ("card", "control", "inset"):
                drawn = self.answer["elevation"]["dark"]["%.1f" % scale][recipe]
                width, height, margin = drawn["width"], drawn["height"], drawn["margin"]
                row, column = drawn["row"], drawn["column"]
                checks = []
                if recipe != "inset":
                    outside = "canvas" if recipe == "card" else ground
                    for i in range(margin):
                        checks.append(("left", i, row[margin - 1 - i], outside, False))
                        checks.append(("right", i, row[margin + width + i], outside, False))
                        checks.append(("top", i, column[margin - 1 - i], outside, False))
                        checks.append(("bottom", i, column[margin + height + i], outside, False))
                if recipe != "control":
                    fill = ground if recipe == "card" else "inset"
                    for i in range(int(4 * scale)):
                        checks.append(("top", i, column[margin + hairline + i], fill, True))
                        checks.append(("bottom", i, column[margin + height - hairline - 1 - i], fill, True))
                        checks.append(("left", i, row[margin + hairline + i], fill, True))
                for side, i, pixel, ground_colour, inside in checks:
                    expected = brand.elevation_colour(recipe, side, i + 0.5, ground_colour, theme="dark",
                                                      scale=scale, inside=inside)
                    with self.subTest(scale=scale, recipe=recipe, side=side, d=i + 0.5, inside=inside):
                        for got, want in zip(channels(pixel), expected):
                            self.assertLessEqual(abs(got - want), 3, "%s against %s" % (
                                channels(pixel), tuple(round(v, 1) for v in expected)))

    def test_the_light_elevation_is_unchanged_by_the_dark_one(self):
        """Adopting dark and then light again draws light's recipes, reach and all."""
        for scale in SCALES:
            for recipe in ("card", "control", "inset"):
                drawn = self.answer["elevation"]["light"]["%.1f" % scale][recipe]
                with self.subTest(scale=scale, recipe=recipe):
                    self.assertEqual(tuple(drawn["reach"]), brand.reach(recipe, "light", scale))
                    self.assertEqual(len(drawn["profile"]) % (4 * len(brand.SHADOWS["light"][recipe])), 0)

    # ------------------------------------------------------------------ the check box

    def assertNear(self, pixel, colour, levels, message=""):
        got, want = channels(pixel), brand.rgb(colour) if isinstance(colour, str) else channels(colour)
        self.assertLessEqual(max(abs(a - b) for a, b in zip(got, want)), levels,
                             "%s: %s against %s" % (message, got, want))

    def test_the_check_box_is_brands_in_light_and_dark(self):
        for theme in ("light", "dark"):
            for state in ("off", "on", "off_disabled", "on_disabled"):
                checked, enabled = state.startswith("on"), not state.endswith("disabled")
                colours = brand.check_box(checked, enabled, theme)
                pick = self.answer["box"][theme]["states"][state]
                with self.subTest(theme=theme, state=state):
                    self.assertNear(pick["outside"], self.answer["box"][theme]["ground"], 0, "the ground")
                    self.assertNear(pick["edge"], colours["edge"], 3, "the hairline")
                    if colours["well"]:
                        # The sunken well: its fill in the middle, and its shadow along the inside of the top.
                        self.assertNear(pick["centre"], colours["fill"], 6, "the well's middle")
                        self.assertGreater(max(abs(a - b) for a, b in zip(channels(pick["near_top"]), brand.rgb(colours["fill"]))),
                                           4, "no inset shadow inside the unchecked box")
                    else:
                        self.assertNear(pick["fill"], colours["fill"], 3, "the fill")
                        self.assertNear(pick["near_top"], colours["fill"], 3, "a flat box has no shadow")
                    if colours["mark"]:
                        self.assertNear(pick["mark"], colours["mark"], 8, "the mark")
                    else:
                        self.assertNear(pick["mark"], colours["fill"], 8 if colours["well"] else 3, "no mark")

    def test_the_check_box_in_high_contrast_is_system_colours_with_no_shadow(self):
        system = self.answer["boxSystem"]
        for state in ("off", "on", "off_disabled", "on_disabled"):
            checked, enabled = state.startswith("on"), not state.endswith("disabled")
            colours = brand.check_box_system(checked, enabled)
            pick = self.answer["box"]["contrast"]["states"][state]
            with self.subTest(state=state):
                self.assertNear(pick["edge"], system[colours["edge"]], 3, "the edge")
                self.assertNear(pick["fill"], system[colours["fill"]], 3, "the fill")
                self.assertNear(pick["near_top"], system[colours["fill"]], 3, "no shadow in High Contrast")
                if colours["mark"]:
                    self.assertNear(pick["mark"], system[colours["mark"]], 8, "the mark")

    def test_a_setting_is_a_check_box_exactly_when_it_picks_items_of_a_list(self):
        for name in self.booleans:
            expected = name.startswith("recover_") or name.startswith("notify_")
            with self.subTest(name):
                self.assertEqual(self.answer["kinds"][name], expected)
        # Switches: what runs, on or off.
        for name in ("notifications", "show_tray", "reduce_motion", "__startup"):
            self.assertFalse(self.answer["kinds"][name], name)

    def test_the_built_window_draws_each_setting_as_its_kind_with_the_glyph_on_the_left(self):
        for theme in ("light", "dark"):
            editors = self.answer["window"][theme]["editors"]
            checks = {name: record for name, record in editors.items() if record["type"] == "SoftCheck"}
            self.assertEqual(set(checks), set(self.booleans), "every true-or-false setting the window shows")
            for name, record in checks.items():
                with self.subTest(theme=theme, name=name):
                    self.assertEqual(record["box"], name.startswith("recover_") or name.startswith("notify_"))
                    self.assertEqual(record["role"], "CheckButton")
                    self.assertEqual(record["glyphX"], 0, "the box or switch sits left of its words")

    # ------------------------------------------------------------------ the Theme setting on the page

    def test_the_theme_is_a_drop_down_of_its_three_choices_in_their_own_words(self):
        english = l10n.catalog("en")
        for theme in ("light", "dark"):
            entry = self.answer["window"][theme]
            combo = entry["editors"]["theme"]
            with self.subTest(theme):
                self.assertEqual(combo["type"], "SoftCombo")
                self.assertEqual([value for value, _ in combo["items"]], list(settings.THEMES))
                self.assertEqual([label for _, label in combo["items"]],
                                 [english["choice.theme." + value] for value in settings.THEMES])
                labels = entry["appearanceLabels"]
                self.assertEqual(labels.count(english["field.theme"]), 1, "one Theme row, not the old read-only one as well")
                self.assertNotIn(english["choice.theme.light"], labels, "the fixed 'Light' label is gone")
                self.assertIn(english["help.theme"], labels)
                self.assertEqual(entry["openedTheme"], theme)

    def test_a_save_sends_the_language_and_theme_only_when_they_were_changed_here(self):
        """So a save of something else never puts back a language or theme chosen elsewhere meanwhile."""
        for theme in ("light", "dark"):
            entry = self.answer["window"][theme]
            untouched, touched = json.loads(entry["untouched"]), json.loads(entry["touched"])
            with self.subTest(theme):
                self.assertNotIn("theme", untouched)
                self.assertNotIn("interface_language", untouched)
                self.assertIn("recover_timeout", untouched, "everything else is still sent")
                self.assertIn(touched["theme"], settings.THEMES)
                self.assertNotIn("interface_language", touched)

    def test_the_panels_own_theme_is_sent_only_when_changed_and_follows_a_change_made_elsewhere(self):
        """v0.6.6. The window is not drawn in the panel's theme, so a change of it in the panel or by Codex
        reopens nothing - and until it followed in place, the drop-down kept showing the old choice, and a
        Save, which leaves out a value still equal to the page's baseline, could not even write the choice it
        showed. Found by review before release."""
        for theme in ("light", "dark"):
            panel = self.answer["window"][theme]["panel"]
            with self.subTest(theme):
                self.assertEqual(panel["built"], "same", "an untouched setting shows its default")
                self.assertEqual(json.loads(panel["sentWhenChanged"]).get("panel_theme"), "dark",
                                 "chosen here, it is sent")
                self.assertNotIn("panel_theme", json.loads(panel["sentWhenPutBack"]),
                                 "put back to what the page was built with, it is not")
                self.assertEqual(panel["followed"], "light", "changed elsewhere, the drop-down shows it")
                self.assertEqual(panel["baselineAfter"], '"light"', "and a Save measures from it")
                self.assertEqual(json.loads(panel["sentWhenChosenBack"]).get("panel_theme"), "same",
                                 "so choosing what the window used to show is a change, and is sent")
                self.assertEqual(panel["kept"], "same",
                                 "an unsaved choice of the person's own is not moved by a change elsewhere")

    def test_unsaved_edits_are_what_differs_from_the_page_as_built(self):
        for theme in ("light", "dark"):
            with self.subTest(theme):
                # built, one box turned, turned back, the theme changed
                self.assertEqual(self.answer["window"][theme]["dirty"], [False, True, False, True])

    def test_the_version_in_the_save_card_is_readable_text(self):
        """People are asked for it in a bug report, so it is drawn as secondary text, at text's contrast on its
        card - not in the idle fill, 2.41:1 in light and 3.10:1 in dark."""
        for theme, tokens in (("light", brand.LIGHT), ("dark", brand.DARK)):
            version = self.answer["window"][theme]["version"]
            fore, card = hex_of(version["fore"]), hex_of(version["card"])
            with self.subTest(theme):
                self.assertEqual(card, brand.card_ground(theme).upper())
                self.assertEqual(fore, tokens["muted"].upper())
                self.assertGreaterEqual(brand.contrast(fore, card), 4.5, "%s on %s" % (fore, card))

    def test_nothing_in_the_dark_window_keeps_a_light_colour(self):
        """Every opaque colour on every control of every page, built and filled, is one of the dark
        palette's or the dark card's ground."""
        allowed = {argb(value) for value in brand.DARK.values()} | {argb(brand.card_ground("dark"))}
        offenders = []
        for key, where in sorted(self.answer["window"]["dark"]["colours"].items()):
            kind, prop, value = key.split("|")
            if int(value) not in allowed:
                offenders.append("%s %s #%06X at %s" % (kind, prop, int(value) & 0xFFFFFF, where))
        self.assertEqual(offenders, [], "\n".join(offenders))
        light = {argb(value) for value in brand.LIGHT.values()}
        stray = [key for key in self.answer["window"]["light"]["colours"] if int(key.split("|")[2]) not in light]
        self.assertEqual(stray, [], "the light window keeps to the light palette too")

    # ------------------------------------------------------------------ reopening

    def test_which_changes_reopen_and_which_wait_for_the_edits(self):
        self.assertEqual(len(self.answer["decisions"]), len(DECISIONS))
        for (case, expected), got in zip(DECISIONS, self.answer["decisions"]):
            with self.subTest(case=case):
                self.assertEqual(got, expected)

    def test_the_window_waits_for_unsaved_edits_and_says_so_in_the_save_card(self):
        """The real CheckReopen, driven through Observe as a read of the settings drives it. An action is on
        its way, so where the window would reopen it waits (recheck), as it waits while minimized or under a
        dialog, and nothing is started. High Contrast is the probe's own answer, "off", so the steps are the same on a
        machine that has it on."""
        self.assertFalse(self.answer["highContrast"], "the probe answers High Contrast 'off' for these steps")
        note = l10n.catalog("en")["note.reopen_pending"]
        expected = [
            # step, recheck (would reopen, or waits for the edits), note shown, openedTheme
            ("opened", False, False, "light"),
            ("unchanged", False, False, "light"),
            ("theme changed, nothing unsaved", True, False, "light"),
            ("an edit", True, True, "light"),
            ("the edit put back", True, False, "light"),
            ("theme changed back", False, False, "light"),
            ("language changed under an edit", True, True, "light"),
            ("all back", False, False, "light"),
            # A second reopen in a row that reads something else again stays, and takes what it read.
            ("first read of a second reopen in a row", False, False, "dark"),
            ("read again", False, False, "dark"),
        ]
        steps = self.answer["checks"]
        self.assertEqual([step["step"] for step in steps], [row[0] for row in expected])
        for step, (name, recheck, shown, opened) in zip(steps, expected):
            with self.subTest(name):
                self.assertFalse(step["reopening"], "nothing was started")
                self.assertEqual(step["recheck"], recheck)
                self.assertEqual(step["note"], shown)
                self.assertEqual(step["text"], note if shown else "")
                self.assertEqual(step["openedTheme"], opened)
                self.assertEqual(step["openedLanguage"], "en")

    def test_a_disagreement_that_never_goes_away_reopens_at_most_twice(self):
        """A window that reads something other than what it was started with - every time - is opened
        by a person (generation 0), reopens, reopens again, and then stays: no loop. Walked with the
        window's own answers."""
        self.assertEqual(self.answer["maxGeneration"], 2)
        # NextGeneration(firstRead, generation) for (True, 0), (True, 1), (True, 2), (True, 9), then
        # (False, 0), (False, 2), (False, 9): a change seen later starts a new count.
        self.assertEqual(self.answer["next"], [1, 2, 3, 9, 1, 1, 1])
        following = {0: 1, 1: 2, 2: 3, 9: 9}
        decided = {case[6]: got for (case, _), got in zip(DECISIONS, self.answer["decisions"])
                   if case[:6] == ("en", "light", "en", "dark", False, True)}
        generation, windows = 0, 1
        while decided[generation] == REOPEN:
            generation = following[generation]
            windows += 1
            self.assertLessEqual(windows, 5, "the chain did not end")
        self.assertEqual(windows, 3, "the person's window and two reopens")
        self.assertEqual(decided[generation], ADOPT)

    def test_a_window_whose_new_one_never_showed_stays_and_goes_on_working(self):
        """It closes only once the new window is up. When the new process ends first, this window takes input
        again, its clock runs, and what a read or a save held back for the reopen - the page as the settings now
        are, "Saved." - is done after all; it does not try again for the same language and theme, but a
        different change reopens it as ever."""
        handover = self.answer["handover"]
        self.assertNotIn("error", handover)
        self.assertFalse(self.answer["highContrast"], "the probe answers High Contrast 'off' for these steps")
        self.assertEqual(handover["heldWhileStaying"], 1, "not reopening: the work is done at once")
        self.assertEqual(handover["heldWhileReopening"], 1, "reopening: the work waits")
        gone = handover["gone"]
        self.assertFalse(gone["disposed"])
        self.assertFalse(gone["reopening"], "left reopening, it stopped watching, reloading and confirming saves")
        self.assertEqual(gone["held"], 3, "both held pieces of work were done")
        self.assertFalse(gone["heldLeft"])
        self.assertTrue(gone["clock"])
        expected = [("what it could not reopen in", False), ("something else", True), ("what it shows", False),
                    ("what it could not reopen in, again", False)]
        self.assertEqual([(step["step"], step["recheck"]) for step in handover["after"]], expected)
        for step in handover["after"]:
            with self.subTest(step["step"]):
                self.assertFalse(step["reopening"])
                self.assertFalse(step["note"])
        self.assertTrue(handover["shown"]["disposed"], "the new window came up, and this one closed")

    def test_the_wait_for_the_new_window_ends_the_way_its_process_says(self):
        wait = self.answer["handover"].get("await")
        self.assertIsNotNone(wait, self.answer["handover"].get("error"))
        self.assertEqual((wait["window"]["shown"], wait["window"]["polls"]), (True, 3), "a window: close this one")
        self.assertEqual((wait["exited"]["shown"], wait["exited"]["polls"]), (False, 2), "ended first: stay")
        self.assertEqual((wait["both"]["shown"], wait["both"]["polls"]), (True, 1), "a window counts first")
        self.assertTrue(wait["neither"]["shown"], "after the wait, whatever it is doing, this one closes")
        self.assertGreaterEqual(wait["neither"]["ms"], 150)
        self.assertGreater(wait["neither"]["polls"], 1)

    def test_a_reopened_window_puts_the_keyboard_where_the_old_one_had_it(self):
        """A keyboard or screen-reader user who saved a theme lands on Save again, in the new window - not on the
        header's first button or the Overview tab while Settings is on screen."""
        focus = self.answer["focus"]
        self.assertNotIn("error", focus)
        for case in focus["names"]:
            with self.subTest(case["expected"]):
                self.assertEqual(case["name"], case["expected"])
                self.assertTrue(case["target"], "the name leads back to the same control")
        self.assertEqual(focus["nothingOnSettings"], "section.appearance")
        self.assertEqual(focus["nothingOnPending"], "page.pending")
        restored = focus["restored"]
        expected = {
            "theme": ("page.settings", "setting.theme"),
            "save": ("page.settings", "save"),
            # The person moved on before the editors were built: they are left where they went.
            "moved": ("page.settings", "page.overview"),
            "pending": ("page.pending", "page.pending"),
            "missing": ("page.settings", "page.settings"),
            "hiddenSave": ("page.history", "page.history"),
            "otherSection": ("page.settings", "page.settings"),
            # Opened by a person: the window's own first control, as ever.
            "none": ("", ""),
        }
        for name, (interim, final) in expected.items():
            with self.subTest(name):
                self.assertEqual((restored[name]["interim"], restored[name]["final"]), (interim, final))

    def test_the_reopen_note_is_whole_beside_the_buttons_in_every_language(self):
        """At the opening width and at the narrowest the window goes, the save card grows for a note that needs
        more lines, rather than cutting off the part that says what to do."""
        notes = self.answer["note"]
        self.assertNotIn("error", notes)
        for locale in l10n.LOCALES:
            for width in NOTE_WIDTHS:
                note = notes[locale][str(width)]
                with self.subTest(locale=locale, width=width):
                    self.assertEqual(note["text"], l10n.catalog(locale)["note.reopen_pending"])
                    self.assertGreater(note["width"], 0)
                    self.assertLessEqual(note["needed"], note["height"], "the note is cut off")
                    self.assertLessEqual(note["noteRight"], note["rowLeft"], "beside the buttons, not under them")
                    self.assertGreaterEqual(note["rowTop"], note["cardTop"], "the buttons inside the card")
                    self.assertLessEqual(note["rowBottom"], note["cardHeight"] - note["cardBottom"])

    def test_the_command_line_is_checked_value_by_value(self):
        self.assertEqual(len(self.answer["arguments"]), len(ARGUMENTS))
        for (arguments, expected), got in zip(ARGUMENTS, self.answer["arguments"]):
            with self.subTest(arguments=arguments):
                self.assertEqual(got, expected)

    def test_a_reopen_passes_on_exactly_what_the_new_window_accepts(self):
        self.assertNotIn("roundTripError", self.answer)
        expected = [
            {"page": "settings", "section": "appearance", "bounds": [120, 80, 1500, 900], "theme": "dark", "generation": 1,
             "frame": [7, 0, 7, 7], "focus": "save"},
            {"page": "pending", "section": "general", "bounds": [-1920, -8, 1000, 600], "maximized": True,
             "theme": "system", "generation": 2, "frame": [11, 0, 11, 11], "focus": "page.pending"},
            {"page": "overview", "bounds": [0, 0, 1000, 600], "theme": "system", "generation": 1, "focus": "setting.theme"},
            {"section": "continuation", "theme": "light", "generation": 9},
        ]
        self.assertEqual(len(self.answer["roundTrip"]), len(ROUND_TRIPS))
        for case, want, got in zip(ROUND_TRIPS, expected, self.answer["roundTrip"]):
            with self.subTest(case=case):
                self.assertEqual(got["parsed"], want)
                self.assertNotIn('"', got["line"])
                for token in got["line"].split(" "):
                    self.assertRegex(token, r"^--(page|section|bounds|maximized|theme|reopened|frame|focus)\b")

    def test_a_reopened_window_is_placed_wholly_on_its_screen(self):
        """By the frame one sees, not the bounds: those reach past it by the resize border Windows keeps invisible,
        so a window snapped or flush against an edge used to come back that border's width in from the edge and
        shorter."""
        self.assertNotIn("placeError", self.answer)
        self.assertEqual(len(self.answer["place"]), len(PLACES))
        for (case, expected), got in zip(PLACES, self.answer["place"]):
            with self.subTest(case=case):
                self.assertEqual(tuple(got), expected)


class ThemeSourceRuleTests(unittest.TestCase):
    """Rules for the source, so they fail without a compiler too."""

    COLOURS = ("Ink", "Muted", "Line", "Surface", "Canvas", "Accent", "OnAccent", "Active", "Idle", "Raised",
               "Inset", "ShadowDark", "ShadowLight", "AccentSoft", "Focus", "Attention", "Success", "Waiting",
               "Warning", "Danger", "Paused", "AccentHover", "AccentPressed", "CardGround")
    THEMED = ("StatusFill", "CheckFill", "CheckEdge", "CheckMark", "ElevationCount", "ElevationShadow")

    def setUp(self):
        self.sources = {name: (GUI / name).read_text(encoding="utf-8")
                        for name in ("Controls.cs", "SettingsApp.cs", "Dashboard.cs")}

    @staticmethod
    def code(text):
        return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//"))

    @staticmethod
    def block(text, signature, end="\n    }\n"):
        start = text.index(signature)
        return text[start:text.index(end, start)]

    def test_no_light_colour_is_drawn_outside_the_theme_it_was_adopted_from(self):
        """Brand's light colours are read in one place - Tokens.Adopt, beside their dark twins - and
        everything else draws from Palette or Tokens. A `Brand.Surface` left in a paint method is a light
        patch in a dark window."""
        pattern = re.compile(r"\bBrand\.(%s)\b" % "|".join(self.COLOURS))
        adopt = self.block(self.sources["Controls.cs"], "internal static void Adopt(bool dark)", "\n        }\n")
        for name, text in self.sources.items():
            code = self.code(text.replace(adopt, "") if name == "Controls.cs" else text)
            with self.subTest(name):
                self.assertEqual(pattern.findall(code), [], "a light brand colour drawn directly")
        self.assertEqual(len(re.findall(r"= Brand\.Dark\.\w+;", adopt)), len(self.COLOURS))
        self.assertEqual(len(re.findall(r"= Brand\.(?!Dark\.)\w+;", adopt)), len(self.COLOURS))

    def test_every_theme_dependent_brand_rule_is_read_with_its_dark_twin(self):
        """A status colour, a check box's colours and an elevation recipe differ by theme, so each is
        read in one expression that asks which theme is in effect."""
        pattern = re.compile(r"(?<!Dark\.)\bBrand\.(%s)\(" % "|".join(self.THEMED))
        for name, text in self.sources.items():
            code = self.code(text)
            for match in pattern.finditer(code):
                start = max(code.rfind(";", 0, match.start()), code.rfind("{", 0, match.start()),
                            code.rfind("}", 0, match.start()))
                with self.subTest(file=name, line=code.count("\n", 0, match.start()) + 1):
                    self.assertIn("Tokens.Dark ? Brand.Dark.%s(" % match.group(1), code[start + 1:match.end()])

    def test_no_colour_is_written_as_a_literal_or_a_named_colour(self):
        named = re.compile(r"\bColor\.(?!FromArgb\b|Transparent\b|Empty\b)[A-Z]\w*")
        literal = re.compile(r"Color\.FromArgb\(\s*(?:0x|\d+\s*,\s*\d+\s*,\s*\d+)")
        for name, text in self.sources.items():
            code = self.code(text)
            with self.subTest(name):
                self.assertEqual(named.findall(code), [])
                self.assertEqual(literal.findall(code), [])

    def test_high_contrast_is_asked_of_windows_each_time(self):
        controls = self.sources["Controls.cs"]
        asked = self.block(controls, "internal static bool HighContrast()", "\n        }\n")
        self.assertIn("SystemParametersInfo(SPI_GETHIGHCONTRAST", asked)
        # Through the one input a probe may answer (Theme.HighContrastOn), which ships as Windows' own answer, which the
        # window's first theme reads too, and which nothing in the window sets.
        self.assertIn("ContrastOn()", self.block(controls, "internal static string Current(", "\n        }\n"))
        self.assertIn("internal static Func<bool> HighContrastOn = HighContrast;", controls)
        self.assertIn("on != null ? on() : HighContrast()", self.block(controls, "internal static bool ContrastOn()", "\n        }\n"))
        self.assertIn("Adopt(CodexAutoResume.Theme.ContrastOn() ?", controls)
        for name, text in self.sources.items():
            with self.subTest(name):
                self.assertEqual(self.code(text).count("HighContrastOn ="), 1 if name == "Controls.cs" else 0)
        uses = sum(self.code(text).count("SystemInformation.HighContrast") for text in self.sources.values())
        self.assertEqual(uses, 1, "SystemInformation.HighContrast only as the fallback, where Windows cannot be asked")
        self.assertIn("SystemInformation.HighContrast", self.code(asked))

    def test_the_version_is_text_not_a_fill(self):
        window = self.sources["SettingsApp.cs"]
        self.assertIn("versionText.ForeColor = Secondary;", window)
        for name, text in self.sources.items():
            with self.subTest(name):
                self.assertIsNone(re.search(r"ForeColor\s*=\s*(?:Palette\.|Tokens\.)?Idle\b", self.code(text)))

    def test_the_theme_is_adopted_before_the_first_control_is_made(self):
        main = self.block(self.sources["SettingsApp.cs"], "internal static int Main(string[] argv)", "\n        }\n")
        adopt = main.index("Palette.Adopt(Theme.Current(Theme.Opened));")
        self.assertLess(main.index("SettingsForm.ParseArguments(argv)"), adopt)
        self.assertLess(adopt, main.index("new SettingsForm("))
        self.assertIn("request.Theme ?? Theme.Stored(root)", main)
        controls = self.sources["Controls.cs"]
        resolve = self.block(controls, "internal static string Resolve(", "\n        }\n")
        self.assertLess(resolve.index("if (highContrast) return Contrast;"), resolve.index("Preference(preference)"),
                        "High Contrast wins over every choice")
        self.assertIn(r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", controls)
        self.assertIn('"AppsUseLightTheme"', controls)

    def test_the_title_bar_goes_dark_with_the_immersive_dark_mode_attribute(self):
        controls = self.sources["Controls.cs"]
        self.assertIn("internal const int DarkTitleBarAttribute = 20;", controls)
        self.assertIn("internal const int DarkTitleBarAttributeBefore20H1 = 19;", controls)
        title = self.block(controls, "internal static void TitleBar(Form form)", "\n        }\n")
        self.assertIn("if (!Palette.Dark || form == null) return;", title)
        self.assertLess(title.index("DarkTitleBarAttribute, ref on"), title.index("DarkTitleBarAttributeBefore20H1, ref on"))
        self.assertIn("Soft.TitleBar(this);", self.sources["SettingsApp.cs"])
        self.assertIn("Soft.TitleBar(dialog);", self.sources["Dashboard.cs"], "the Timeline dialog too")

    def test_every_elevation_reads_each_shadows_own_inset_flag(self):
        """Dark's card mixes outer shadows with an inset top light; a recipe's name says nothing."""
        elevation = self.block(self.sources["Controls.cs"], "internal static class Elevation")
        self.assertNotIn("id >= 4", elevation)
        self.assertNotIn("First(", elevation)
        self.assertIn("Tokens.Dark ? Brand.Dark.ElevationShadow(", elevation)
        card = self.block(self.sources["Controls.cs"], "internal sealed class SoftCard ")
        self.assertIn('Soft.Body(e.Graphics, ClientRectangle, radius, Palette.Card, Palette.Line, "card");', card)
        self.assertIn("BackColor = Palette.Card;", card)

    def test_the_window_reopens_on_a_save_a_change_elsewhere_and_windows_app_mode(self):
        window = self.sources["SettingsApp.cs"]
        dashboard = self.sources["Dashboard.cs"]
        save = self.block(window, "private void Save()", "\n        }\n")
        self.assertLess(save.index("startupBaseline = startAtSignIn;"), save.index("CheckReopen(false);"))
        self.assertLess(save.index("CheckReopen(false);"), save.index("RefreshStatusAsync("))
        watch = self.block(window, "private void WatchSettings()", "\n        }\n")
        self.assertIn('bridge.Call("settings", null)', watch)
        self.assertIn("busy > 0", watch)
        wndproc = self.block(window, "protected override void WndProc(ref Message m)", "\n        }\n")
        self.assertIn('"ImmersiveColorSet"', wndproc)
        self.assertIn("SPI_SETHIGHCONTRAST", wndproc)
        self.assertIn("TickReopen();", self.block(dashboard, "private void StartClock()", "\n        }\n"))
        check = self.block(window, "private void CheckReopen(bool firstRead)", "\n        }\n")
        self.assertIn("Dirty()", check)
        self.assertIn("WindowState == FormWindowState.Minimized || busy > 0", check)
        reopen = self.block(window, "private void Reopen(bool firstRead)", "\n        }\n")
        self.assertLess(reopen.index("Process.Start(info)"), reopen.index("reopening = true;"),
                        "the new window is started before this one gives up")
        # The wait asks the new process for its window first and whether it ended second, and its answer alone
        # decides the ending (FinishReopen, driven both ways by the probe).
        self.assertLess(reopen.index("started.MainWindowHandle != IntPtr.Zero"), reopen.index("started.HasExited"))
        self.assertIn("shown = AwaitWindow(", reopen)
        self.assertIn("FinishReopen(shown)", reopen)
        self.assertEqual(reopen.count("FinishReopen("), 1)
        self.assertIn("ReopenArguments(", reopen)
        self.assertIn("reopenFocus ?? FocusName()", reopen)
        self.assertIn("InvisibleFrame()", reopen)
        finish = self.block(window, "private void FinishReopen(bool shown)", "\n        }\n")
        self.assertIn("if (shown)", finish)
        self.assertLess(finish.index("Close();"), finish.index("reopening = false;"))
        load = self.block(window, "Load += delegate", "\n            };\n")
        self.assertLess(load.index("ShowPage(firstPage);"), load.index("FocusInterim();"))
        reload = self.block(window, "private void Reload()", "\n        }\n")
        self.assertLess(reload.index("Observe(current, first);"), reload.index("HoldForReopen("))
        self.assertLess(reload.index("BuildEditorsLater();"), reload.index("FocusPending();"))
        self.assertIn("HoldForReopen(", save)
        self.assertLess(save.index("string focus = FocusName();"), save.index('CallAsync("update"'))
        self.assertLess(save.index("reopenFocus = focus;"), save.index("CheckReopen(false);"))
        self.assertIn("PlaceOnScreen(request.Bounds, Screen.FromRectangle(request.Bounds).WorkingArea, MinimumSize, request.Frame)",
                      window)
        self.assertNotIn("Mutex", window[window.index("// ------------------------------------------------------------------ reopening"):
                                          window.index("// ------------------------------------------------------------------ layout audit")],
                         "nothing single-instance stands between the two windows")

    def test_the_window_has_no_single_instance_rule_to_refuse_the_new_one(self):
        for name, text in self.sources.items():
            code = self.code(text)
            made = re.findall(r"\bnew\s+(?:System\.Threading\.)?Mutex\b", code)
            named = re.findall(r'\bnew\s+(?:System\.Threading\.)?Mutex\(\s*\w+\s*,\s*"([^"]*)"', code)
            with self.subTest(name):
                self.assertEqual(len(made), len(named), "a mutex whose name cannot be read here")
                # The installer's lock, which Repair takes (Dashboard.cs), is the only one.
                self.assertEqual([m for m in named if m != "Local\\\\CodexAutoResume.Install"], [],
                                 "a mutex other than the installer's lock")

    def test_the_note_about_a_pending_reopen_sits_in_the_save_card(self):
        footer = self.block(self.sources["SettingsApp.cs"], "private void BuildFooter()", "\n        }\n")
        self.assertIn("savebar.Controls.Add(reopenNote, 1, 0);", footer)
        self.assertIn("reopenNote.LiveSetting = AutomationLiveSetting.Polite;", footer)
        english = json.loads((ROOT / "src" / "codex_auto_resume" / "locales" / "en.json").read_text(encoding="utf-8"))
        note = self.block(self.sources["SettingsApp.cs"], "private void ShowReopenNote(bool show)", "\n        }\n")
        self.assertIn('"note.reopen_pending"', note)
        self.assertIn(english["note.reopen_pending"], note.replace("\n", " ").replace('"', "").replace("  ", " "))

    def test_the_check_box_is_one_control_class_with_a_kind(self):
        controls = self.sources["Controls.cs"]
        check = self.block(controls, "internal sealed class SoftCheck ")
        self.assertIn("internal bool Box", check)
        self.assertIn("AccessibleRole = AccessibleRole.CheckButton;", check)
        self.assertIn("if (Focused && ShowFocusCues)", check)
        draw = self.block(controls, "internal static void DrawBox(", "\n        }\n")
        self.assertLess(draw.index("if (Palette.Contrast)"), draw.index("Tokens.Dark ? Brand.Dark.CheckFill("))
        self.assertIn("well = false;", draw[:draw.index("else")], "no shadow in High Contrast")
        self.assertIn("pen.LineJoin = LineJoin.Miter;", draw)
        self.assertIn("LineCap.Flat", draw)
        window = self.sources["SettingsApp.cs"]
        self.assertIn("NewCheck(Humanise(name), Equals(Get(current, name), true), IsListItem(name));", window)
        self.assertIn('NewCheck(S("field.startup", "Run at Windows sign-in"), false, false);', window)
        self.assertNotIn('ChoiceCombo(field, current, "choice.");', window)
        # Each theme in its own words: the Theme's "Use system setting", the panel theme's "Same as
        # Theme" and "Codex's theme" (v0.6.6) - never the generic "choice." the other settings share.
        self.assertIn('bool themed = name == "theme" || name == "panel_theme";', window)
        self.assertIn('themed ? "choice." + name + "." : "choice."', window)


if __name__ == "__main__":
    unittest.main()
