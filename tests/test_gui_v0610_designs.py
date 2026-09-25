r"""The window in the designs (v0.6.10): Soft, Classic and Plain.

* PALETTE (D12). Palette.Contrast meant two things until the designs came - draw in system colours, and draw no depth,
  glow or tint - and Classic and Plain need the second without the first. So Contrast is the system colours alone, and
  Depth, Halo and AccentBar are flags of their own that High Contrast also clears. A design's colours are its own class
  in Brand.cs, read in Tokens alone; its corners are never rounder than Soft's.
* MOTION (D5). One gate, the stoppers' (Soft.ReduceMotion), in every design: no design moves or holds anything of its
  own. v0.6.10 split it in two for Still, which drew exactly what Reduce motion draws; since v0.6.11 a stored Still is
  Soft with Reduce motion on (settings._migrate), which the window draws as Still drew. Plain's light still dims on its
  breath - with no glow - because a light that says the product is running must move (the critic's correction to D12).
* MARKS (D14). Classic draws v0.6.2's accent bar inside each card's left hairline and underlines the current tab; Plain
  draws its current tab as a flat quiet-accent ground; neither draws a shadow or a well. Rows stay flat hairline rows.
* LAYOUT (D15). A design changes paint and never layout: the layout audit, run in each design, writes down the same
  place for everything, so an audit of one design is an audit of all.

The real compiled window is loaded and its own methods are called through reflection, as the other window tests do.
Nothing is shown, no input is sent anywhere, and nothing of this machine's is read or changed: Windows' High Contrast
and animation answers are the probe's own (Theme.HighContrastOn, Soft.WindowsAnimates), and every picture is drawn
into a bitmap.
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

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")

DESIGNS = brand.DESIGNS
# Palette's colour fields and the brand token each is in a design's palette; Card is the card's ground.
TOKENS = {"Ink": "ink", "Muted": "muted", "Secondary": "muted", "Line": "line", "Surface": "surface",
          "Canvas": "canvas", "Raised": "raised", "Inset": "inset", "Accent": "accent",
          "AccentHover": "accent_hover", "AccentPressed": "accent_pressed", "OnAccent": "on_accent",
          "AccentSoft": "accent_soft", "Focus": "focus", "Active": "active", "Idle": "idle",
          "Attention": "attention", "Success": "success", "Waiting": "waiting", "Warning": "warning",
          "Danger": "danger", "Paused": "paused", "Card": None}
# The light drawn at 300%, at moments of monitoring's cycle as fractions of it: lit, dimming, darkest, rising, the bloom.
LIGHT_SCALE = 3.0
LIGHT_SIDE = 96
LIGHT_FRACTIONS = (0.0, 0.16, 0.34, 0.5, 0.66, 0.75, 0.84, 0.92)
LIGHT_MOMENTS = tuple(brand.GLOW["monitoring_ms"] * fraction for fraction in LIGHT_FRACTIONS)
LIGHT_STATES = ("monitoring", "checking", "attention")

PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$static = [Reflection.BindingFlags]'Static,NonPublic,Public'
$instance = [Reflection.BindingFlags]'Instance,NonPublic,Public'
$utf8 = New-Object Text.UTF8Encoding $false
$work = [string]$env:CAR_WORK
$t = @{}
foreach ($name in @('Palette', 'Tokens', 'Soft', 'Theme', 'HaloDot', 'SoftCard', 'SoftStack', 'NavButton', 'SoftCheck',
                    'SettingsForm')) {
    $t[$name] = $assembly.GetType('CodexAutoResume.' + $name, $true)
}
# Answers for the window's inputs from Windows (Theme.HighContrastOn, Soft.WindowsAnimates), compiled, so they hold on
# any thread.
Add-Type -TypeDefinition @'
public static class Said {
    public static bool Yes() { return true; }
    public static bool No() { return false; }
    public static System.Func<bool> Answer(bool yes) { return yes ? new System.Func<bool>(Yes) : new System.Func<bool>(No); }
}
'@
$adoptDesign = $t.Palette.GetMethod('AdoptDesign', $static)
$adopt = $t.Palette.GetMethod('Adopt', $static)
function Look([string]$design, [string]$theme) {
    $null = $adoptDesign.Invoke($null, [object[]]@($design))
    $null = $adopt.Invoke($null, [object[]]@($theme))
}
function Field([string]$type, [string]$name) { return $t[$type].GetField($name, $static).GetValue($null) }
function Property([string]$type, [string]$name) { return $t[$type].GetProperty($name, $static).GetValue($null, $null) }
$t.Theme.GetField('HighContrastOn', $static).SetValue($null, [Said]::Answer($false))
$animates = $t.Soft.GetField('WindowsAnimates', $static)
$reduce = $t.Soft.GetField('ReduceMotionSetting', $static)
$animates.SetValue($null, [Said]::Answer($true))
$reduce.SetValue($null, $false)
$scaleField = $t.SettingsForm.GetField('dpiScale', $static)
$systemScale = [double]$t.SettingsForm.GetField('SystemScale', $static).GetValue($null)
$out = @{}

# ------------------------------------------------------------------ the palette in each design and theme
$names = ConvertFrom-Json $env:CAR_NAMES
$out.palette = @{}
foreach ($design in (ConvertFrom-Json $env:CAR_DESIGNS)) {
    foreach ($theme in @('light', 'dark', 'contrast')) {
        Look $design $theme
        $entry = @{ design = [string](Field 'Palette' 'Design'); theme = [string](Field 'Palette' 'Theme')
                    contrast = [bool](Field 'Palette' 'Contrast'); depth = [bool](Field 'Palette' 'Depth')
                    halo = [bool](Field 'Palette' 'Halo'); bar = [bool](Field 'Palette' 'AccentBar')
                    radii = @([int](Field 'Palette' 'RadiusCard'), [int](Field 'Palette' 'RadiusControl'),
                              [int](Field 'Palette' 'RadiusSmall'), [int](Field 'Palette' 'RadiusCheck'))
                    tokensDesign = [string](Field 'Tokens' 'Design'); colours = @{}; check = @() }
        foreach ($name in $names) {
            $colour = Field 'Palette' ([string]$name)
            $entry.colours[[string]$name] = @([int]$colour.ToArgb(), [string]$colour.Name, [bool]$colour.IsSystemColor)
        }
        foreach ($on in @($false, $true)) {
            foreach ($enabled in @($false, $true)) {
                $fill = $t.Tokens.GetMethod('CheckFill', $static).Invoke($null, [object[]]@($on, $enabled))
                $edge = $t.Tokens.GetMethod('CheckEdge', $static).Invoke($null, [object[]]@($on, $enabled))
                $call = [object[]]@($on, $enabled, $null)
                $marked = [bool]$t.Tokens.GetMethod('CheckMark', $static).Invoke($null, $call)
                $entry.check += ,@([bool]$on, [bool]$enabled, [int]$fill.ToArgb(), [int]$edge.ToArgb(), $marked, [int]$call[2].ToArgb())
            }
        }
        $out.palette[$design + '|' + $theme] = $entry
    }
}

# ------------------------------------------------------------------ the one gate
$out.motion = @()
foreach ($design in (ConvertFrom-Json $env:CAR_DESIGNS)) {
    foreach ($reduced in @($false, $true)) {
        foreach ($animating in @($true, $false)) {
            foreach ($contrast in @($false, $true)) {
                $reduce.SetValue($null, [bool]$reduced)
                $animates.SetValue($null, [Said]::Answer([bool]$animating))
                Look $design $(if ($contrast) { 'contrast' } else { 'light' })
                $out.motion += ,@([string]$design, [bool]$reduced, [bool]$animating, [bool]$contrast,
                                  [bool](Property 'Soft' 'ReduceMotion'))
            }
        }
    }
}
$reduce.SetValue($null, $false)
$animates.SetValue($null, [Said]::Answer($true))

# ------------------------------------------------------------------ the light, drawn
# At 300%, into a bitmap, at moments the probe chooses: the dot's own clock stopped and the moment it entered its state
# set back. A row of pixels through the dot's middle for each moment.
function Frames([string]$state) {
    $scaleField.SetValue($null, [double]$env:CAR_LIGHT_SCALE)
    $side = [int]$env:CAR_LIGHT_SIDE
    $light = [Activator]::CreateInstance($t.HaloDot, $true)
    $light.Size = New-Object Drawing.Size $side, $side
    $t.HaloDot.GetProperty('State', $instance).SetValue($light, $state, $null)
    $clock = $t.HaloDot.GetField('clock', $instance).GetValue($light)
    $clock.Stop()
    $stopped = $clock.Elapsed.TotalMilliseconds
    $entered = $t.HaloDot.GetField('enteredAt', $instance)
    $frames = @()
    foreach ($ms in (ConvertFrom-Json $env:CAR_LIGHT_MOMENTS)) {
        $entered.SetValue($light, [double]($stopped - [double]$ms))
        $bitmap = New-Object Drawing.Bitmap $side, $side
        $light.DrawToBitmap($bitmap, (New-Object Drawing.Rectangle 0, 0, $side, $side))
        $row = [int[]]::new($side)
        for ($x = 0; $x -lt $side; $x++) { $row[$x] = $bitmap.GetPixel($x, [int][Math]::Floor($side / 2)).ToArgb() }
        $bitmap.Dispose()
        $frames += ,$row
    }
    $light.Dispose()
    $scaleField.SetValue($null, $systemScale)
    return ,$frames
}
$out.light = @{}
foreach ($design in (ConvertFrom-Json $env:CAR_DESIGNS)) {
    foreach ($reduced in @($false, $true)) {
        $reduce.SetValue($null, [bool]$reduced)
        Look $design 'light'
        foreach ($state in (ConvertFrom-Json $env:CAR_LIGHT_STATES)) {
            $out.light[$design + '|' + [string]$reduced + '|' + $state] = Frames $state
        }
    }
}
# A Still stored by v0.6.10, as the window takes it: the file's design as Design.Preference reads it, and the Reduce
# motion the bridge's first read brings (settings._migrate).
$reduce.SetValue($null, $true)
Look 'still' 'light'
$out.storedStill = @{ design = [string](Field 'Palette' 'Design'); frames = @{} }
foreach ($state in (ConvertFrom-Json $env:CAR_LIGHT_STATES)) { $out.storedStill.frames[$state] = Frames $state }
$reduce.SetValue($null, $false)

# ------------------------------------------------------------------ a card on its ground, a tab, a box, a switch
# At 100%: a card 200 by 100 with 40 px of ground round it, drawn with the ground's stamps as a page draws it.
function CardPicture() {
    $scaleField.SetValue($null, [double]1.0)
    $stack = [Activator]::CreateInstance($t.SoftStack, $true)
    $stack.Size = New-Object Drawing.Size 280, 180
    $card = [Activator]::CreateInstance($t.SoftCard, $true)
    $card.AutoSize = $false
    $card.Margin = New-Object Windows.Forms.Padding 40
    $card.Size = New-Object Drawing.Size 200, 100
    $stack.Controls.Add($card)
    $stack.CreateControl()
    $stack.PerformLayout()
    $bitmap = New-Object Drawing.Bitmap 280, 180
    $stack.DrawToBitmap($bitmap, (New-Object Drawing.Rectangle 0, 0, 280, 180))
    $bounds = $card.Bounds
    $middle = $bounds.Top + [int]($bounds.Height / 2)
    $centre = $bounds.Left + [int]($bounds.Width / 2)
    $row = [int[]]::new(280)
    for ($x = 0; $x -lt 280; $x++) { $row[$x] = $bitmap.GetPixel($x, $middle).ToArgb() }
    $column = [int[]]::new(180)
    for ($y = 0; $y -lt 180; $y++) { $column[$y] = $bitmap.GetPixel($centre, $y).ToArgb() }
    $bitmap.Dispose()
    $stack.Dispose()
    $scaleField.SetValue($null, $systemScale)
    return @{ bounds = @($bounds.X, $bounds.Y, $bounds.Width, $bounds.Height); row = $row; column = $column
              hairline = 1; canvas = [int](Field 'Palette' 'Canvas').ToArgb(); card = [int](Field 'Palette' 'Card').ToArgb()
              accent = [int](Field 'Palette' 'Accent').ToArgb(); line = [int](Field 'Palette' 'Line').ToArgb() }
}
# A page's tab, chosen, and a section's, at 100%: a column of pixels down its middle and a row along its middle.
function TabPicture([bool]$vertical) {
    $scaleField.SetValue($null, [double]1.0)
    $tab = [Activator]::CreateInstance($t.NavButton, $true)
    $tab.Text = 'Overview'
    $tab.Size = New-Object Drawing.Size 120, 40
    $t.NavButton.GetField('Vertical', $instance).SetValue($tab, $vertical)
    $t.NavButton.GetProperty('Current', $instance).SetValue($tab, $true, $null)
    $bitmap = New-Object Drawing.Bitmap 120, 40
    $tab.DrawToBitmap($bitmap, (New-Object Drawing.Rectangle 0, 0, 120, 40))
    $face = $t.NavButton.GetProperty('Face', $instance).GetValue($tab, $null)
    $column = [int[]]::new(40)
    for ($y = 0; $y -lt 40; $y++) { $column[$y] = $bitmap.GetPixel(60, $y).ToArgb() }
    $row = [int[]]::new(120)
    for ($x = 0; $x -lt 120; $x++) { $row[$x] = $bitmap.GetPixel($x, 20).ToArgb() }
    $bitmap.Dispose()
    $tab.Dispose()
    $scaleField.SetValue($null, $systemScale)
    return @{ face = @($face.X, $face.Y, $face.Width, $face.Height); column = $column; row = $row
              accent = [int](Field 'Palette' 'Accent').ToArgb(); soft = [int](Field 'Palette' 'AccentSoft').ToArgb()
              inset = [int](Field 'Palette' 'Inset').ToArgb(); canvas = [int](Field 'Palette' 'Canvas').ToArgb() }
}
# A check box and a switch, off and on, at 200%, as the theme test draws the box.
function Controls() {
    $scaleField.SetValue($null, [double]2.0)
    $ground = Field 'Palette' 'Card'
    $drawBox = $t.SoftCheck.GetMethod('DrawBox', $static)
    $switch = $t.Soft.GetMethod('Switch', $static)
    $pixels = @()
    foreach ($on in @($false, $true)) {
        $bitmap = New-Object Drawing.Bitmap 140, 60
        $g = [Drawing.Graphics]::FromImage($bitmap)
        $g.Clear($ground)
        $null = $drawBox.Invoke($null, [object[]]@($g, [Drawing.Rectangle]::new(10, 10, 36, 36), [bool]$on, $true))
        $null = $switch.Invoke($null, [object[]]@($g, [Drawing.Rectangle]::new(56, 8, 80, 44), [bool]$on, $true, $ground))
        $g.Dispose()
        for ($y = 0; $y -lt 60; $y += 2) { for ($x = 0; $x -lt 140; $x += 2) { $pixels += [int]$bitmap.GetPixel($x, $y).ToArgb() } }
        $bitmap.Dispose()
    }
    $scaleField.SetValue($null, $systemScale)
    return ,$pixels
}
$out.pictures = @{}
foreach ($design in (ConvertFrom-Json $env:CAR_DESIGNS)) {
    foreach ($theme in @('light', 'dark', 'contrast')) {
        Look $design $theme
        $out.pictures[$design + '|' + $theme] = @{ card = (CardPicture); tab = (TabPicture $false); section = (TabPicture $true)
                                                   controls = (Controls) }
    }
}

# ------------------------------------------------------------------ the layout, in each design
$audit = $t.SettingsForm.GetMethod('LayoutAudit', $static)
$geometry = $t.SettingsForm.GetField('AuditedGeometry', $static)
$schema = [IO.File]::ReadAllText((Join-Path $work 'schema.json'), $utf8)
$current = [IO.File]::ReadAllText((Join-Path $work 'settings.json'), $utf8)
$snapshot = [IO.File]::ReadAllText((Join-Path $work 'snapshot.json'), $utf8)
$english = [IO.File]::ReadAllText((Join-Path $work 'strings-en.json'), $utf8)
$out.layout = @{}
foreach ($design in (ConvertFrom-Json $env:CAR_DESIGNS)) {
    Look $design 'light'
    $report = [string]$audit.Invoke($null, [object[]]@($schema, $current, $english, $snapshot, [double]1.0))
    $out.layout[$design] = @{ report = $report; geometry = [string]$geometry.GetValue($null) }
}
Look 'soft' 'light'
[IO.File]::WriteAllText((Join-Path $work 'result.json'), ($out | ConvertTo-Json -Depth 8 -Compress), $utf8)
"""


def argb(value: str) -> int:
    r, g, b = brand.rgb(value)
    return ((0xFF << 24) | (r << 16) | (g << 8) | b) - (1 << 32)


def channels(pixel: int) -> tuple:
    pixel &= 0xFFFFFFFF
    return ((pixel >> 16) & 255, (pixel >> 8) & 255, pixel & 255)


def far(one: int, other: int) -> int:
    """How far apart two pixels are, on the channel they differ most on."""
    return max(abs(a - b) for a, b in zip(channels(one), channels(other)))


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class WindowDesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_gui_layout import fullest_snapshot
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll", "/reference:System.Windows.Forms.dll",
                        *[str(path) for path in guiscan.sources()]],
                       check=True, capture_output=True, timeout=300)
        reply = {"ok": True, "language": "en", "strings": l10n.catalog("en"), "endonyms": dict(l10n.ENDONYMS),
                 "preference": "en", "system_language": "en"}
        (work / "strings-en.json").write_text(json.dumps(reply, ensure_ascii=False), encoding="utf-8")
        current = dict(settings.defaults(), continuation_style="custom", custom_message_mode="per_reason")
        (work / "schema.json").write_text(json.dumps(settings.describe(), ensure_ascii=False), encoding="utf-8")
        (work / "settings.json").write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
        now = time.time()
        (work / "snapshot.json").write_text(json.dumps(fullest_snapshot(now), ensure_ascii=False), encoding="utf-8")
        probe = work / "probe.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        # A light held for a picture is no light that moves: the probe's clock is the only one. And the window's own
        # clock - what a countdown is worked out against - is the moment the reply was seeded at, as the pictures pin it,
        # so the four audits, seconds apart, read the same countdowns (Soft.StillNow).
        env = {key: value for key, value in os.environ.items() if key != "CODEX_AR_STILL_LIGHT"}
        env["CODEX_AR_STILL_NOW"] = repr(now)
        cls.result = subprocess.run(
            [str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1200,
            env=dict(env, CAR_EXE=str(exe), CAR_WORK=str(work), CAR_DESIGNS=json.dumps(list(DESIGNS)),
                     CAR_NAMES=json.dumps(list(TOKENS)), CAR_LIGHT_SCALE=repr(LIGHT_SCALE), CAR_LIGHT_SIDE=str(LIGHT_SIDE),
                     CAR_LIGHT_MOMENTS=json.dumps(list(LIGHT_MOMENTS)), CAR_LIGHT_STATES=json.dumps(list(LIGHT_STATES))))
        answer = work / "result.json"
        cls.answer = (json.loads(answer.read_text(encoding="utf-8-sig"))
                      if cls.result.returncode == 0 and answer.is_file() else {})

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-3000:])

    # ------------------------------------------------------------------ the palette (D12)

    def test_each_design_draws_in_its_own_palette_light_and_dark(self):
        for design in DESIGNS:
            for theme in brand.THEMES:
                entry = self.answer["palette"][design + "|" + theme]
                tokens = brand.palette(theme, design)
                with self.subTest(design=design, theme=theme):
                    self.assertEqual((entry["design"], entry["theme"], entry["contrast"]), (design, theme, False))
                    self.assertEqual(entry["tokensDesign"], "soft" if tokens is brand.palette(theme) else design)
                    for field, token in TOKENS.items():
                        expected = brand.card_ground(theme, design) if token is None else tokens[token]
                        self.assertEqual(entry["colours"][field][0], argb(expected), field)
                        self.assertFalse(entry["colours"][field][2], field + " is a system colour outside High Contrast")

    def test_depth_glow_and_the_accent_bar_are_the_designs_and_never_high_contrasts(self):
        for design in DESIGNS:
            for theme in ("light", "dark", "contrast"):
                entry = self.answer["palette"][design + "|" + theme]
                contrast = theme == "contrast"
                with self.subTest(design=design, theme=theme):
                    self.assertEqual(entry["contrast"], contrast)
                    self.assertEqual(entry["depth"], brand.design_depth(design) and not contrast)
                    self.assertEqual(entry["halo"], brand.design_glow(design) and not contrast)
                    self.assertEqual(entry["bar"], brand.design_accent_bar(design) and not contrast)
        self.assertFalse(self.answer["palette"]["classic|light"]["depth"])
        self.assertFalse(self.answer["palette"]["plain|dark"]["depth"])
        self.assertTrue(self.answer["palette"]["soft|light"]["depth"])

    def test_the_corners_are_the_designs_never_rounder_than_softs_and_softs_in_high_contrast(self):
        roles = ("card", "control", "small", "check")
        for design in DESIGNS:
            for theme in ("light", "dark", "contrast"):
                radii = self.answer["palette"][design + "|" + theme]["radii"]
                drawn = "soft" if theme == "contrast" else design
                with self.subTest(design=design, theme=theme):
                    self.assertEqual(radii, [brand.design_radii(drawn)[role] for role in roles])
                    self.assertTrue(all(mine <= brand.RADII[role] for mine, role in zip(radii, roles)))

    def test_high_contrast_is_system_colours_whatever_the_design(self):
        first = self.answer["palette"]["soft|contrast"]["colours"]
        for design in DESIGNS:
            colours = self.answer["palette"][design + "|contrast"]["colours"]
            with self.subTest(design):
                self.assertEqual(colours, first)
                self.assertTrue(all(value[2] for value in colours.values()))

    def test_each_designs_check_box_is_its_own(self):
        for design in DESIGNS:
            for theme in brand.THEMES:
                for on, enabled, fill, edge, marked, mark in self.answer["palette"][design + "|" + theme]["check"]:
                    expected = brand.check_box(on, enabled, theme, design)
                    with self.subTest(design=design, theme=theme, on=on, enabled=enabled):
                        self.assertEqual(fill, argb(expected["fill"]))
                        self.assertEqual(edge, argb(expected["edge"]))
                        self.assertEqual(marked, expected["mark"] is not None)
                        if expected["mark"] is not None:
                            self.assertEqual(mark, argb(expected["mark"]))

    # ------------------------------------------------------------------ the one gate (D5)

    def test_every_stopper_holds_motion_in_every_design_and_nothing_else_does(self):
        """The truth table: design, the product's Reduce motion, Windows' animation effects and High Contrast, against
        the one gate - the popup's, the card's, the icon's and the panel's too: the design never moves the answer."""
        rows = self.answer["motion"]
        self.assertEqual(len(rows), len(DESIGNS) * 8)
        for design, reduced, animating, contrast, held in rows:
            with self.subTest(design=design, reduced=reduced, animating=animating, contrast=contrast):
                self.assertEqual(held, reduced or not animating or contrast)

    def test_a_stored_still_draws_every_frame_v0610_still_drew(self):
        """v0.6.10's Still held the light as Reduce motion does, in Soft's colours with no glow. A stored Still reaches
        the window as Soft (Brand.DesignOf) with Reduce motion on, and the light is Soft's under Reduce motion, held."""
        stored = self.answer["storedStill"]
        self.assertEqual(stored["design"], "soft")
        for state in LIGHT_STATES:
            frames = stored["frames"][state]
            with self.subTest(state):
                self.assertEqual(frames, self.answer["light"]["soft|True|" + state])
                self.assertEqual(len({tuple(frame) for frame in frames}), 1, "the light does not move")

    def test_under_reduce_motion_no_design_moves_the_light(self):
        for design in DESIGNS:
            for state in LIGHT_STATES:
                frames = self.answer["light"][design + "|True|" + state]
                with self.subTest(design=design, state=state):
                    self.assertEqual(len({tuple(frame) for frame in frames}), 1)

    def test_plain_dims_the_light_on_its_breath_with_no_glow(self):
        """The critic's correction to D12: the dimming is the breath, not depth or a glow, so Plain keeps it. Successive
        frames of the dot differ in its colour, and nothing is ever drawn past the dot, where Soft's glow spreads."""
        side, dot = LIGHT_SIDE, brand.STATUS_DOT["window"] * LIGHT_SCALE
        ground = argb(brand.card_ground("light", "plain"))
        frames = self.answer["light"]["plain|False|monitoring"]
        centre = [frame[side // 2] for frame in frames]
        self.assertGreater(len(set(centre)), 2, "the dot's colour moves with its breath")
        outside = [x for x in range(side) if abs(x + 0.5 - side / 2) > dot + 2]
        for index, frame in enumerate(frames):
            with self.subTest(moment=LIGHT_MOMENTS[index]):
                self.assertEqual([frame[x] for x in outside], [ground] * len(outside), "no glow past the dot")
        soft = self.answer["light"]["soft|False|monitoring"]
        self.assertTrue(any(frame[x] != argb(brand.card_ground("light")) for frame in soft for x in outside),
                        "Soft's glow does spread past the dot, so the probe looked where a glow would be")

    def test_classic_breathes_with_its_glow(self):
        side, dot = LIGHT_SIDE, brand.STATUS_DOT["window"] * LIGHT_SCALE
        ground = argb(brand.card_ground("light", "classic"))
        frames = self.answer["light"]["classic|False|monitoring"]
        outside = [x for x in range(side) if abs(x + 0.5 - side / 2) > dot + 2]
        self.assertGreater(len({frame[side // 2] for frame in frames}), 2)
        self.assertTrue(any(frame[x] != ground for frame in frames for x in outside), "Classic keeps the glow")

    # ------------------------------------------------------------------ marks (D12, D14)

    def test_a_card_in_a_design_without_depth_leaves_its_ground_untouched(self):
        """Soft lifts a card with a shadow; Classic and Plain draw the card and its hairline and nothing round
        it: every pixel of the ground outside the card is the canvas."""
        for design in DESIGNS:
            for theme in brand.THEMES:
                card = self.answer["pictures"][design + "|" + theme]["card"]
                left, top, width, height = card["bounds"]
                # A pixel off the card's edge on each side is left out: anti-aliasing may touch it in any design.
                outside = (card["row"][:left - 1] + card["row"][left + width + 1:] + card["column"][:top - 1]
                           + card["column"][top + height + 1:])
                with self.subTest(design=design, theme=theme):
                    self.assertEqual((width, height), (200, 100), "laid out as asked")
                    self.assertEqual(card["canvas"], argb(brand.palette(theme, design)["canvas"]))
                    if brand.design_depth(design):
                        self.assertTrue(any(pixel != card["canvas"] for pixel in outside), "a lift is drawn round it")
                    else:
                        self.assertEqual(outside, [card["canvas"]] * len(outside), "nothing is drawn round it")

    def test_classic_draws_its_accent_bar_inside_the_cards_left_hairline_and_no_other_design_does(self):
        for design in DESIGNS:
            for theme in ("light", "dark", "contrast"):
                card = self.answer["pictures"][design + "|" + theme]["card"]
                left, _, width, _ = card["bounds"]
                bar = card["row"][left + 1:left + 1 + brand.ACCENT_BAR]
                beside = card["row"][left + 1 + brand.ACCENT_BAR + 2]
                with self.subTest(design=design, theme=theme):
                    if brand.design_accent_bar(design) and theme != "contrast":
                        self.assertTrue(all(far(pixel, card["accent"]) <= 2 for pixel in bar), "a bar in the accent")
                        self.assertLessEqual(far(beside, card["card"]), 2, "and the card's own ground past it")
                        self.assertLessEqual(far(card["row"][left], card["line"]), 2, "inside the hairline")
                    else:
                        self.assertTrue(all(far(pixel, card["accent"]) > 16 for pixel in bar), "no bar")

    def test_classic_underlines_the_current_tab_and_plain_draws_it_flat(self):
        for design in DESIGNS:
            for theme in brand.THEMES:
                tab = self.answer["pictures"][design + "|" + theme]["tab"]
                x, y, width, height = tab["face"]
                under = tab["column"][y + height - brand.ACCENT_BAR:y + height]
                above = tab["column"][y + 2:y + height - brand.ACCENT_BAR - 1]
                with self.subTest(design=design, theme=theme):
                    if brand.design_accent_bar(design):
                        self.assertEqual(under, [tab["accent"]] * brand.ACCENT_BAR, "underlined in the accent")
                        # Classic's well is its canvas, so a well would not show by its colour: by its hairline and
                        # its shade at the top of the face, which a tab on its ground does not have.
                        self.assertEqual(tab["column"][y:y + 3], [tab["canvas"]] * 3, "and not pressed into a well")
                    else:
                        self.assertNotIn(tab["accent"], under)
                    if brand.design_depth(design):
                        self.assertNotEqual(tab["column"][y:y + 3], [tab["canvas"]] * 3, "Soft's is pressed into one")
                    if not brand.design_depth(design) and not brand.design_accent_bar(design):
                        self.assertIn(tab["soft"], above, "a flat quiet-accent ground")
                section = self.answer["pictures"][design + "|" + theme]["section"]
                sx, sy, _, _ = section["face"]
                with self.subTest(design=design, theme=theme, tab="section"):
                    lead = section["row"][sx:sx + brand.ACCENT_BAR]
                    if brand.design_accent_bar(design):
                        self.assertEqual(lead, [section["accent"]] * brand.ACCENT_BAR, "a section's bar at its left")
                    else:
                        self.assertNotIn(section["accent"], lead)

    def test_high_contrast_pixels_are_the_same_in_every_design(self):
        """High Contrast replaces every design: the card on its ground, a chosen tab, a check box and a switch are drawn
        pixel for pixel alike whichever design is chosen - and so is the light, which does not move there."""
        first = self.answer["pictures"]["soft|contrast"]
        for design in DESIGNS[1:]:
            with self.subTest(design):
                self.assertEqual(self.answer["pictures"][design + "|contrast"], first)

    def test_a_flat_design_draws_its_switch_and_check_box_flat(self):
        """Classic and Plain have no well to sink a switch or an empty box into: each is its fill and its hairline, so
        the drawn switch and box differ from Soft's in the same colours only where Soft's well shades them."""
        for design in ("classic", "plain"):
            for theme in brand.THEMES:
                pixels = self.answer["pictures"][design + "|" + theme]["controls"]
                palette = brand.palette(theme, design)
                allowed = {argb(value) for value in palette.values()} | {argb(brand.card_ground(theme, design))}
                with self.subTest(design=design, theme=theme):
                    # No shade of a well: every fully covered pixel is one of the design's own colours; what is not is
                    # an anti-aliased edge between two of them, which a shadow's gradient would outnumber.
                    stray = [pixel for pixel in pixels if pixel not in allowed]
                    self.assertLess(len(stray), len(pixels) // 8, "shaded, not flat")

    def test_rows_stay_flat_hairline_rows_in_every_design(self):
        """The user's rule (window-lists-stay-flat): Pending's and History's rows are drawn with no design flag at all -
        no depth, no accent bar, no corner - so every design draws the same flat row over its hairline."""
        dashboard = guiscan.dashboard()
        for name in ("private void DrawCell(", "private void DrawHeader("):
            start = dashboard.index(name)
            body = dashboard[start:dashboard.index("\n        }\n", start)]
            with self.subTest(name):
                for flag in ("Palette.Depth", "Palette.AccentBar", "Palette.Halo", "Palette.Radius", "StampOuter",
                             "Palette.Design"):
                    self.assertNotIn(flag, body)

    # ------------------------------------------------------------------ layout (D15)

    def test_a_design_changes_paint_and_never_layout(self):
        """The layout audit in each design, English at 100%: where every control is on every page and Settings section
        is the same text in all of them, and so is the audit's report. So the audit test_gui_layout runs in every language
        at every scaling holds for every design."""
        soft = self.answer["layout"]["soft"]
        self.assertGreater(soft["geometry"].count("\n"), 500, "the audit wrote down where things are")
        for page in ("== overview", "== pending", "== history", "== statistics", "== diagnostics",
                     "== settings/appearance"):
            self.assertIn(page + "\n", soft["geometry"])
        for design in DESIGNS[1:]:
            drawn = self.answer["layout"][design]
            with self.subTest(design):
                self.assertEqual(drawn["report"], soft["report"])
                self.assertEqual(drawn["geometry"], soft["geometry"])


class DesignSourceRuleTests(unittest.TestCase):
    """Rules for the source, so they fail without a compiler too."""

    def test_every_motion_in_the_window_reads_the_one_gate(self):
        self.assertIn("if (control == null || Soft.ReduceMotion ||", guiscan.member_body("Motion", "Allowed"))
        self.assertIn("!Soft.ReduceMotion", guiscan.member_body("SoftPage", "ScrollTo"))
        halo = guiscan.type_body("HaloDot")
        self.assertIn("Soft.ReduceMotion", guiscan.member_body("HaloDot", "ShouldRun"))
        self.assertIn("Brand.Glow(state, since, since, Soft.ReduceMotion,", halo)
        self.assertIn("MotionAllowed(Soft.ReduceMotion,", guiscan.member_body("TaskbarMark", "MayMove"))
        # No design decides what moves: the gates v0.6.10 had for it are gone, and neither Brand nor Palette.Look has
        # a motion rule to ask.
        for name in guiscan.handwritten():
            code = "\n".join(line for line in guiscan.read(name).splitlines() if not line.lstrip().startswith("//"))
            with self.subTest(name):
                self.assertEqual(re.findall(r"\b(?:LightStill|ControlsStill|Look\.Breathes|Look\.Glides)\b", code), [])
        generated = (guiscan.ROOT / "gui" / "Brand.cs").read_text(encoding="utf-8")
        for rule in ("DesignBreathes", "DesignGlides", "Breathes", "Glides"):
            self.assertNotRegex(generated, r"\b%s\b" % rule)

    def test_the_design_adds_nothing_to_what_the_window_asks_of_windows(self):
        """B16: no new question is asked of Windows. The design is a stored setting, read with the theme."""
        design = guiscan.type_body("Design")
        for asked in ("DllImport", "Registry", "SystemParametersInfo", "Environment."):
            self.assertNotIn(asked, design)


if __name__ == "__main__":
    unittest.main()
