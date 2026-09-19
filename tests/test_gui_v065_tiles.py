r"""A conversation is a tile, on every surface (v0.6.5): the window's lists of conversations match the popup's task tiles.

bb0671e gave the popup's task tiles depth - brand's control lift under them and, in dark, the dark card's one-pixel top
light inside the hairline on a `raised` ground (tray_popup.DEPTH, requirement 11) - and the panel's rows are the same
tiles. The design rule is that the three surfaces look like one product: what one gains, the others match. So the
window's lists of conversations, Pending's and History's, draw each row as that tile (SettingsForm.DrawTile), with the
chosen row pressed into a well as a chosen choice card is, brand's gap between tiles (tile_gap, the popup's and the
panel's), the Auto-resume switch closing the tile at brand's padding of a tile as it closes the popup's and the
panel's, and nothing to list said from a sunken well where the first tile would stand, as the popup says it
(EmptyWell). A choice card is not a conversation: it rests as a button and the panel's segment for the same setting
do, with no top light. The Timeline's events and Why it is waiting's checks stay rows with a hairline between them, as
the panel's settings and compatibility rows are - nothing there is picked.

The real compiled window is built in the probe's own process, as LayoutAudit builds it - a bridge rooted where nothing
is, nothing asked of the watcher - inside a window of the probe's own far off the screen, shown without taking
activation; its lists are drawn to a bitmap in light, dark and High Contrast and read pixel by pixel. Nothing is sent
to any other window.
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

from codex_auto_resume import brand, l10n, tray_popup

from test_gui_layout import fullest_snapshot

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "gui"
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
SCALES = (1.0, 1.5, 2.0)

PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
Add-Type -ReferencedAssemblies System.Windows.Forms, System.Drawing -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Windows.Forms;
public class QuietForm : Form {
    protected override bool ShowWithoutActivation { get { return true; } }
    protected override CreateParams CreateParams { get { CreateParams cp = base.CreateParams; cp.ExStyle |= 0x08000000 | 0x80; return cp; } }
}
public static class Placer {
    [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr hWnd, IntPtr after, int x, int y, int cx, int cy, uint flags);
    // SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE: Windows holds only top-level windows to the screen's size.
    public static void Size(Control child, int width, int height) { SetWindowPos(child.Handle, IntPtr.Zero, 0, 0, width, height, 0x0002 | 0x0004 | 0x0010); }
}
'@
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$static = [Reflection.BindingFlags]'Static,NonPublic,Public'
$instance = [Reflection.BindingFlags]'Instance,NonPublic,Public'
$form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$palette = $assembly.GetType('CodexAutoResume.Palette', $true)
$soft = $assembly.GetType('CodexAutoResume.Soft', $true)
$choiceType = $assembly.GetType('CodexAutoResume.ChoiceCard', $true)
$parse = $assembly.GetType('CodexAutoResume.Json', $true).GetMethod('Parse', $static)
$work = [string]$env:CAR_WORK
$utf8 = New-Object Text.UTF8Encoding $false
function Read-Json([string]$name) { return $parse.Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $work $name), $utf8))) }
function Get-Field($target, [string]$name) { return $form.GetField($name, $instance).GetValue($target) }
function Invoke-Window($target, [string]$name, [object[]]$arguments) {
    $method = @($form.GetMethods($instance) | Where-Object { $_.Name -eq $name -and $_.GetParameters().Count -eq $arguments.Count })[0]
    return $method.Invoke($target, $arguments)
}
function Pump([int]$ms) { $sw = [Diagnostics.Stopwatch]::StartNew(); do { [Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 2 } while ($sw.ElapsedMilliseconds -lt $ms) }
function Box($r) { return ,@([int]$r.X, [int]$r.Y, [int]$r.Width, [int]$r.Height) }
function Colour([string]$name) { return [int]$palette.GetField($name, $static).GetValue($null).ToArgb() }
# Nothing moves: the product's own Reduce motion, so a switch is drawn at rest.
$soft.GetField('ReduceMotionSetting', $static).SetValue($null, $true)
$systemScale = [double]$form.GetField('SystemScale', $static).GetValue($null)
$nowhere = [string](Join-Path $work 'nowhere')
$bridgeType = $assembly.GetType('CodexAutoResume.Bridge', $true)
$persistentType = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
$three = @($form.GetConstructors($instance) | Where-Object { $_.GetParameters().Count -eq 3 })[0]
$out = @{ system = $systemScale; scales = @{} }
# At each scale the audit measures, whatever this machine's: the window's scale and its font with it, as LayoutAudit sets
# them.
foreach ($scale in (ConvertFrom-Json $env:CAR_SCALES)) {
    $form.GetField('dpiScale', $static).SetValue($null, [double]$scale)
    $factor = [single]($scale / $systemScale)
    $box = [Drawing.SystemFonts]::MessageBoxFont
    [Drawing.Font]$font = New-Object Drawing.Font $box.FontFamily, ($box.SizeInPoints * $factor), $box.Style, ([Drawing.GraphicsUnit]::Point)
    $key = ([double]$scale).ToString('0.0', [Globalization.CultureInfo]::InvariantCulture)
    $out.scales[$key] = @{ hairline = [int]$soft.GetProperty('Hairline', $static).GetValue($null) }
    foreach ($theme in @('light', 'dark', 'contrast')) {
        # The theme is the probe's, not this machine's.
        $null = $palette.GetMethod('Adopt', $static).Invoke($null, [object[]]@($theme))
        $frame = New-Object QuietForm
        $frame.FormBorderStyle = 'None'
        $frame.ShowInTaskbar = $false
        $frame.StartPosition = 'Manual'
        $frame.Location = New-Object Drawing.Point -30000, -30000
        # Every Form is held to the screen's size (MaxWindowTrackSize), and at 150% and 200% the opening
        # size is larger than a CI runner's screen - larger than many - so the window inside is sized by
        # Windows itself once it is a child, which nothing clamps.
        $opening = New-Object Drawing.Size ([int][Math]::Round([int]$form.GetField('OpeningWidth', $static).GetValue($null) * $scale)), ([int][Math]::Round([int]$form.GetField('OpeningHeight', $static).GetValue($null) * $scale))
        $frame.ClientSize = $opening
        $once = $bridgeType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere))
        $bridge = $persistentType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere, $once))
        $window = $three.Invoke([object[]]@($bridge, (Read-Json 'strings-en.json'), $font.PSObject.BaseObject))
        $form.GetField('auditing', $instance).SetValue($window, $true)
        $window.TopLevel = $false
        $window.FormBorderStyle = 'None'
        $window.MinimumSize = [Drawing.Size]::Empty
        $window.Location = [Drawing.Point]::Empty
        $window.ClientSize = $opening
        $frame.Controls.Add($window)
        [Placer]::Size($window, $opening.Width, $opening.Height)
        if ($window.ClientSize -ne $opening) { throw ('the window is ' + $window.ClientSize + ', not its opening size ' + $opening) }
        Invoke-Window $window 'ApplySnapshot' @((Read-Json 'snapshot.json'))
        $null = Invoke-Window $window 'ShowPage' @('pending')
        $window.Visible = $true
        $frame.Show()
        Pump 100
        if ($window.ClientSize -ne $opening) { throw ('the window became ' + $window.ClientSize + ', not its opening size ' + $opening) }
        $entry = @{ card = (Colour 'Card'); raised = (Colour 'Raised'); inset = (Colour 'Inset'); line = (Colour 'Line')
                    chosen = (Colour 'AccentSoft') }
        foreach ($name in @('pendingList', 'historyList')) {
            if ($name -eq 'historyList') { $null = Invoke-Window $window 'ShowPage' @('history'); Pump 60 }
            $list = Get-Field $window $name
            # The first row chosen, the others not.
            foreach ($item in $list.Items) { $item.Selected = $false }
            $list.Items[0].Selected = $true
            $list.Refresh()
            Pump 60
            $tiles = @()
            foreach ($item in $list.Items) { $tiles += ,(Box (Invoke-Window $window 'RowTile' @($list, $item))) }
            $rows = @()
            foreach ($item in $list.Items) { $rows += ,(Box $item.Bounds) }
            $bitmap = New-Object Drawing.Bitmap $list.Width, $list.Height
            $list.DrawToBitmap($bitmap, (New-Object Drawing.Rectangle 0, 0, $list.Width, $list.Height))
            # Two columns of pixels from the top of the list to below the third tile: one down the tiles' right padding, where
            # nothing is drawn in them, for their grounds; one down their middle, clear of their rounded corners, for their
            # edges and the gaps between them.
            $x = $tiles[1][0] + $tiles[1][2] - [int][Math]::Round(6 * $scale)
            $middle = $tiles[1][0] + [int]($tiles[1][2] / 2)
            # Over the first tile, a column no heading's letters reach: the end of the wide Status column, whose heading is
            # one short word. (A tile's middle can fall on a heading, and at 200% its letters come within 10 px of the tile.)
            $clear = [int]$list.Columns[0].Width + [int]$list.Columns[1].Width - [int][Math]::Round(6 * $scale)
            $above = @()
            for ($y = 0; $y -lt $tiles[0][1] + $tiles[0][3]; $y++) { $above += [int]$bitmap.GetPixel($clear, $y).ToArgb() }
            $down = @(); $across = @()
            for ($y = 0; $y -lt [Math]::Min($bitmap.Height, $tiles[2][1] + $tiles[2][3] + [int][Math]::Round(20 * $scale)); $y++) {
                $down += [int]$bitmap.GetPixel($x, $y).ToArgb()
                $across += [int]$bitmap.GetPixel($middle, $y).ToArgb()
            }
            # And a row of pixels across the second tile's middle, end to end: where its switch ends.
            $through = @()
            $y = $tiles[1][1] + [int]($tiles[1][3] / 2)
            for ($x = 0; $x -lt $bitmap.Width; $x++) { $through += [int]$bitmap.GetPixel($x, $y).ToArgb() }
            $bitmap.Dispose()
            # Nothing chosen: the headings draw the part of the first tile's lift that reaches up into them.
            foreach ($item in $list.Items) { $item.Selected = $false }
            $list.Refresh()
            Pump 60
            $bitmap = New-Object Drawing.Bitmap $list.Width, $list.Height
            $list.DrawToBitmap($bitmap, (New-Object Drawing.Rectangle 0, 0, $list.Width, $list.Height))
            $free = @()
            for ($y = 0; $y -lt $tiles[0][1] + $tiles[0][3]; $y++) { $free += [int]$bitmap.GetPixel($clear, $y).ToArgb() }
            $bitmap.Dispose()
            $entry[$name] = @{ tiles = $tiles; rows = $rows; down = $down; middle = $across; through = $through; free = $free; above = $above
                               columns = @($list.Columns | ForEach-Object { [int]$_.Width }); client = @($list.ClientSize.Width, $list.ClientSize.Height) }
        }
        # Nothing to list: the well under the headings, where the first tile stood.
        Invoke-Window $window 'ApplySnapshot' @((Read-Json 'empty.json'))
        foreach ($pair in @(@('pendingList', 'pendingEmpty', 'pending'), @('historyList', 'historyEmpty', 'history'))) {
            $null = Invoke-Window $window 'ShowPage' @($pair[2])
            Pump 80
            $list = Get-Field $window $pair[0]
            $well = Get-Field $window $pair[1]
            $list.Refresh()
            Pump 40
            $bitmap = New-Object Drawing.Bitmap $list.Width, $list.Height
            $list.DrawToBitmap($bitmap, (New-Object Drawing.Rectangle 0, 0, $list.Width, $list.Height))
            $b = $well.Bounds
            $column = @()
            for ($y = 0; $y -lt [Math]::Min($bitmap.Height, $b.Bottom + 4); $y++) { $column += [int]$bitmap.GetPixel([Math]::Max(0, $b.X + [int][Math]::Round(12 * $scale)), $y).ToArgb() }
            $bitmap.Dispose()
            $entry[$pair[1]] = @{ parent = $(if ($well.Parent) { $well.Parent.GetType().Name } else { '' }); list = [bool]($well.Parent -eq $list); visible = [bool]$well.Visible
                                  bounds = (Box $b); client = @($list.ClientSize.Width, $list.ClientSize.Height); rows = $list.Items.Count
                                  preferred = [int]$well.GetPreferredSize((New-Object Drawing.Size $b.Width, 0)).Height; column = $column; text = [string]$well.Text }
        }
        # A choice card, resting and chosen, down a column clear of its words and its corners.
        $cards = @{}
        foreach ($chosen in @($false, $true)) {
            $card = [Activator]::CreateInstance($choiceType, $instance, $null, [object[]]@('standard', 'Standard', 'Says why.'), $null)
            $card.Size = New-Object Drawing.Size ([int][Math]::Round(300 * $scale)), ([int][Math]::Round(60 * $scale))
            $card.Checked = $chosen
            $bitmap = New-Object Drawing.Bitmap $card.Width, $card.Height
            $card.DrawToBitmap($bitmap, (New-Object Drawing.Rectangle 0, 0, $card.Width, $card.Height))
            $column = @()
            for ($y = 0; $y -lt $card.Height; $y++) { $column += [int]$bitmap.GetPixel([int]($card.Width - [Math]::Round(30 * $scale)), $y).ToArgb() }
            $bitmap.Dispose()
            $card.Dispose()
            $cards[[string]$chosen] = $column
        }
        $entry.choice = $cards
        $out.scales[$key][$theme] = $entry
        $frame.Close()
        $frame.Dispose()
    }
}
$form.GetField('dpiScale', $static).SetValue($null, $systemScale)
[IO.File]::WriteAllText((Join-Path $work 'result.json'), ($out | ConvertTo-Json -Depth 8 -Compress), $utf8)
[GC]::Collect()
[GC]::WaitForPendingFinalizers()
[Environment]::Exit(0)
"""


def channels(pixel) -> tuple:
    if not isinstance(pixel, int):
        return tuple(int(round(value)) for value in pixel)
    pixel &= 0xFFFFFFFF
    return ((pixel >> 16) & 255, (pixel >> 8) & 255, pixel & 255)


def luminance(pixel) -> float:
    r, g, b = channels(pixel)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def near(one, other, levels=3) -> bool:
    return all(abs(a - b) <= levels for a, b in zip(channels(one), channels(other)))


def top_light(theme="dark") -> tuple:
    """A tile's ground under the dark card's one-pixel top light, as the popup draws it (tray_popup.DEPTH)."""
    light = [shadow for shadow in brand.shadows("card", theme) if shadow.inset]
    assert len(light) == 1
    raised = brand.palette(theme)["raised"]
    return brand.rgb(brand.mix(raised, brand.palette(theme)[light[0].token], light[0].alpha))


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class TileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll", "/reference:System.Windows.Forms.dll",
                        *[str(GUI / name) for name in ("SettingsApp.cs", "Dashboard.cs", "Controls.cs", "Brand.cs")]],
                       check=True, capture_output=True, timeout=300)
        reply = {"ok": True, "language": "en", "strings": l10n.catalog("en"), "endonyms": dict(l10n.ENDONYMS),
                 "preference": "en", "system_language": "en"}
        (work / "strings-en.json").write_text(json.dumps(reply, ensure_ascii=False), encoding="utf-8")
        (work / "snapshot.json").write_text(json.dumps(fullest_snapshot(time.time()), ensure_ascii=False), encoding="utf-8")
        empty = fullest_snapshot(time.time())
        empty["pending"], empty["history"] = [], []
        (work / "empty.json").write_text(json.dumps(empty, ensure_ascii=False), encoding="utf-8")
        probe = work / "tiles.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        cls.result = subprocess.run(
            [str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
            env=dict(os.environ, CAR_EXE=str(exe), CAR_WORK=str(work), CAR_SCALES=json.dumps(SCALES)))
        answer = work / "result.json"
        cls.answer = (json.loads(answer.read_text(encoding="utf-8-sig"))
                      if cls.result.returncode == 0 and answer.is_file() else {})

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-4000:])
        self.assertEqual(sorted(self.answer["scales"]), ["%.1f" % scale for scale in SCALES])

    def at(self, scale):
        """What was drawn at `scale`; px, hairline and column then answer for it."""
        self.scale = scale
        self.drawn = self.answer["scales"]["%.1f" % scale]
        self.hairline = self.drawn["hairline"]
        return self.subTest(scale=scale)

    def px(self, value):
        return int(round(value * self.scale))

    def column(self, theme, name="pendingList"):
        """(the pixels down the tiles' right padding, down their middle, the tiles) of a list in `theme`."""
        found = self.drawn[theme][name]
        return found["down"], found["middle"], found["tiles"]

    def lift(self, middle, y, h, theme):
        """The gap under a tile whose bottom edge is at y + h: brand's control lift over the card, as far as the light
        of the tile below does not reach."""
        for k in range(self.px(brand.SPACING["xs"])):
            expected = brand.elevation_colour("control", "bottom", k + 0.5, brand.card_ground(theme), theme,
                                              scale=self.scale)
            with self.subTest(theme=theme, d=k):
                self.assertTrue(near(middle[y + h + k], expected, 3),
                                "%s against %s" % (channels(middle[y + h + k]), channels(expected)))

    # ---------------------------------------------------------------- the geometry

    def test_each_row_is_a_tile_a_buttons_height_with_brands_gap_between(self):
        """The popup's tiles and the panel's are brand's tile_gap apart (8 px); the window's were 12 - 4 over each tile
        and 8 under it - so the same tiles had a looser rhythm in the window. A tile now starts where its row does, and
        the gap is the one under the tile before."""
        for scale in SCALES:
            with self.at(scale):
                for name in ("pendingList", "historyList"):
                    found = self.drawn["light"][name]
                    tiles, rows = found["tiles"], found["rows"]
                    with self.subTest(name):
                        self.assertGreaterEqual(len(tiles), 3)
                        for (x, y, w, h), (rx, ry, rw, rh) in zip(tiles, rows):
                            self.assertEqual(h, self.px(brand.LAYOUT["button_height"]), "as tall as a row was: a button's height")
                            self.assertEqual(y, ry, "nothing over it: the first stands right under the headings")
                            self.assertEqual(x - rx, self.px(brand.SPACING["s"]), "room beside it for its lift")
                            self.assertEqual(w, sum(found["columns"]) - 2 * self.px(brand.SPACING["s"]))
                        gaps = {tiles[i + 1][1] - (tiles[i][1] + tiles[i][3]) for i in range(len(tiles) - 1)}
                        self.assertEqual(gaps, {self.px(brand.LAYOUT["tile_gap"])},
                                         "brand's gap between tiles, as the popup's and the panel's")
                        self.assertLessEqual(tiles[0][0] + tiles[0][2] + self.px(brand.SPACING["s"]), found["client"][0],
                                             "the lift on the right has its room inside the list")

    def test_the_switch_closes_the_tile_at_brands_padding(self):
        """The popup and the panel pin the switch brand's tile padding (12 px) from the tile's right edge; the window
        drew it 2 px into its column, which fills the rest of the list, so it stood about 47 px from the edge at 100%
        and further the wider the window."""
        for scale in SCALES:
            with self.at(scale):
                for theme in ("light", "dark"):
                    found = self.drawn[theme]["pendingList"]
                    x, y, w, h = found["tiles"][1]
                    through = found["through"]
                    ground = self.drawn[theme]["raised"]
                    # From inside the tile's right edge - past its hairline and rounded corner - leftwards to the first
                    # pixel of the switch.
                    right = next(i for i in range(x + w - self.hairline - 2, x, -1)
                                 if not near(through[i], ground, 12))
                    with self.subTest(theme=theme):
                        self.assertAlmostEqual((x + w) - (right + 1), self.px(brand.LAYOUT["tile_pad"][1]), delta=1)

    def test_the_headings_draw_the_first_tiles_lift(self):
        """The first tile stands right under the headings, which are a window of their own: they draw the part of its
        lift that reaches up into them, and none over a first tile pressed into a well."""
        for scale in SCALES:
            with self.at(scale):
                found = self.drawn["light"]["pendingList"]
                x, y, w, h = found["tiles"][0]
                card = self.drawn["light"]["card"]
                band = range(y - self.px(brand.SPACING["s"]), y)
                self.assertTrue(any(found["free"][k] != card for k in band), "the lift over a raised first tile")
                self.assertTrue(all(found["above"][k] == card for k in band), "none over a chosen one")
                for k in band:
                    with self.subTest(d=y - k):
                        self.assertTrue(near(found["free"][k], card, 3), "brand's lift, faint over its top edge")

    # ---------------------------------------------------------------- light

    def test_light_a_tile_is_raised_on_brands_control_lift(self):
        for scale in SCALES:
            with self.at(scale):
                for name in ("pendingList", "historyList"):
                    down, middle, tiles = self.column("light", name)
                    x, y, w, h = tiles[1]
                    with self.subTest(name):
                        self.assertTrue(near(down[y + h // 2], self.drawn["light"]["raised"], 0), "a tile's ground is `raised`")
                        self.assertTrue(near(middle[y + self.hairline], self.drawn["light"]["raised"], 0), "no top light in light")
                        self.lift(middle, y, h, "light")
                        self.assertLess(luminance(middle[y + h]), luminance(self.drawn["light"]["card"]) - 5,
                                        "a shadow under it, not the card")

    def test_light_the_chosen_tile_is_pressed_into_a_well_with_no_lift(self):
        for scale in SCALES:
            with self.at(scale):
                down, middle, tiles = self.column("light")
                x, y, w, h = tiles[0]
                # Six pixels in from the right edge, where the well's inner light has all but faded.
                self.assertTrue(near(down[y + h // 2], self.drawn["light"]["inset"], 3), "chosen, the inset ground")
                self.assertLess(luminance(middle[y + self.hairline]), luminance(self.drawn["light"]["inset"]),
                                "the inset shadow inside its top edge")
                self.assertGreaterEqual(luminance(middle[y + h + 1]), luminance(self.drawn["light"]["card"]) - 1,
                                        "no lift under a tile pressed in")

    # ---------------------------------------------------------------- dark

    def test_dark_a_tile_has_the_dark_cards_top_light_on_a_raised_ground(self):
        for scale in SCALES:
            with self.at(scale):
                for name in ("pendingList", "historyList"):
                    down, middle, tiles = self.column("dark", name)
                    x, y, w, h = tiles[1]
                    with self.subTest(name):
                        self.assertTrue(near(down[y + h // 2], brand.rgb(brand.DARK["raised"]), 0), "`raised`, as the popup's")
                        self.assertGreater(luminance(self.drawn["dark"]["raised"]), luminance(self.drawn["dark"]["card"]),
                                           "a step brighter than the card")
                        self.assertTrue(near(middle[y + self.hairline], top_light(), 3),
                                        "%s against %s" % (channels(middle[y + self.hairline]), top_light()))
                        self.lift(middle, y, h, "dark")

    def test_dark_the_chosen_tile_has_no_top_light(self):
        for scale in SCALES:
            with self.at(scale):
                down, middle, tiles = self.column("dark")
                x, y, w, h = tiles[0]
                self.assertTrue(near(down[y + h // 2], self.drawn["dark"]["inset"], 0))
                self.assertLessEqual(luminance(middle[y + self.hairline]), luminance(self.drawn["dark"]["inset"]),
                                     "a well's shadow inside its top edge, not a light")

    # ---------------------------------------------------------------- High Contrast

    def test_high_contrast_is_system_colours_and_no_shadow(self):
        for scale in SCALES:
            with self.at(scale):
                down, middle, tiles = self.column("contrast")
                contrast = self.drawn["contrast"]
                x, y, w, h = tiles[1]
                self.assertTrue(near(down[y + h // 2], contrast["raised"], 0), "Window")
                for k in range(self.px(brand.SPACING["s"])):
                    with self.subTest(d=k):
                        self.assertEqual(middle[y + h + k], contrast["card"], "no shadow in High Contrast")
                x, y, w, h = tiles[0]
                self.assertTrue(near(down[y + h // 2], contrast["chosen"], 0), "chosen, Highlight")

    # ---------------------------------------------------------------- the choice cards

    def test_a_resting_choice_card_is_the_panels_segment_not_a_tile(self):
        """Message style is the one setting with a twin on another surface: the panel's .segment, raised on brand's
        control lift with no top light, as every button is. A choice card drew the same until the tiles came, then took
        a conversation tile's top light in dark and no longer matched it."""
        for scale in SCALES:
            with self.at(scale):
                resting, chosen = self.drawn["dark"]["choice"]["False"], self.drawn["dark"]["choice"]["True"]
                raised = brand.rgb(brand.DARK["raised"])
                self.assertTrue(near(resting[self.hairline], raised, 0),
                                "%s: no top light inside the hairline" % (channels(resting[self.hairline]),))
                self.assertFalse(near(resting[self.hairline], top_light(), 1), "not a tile's top light")
                self.assertTrue(near(resting[len(resting) // 2], raised, 0))
                self.assertLessEqual(luminance(chosen[self.hairline]), luminance(chosen[len(chosen) // 2]),
                                     "chosen, a well: no light")
                resting = self.drawn["light"]["choice"]["False"]
                self.assertTrue(near(resting[self.hairline], brand.rgb(brand.LIGHT["raised"]), 0), "light has no top light")

    # ---------------------------------------------------------------- nothing to list

    def test_nothing_to_list_is_said_from_a_well_where_the_first_tile_stood(self):
        """The popup says 'Nothing is waiting' from a sunken well; the window said it in a line over the list's card,
        whose headings then floated over nothing. Now the well is in the list, under its headings, across the tiles'
        width, as tall as its words and the popup's padding round them."""
        for scale in SCALES:
            with self.at(scale):
                for theme in ("light", "dark", "contrast"):
                    drawn = self.drawn[theme]
                    for name, listed in (("pendingEmpty", "pendingList"), ("historyEmpty", "historyList")):
                        well = drawn[name]
                        x, y, w, h = well["bounds"]
                        side, pad = self.px(brand.SPACING["s"]), self.px(brand.SPACING["l"])
                        with self.subTest(theme=theme, well=name):
                            self.assertEqual(well["rows"], 0)
                            self.assertTrue(well["list"] and well["visible"], "shown, in the list: %s" % well["parent"])
                            self.assertEqual(y, drawn[listed]["rows"][0][1], "where the first tile stood, under the headings")
                            self.assertEqual((x, w), (side, well["client"][0] - 2 * side), "across the tiles' width")
                            self.assertEqual(h, well["preferred"], "as tall as its words at that width")
                            self.assertGreater(h, 2 * pad, "the popup's padding round its words")
                            column = well["column"]
                            self.assertTrue(near(column[y], drawn["line"], 3),
                                            "%s: the hairline along its top" % (channels(column[y]),))
                            self.assertTrue(near(column[y + pad // 2], drawn["inset"], 8),
                                            "%s: the inset fill" % (channels(column[y + pad // 2]),))
                            if theme != "contrast":
                                self.assertLess(luminance(column[y + self.hairline]), luminance(drawn["inset"]),
                                                "the inset shadow inside its top edge")


class TileSourceTests(unittest.TestCase):
    """The rule held in the source, so it fails without a compiler too."""

    @classmethod
    def setUpClass(cls):
        cls.dashboard = (GUI / "Dashboard.cs").read_text(encoding="utf-8")
        cls.controls = (GUI / "Controls.cs").read_text(encoding="utf-8")

    def method(self, source, signature):
        start = source.index(signature)
        return source[start:source.index("\n        }\n", start)]

    def constant(self, name):
        return re.search(r'internal const string %s = "(\w+)";' % name, self.controls).group(1)

    def test_the_windows_tile_is_the_popups_tile_recipe(self):
        """One recipe on both surfaces: the window's tile is brand's recipe named TileLift under it and, inside it in
        dark, the inset shadows of the one named TileLight - exactly what the popup's tiles are made of."""
        lift, light = self.constant("TileLift"), self.constant("TileLight")
        for theme in ("light", "dark"):
            window = brand.shadows(lift, theme)
            if theme == "dark":
                window += tuple(shadow for shadow in brand.shadows(light, theme) if shadow.inset)
            with self.subTest(theme):
                self.assertEqual(window, tray_popup.recipe_shadows("tile", theme))
                self.assertEqual(tray_popup.tile_ground(theme), brand.palette(theme)["raised"])
        tile = self.method(self.controls, "internal static void Tile(Graphics g, Rectangle face, float radius, Color fill)")
        self.assertIn("Palette.Dark ? TileLight : null", tile, "the top light in dark only")
        self.assertIn("private const int RowTileBelow = Brand.TileGap;", self.dashboard, "brand's gap between tiles")
        self.assertNotIn("RowTileAbove", self.dashboard, "nothing over a tile: the gap is the one under the tile before")

    def test_the_lists_of_conversations_are_tiled_and_nothing_else_is(self):
        self.assertIn("TileRows(pendingList);", self.dashboard)
        self.assertIn("TileRows(historyList);", self.dashboard)
        self.assertEqual(self.dashboard.count("TileRows("), 3, "the method and its two lists")
        self.assertNotIn("TileRows(", self.method(self.dashboard, "private Form BuildTimeline("))
        gates = self.dashboard[self.dashboard.index("internal sealed class GateList"):]
        self.assertIn("g.FillRectangle(rule, 0, y, Width, Soft.Hairline)", gates[:gates.index("\n    }\n")],
                      "Why it is waiting keeps its rows")

    def test_a_tile_lifts_and_a_chosen_one_is_pressed_in(self):
        tile = self.method(self.dashboard, "private Color DrawTile(")
        self.assertIn("if (!item.Selected) Elevation.StampOuter(g, RowTile(list, item), Soft.TileLift, radius, e.Bounds);", tile)
        self.assertIn("e.ItemIndex - 1", tile, "the lift of the tile above reaches into the gap over this one")
        self.assertIn("e.ItemIndex + 1", tile, "and the light of the one below into the gap under it")
        self.assertIn("Soft.Tile(g, tile, radius, fill);", tile)
        self.assertIn("Soft.Body(g, tile, radius, fill, Palette.Line, true);", tile, "chosen, a well")
        rows = self.method(self.dashboard, "private void TileRows(ListView list)")
        self.assertIn("list.ItemSelectionChanged +=", rows, "a lift gained or lost is repainted beside its row too")
        self.assertIn("Rectangle.Inflate(e.Item.Bounds, 0, Px(RowTileBelow))", rows)
        self.assertIn("if (e.Item == list.TopItem) Headings(list);", rows, "and in the headings, over the first row shown")
        self.assertIn("soft.ScrollChanged +=", rows, "and again when the first row shown changes")
        header = self.method(self.dashboard, "private void DrawHeader(")
        self.assertIn("if (top != null && !top.Selected)", header)
        self.assertIn("Elevation.StampOuter(e.Graphics, tile, Soft.TileLift,", header)
        card = self.controls[self.controls.index("internal sealed class ChoiceCard"):]
        paint = self.method(card, "protected override void OnPaint(PaintEventArgs e)")
        self.assertNotIn("Soft.Tile(", paint, "a choice card is not a conversation's tile")
        self.assertIn('string ISoftLifted.Lift { get { return Checked ? null : "control"; } }', card)

    def test_the_switch_and_its_heading_close_the_tile(self):
        draw = self.method(self.dashboard, "private void DrawResumeBox(")
        self.assertIn("new Rectangle(cell.Right - width,", draw)
        header = self.method(self.dashboard, "private void DrawHeader(")
        self.assertIn("list == pendingList && e.ColumnIndex == ResumeColumn", header)
        self.assertIn("TextFormatFlags.Right | TextFormatFlags.NoPadding", header)

    def test_nothing_to_list_is_a_well_in_the_list_not_a_line_over_its_card(self):
        for build, name, key in (("private Control BuildPending(", "pendingEmpty", "pending.empty"),
                                 ("private Control BuildHistory(", "historyEmpty", "history.empty")):
            with self.subTest(name):
                body = self.method(self.dashboard, build)
                self.assertIn("%s = new EmptyWell();" % name, body)
                self.assertNotIn('GroundText(S("%s"' % key, body)
                self.assertNotIn("page.Controls.Add(%s);" % name, body)
                self.assertIn(", %s)" % name, body, "handed to its list's card")
        card = self.method(self.dashboard, "private Control ListCard(")
        self.assertIn("host.ShowWhenEmpty(empty, Px(RowTileSide));", card)
        host = self.controls[self.controls.index("internal sealed class SoftListHost"):]
        self.assertIn("List.Controls.Add(control);", self.method(host, "internal void ShowWhenEmpty("),
                      "a child of the list, as its headings are, never a window over it")

    def test_a_tiles_cells_are_measured_as_they_are_drawn(self):
        for signature in ("private void MeasureCells(", "private int HeadingWidth(", "private int LeastWidth(",
                          "private void DrawHeader(", "private void DrawCell("):
            with self.subTest(signature):
                body = self.method(self.dashboard, signature)
                self.assertIn("TileBefore(list,", body)
                self.assertIn("TileAfter(list,", body)


if __name__ == "__main__":
    unittest.main()
