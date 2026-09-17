r"""The v0.6.4 window material: the panel's shadows, its fields, and the status light.

The real compiled window is loaded and its drawing code is asked for numbers through
reflection, as `test_gui_v063.py` does, so what the window draws - not a second copy of the
rule - is held to `brand.py`, which the panel's stylesheet and the tray popup read as well.
Nothing is shown: the shadows are drawn into bitmaps, and the one native control measured
lives in Windows' hidden parking window.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from codex_auto_resume import brand

ROOT = Path(__file__).resolve().parents[1]
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")

SCALES = (1.0, 1.5, 2.0)
RECIPES = ("card", "control", "inset")
SIDES = ("left", "top", "right", "bottom")
STATES = ("monitoring", "waiting", "checking", "recovering", "attention", "failed", "paused", "idle",
          "stopped", "")
ELAPSED = (0.0, 250.0, 900.0, 1100.0, 1799.0, 1800.0, 2700.0, 3600.0, 5000.0, 12345.6)
SINCE = (-1.0, 0.0, 350.0, 700.0, 1399.0, 1400.0, 9000.0)
# recipe -> (width, height, margin) in CSS px; drawn at each scale
BODIES = {"card": (240, 160, 32), "control": (160, 34, 16), "inset": (280, 35, 0)}
GROUND = {"card": "canvas", "control": "surface", "inset": "inset"}
FONTS = (9.0, 12.0)

PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$static = [Reflection.BindingFlags]'Static,NonPublic,Public'
$instance = [Reflection.BindingFlags]'Instance,NonPublic,Public'
$elevation = $assembly.GetType('CodexAutoResume.Elevation', $true)
$halo = $assembly.GetType('CodexAutoResume.HaloDot', $true)
$palette = $assembly.GetType('CodexAutoResume.Palette', $true)
$brandType = $assembly.GetType('CodexAutoResume.Brand', $true)
$comboType = $assembly.GetType('CodexAutoResume.SoftCombo', $true)
$numberType = $assembly.GetType('CodexAutoResume.SoftNumber', $true)
$cardType = $assembly.GetType('CodexAutoResume.SoftCard', $true)
$profile = $elevation.GetMethod('Profile', $static)
$render = $elevation.GetMethod('Render', $static)
$reach = $elevation.GetMethod('Reach', $static, $null, [Type[]]@([string], [double]), $null)
$opacity = $halo.GetMethod('HaloOpacity', $static)
$scaleOf = $halo.GetMethod('HaloScale', $static)
$arcOf = $halo.GetMethod('HaloArc', $static)
$colour = $halo.GetMethod('DotColour', $static, $null, [Type[]]@([string], [bool]), $null)
foreach ($pair in @(@('Profile', $profile), @('Render', $render), @('Reach', $reach), @('HaloOpacity', $opacity),
                    @('HaloScale', $scaleOf), @('HaloArc', $arcOf), @('DotColour', $colour))) {
    if (-not $pair[1]) { throw ('missing ' + $pair[0]) }
}

$out = @{ profile = @{}; render = @{}; reach = @{}; glow = @(); colour = @{}; system = @{}; combo = @(); other = @{} }
$bodies = ConvertFrom-Json $env:CAR_BODIES
foreach ($scale in (ConvertFrom-Json $env:CAR_SCALES)) {
    $key = ([double]$scale).ToString('0.0', [Globalization.CultureInfo]::InvariantCulture)
    $out.profile[$key] = @{}
    $out.render[$key] = @{}
    $out.reach[$key] = @{}
    foreach ($recipe in (ConvertFrom-Json $env:CAR_RECIPES)) {
        $out.profile[$key][$recipe] = @($profile.Invoke($null, [object[]]@([string]$recipe, [double]$scale)) | ForEach-Object { [double]$_ })
        $padding = $reach.Invoke($null, [object[]]@([string]$recipe, [double]$scale))
        $out.reach[$key][$recipe] = @($padding.Left, $padding.Top, $padding.Right, $padding.Bottom)
        $body = $bodies.$recipe
        $width = [int][Math]::Round($body[0] * $scale)
        $height = [int][Math]::Round($body[1] * $scale)
        $margin = [int][Math]::Round($body[2] * $scale)
        $pixels = [int[]]$render.Invoke($null, [object[]]@([string]$recipe, [double]$scale, $width, $height, $margin))
        $across = $width + 2 * $margin
        $down = $height + 2 * $margin
        $middle = $margin + [int][Math]::Floor($height / 2)
        # [int[]]::new, not New-Object: an array a cmdlet returns is serialised as {value, Count}.
        $row = [int[]]::new($across)
        [Array]::Copy($pixels, $middle * $across, $row, 0, $across)
        $column = [int[]]::new($down)
        $centre = $margin + [int][Math]::Floor($width / 2)
        for ($y = 0; $y -lt $down; $y++) { $column[$y] = $pixels[$y * $across + $centre] }
        $seam = @()
        if ($margin -gt 0) {
            $band = [int[]]::new($across)
            [Array]::Copy($pixels, ($margin + $height + [int][Math]::Round(3 * $scale)) * $across, $band, 0, $across)
            $seam = $band
        }
        $out.render[$key][$recipe] = @{ width = $width; height = $height; margin = $margin; row = $row; column = $column; seam = $seam }
    }
}

foreach ($state in (ConvertFrom-Json $env:CAR_STATES)) {
    $out.colour[$state] = $colour.Invoke($null, [object[]]@([string]$state, $false)).ToArgb()
    $out.system[$state] = $colour.Invoke($null, [object[]]@([string]$state, $true)).Name
    foreach ($elapsed in (ConvertFrom-Json $env:CAR_ELAPSED)) {
        foreach ($since in (ConvertFrom-Json $env:CAR_SINCE)) {
            foreach ($reduced in @($false, $true)) {
                $call = [object[]]@([string]$state, [double]$elapsed, [double]$since, [bool]$reduced)
                $out.glow += ,@([string]$state, [double]$elapsed, [double]$since, [bool]$reduced,
                                [double]$opacity.Invoke($null, $call), [double]$scaleOf.Invoke($null, $call),
                                [double]$arcOf.Invoke($null, $call))
            }
        }
    }
}

$field = [int]$comboType.GetProperty('FieldHeight', $static).GetValue($null, $null)
$recreate = [System.Windows.Forms.Control].GetMethod('RecreateHandle', $instance)
foreach ($points in (ConvertFrom-Json $env:CAR_FONTS)) {
    $combo = [Activator]::CreateInstance($comboType, $true)
    $windowless = -not $combo.IsHandleCreated
    $combo.Font = New-Object System.Drawing.Font('Segoe UI', ([single]$points))
    $null = $combo.Items.Add('Same as the interface (English)')
    $combo.SelectedIndex = 0
    $stillWindowless = -not $combo.IsHandleCreated
    $before = $combo.GetPreferredSize([System.Drawing.Size]::Empty).Height
    $heightBefore = $combo.Height
    # Its window, made as showing it would make it.
    $null = $combo.Handle
    $made = $combo.Height
    $combo.Font = New-Object System.Drawing.Font('Segoe UI', ([single]$points + 1))
    $height = $combo.Height
    $preferred = $combo.GetPreferredSize([System.Drawing.Size]::Empty).Height
    $null = $recreate.Invoke($combo, $null)
    $out.combo += ,@([double]$points, $before, $heightBefore, $height, $preferred, $field,
                     $windowless, $stillWindowless, $made, $combo.Height, $combo.IsHandleCreated)
    $combo.Dispose()
}
$number = [Activator]::CreateInstance($numberType, $true)
$spin = $numberType.GetField('Spin', $instance).GetValue($number)
$out.other.spin = $spin.GetType().FullName
$out.other.numberHeight = $number.Height
$out.other.room = [int]$cardType.GetProperty('Room', $static).GetValue($null, $null)
$number.Dispose()
$out.other.contrast = [bool]$palette.GetField('Contrast', $static).GetValue($null)
$out.other.hover = $palette.GetField('AccentHover', $static).GetValue($null).ToArgb()
$out.other.pressed = $palette.GetField('AccentPressed', $static).GetValue($null).ToArgb()

$out | ConvertTo-Json -Depth 8 -Compress
"""


def argb(value: str) -> int:
    """A `#RRGGBB` token as the signed 32-bit ARGB integer Color.ToArgb() returns."""
    r, g, b = brand.rgb(value)
    unsigned = 0xFF000000 | (r << 16) | (g << 8) | b
    return unsigned - (1 << 32)


def channels(pixel: int) -> tuple:
    pixel &= 0xFFFFFFFF
    return ((pixel >> 16) & 255, (pixel >> 8) & 255, pixel & 255)


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class MaterialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll",
                        "/reference:System.Windows.Forms.dll",
                        *[str(ROOT / "gui" / name)
                          for name in ("SettingsApp.cs", "Dashboard.cs", "Controls.cs", "Brand.cs")]],
                       check=True, capture_output=True, timeout=300)
        probe = work / "probe.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        cls.result = subprocess.run(
            [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
            env=dict(os.environ, CAR_EXE=str(exe), CAR_SCALES=json.dumps(SCALES),
                     CAR_RECIPES=json.dumps(RECIPES), CAR_BODIES=json.dumps(BODIES),
                     CAR_STATES=json.dumps(STATES), CAR_ELAPSED=json.dumps(ELAPSED),
                     CAR_SINCE=json.dumps(SINCE), CAR_FONTS=json.dumps(FONTS)))
        cls.answer = (json.loads(cls.result.stdout)
                      if cls.result.returncode == 0 and cls.result.stdout.strip() else {})

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-2000:])

    # ---------------------------------------------------------------- shadows

    def test_every_shadow_is_the_panels_gaussian_within_two_levels(self):
        """Each stamped shadow, across the middle of each edge, against brand.shadow_alpha."""
        for scale in SCALES:
            for recipe in RECIPES:
                values = self.answer["profile"]["%.1f" % scale][recipe]
                samples = len(values) // 8
                self.assertGreater(samples, 4)
                for index, shadow in enumerate(brand.SHADOWS["light"][recipe]):
                    for side_index, side in enumerate(SIDES):
                        for i in range(samples):
                            expected = brand.shadow_alpha(shadow, i + 0.5, side, scale)
                            got = values[(index * 4 + side_index) * samples + i]
                            with self.subTest(scale=scale, recipe=recipe, shadow=index, side=side, d=i + 0.5):
                                self.assertLessEqual(abs(got - expected), 2 / 255,
                                                     "%.4f against %.4f" % (got, expected))

    def test_a_composited_body_matches_the_panel_model(self):
        """The whole recipe - highlight, shadow, fill, hairline - as a page shows it."""
        for scale in SCALES:
            hairline = max(1, int(math.floor(scale + 1e-6)))
            for recipe in RECIPES:
                drawn = self.answer["render"]["%.1f" % scale][recipe]
                width, height, margin = drawn["width"], drawn["height"], drawn["margin"]
                row, column = drawn["row"], drawn["column"]
                if recipe == "inset":
                    # Inside the hairline, from each edge inward; the far edge is out of reach.
                    reach = int(math.ceil(6 * scale))
                    checks = []
                    for i in range(reach):
                        checks.append(("left", i, row[margin + hairline + i]))
                        checks.append(("right", i, row[margin + width - hairline - 1 - i]))
                        checks.append(("top", i, column[margin + hairline + i]))
                        checks.append(("bottom", i, column[margin + height - hairline - 1 - i]))
                else:
                    checks = []
                    for i in range(margin):
                        checks.append(("left", i, row[margin - 1 - i]))
                        checks.append(("right", i, row[margin + width + i]))
                        checks.append(("top", i, column[margin - 1 - i]))
                        checks.append(("bottom", i, column[margin + height + i]))
                for side, i, pixel in checks:
                    expected = brand.elevation_colour(recipe, side, i + 0.5, GROUND[recipe], scale=scale)
                    with self.subTest(scale=scale, recipe=recipe, side=side, d=i + 0.5):
                        for got, want in zip(channels(pixel), expected):
                            self.assertLessEqual(abs(got - want), 3, "%s against %s" % (
                                channels(pixel), tuple(round(v, 1) for v in expected)))

    def test_a_long_edge_has_no_seam_where_its_pieces_meet(self):
        for scale in SCALES:
            for recipe in ("card", "control"):
                drawn = self.answer["render"]["%.1f" % scale][recipe]
                width, margin, band = drawn["width"], drawn["margin"], drawn["seam"]
                corner = int(math.ceil(brand.RADII[recipe if recipe == "card" else "control"] * scale
                                       + 1.5 * brand.SHADOWS["light"][recipe][0].blur * scale)) + 2
                stretch = band[margin + corner:margin + width - corner]
                with self.subTest(scale=scale, recipe=recipe):
                    self.assertTrue(stretch, "the body is too short to have a straight middle")
                    self.assertEqual(len(set(stretch)), 1, "the stretched middle is not one colour")

    def test_the_reach_a_ground_keeps_free_is_brands(self):
        for scale in SCALES:
            for recipe in ("card", "control"):
                with self.subTest(scale=scale, recipe=recipe):
                    self.assertEqual(tuple(self.answer["reach"]["%.1f" % scale][recipe]),
                                     brand.reach(recipe, scale=scale))
            self.assertEqual(self.answer["reach"]["%.1f" % scale]["inset"], [0, 0, 0, 0])

    # ---------------------------------------------------------------- status light

    def test_the_glow_is_brands_for_every_state_and_moment(self):
        self.assertEqual(len(self.answer["glow"]), len(STATES) * len(ELAPSED) * len(SINCE) * 2)
        for state, elapsed, since, reduced, opacity, scale, arc in self.answer["glow"]:
            frame = brand.glow(state, elapsed, since if since >= 0 else None, reduced=reduced)
            with self.subTest(state=state, elapsed=elapsed, since=since, reduced=reduced):
                if frame is None:
                    self.assertEqual((opacity, scale, arc), (0, 0, -1))
                    continue
                self.assertAlmostEqual(opacity, frame["opacity"], delta=1e-9)
                self.assertAlmostEqual(scale, frame["scale"], delta=1e-9)
                self.assertAlmostEqual(arc, -1 if frame["arc"] is None else frame["arc"], delta=1e-9)

    def test_the_dot_is_brands_colour_for_every_state(self):
        """Cyan for every running state, the greys unchanged for a pause and for a watcher that
        is stopped or unknown, amber for one that runs unwell, red for a failure."""
        for state in STATES:
            with self.subTest(state):
                self.assertEqual(self.answer["colour"][state], argb(brand.LIGHT[brand.status_fill(state)]))
                self.assertEqual(self.answer["system"][state], brand.status_system(state))
        for state in ("monitoring", "waiting", "checking", "recovering"):
            self.assertEqual(self.answer["colour"][state], argb(brand.LIGHT["active"]))
        for state in ("idle", "stopped", ""):
            self.assertEqual(self.answer["colour"][state], argb(brand.LIGHT["idle"]))

    # ---------------------------------------------------------------- fields

    def test_a_drop_down_reports_the_height_it_really_has(self):
        """A row measured from the base class's answer - 33 for a 42-pixel field - cut the
        field's bottom edge off.

        A drop-down has no window until it is shown, as every other field in a Settings section
        built out of sight has none: setting an owner-drawn combo's item height used to make one
        in the constructor, so the height it had "before a window" was never measured at all.
        """
        for (points, before, height_before, height, preferred, field,
             windowless, still_windowless, made, recreated, has_window) in self.answer["combo"]:
            with self.subTest(points=points):
                self.assertTrue(windowless, "constructing a drop-down gave it a window")
                self.assertTrue(still_windowless, "a font, an item or a choice given it before it is shown gave it a window")
                self.assertEqual(before, field, "what it reports before it has a window")
                self.assertEqual(height_before, field, "the height it has before it has a window")
                self.assertEqual(made, field, "once it has a window")
                self.assertEqual(height, field, "after a font change")
                self.assertEqual(preferred, height)
                self.assertTrue(has_window)
                self.assertEqual(recreated, field, "after its window is made again")

    def test_a_number_field_is_a_well_around_the_real_spin_box(self):
        self.assertEqual(self.answer["other"]["spin"], "System.Windows.Forms.NumericUpDown")
        self.assertEqual(self.answer["other"]["numberHeight"], self.answer["combo"][0][5])

    def test_a_card_keeps_no_band_for_its_shadow(self):
        self.assertEqual(self.answer["other"]["room"], 0)

    def test_the_primary_button_states_are_brands(self):
        if self.answer["other"]["contrast"]:
            self.skipTest("High Contrast is on; the palette is system colours")
        self.assertEqual(self.answer["other"]["hover"], argb(brand.LIGHT["accent_hover"]))
        self.assertEqual(self.answer["other"]["pressed"], argb(brand.LIGHT["accent_pressed"]))


def compile_window(work: Path) -> Path:
    exe = work / "CodexAutoResumeSettings.exe"
    subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                    "/reference:System.dll", "/reference:System.Drawing.dll",
                    "/reference:System.Windows.Forms.dll",
                    *[str(ROOT / "gui" / name)
                      for name in ("SettingsApp.cs", "Dashboard.cs", "Controls.cs", "Brand.cs")]],
                   check=True, capture_output=True, timeout=300)
    return exe


SCROLL_PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
Add-Type -Namespace ScrollProbe -Name Native -MemberDefinition @'
[DllImport("user32.dll")] public static extern System.IntPtr SendMessage(System.IntPtr window, int message, System.IntPtr wParam, System.IntPtr lParam);
[DllImport("user32.dll")] public static extern int GetWindowLong(System.IntPtr window, int index);
'@
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$static = [Reflection.BindingFlags]'Static,NonPublic,Public'
$instance = [Reflection.BindingFlags]'Instance,NonPublic,Public'
$barType = $assembly.GetType('CodexAutoResume.SoftBar', $true)
$pageType = $assembly.GetType('CodexAutoResume.SoftPage', $true)
$hostType = $assembly.GetType('CodexAutoResume.SoftListHost', $true)
$listType = $assembly.GetType('CodexAutoResume.SoftList', $true)
$comboType = $assembly.GetType('CodexAutoResume.SoftCombo', $true)
$softType = $assembly.GetType('CodexAutoResume.Soft', $true)
$formType = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$scrollerType = $assembly.GetType('CodexAutoResume.ISoftScroller', $true)
function Get-Member2($target, [string]$name) { return $target.GetType().GetProperty($name, $instance).GetValue($target, $null) }
function Set-Member2($target, [string]$name, $value) { $target.GetType().GetProperty($name, $instance).SetValue($target, $value, $null) }
function Invoke-Member2($target, [string]$name, [object[]]$arguments) {
    $method = @($target.GetType().GetMethods($instance) | Where-Object { $_.Name -eq $name -and $_.GetParameters().Count -eq $arguments.Count })[0]
    return $method.Invoke($target, $arguments)
}
function Box($r) { return ,@([int]$r.X, [int]$r.Y, [int]$r.Width, [int]$r.Height) }
$wheel = 0x020A
function Turn($control, [int]$delta) { $null = [ScrollProbe.Native]::SendMessage($control.Handle, $wheel, [IntPtr]($delta -shl 16), [IntPtr]::Zero) }
$reduce = $softType.GetField('ReduceMotionSetting', $static)
$out = @{}
$out.scale = [double]$formType.GetProperty('DpiScale', $static).GetValue($null)
$out.lines = [int][Windows.Forms.SystemInformation]::MouseWheelScrollLines
foreach ($name in @('TrackWidth', 'ThumbInset', 'TrackMargin', 'MinThumb', 'Line', 'RevealRoom')) { $out[$name] = [int]$barType.GetField($name, $static).GetValue($null) }
$out.gutter = [int]$barType.GetProperty('Gutter', $static).GetValue($null)

# The arithmetic.
$thumb = $barType.GetMethod('Thumb', $static)
$out.thumb = @()
foreach ($case in (ConvertFrom-Json $env:CAR_THUMBS)) {
    $call = [object[]]@([int]$case[0], [int]$case[1], [int]$case[2], [int]$case[3], [int]$case[4], $null, $null)
    $null = $thumb.Invoke($null, $call)
    $out.thumb += ,@([int]$call[5], [int]$call[6])
}
$offsetAt = $barType.GetMethod('OffsetAt', $static)
$out.offsetAt = @()
foreach ($case in (ConvertFrom-Json $env:CAR_OFFSETS)) { $out.offsetAt += [int]$offsetAt.Invoke($null, [object[]]@([int]$case[0], [int]$case[1], [int]$case[2], [int]$case[3], [int]$case[4])) }
$wheelStep = $barType.GetMethod('WheelStep', $static)
$out.wheelStep = @()
foreach ($case in (ConvertFrom-Json $env:CAR_WHEELS)) { $out.wheelStep += [int]$wheelStep.Invoke($null, [object[]]@([int]$case[0], [int]$case[1], [int]$case[2], [int]$case[3])) }
$pageStep = $barType.GetMethod('PageStep', $static)
$out.pageStep = @()
foreach ($case in (ConvertFrom-Json $env:CAR_PAGES)) { $out.pageStep += [int]$pageStep.Invoke($null, [object[]]@([int]$case[0], [int]$case[1])) }
$intoView = $barType.GetMethod('IntoView', $static)
$out.intoView = @()
foreach ($case in (ConvertFrom-Json $env:CAR_VIEWS)) { $out.intoView += [int]$intoView.Invoke($null, [object[]]@([int]$case[0], [int]$case[1], [int]$case[2], [int]$case[3], [int]$case[4], [int]$case[5])) }
$glideStep = $barType.GetMethod('GlideStep', $static)
$out.glide = @()
$at = 0
for ($frame = 0; $frame -lt 40 -and $at -ne 150; $frame++) { $at = [int]$glideStep.Invoke($null, [object[]]@([int]$at, 150)); $out.glide += $at }

# The colours, as High Contrast and as the brand has them.
$trackFill = $barType.GetMethod('TrackFill', $static)
$trackEdge = $barType.GetMethod('TrackEdge', $static)
$thumbFill = $barType.GetMethod('ThumbFill', $static)
$thumbEdge = $barType.GetMethod('ThumbEdge', $static)
$out.contrast = @{ track = @($trackFill.Invoke($null, [object[]]@($true)).Name, $trackEdge.Invoke($null, [object[]]@($true)).Name)
                   thumb = @(); edge = @() }
$out.light = @{ track = @($trackFill.Invoke($null, [object[]]@($false)).ToArgb(), $trackEdge.Invoke($null, [object[]]@($false)).ToArgb())
                thumb = @(); edge = @() }
foreach ($state in 0, 1, 2) {
    $out.contrast.thumb += [string]$thumbFill.Invoke($null, [object[]]@([int]$state, $true)).Name
    $out.contrast.edge += [string]$thumbEdge.Invoke($null, [object[]]@([int]$state, $true)).Name
    $out.light.thumb += [int]$thumbFill.Invoke($null, [object[]]@([int]$state, $false)).ToArgb()
    $out.light.edge += [int]$thumbEdge.Invoke($null, [object[]]@([int]$state, $false)).ToArgb()
}

# A page, never shown: 300 by 400 with 10 of padding, holding a panel docked to its top.
$reduce.SetValue($null, $true)
function New-Page([int]$height) {
    $page = [Activator]::CreateInstance($pageType, $true)
    $page.Size = New-Object Drawing.Size 300, 400
    $page.Padding = New-Object Windows.Forms.Padding 10
    $content = New-Object Windows.Forms.Panel
    $content.Dock = [Windows.Forms.DockStyle]::Top
    $content.Height = $height
    $page.Controls.Add($content)
    Set-Member2 $page 'Scrolls' $true
    $page.PerformLayout()
    return ,@($page, $content)
}
function State($page) {
    $bar = Get-Member2 $page 'Bar'
    return @{ overflowing = [bool](Get-Member2 $page 'Overflowing'); extent = [int](Get-Member2 $page 'Extent')
              offset = [int](Get-Member2 $page 'Offset'); display = (Box $page.DisplayRectangle)
              track = (Box (Get-Member2 $bar 'Track')); thumb = (Box (Get-Member2 $bar 'Thumb')); top = [int]$page.Controls[0].Top }
}
$short = New-Page 200
$out.short = State $short[0]
$tall = New-Page 1000
$page = $tall[0]
$out.tall = State $page
$null = Invoke-Member2 $page 'ScrollTo' @([int]300, $false)
$out.scrolled = State $page
$null = Invoke-Member2 $page 'ScrollTo' @([int]5000, $false)
$out.clamped = State $page
$null = Invoke-Member2 $page 'ScrollTo' @([int]0, $false)
$out.wheelDown = @([bool](Invoke-Member2 $page 'Wheel' @([int]-120)), [int](Get-Member2 $page 'Offset'))
$null = Invoke-Member2 $page 'ScrollTo' @([int]0, $false)
$out.wheelUpAtTop = @([bool](Invoke-Member2 $page 'Wheel' @([int]120)), [int](Get-Member2 $page 'Offset'))
$null = $scrollerType.GetMethod('Page').Invoke($page, [object[]]@([int]1))
$out.paged = [int](Get-Member2 $page 'Offset')
$page.Size = New-Object Drawing.Size 300, 1200
$page.PerformLayout()
$out.grown = State $page

# The wheel over a child that does not use it, and over a drop-down that must not change under it.
$over = New-Page 1000
$label = New-Object Windows.Forms.Label
$label.Text = 'over this'
$label.Dock = [Windows.Forms.DockStyle]::Top
$over[1].Controls.Add($label)
$combo = [Activator]::CreateInstance($comboType, $true)
$null = $combo.Items.Add('one')
$null = $combo.Items.Add('two')
$combo.Dock = [Windows.Forms.DockStyle]::Top
$over[1].Controls.Add($combo)
$null = $formType.GetMethod('IgnoreWheel', $static).Invoke($null, [object[]]@($combo))
$over[0].CreateControl()
$combo.SelectedIndex = 0
Turn $label -120
$out.overLabel = [int](Get-Member2 $over[0] 'Offset')
$null = Invoke-Member2 $over[0] 'ScrollTo' @([int]0, $false)
Turn $combo -120
$out.overCombo = @([int]$combo.SelectedIndex, [int](Get-Member2 $over[0] 'Offset'))

# Focus arriving from the keyboard: twenty buttons 50 apart, then one added after the page was built.
$reveal = [Activator]::CreateInstance($pageType, $true)
$reveal.Size = New-Object Drawing.Size 300, 400
$stack = New-Object Windows.Forms.Panel
$stack.Dock = [Windows.Forms.DockStyle]::Top
$stack.Height = 1000
for ($i = 0; $i -lt 20; $i++) { $button = New-Object Windows.Forms.Button; $button.SetBounds(0, $i * 50, 100, 40); $stack.Controls.Add($button) }
$reveal.Controls.Add($stack)
Set-Member2 $reveal 'Scrolls' $true
$reveal.PerformLayout()
$onEnter = [Windows.Forms.Control].GetMethod('OnEnter', $instance)
$null = $onEnter.Invoke($stack.Controls[15], [object[]]@([EventArgs]::Empty))
$below = [int](Get-Member2 $reveal 'Offset')
$null = $onEnter.Invoke($stack.Controls[2], [object[]]@([EventArgs]::Empty))
$above = [int](Get-Member2 $reveal 'Offset')
$late = New-Object Windows.Forms.Button
$late.SetBounds(0, 1000, 100, 40)
$stack.Height = 1050
$stack.Controls.Add($late)
$reveal.PerformLayout()
$null = $onEnter.Invoke($late, [object[]]@([EventArgs]::Empty))
$out.reveal = @($below, $above, [int](Get-Member2 $reveal 'Offset'))

# Motion: a glide when motion is allowed and the page is on a window, none when it is reduced.
$reduce.SetValue($null, $false)
$moving = New-Page 1000
$null = $moving[0].Handle
$out.motion = @{ reduced = [bool]$softType.GetProperty('ReduceMotion', $static).GetValue($null)
                 shown = [bool]$softType.GetMethod('Shown', $static).Invoke($null, [object[]]@($moving[0])) }
$null = Invoke-Member2 $moving[0] 'ScrollTo' @([int]200, $true)
$out.motion.allowed = @([bool](Get-Member2 $moving[0] 'Gliding'), [int](Get-Member2 $moving[0] 'Offset'))
$null = Invoke-Member2 $moving[0] 'ScrollTo' @([int]0, $false)
$reduce.SetValue($null, $true)
$null = Invoke-Member2 $moving[0] 'ScrollTo' @([int]200, $true)
$out.motion.still = @([bool](Get-Member2 $moving[0] 'Gliding'), [int](Get-Member2 $moving[0] 'Offset'))

# A list of sixty rows in a host 300 by 200, with windows and never shown.
$list = [Activator]::CreateInstance($listType, $true)
$list.View = [Windows.Forms.View]::Details
$list.BorderStyle = [Windows.Forms.BorderStyle]::None
$null = $list.Columns.Add('Conversation', 120)
for ($i = 0; $i -lt 60; $i++) { $null = $list.Items.Add('row ' + $i) }
$listHost = $hostType.GetConstructors($instance)[0].Invoke([object[]]@($list))
$listHost.Size = New-Object Drawing.Size 300, 200
$listHost.CreateControl()
$listHost.PerformLayout()
$null = Invoke-Member2 $listHost 'Sync' @()
$clip = Get-Member2 $listHost 'Clip'
$out.list = @{ overflowing = [bool](Get-Member2 $listHost 'Overflowing')
               native = (([ScrollProbe.Native]::GetWindowLong($list.Handle, -16)) -band 0x00200000) -ne 0
               host = $listHost.Width; clip = $clip.Width; client = $list.ClientSize.Width; width = $list.Width
               extent = [int]$scrollerType.GetProperty('Extent').GetValue($listHost, $null)
               viewport = [int]$scrollerType.GetProperty('Viewport').GetValue($listHost, $null)
               track = (Box (Get-Member2 (Get-Member2 $listHost 'Bar') 'Track')) }
$null = $scrollerType.GetMethod('ScrollTo').Invoke($listHost, [object[]]@([int]10))
$out.list.scrolled = @([int]$scrollerType.GetProperty('Offset').GetValue($listHost, $null), [int]$list.TopItem.Index)
$out | ConvertTo-Json -Depth 8 -Compress
"""

# (track, extent, viewport, offset, minimum) -> (start, length)
THUMBS = [((300, 1000, 400, 0, 48), (0, 120)), ((300, 1000, 400, 600, 48), (180, 120)),
          ((300, 1000, 400, 300, 48), (90, 120)), ((300, 1000, 400, 9999, 48), (180, 120)),
          ((300, 100000, 400, 50000, 48), (127, 48)), ((300, 400, 400, 0, 48), (0, 300)),
          ((30, 1000, 400, 500, 48), (0, 30))]
# (track, extent, viewport, length, start) -> offset
OFFSETS = [((300, 1000, 400, 120, 0), 0), ((300, 1000, 400, 120, 90), 300), ((300, 1000, 400, 120, 180), 600),
           ((300, 1000, 400, 120, 500), 600), ((300, 1000, 400, 120, -5), 0)]
# (delta, lines, line, viewport) -> pixels, a turn down positive
WHEELS = [((-120, 3, 50, 400), 150), ((120, 3, 50, 400), -150), ((-40, 3, 50, 400), 50),
          ((-120, -1, 50, 400), 350), ((-120, 0, 50, 400), 0)]
PAGES = [((400, 50), 350), ((40, 50), 50), ((0, 0), 1)]
# (offset, top, bottom, viewport, margin, extent) -> offset
VIEWS = [((0, 100, 140, 400, 16, 2000), 0), ((0, 600, 640, 400, 16, 2000), 256), ((500, 100, 140, 400, 16, 2000), 84),
         ((0, 100, 900, 400, 16, 2000), 84), ((0, 1990, 2000, 400, 16, 2000), 1600), ((300, 10, 30, 400, 16, 2000), 0)]


def px(value: int, scale: float) -> int:
    """Soft.Px: C#'s Math.Round, which rounds a half to even, as Python's round does."""
    return int(round(value * scale))


def thumb(track, extent, viewport, offset, minimum):
    if track <= 0 or extent <= viewport or viewport <= 0:
        return 0, max(0, track)
    length = min(track, max(min(minimum, track), int(round(track * viewport / extent))))
    span = extent - viewport
    return int(round((track - length) * max(0, min(span, offset)) / span)), length


def luminance(pixel: int) -> float:
    r, g, b = channels(pixel)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class SoftScrollTests(unittest.TestCase):
    """The soft scroll bar every page, the Settings sections, the gate list and the lists scroll on.

    The window's own classes are built and never shown: a page and a list host hold stand-in content,
    the wheel is sent as the message Windows sends, and focus arriving is raised as the control's own
    Enter. Nothing is sent to any window but these.
    """

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = compile_window(work)
        probe = work / "scroll.ps1"
        probe.write_text(SCROLL_PROBE, encoding="utf-8")
        cls.result = subprocess.run(
            [str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
            env=dict(os.environ, CAR_EXE=str(exe),
                     CAR_THUMBS=json.dumps([case for case, _ in THUMBS]),
                     CAR_OFFSETS=json.dumps([case for case, _ in OFFSETS]),
                     CAR_WHEELS=json.dumps([case for case, _ in WHEELS]),
                     CAR_PAGES=json.dumps([case for case, _ in PAGES]),
                     CAR_VIEWS=json.dumps([case for case, _ in VIEWS])))
        cls.answer = (json.loads(cls.result.stdout)
                      if cls.result.returncode == 0 and cls.result.stdout.strip() else {})

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-3000:])
        self.scale = self.answer["scale"]

    def px(self, value):
        return px(value, self.scale)

    def test_the_thumb_is_as_long_as_what_shows_and_travels_the_whole_track(self):
        for (case, expected), got in zip(THUMBS, self.answer["thumb"]):
            with self.subTest(case=case):
                self.assertEqual(tuple(got), expected)
                self.assertEqual(tuple(got), thumb(*case))

    def test_dragging_the_thumb_lands_on_the_offset_it_stands_for(self):
        for (case, expected), got in zip(OFFSETS, self.answer["offsetAt"]):
            with self.subTest(case=case):
                self.assertEqual(got, expected)

    def test_a_wheel_notch_is_three_lines_and_a_press_on_the_track_a_page(self):
        for (case, expected), got in zip(WHEELS, self.answer["wheelStep"]):
            with self.subTest(case=case):
                self.assertEqual(got, expected)
        for (case, expected), got in zip(PAGES, self.answer["pageStep"]):
            with self.subTest(case=case):
                self.assertEqual(got, expected)
        self.assertEqual(self.answer["Line"] * 3, 99, "a notch is what the panel's page moves for one")

    def test_a_control_is_scrolled_into_view_moving_as_little_as_it_can(self):
        for (case, expected), got in zip(VIEWS, self.answer["intoView"]):
            with self.subTest(case=case):
                self.assertEqual(got, expected)

    def test_a_glide_arrives_and_never_overshoots(self):
        frames = self.answer["glide"]
        self.assertEqual(frames[-1], 150)
        self.assertLessEqual(len(frames), 12, "a glide longer than about 180 ms reads as lag")
        self.assertEqual(frames, sorted(frames))

    def test_the_bar_shows_only_while_there_is_more_than_fits(self):
        short, tall = self.answer["short"], self.answer["tall"]
        self.assertFalse(short["overflowing"])
        self.assertEqual(short["track"], [0, 0, 0, 0])
        self.assertEqual(short["display"], [10, 10, 280, 380], "no gutter while nothing scrolls")
        self.assertTrue(tall["overflowing"])
        self.assertEqual(tall["extent"], 1020, "the content and the page's padding")
        gutter, margin, width = self.px(18), self.px(3), self.px(12)
        self.assertEqual(self.answer["gutter"], gutter)
        self.assertEqual(tall["display"], [10, 10, 280 - gutter, 1020 - 20], "what the page holds keeps clear of the bar")
        self.assertEqual(tall["track"], [300 - margin - width, margin, width, 400 - 2 * margin])
        inset = self.px(2)
        start, length = thumb(tall["track"][3] - 2 * inset, 1020, 400, 0, self.px(32))
        self.assertEqual(tall["thumb"], [tall["track"][0] + inset, margin + inset + start, width - 2 * inset, length])
        grown = self.answer["grown"]
        self.assertFalse(grown["overflowing"], "a page made taller than what it holds hides the bar")
        self.assertEqual((grown["offset"], grown["top"]), (0, 10))

    def test_scrolling_moves_what_the_page_holds_and_stops_at_its_end(self):
        scrolled, clamped = self.answer["scrolled"], self.answer["clamped"]
        self.assertEqual((scrolled["offset"], scrolled["top"]), (300, 10 - 300))
        self.assertGreater(scrolled["thumb"][1], self.answer["tall"]["thumb"][1])
        self.assertEqual(clamped["offset"], 1020 - 400)
        self.assertEqual(clamped["thumb"][1] + clamped["thumb"][3],
                         clamped["track"][1] + clamped["track"][3] - self.px(2), "the thumb at the end of its track")

    def test_the_wheel_and_the_track_scroll_the_page(self):
        lines, line = self.answer["lines"], self.px(33)
        step = 0 if lines == 0 else (400 - line if lines < 0 else lines * line)
        moved, offset = self.answer["wheelDown"]
        self.assertEqual(offset, min(620, step))
        self.assertEqual(moved, step > 0)
        self.assertEqual(self.answer["wheelUpAtTop"], [False, 0], "a turn with nowhere to go goes on to what holds the page")
        self.assertEqual(self.answer["paged"], min(620, max(line, 400 - line)))

    def test_the_wheel_over_a_child_or_a_drop_down_scrolls_the_page(self):
        lines, line = self.answer["lines"], self.px(33)
        if lines <= 0:
            self.skipTest("Windows is set to scroll a page or nothing per notch")
        self.assertEqual(self.answer["overLabel"], min(620, lines * line), "a label hands the wheel to its page")
        selected, offset = self.answer["overCombo"]
        self.assertEqual(selected, 0, "the drop-down under the pointer changed")
        self.assertEqual(offset, min(620, lines * line), "and the page did not scroll")

    def test_a_control_the_keyboard_moves_to_is_scrolled_into_view(self):
        room = self.px(16)
        below, above, late = self.answer["reveal"]
        self.assertEqual(below, 790 + room - 400, "the 16th button, below the page, shown with room under it")
        self.assertEqual(above, 100 - room, "the 3rd, above it again")
        self.assertEqual(late, min(1050 - 400, 1040 + room - 400), "a button added after the page was built")

    def test_nothing_glides_when_motion_is_reduced(self):
        motion = self.answer["motion"]
        self.assertEqual(motion["still"], [False, 200], "with motion reduced the page is there at once")
        if motion["reduced"] or not motion["shown"]:
            self.skipTest("Windows' animation effects are off here, so every scroll is immediate")
        self.assertEqual(motion["allowed"], [True, 0], "with motion allowed the page glides there")

    def test_high_contrast_draws_the_bar_in_system_colours(self):
        contrast = self.answer["contrast"]
        self.assertEqual(contrast["track"], ["Window", "WindowFrame"])
        self.assertEqual(contrast["thumb"], ["GrayText", "Highlight", "Highlight"])
        self.assertEqual(contrast["edge"], contrast["thumb"])

    def test_the_bar_is_the_panels_material_and_darkens_a_step_under_the_pointer(self):
        light = self.answer["light"]
        self.assertEqual(light["track"], [argb(brand.LIGHT["inset"]), argb(brand.LIGHT["line"])])
        self.assertEqual(light["thumb"], [argb(brand.LIGHT["raised"])] * 3)
        rest, hover, drag = (luminance(value) for value in light["edge"])
        self.assertEqual(light["edge"][0], argb(brand.LIGHT["line"]))
        self.assertGreater(rest, hover)
        self.assertGreater(hover, drag)
        self.assertGreater(drag, luminance(argb(brand.LIGHT["muted"])))

    def test_a_list_hides_its_own_bar_behind_the_soft_one(self):
        shown = self.answer["list"]
        if not shown["native"]:
            self.skipTest("the list computed no scroll bar without being on screen")
        self.assertTrue(shown["overflowing"])
        gutter = self.px(18)
        self.assertEqual(shown["clip"], shown["host"] - gutter, "the list's rows end where the gutter starts")
        self.assertEqual(shown["client"], shown["clip"], "its rows - and so its columns - fill the clip exactly")
        self.assertGreater(shown["width"], shown["clip"], "and its own bar lies past the clip, unseen")
        self.assertEqual(shown["extent"], 60)
        self.assertGreater(shown["viewport"], 0)
        self.assertEqual(shown["track"][0], shown["host"] - self.px(3) - self.px(12))
        self.assertEqual(shown["scrolled"], [10, 10], "the soft bar scrolls the list itself")


class SourceRuleTests(unittest.TestCase):
    """Rules that hold for the source, so they fail without a compiler too."""

    def setUp(self):
        self.controls = (ROOT / "gui" / "Controls.cs").read_text(encoding="utf-8")
        self.code = "\n".join(line for line in self.controls.splitlines()
                              if not line.lstrip().startswith("//") and not line.lstrip().startswith("///"))

    def body(self, signature):
        start = self.controls.index(signature)
        return self.controls[start:self.controls.index("\n        }\n", start)]

    def test_no_unsafe_code_and_no_initialized_constant_array(self):
        """The in-box compiler puts an initialized constant array in a class it names with a
        fresh random GUID, and build/normalize_pe.py refuses the executable."""
        self.assertNotRegex(self.code, r"\bunsafe\b")
        self.assertNotRegex(self.code, r"new\s+(?:byte|short|int|long|float|double|char|bool)\s*\[\s*\d*\s*\]\s*\{")
        self.assertNotRegex(self.code, r"(?:byte|short|int|long|float|double|char|bool)\s*\[\s*\]\s+\w+\s*=\s*\{")

    def test_high_contrast_draws_no_shadow(self):
        for signature in ("internal static void StampOuter(", "internal static void StampInner("):
            with self.subTest(signature):
                body = self.body(signature)
                self.assertRegex(body.split("{", 1)[1].lstrip(), r"^if \(Palette\.Contrast\b")

    def test_the_status_light_is_a_flat_dot_and_its_glow_is_off_in_high_contrast(self):
        paint = self.body("protected override void OnPaint(PaintEventArgs e)\n        {\n            Graphics g = e.Graphics;\n            g.Clear(")
        self.assertIn("using (var brush = new SolidBrush(colour)) g.FillEllipse(", paint,
                      "the dot is one solid colour")
        self.assertIn("!Palette.Contrast", paint[:paint.index("Glow(g")], "no glow in High Contrast")
        halo = self.controls[self.controls.index("internal sealed class HaloDot"):]
        self.assertNotIn("Palette.Waiting", halo, "waiting is drawn in the running cyan, not blue")
        self.assertIn("Brand.Glow(", halo)
        self.assertIn("Brand.StatusFill(", halo)
        self.assertIn("Brand.StatusSystem(", halo)

    def test_every_ground_and_lifted_control_paints_behind_its_corners(self):
        for name in ("SoftCard", "SoftButton", "SoftCombo", "SoftNumber", "ChoiceCard", "SoftTextArea", "SoftQuote"):
            start = self.controls.index("internal sealed class %s " % name)
            end = self.controls.find("\n    internal ", start + 10)
            end = self.controls.find("\n    /// ", start + 10) if end < 0 else min(end, self.controls.find("\n    /// ", start + 10))
            with self.subTest(name):
                self.assertIn("Ground.PaintBehind(this", self.controls[start:end])

    def test_the_grounds_are_buffered_and_opaque(self):
        for name in ("SoftStack", "SoftRows", "SoftPage", "SoftFlow", "SoftCard", "ChoiceGroup"):
            start = self.controls.index("internal sealed class %s " % name)
            body = self.controls[start:self.controls.index("\n    }\n", start)]
            with self.subTest(name):
                self.assertIn("ISoftGround", body.splitlines()[0])
                self.assertIn("ControlStyles.OptimizedDoubleBuffer", body)
                self.assertNotIn("Color.Transparent", body)

    def test_the_soft_bar_has_no_shadow_in_high_contrast_and_no_native_bar_behind_it(self):
        draw = self.body("internal static void Draw(Graphics g, Rectangle track, Rectangle thumb, int state)")
        self.assertIn("bool contrast = Palette.Contrast;", draw)
        self.assertIn("Soft.Body(g, track, radius, TrackFill(contrast), TrackEdge(contrast), !contrast);", draw,
                      "the well's inset shadow is off in High Contrast")
        self.assertIn("if (!contrast)", draw[:draw.index("Elevation.StampOuter(")], "and so is the thumb's lift")
        page = self.controls[self.controls.index("internal sealed class SoftPage "):]
        page = page[:page.index("\n    }\n")]
        self.assertNotIn("AutoScroll", page, "the page scrolls itself; Windows' bar is never asked for")
        self.assertIn("public override Rectangle DisplayRectangle", page)
        self.assertIn("if (animate && !Soft.ReduceMotion && IsHandleCreated && Soft.Shown(this))",
                      self.body("internal void ScrollTo(int target, bool animate)"), "no glide with motion reduced")


if __name__ == "__main__":
    unittest.main()
