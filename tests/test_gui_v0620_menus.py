r"""v0.6.18: the right-click menus in the window's own design (the owner, 2026-10-22, with a picture of the Pending row's
menu: "우클릭 할 때 뜨는 거도 우리 디자인에 맞추자").

Every menu the window opens is a SoftMenu, every submenu a SoftMenuDrop made by its Branch, and both are drawn by the one
SoftMenuRenderer as a card of the cards' material in a layered window (SoftMenuLayer, gui/SoftMenu.cs): the card's
ground, a rounded hairline, the cards' shadow round it, the item in hand a raised pill, words in the ink, an item that
cannot be used in the secondary ink, hairline rules, chevrons in the ink, at the window's scale and in its font. In High
Contrast the menu is Windows' own, drawn by Windows' renderer. Wording, item order and what each item does are untouched
(tests/test_gui_v0611_tools.py holds the row menu's order).

The source half reads the window with guiscan; the built half compiles the real window and draws menus into bitmaps,
never on the screen.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import tempfile
import unittest

import guiscan
from codex_auto_resume import l10n, settings
from test_gui_v0611_access import CSC, POWERSHELL, compile_window, reply, run_probe


def code_only(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//"))


class SourceTests(unittest.TestCase):
    def test_the_menus_are_compiled(self):
        self.assertIn("gui/SoftMenu.cs", guiscan.group("controls"))

    def test_every_menu_the_window_creates_is_a_soft_menu(self):
        """Nothing makes a ContextMenuStrip or a drop-down menu of Windows' own: a menu is a SoftMenu, a submenu Branch's."""
        for name in guiscan.handwritten():
            code = code_only(guiscan.read(name))
            with self.subTest(name):
                for pattern in (r"new\s+ContextMenuStrip\s*\(", r"new\s+ToolStripDropDownMenu\s*\(",
                                r"new\s+ContextMenu\s*\(", r"new\s+ToolStripDropDown\s*\("):
                    self.assertIsNone(re.search(pattern, code), pattern)
                for assigned in re.findall(r"\.ContextMenuStrip\s*=\s*(\w+)\s*;", code):
                    self.assertRegex(guiscan.window() + guiscan.read("gui/SoftMenu.cs"),
                                     r"(SoftMenu\s+%s\b|%s\s*=\s*new\s+SoftMenu\s*\()" % (assigned, assigned),
                                     "%s is given a menu that is not a SoftMenu" % assigned)

    def test_every_menu_class_is_dressed_by_the_one_renderer(self):
        derived = []
        for name in guiscan.handwritten():
            derived += re.findall(r"class\s+(\w+)\s*:\s*(?:ContextMenuStrip|ToolStripDropDownMenu|ToolStripDropDown)\b",
                                  code_only(guiscan.read(name)))
        self.assertEqual(sorted(derived), ["SoftMenu", "SoftMenuDrop"])
        for name in derived:
            with self.subTest(name):
                body = guiscan.type_body(name)
                self.assertIn("SoftMenuRenderer.Dress(this);", body)
                self.assertIn("new SoftMenuLayer(this, PaintFace)", body)

    def test_every_submenu_is_made_by_branch(self):
        for name in guiscan.handwritten():
            code = code_only(guiscan.read(name))
            for variable in set(re.findall(r"(\w+)\.DropDownItems\.Add", code)):
                with self.subTest(name=name, submenu=variable):
                    self.assertRegex(code, r"\b%s\s*=\s*\w+\.Branch\(" % variable)
        self.assertIn("item.DropDown = new SoftMenuDrop(Font);", guiscan.member_body("SoftMenu", "Branch"))

    def test_the_renderer_draws_only_the_palette(self):
        renderer = code_only(guiscan.type_body("SoftMenuRenderer"))
        for written in ("Color.FromArgb", "SystemColors.", "Color.Black", "Color.White", "Brand.Light", "Brand.Dark"):
            self.assertNotIn(written, renderer)
        table = {name: re.search(r"internal static Color %s \{ get \{ return ([\w.]+); \} \}" % name, renderer)
                 for name in ("Ground", "Rule", "Hover", "Text", "Disabled", "Chosen")}
        self.assertEqual({name: match.group(1) if match else None for name, match in table.items()},
                         {"Ground": "Palette.Card", "Rule": "Palette.Line", "Hover": "Palette.Raised",
                          "Text": "Palette.Ink", "Disabled": "Palette.Secondary", "Chosen": "Palette.Accent"})
        # Every colour it paints is the table's.
        for used in re.findall(r"new (?:SolidBrush|Pen)\(([^,)]+)", renderer):
            with self.subTest(used):
                self.assertIn(used.split("?")[-1].split(":")[-1].strip(),
                              ("Ground", "Rule", "Hover", "Text", "Disabled", "Chosen",
                               "e.Item.Enabled ? Chosen", "e.Item != null && !e.Item.Enabled ? Disabled"))

    def test_high_contrast_keeps_windows_renderer(self):
        dress = guiscan.member_body("SoftMenuRenderer", "Dress")
        self.assertLess(dress.index("if (Palette.Contrast) return;"), dress.index("menu.Renderer = For();"))
        self.assertIn("on = !Palette.Contrast;", guiscan.type_body("SoftMenuLayer"))


@unittest.skipUnless(os.name == "nt" and CSC.is_file() and POWERSHELL.is_file(),
                     "needs the in-box C# compiler and Windows PowerShell")
class BuiltTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = compile_window(work)
        import json
        (work / "strings-en.json").write_text(json.dumps(reply("en"), ensure_ascii=False), encoding="utf-8")
        cls.answer = run_probe(PROBE, work, 600, CAR_EXE=str(exe))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_the_pending_rows_menu_is_a_soft_menu(self):
        self.assertEqual(self.answer["pending"], {"type": "SoftMenu", "renderer": "SoftMenuRenderer", "list": True})

    def test_in_light_and_dark_the_menu_is_a_card_of_the_palette(self):
        for theme in ("light", "dark"):
            with self.subTest(theme):
                menu = self.answer[theme]
                self.assertEqual(menu["renderer"], "SoftMenuRenderer")
                self.assertEqual(menu["subRenderer"], "SoftMenuRenderer")
                self.assertTrue(menu["sameRenderer"], "one renderer for a menu and its submenu")
                self.assertEqual(menu["subType"], "SoftMenuDrop")
                self.assertTrue(menu["subFont"], "a submenu is set in the menu's font")
                self.assertTrue(menu["layered"], "the window is layered, for the shadow round the card")
                self.assertFalse(menu["dropShadow"], "Windows' square shadow is gone")
                self.assertEqual(menu["table"], menu["palette"], "the colour table is the palette's")

    def test_the_card_is_drawn_round_with_its_ground_and_the_pill_in_hand(self):
        for theme in ("light", "dark"):
            with self.subTest(theme):
                drawn = self.answer[theme]["drawn"]
                self.assertEqual(drawn["size"], drawn["window"], "the picture is the menu's whole window")
                self.assertTrue(drawn["selected"], "the probe could not put an item in hand")
                self.assertEqual(drawn["ground"], self.answer[theme]["palette"]["Ground"] | -16777216,
                                 "inside the card is the card's ground, opaque")
                self.assertLess(drawn["outerCorner"] >> 24 & 255, 255, "the window's corner is shadow or nothing")
                self.assertLess(drawn["cardCorner"] >> 24 & 255, 255, "the card's corner is round")
                self.assertEqual(drawn["pill"], self.answer[theme]["palette"]["Hover"] | -16777216,
                                 "the item in hand rises into a raised pill")

    def test_at_twice_the_scale_the_card_keeps_its_room(self):
        twice = self.answer["twice"]
        left, top, right, bottom = twice["reach"]
        width, height = twice["window"]
        self.assertEqual(twice["size"], twice["window"])
        self.assertEqual(twice["card"], [left, top, width - left - right, height - top - bottom],
                         "the window is the card with the cards' reach round it, at twice the scale")
        self.assert_within(twice, 8)

    def assert_within(self, drawn, pad):
        cx, cy, cw, ch = drawn["card"]
        for name in ("inside", "item"):
            x, y, w, h = drawn[name]
            self.assertGreaterEqual(x, cx + pad, name)
            self.assertGreaterEqual(y, cy + pad, name)
            self.assertLessEqual(x + w, cx + cw - pad, name)
            self.assertLessEqual(y + h, cy + ch, name)

    def test_the_items_are_laid_out_inside_the_card(self):
        for theme in ("light", "dark"):
            with self.subTest(theme):
                self.assert_within(self.answer[theme]["drawn"], 4)

    def test_high_contrast_is_windows_menu(self):
        contrast = self.answer["contrast"]
        self.assertTrue(contrast["system"], "the renderer must be Windows' own (ToolStripManager's)")
        self.assertNotEqual(contrast["renderer"], "SoftMenuRenderer")
        self.assertFalse(contrast["layered"])
        self.assertFalse(contrast["layer"], "no card is drawn in High Contrast")


PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$flags = [Reflection.BindingFlags]'Instance,Static,NonPublic,Public'
$F = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$PT = $assembly.GetType('CodexAutoResume.Palette', $true)
$M = $assembly.GetType('CodexAutoResume.SoftMenu', $true)
$R = $assembly.GetType('CodexAutoResume.SoftMenuRenderer', $true)
$L = $assembly.GetType('CodexAutoResume.SoftMenuLayer', $true)
$E = $assembly.GetType('CodexAutoResume.Elevation', $true)
$J = $assembly.GetType('CodexAutoResume.Json', $true)
$BT = $assembly.GetType('CodexAutoResume.Bridge', $true)
$PB = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
$utf8 = New-Object Text.UTF8Encoding $false
$adopt = $PT.GetMethod('Adopt', $flags, $null, [type[]]@([string]), $null)
$createParams = [Windows.Forms.Control].GetProperty('CreateParams', $flags)
$out = @{}

function Table {
    $t = @{}
    foreach ($name in @('Ground', 'Rule', 'Hover', 'Text', 'Disabled', 'Chosen')) { $t[$name] = [int]$R.GetProperty($name, $flags).GetValue($null, $null).ToArgb() }
    return $t
}
function Palette-Of {
    $pal = @{}
    $map = @{ Ground = 'Card'; Rule = 'Line'; Hover = 'Raised'; Text = 'Ink'; Disabled = 'Secondary'; Chosen = 'Accent' }
    foreach ($name in $map.Keys) { $pal[$name] = [int]$PT.GetField($map[$name], $flags).GetValue($null).ToArgb() }
    return $pal
}
function New-Menu {
    $menu = [Activator]::CreateInstance($M, $true)
    $menu.Font = [Drawing.SystemFonts]::MessageBoxFont
    $first = [Windows.Forms.ToolStripMenuItem]::new('Postpone')
    $null = $menu.Items.Add($first)
    $branch = $M.GetMethod('Branch', $flags).Invoke($menu, [object[]]@('How this conversation resumes'))
    $sub = [Windows.Forms.ToolStripMenuItem]::new('As in Settings')
    $sub.Checked = $true
    $null = $branch.DropDownItems.Add($sub)
    $null = $branch.DropDownItems.Add([Windows.Forms.ToolStripMenuItem]::new('Ask me first'))
    $null = $menu.Items.Add($branch)
    $null = $menu.Items.Add([Windows.Forms.ToolStripSeparator]::new())
    $off = [Windows.Forms.ToolStripMenuItem]::new('Let it continue')
    $off.Enabled = $false
    $null = $menu.Items.Add($off)
    $null = $menu.Items.Add([Windows.Forms.ToolStripMenuItem]::new('Message for this conversation...'))
    return ,@($menu, $branch, $first)
}
function Layered($control) { return ((([int]$createParams.GetValue($control, $null).ExStyle) -band 0x80000) -ne 0) }
function Pixel($image, [int]$x, [int]$y) { return [int]$image.GetPixel($x, $y).ToArgb() }
function Draw($menu, $first) {
    $menu.Size = $menu.GetPreferredSize([Drawing.Size]::Empty)
    $menu.PerformLayout()
    $null = $menu.Handle
    $first.Select()
    $layer = $M.GetProperty('Layer', $flags).GetValue($menu, $null)
    $null = $L.GetMethod('Render', $flags).Invoke($layer, @())
    $image = $L.GetProperty('Image', $flags).GetValue($layer, $null)
    $card = $L.GetProperty('Card', $flags).GetValue($layer, $null)
    $item = $first.Bounds
    $last = $menu.Items[$menu.Items.Count - 1].Bounds
    $inside = $menu.DisplayRectangle
    return @{ size = @($image.Width, $image.Height); window = @($menu.Width, $menu.Height); selected = [bool]$first.Selected
              card = @($card.X, $card.Y, $card.Width, $card.Height); inside = @($inside.X, $inside.Y, $inside.Width, $inside.Height)
              item = @($item.X, $item.Y, $item.Width, $item.Height)
              ground = (Pixel $image ($card.X + [int]($card.Width / 2)) ($last.Bottom + 2))
              outerCorner = (Pixel $image 0 0); cardCorner = (Pixel $image $card.X $card.Y)
              pill = (Pixel $image ($item.Right - 4) ($item.Y + [int]($item.Height / 2))) }
}

foreach ($theme in @('light', 'dark')) {
    $null = $adopt.Invoke($null, [object[]]@($theme))
    $made = New-Menu
    $menu = $made[0]; $branch = $made[1]
    $menu.Visible = $false
    $result = @{ renderer = $menu.Renderer.GetType().Name; subRenderer = $branch.DropDown.Renderer.GetType().Name
                 sameRenderer = [object]::ReferenceEquals($menu.Renderer, $branch.DropDown.Renderer)
                 subType = $branch.DropDown.GetType().Name; subFont = $branch.DropDown.Font.Equals($menu.Font)
                 layered = (Layered $menu); dropShadow = [bool]$menu.DropShadowEnabled
                 table = (Table); palette = (Palette-Of) }
    $result.drawn = Draw $menu $made[2]
    $out[$theme] = $result
    $menu.Dispose()
}

# Twice the scale: the card's room is the cards' reach and its padding at that scale.
$null = $adopt.Invoke($null, [object[]]@('light'))
$dpi = $F.GetField('dpiScale', $flags)
$saved = [double]$dpi.GetValue($null)
$dpi.SetValue($null, [double]2.0)
$made = New-Menu
$reach = $E.GetMethod('Reach', $flags, $null, [type[]]@([string]), $null).Invoke($null, [object[]]@('card'))
$drawn = Draw $made[0] $made[2]
$out.twice = $drawn
$out.twice.reach = @($reach.Left, $reach.Top, $reach.Right, $reach.Bottom)
$made[0].Dispose()
$dpi.SetValue($null, $saved)

# High Contrast: Windows' menu.
$null = $adopt.Invoke($null, [object[]]@('contrast'))
$made = New-Menu
$out.contrast = @{ renderer = $made[0].Renderer.GetType().Name
                   system = [object]::ReferenceEquals($made[0].Renderer, [Windows.Forms.ToolStripManager]::Renderer)
                   layered = (Layered $made[0]); layer = ($M.GetProperty('Layer', $flags).GetValue($made[0], $null) -ne $null) }
$made[0].Dispose()
$null = $adopt.Invoke($null, [object[]]@('light'))

# The window's own Pending menu.
$english = $J.GetMethod('Parse', $flags).Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $env:CAR_WORK 'strings-en.json'), $utf8)))
$nowhere = [string](Join-Path $env:CAR_WORK 'nowhere')
$once = $BT.GetConstructors($flags)[0].Invoke([object[]]@($nowhere))
$bridge = $PB.GetConstructors($flags)[0].Invoke([object[]]@($nowhere, $once))
$three = @($F.GetConstructors($flags) | Where-Object { $_.GetParameters().Count -eq 3 })[0]
$window = $three.Invoke([object[]]@($bridge, $english, [Drawing.SystemFonts]::MessageBoxFont))
$F.GetField('auditing', $flags).SetValue($window, $true)
$window.TopLevel = $false
$show = @($F.GetMethods($flags) | Where-Object { $_.Name -eq 'ShowPage' -and $_.GetParameters().Count -eq 1 })[0]
$null = $show.Invoke($window, [object[]]@('pending'))
$pendingMenu = $F.GetField('pendingMenu', $flags).GetValue($window)
$list = $F.GetField('pendingList', $flags).GetValue($window)
$out.pending = @{ type = $pendingMenu.GetType().Name; renderer = $pendingMenu.Renderer.GetType().Name
                  list = [object]::ReferenceEquals($list.ContextMenuStrip, $pendingMenu) }
$window.Dispose()

[IO.File]::WriteAllText((Join-Path $env:CAR_WORK 'result.json'), (ConvertTo-Json $out -Compress -Depth 6), $utf8)
"""


if __name__ == "__main__":
    unittest.main()
