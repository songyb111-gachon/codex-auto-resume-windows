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
        for signature in ("internal static void StampOuter(", "internal static void StampInset("):
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
        for name in ("SoftStack", "SoftPage", "SoftFlow", "SoftCard", "ChoiceGroup"):
            start = self.controls.index("internal sealed class %s " % name)
            body = self.controls[start:self.controls.index("\n    }\n", start)]
            with self.subTest(name):
                self.assertIn("ISoftGround", body.splitlines()[0])
                self.assertIn("ControlStyles.OptimizedDoubleBuffer", body)
                self.assertNotIn("Color.Transparent", body)


if __name__ == "__main__":
    unittest.main()
