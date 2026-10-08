"""v0.6.11: the edition beside the version - since v0.6.14 an advanced edition's only.

The owner's rule: wherever the version is shown, the edition is named beside it - the Dashboard's save
bar ("v0.6.11 · Standard"), Diagnostics' Version row, the panel's heading in Codex - and the
notification-area icon's tooltip names it after the product. Positions and every other word stay.
The owner's rule of 2026-10-05, from v0.6.14: no Standard label in the standard edition - each of those
surfaces shows the version (or the product's name) alone there, exactly as with no edition at all, while
an advanced installation, loaded or not, keeps its word. Only the word goes: the status still carries the
code `standard`, and the version picker's Edition column still says Standard, since there it names what a
row installs (test_gui_versions).

One code says which (edition.shown): `standard` or `advanced`, the edition that runs, or
`advanced_not_loaded` for an advanced installation whose package could not be taken - it runs as the
standard edition, and says so. The status carries it for the window and the panel, the watcher hands
it to its icon, and each surface says it in the catalog's word for the reader's language
(`edition.<code>`, in all 18 catalogs).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import brand, control, edition, interface, l10n  # noqa: E402
from codex_auto_resume.domain.plug import NULL, DamagedPlug, Edition, Plug, PlugFailure, guard  # noqa: E402
from codex_auto_resume.mcp import panel  # noqa: E402
from codex_auto_resume.ui import tray  # noqa: E402
from test_control import ControlTestCase  # noqa: E402
from test_mcpui_v063 import ROOT_TOKENS, RULES, declared  # noqa: E402
from test_mcpui_v064 import NODE, run_page, say, snapshot  # noqa: E402

import guiscan  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CODES = ("standard", "advanced", edition.NOT_LOADED)
# The codes whose word a surface shows beside the version (v0.6.14): an advanced installation's, loaded or not.
NAMED = ("advanced", edition.NOT_LOADED)
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")


class AdvancedPlug(Plug):
    """An advanced edition's plug that answers nothing: only its edition is asked here."""
    __slots__ = ()
    edition = Edition.ADVANCED
    badge = "Advanced"


class ShownTests(unittest.TestCase):
    def test_the_code_is_the_edition_that_runs(self):
        self.assertEqual(edition.shown(NULL), "standard")
        self.assertEqual(edition.shown(guard(NULL)), "standard")
        self.assertEqual(edition.shown(AdvancedPlug()), "advanced")
        self.assertEqual(edition.shown(guard(AdvancedPlug())), "advanced")
        for failure in PlugFailure:
            with self.subTest(failure):
                self.assertEqual(edition.shown(DamagedPlug(failure)), "advanced_not_loaded")
                self.assertEqual(edition.shown(guard(DamagedPlug(failure))), "advanced_not_loaded")
        self.assertEqual(edition.NOT_LOADED, "advanced_not_loaded")
        self.assertEqual(set(CODES), {str(item) for item in Edition} | {edition.NOT_LOADED})

    def test_every_catalog_says_each_in_a_word_of_its_own(self):
        for locale in l10n.LOCALES:
            table = l10n._read(locale)
            with self.subTest(locale):
                words = [table["edition." + code] for code in CODES]
                self.assertTrue(all(word.strip() for word in words))
                self.assertEqual(len(set(words)), len(words), words)
                self.assertFalse(any(l10n.placeholders(word) for word in words))
                # Not loaded is the advanced edition's word, and says more.
                self.assertTrue(words[2].startswith(words[1]), words)
        english = l10n._read(l10n.DEFAULT)
        self.assertEqual([english["edition." + code] for code in CODES],
                         ["Standard", "Advanced", "Advanced - not loaded"])


class StatusTests(ControlTestCase):
    def test_the_status_names_the_edition_after_the_version(self):
        status = self.control.get_status()
        self.assertEqual(status["edition"], "standard")
        self.assertEqual(list(status)[:2], ["version", "edition"])

    def test_an_advanced_plug_is_named_and_one_not_loaded_says_so(self):
        advanced = control.Control(self.paths, plug=AdvancedPlug())
        self.assertEqual(advanced.get_status()["edition"], "advanced")
        damaged = control.Control(self.paths, plug=DamagedPlug(PlugFailure.IMPORT_FAILED))
        self.assertEqual(damaged.get_status()["edition"], "advanced_not_loaded")


class TooltipTests(unittest.TestCase):
    def test_the_title_names_the_edition_in_the_readers_word(self):
        english, korean = interface.STRINGS["en"], interface.STRINGS["ko"]
        paused = {"enabled": False}
        self.assertEqual(tray.tooltip(paused, english, 0, "advanced"), "Codex Auto Resume · Advanced\nPaused")
        self.assertEqual(tray.tooltip(paused, korean, 0, "advanced"),
                         "Codex Auto Resume · 고급판\n" + korean["tray.paused"])
        self.assertEqual(tray.tooltip(paused, english, 0, edition.NOT_LOADED),
                         "Codex Auto Resume · Advanced - not loaded\nPaused")
        self.assertEqual(tray.tooltip({}, english, 0, "advanced"), "Codex Auto Resume · Advanced")
        # With no edition handed to it, the tooltip is what it was.
        self.assertEqual(tray.tooltip(paused, english, 0), "Codex Auto Resume\nPaused")

    def test_the_standard_edition_is_named_nowhere_in_the_tooltip(self):
        """v0.6.14 (the owner, 2026-10-05): the standard edition's tooltip is the one with no edition, in every
        language and every state - its catalog word appears nowhere in its title - while the code it is handed
        stays the status's."""
        self.assertEqual(tray.UNNAMED_EDITION, str(Edition.STANDARD))
        self.assertEqual(edition.shown(NULL), tray.UNNAMED_EDITION)
        english = interface.STRINGS["en"]
        self.assertEqual(tray.tooltip({"enabled": False}, english, 0, "standard"), "Codex Auto Resume\nPaused")
        self.assertEqual(tray.tooltip({}, english, 0, "standard"), "Codex Auto Resume")
        snapshots = ({}, {"enabled": False}, {"failed": True}, {"enabled": True},
                     {"enabled": True, "waiting": 2, "running": 1, "next_at": 200})
        for language, strings in interface.STRINGS.items():
            word = strings["edition.standard"]
            for state in snapshots:
                with self.subTest(language=language, snapshot=state):
                    text = tray.tooltip(state, strings, 0, "standard")
                    self.assertEqual(text, tray.tooltip(state, strings, 0))
                    self.assertNotIn(word, text.split("\n", 1)[0])
                    self.assertNotIn(" · " + word, text)

    def test_every_language_keeps_its_whole_tooltip_with_the_longest_edition(self):
        for language, strings in interface.STRINGS.items():
            for code in CODES:
                with self.subTest(language=language, edition=code):
                    busy = {"enabled": True, "waiting": 99, "running": 99, "next_at": 10 ** 6}
                    text = tray.tooltip(busy, strings, 0, code)
                    self.assertLess(len(text), tray.TIP_CHARS)
                    # Nothing cut: the status line is the one the tooltip without the edition ends in.
                    self.assertTrue(text.endswith(tray.tooltip(busy, strings, 0).split("\n", 1)[1]))

    def test_the_watcher_hands_its_icon_the_edition_that_runs(self):
        app = (ROOT / "src" / "codex_auto_resume" / "runtime" / "app.py").read_text(encoding="utf-8")
        self.assertIn("edition=edition.shown(self.plug)", app)
        icon = (ROOT / "src" / "codex_auto_resume" / "ui" / "tray" / "icon.py").read_text(encoding="utf-8")
        self.assertEqual(icon.count("tooltip("), icon.count("time.time(), self.edition)"))


class PanelTests(unittest.TestCase):
    def test_the_heading_names_the_edition_beside_the_version(self):
        script = (ROOT / "src" / "codex_auto_resume" / "mcp" / "assets" / "panel.js").read_text(encoding="utf-8")
        heading = script[script.index("function renderHero("):]
        heading = heading[:heading.index("var line = ")]
        self.assertIn("'Codex Auto Resume · v' + (status.version || '?')", heading)
        # v0.6.14: an advanced edition's word only - the standard edition is named nowhere beside the version.
        self.assertIn("var named = status.edition && status.edition !== '%s';" % tray.UNNAMED_EDITION, heading)
        self.assertIn("if (named) eyebrow.appendChild(element('span', 'edition', "
                      "t('edition.' + status.edition, status.edition)));", heading)
        _names, prefixes = panel.panel_keys()
        self.assertIn("edition.", prefixes)
        for locale, table in panel.panel_catalogs().items():
            with self.subTest(locale):
                for code in CODES:
                    self.assertIn("edition." + code, table)

    @unittest.skipUnless(NODE, "needs Node to run the panel's own code")
    def test_the_edition_follows_the_version_after_a_space_with_no_separator(self):
        """The owner's decision of 2026-10-02: quiet secondary text after the version, not "· Advanced"."""
        for code in NAMED:
            data = snapshot(interface_language="ko")
            data["status"].update(version="0.6.11-beta.2", edition=code)
            shown = run_page(say("""(function () {
              var eyebrow = ROOT_NODE.all(function (n) { return n.className === 'eyebrow'; })[0];
              return {text: eyebrow.textContent, own: eyebrow._text,
                      spans: eyebrow.children.map(function (n) { return [n.tagName, n.className, n.textContent]; })};
            })()"""), data=data, locale="ko")
            word = l10n._read("ko")["edition." + code]
            with self.subTest(code):
                self.assertEqual(shown["own"], "Codex Auto Resume · v0.6.11-beta.2 ")
                self.assertEqual(shown["spans"], [["span", "edition", word]])
                self.assertEqual(shown["text"], "Codex Auto Resume · v0.6.11-beta.2 " + word)
        # A status that names no edition shows the version alone, as before.
        shown = run_page(say("ROOT_NODE.all(function (n) { return n.className === 'eyebrow'; })"
                             ".map(function (n) { return [n.textContent, n.children.length]; })"))
        self.assertEqual(shown, [["Codex Auto Resume · v0", 0]])

    @unittest.skipUnless(NODE, "needs Node to run the panel's own code")
    def test_the_standard_edition_is_named_nowhere_in_the_heading(self):
        """v0.6.14 (the owner, 2026-10-05): in every language the panel offers, the standard edition's heading is the
        version alone - no trailing space, no .edition span anywhere on the page, and not its catalog word."""
        for locale in l10n.OFFERED:
            data = snapshot(interface_language=locale)
            data["status"].update(version="0.6.14", edition="standard")
            shown = run_page(say("""(function () {
              var eyebrow = ROOT_NODE.all(function (n) { return n.className === 'eyebrow'; })[0];
              return {text: eyebrow.textContent, own: eyebrow._text, children: eyebrow.children.length,
                      editions: ROOT_NODE.all(function (n) { return n.className === 'edition'; }).length};
            })()"""), data=data, locale=locale)
            with self.subTest(locale):
                self.assertEqual(shown, {"text": "Codex Auto Resume · v0.6.14", "own": "Codex Auto Resume · v0.6.14",
                                         "children": 0, "editions": 0})
                self.assertNotIn(l10n._read(locale)["edition.standard"], shown["text"])

    def test_the_edition_is_smaller_muted_and_on_the_versions_baseline(self):
        """Smaller - .62 of the eyebrow, never under 10px - muted in both editions (nothing names one edition's colour),
        and on the version's baseline - which an inline run in the eyebrow's line is, and nothing moves it off."""
        self.assertEqual(declared(".edition", "font-size"), "var(--type-edition)")
        self.assertEqual(ROOT_TOKENS["--type-edition"], "max(10px, calc(var(--type-small) * .62))")
        self.assertEqual(declared(".edition", "color"), "var(--muted)")
        self.assertEqual(declared(".edition", "vertical-align"), "baseline")
        self.assertEqual(declared(".eyebrow", "color"), "var(--muted)")
        small = brand.TYPE_SCALE["small"]
        self.assertLess(max(10, small * .62), small)
        for _where, selectors, declarations in RULES:
            if any("edition" in selector for selector in selectors):
                self.assertEqual(selectors, (".edition",), "one rule, for every edition")
                self.assertNotIn("display", declarations)
                self.assertNotIn("position", declarations)

    def test_the_panel_and_the_window_take_the_same_two_numbers(self):
        theme = guiscan.read("SoftTheme.cs")
        share = float(re.search(r"internal const float AsideShare = ([0-9.]+)f;", theme).group(1))
        least = float(re.search(r"internal const float AsideLeast = ([0-9.]+)f;", theme).group(1))
        self.assertEqual(share, 0.62)
        # 7.5 pt is 10 px at 96 DPI, the panel's floor.
        self.assertEqual(least * 96 / 72, 10)
        self.assertEqual(ROOT_TOKENS["--type-edition"],
                         "max(%gpx, calc(var(--type-small) * %s))" % (least * 96 / 72, ("%g" % share).lstrip("0")))


class WindowTests(unittest.TestCase):
    def test_the_save_bar_and_diagnostics_show_the_version_line(self):
        window = guiscan.whole()
        method = guiscan.member_body("SettingsForm", "ShowVersion")
        self.assertIn('"v" + Convert.ToString(Get(status, "version"), CultureInfo.InvariantCulture)', method)
        self.assertIn('S("edition." + edition, edition)', method)
        # v0.6.14: an advanced edition's word only (QuietEditionTests.test_the_window_names_no_standard_edition runs it).
        self.assertIn("bool named = !string.IsNullOrEmpty(edition) && edition != UnnamedEdition;", method)
        self.assertIn('named ? S("edition." + edition, edition) : null', method)
        self.assertIn('private const string UnnamedEdition = "%s";' % tray.UNNAMED_EDITION, window)
        self.assertNotIn("u00B7", method)
        self.assertNotIn("·", method)
        self.assertEqual(re.findall(r"ShowVersion\((\w+), status\);", window), ["versionText", "diagVersion"])
        self.assertEqual(re.findall(r"(?:versionText|diagVersion)\.Text = ", window), [])
        # Both are the label that draws the edition as quiet text (VersionLabel, below).
        self.assertIn("private readonly VersionLabel versionText = new VersionLabel();", window)
        self.assertIn("private VersionLabel diagVersion;", window)
        self.assertIn('diagVersion = Fact(facts, S("diag.version", "Version"), new VersionLabel());', window)
        # The save bar's version stays secondary text, and Diagnostics' value the page's ink.
        self.assertIn("versionText.ForeColor = Secondary;", window)
        label = guiscan.type_body("VersionLabel")
        self.assertIn("internal static Color EditionColor { get { return Palette.Secondary; } }", label)
        self.assertNotRegex(label, r"\bAccent\b")

    def test_the_layout_audit_measures_the_longest_edition(self):
        from test_gui_layout import fullest_snapshot
        self.assertEqual(fullest_snapshot(0)["status"]["edition"], edition.NOT_LOADED)
        longest = {locale: max((l10n._read(locale)["edition." + code] for code in CODES), key=len)
                   for locale in l10n.LOCALES}
        for locale, word in longest.items():
            with self.subTest(locale):
                self.assertEqual(word, l10n._read(locale)["edition." + edition.NOT_LOADED])


# The edition as quiet secondary text in the window (VersionLabel): every design in light, dark and High Contrast, at
# every one of Windows' text sizes, as the save bar shows it (secondary text, centred in its row) and as Diagnostics'
# Version row does (the page's ink, at the top of its cell). The English words, whose letters stand on the baseline:
# a letter that hangs below it would move the lowest ink the baseline is read from.
QUIET_VERSION = "v0.6.11-beta.2"
QUIET_WORDS = ("Standard", "Advanced", "Advanced - not loaded")
QUIET_TEXT = (1.0, 1.25, 1.5, 1.75, 2.0, 2.25)
QUIET_THEMES = ("light", "dark", "contrast")

QUIET_PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
# The picture read in compiled code: PowerShell asking a bitmap for each pixel takes minutes.
Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @'
using System;
using System.Drawing;
public static class Ink {
    static int Far(Color a, Color b) { return Math.Abs(a.R - b.R) + Math.Abs(a.G - b.G) + Math.Abs(a.B - b.B); }
    // The lowest row with ink in columns [from, to): a pixel at least half as far from the ground as the ink is.
    public static int Bottom(Bitmap picture, int from, int to, Color ground, Color ink) {
        int least = Math.Max(1, Far(ground, ink) / 2);
        for (int y = picture.Height - 1; y >= 0; y--)
            for (int x = Math.Max(0, from); x < Math.Min(to, picture.Width); x++)
                if (Far(picture.GetPixel(x, y), ground) >= least) return y;
        return -1;
    }
    // The pixel in columns [from, to) farthest from the ground: the colour the words there are drawn in.
    public static Color Farthest(Bitmap picture, int from, int to, Color ground) {
        Color found = ground; int most = -1;
        for (int y = 0; y < picture.Height; y++)
            for (int x = Math.Max(0, from); x < Math.Min(to, picture.Width); x++) {
                Color pixel = picture.GetPixel(x, y);
                if (Far(pixel, ground) > most) { most = Far(pixel, ground); found = pixel; }
            }
        return found;
    }
    public static int Distance(Color a, Color b) { return Far(a, b); }
    // How many pixels of columns [0, to) differ between two pictures of one size.
    public static int Differing(Bitmap a, Bitmap b, int to) {
        int count = 0;
        for (int y = 0; y < Math.Min(a.Height, b.Height); y++)
            for (int x = 0; x < Math.Min(to, Math.Min(a.Width, b.Width)); x++)
                if (a.GetPixel(x, y).ToArgb() != b.GetPixel(x, y).ToArgb()) count++;
        return count;
    }
}
'@
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$static = [Reflection.BindingFlags]'Static,NonPublic,Public'
$instance = [Reflection.BindingFlags]'Instance,NonPublic,Public'
$labelType = $assembly.GetType('CodexAutoResume.VersionLabel', $true)
$wrapType = $assembly.GetType('CodexAutoResume.WrapLabel', $true)
$palette = $assembly.GetType('CodexAutoResume.Palette', $true)
$set = $labelType.GetMethod('Set', $instance)
$placed = $labelType.GetMethod('Placed', $instance)
$aside = $labelType.GetProperty('AsideFont', $instance)
$drawn = $labelType.GetProperty('EditionDrawn', $instance)
$split = $labelType.GetProperty('Split', $instance)
function Colour([string]$name) { return $palette.GetField($name, $static).GetValue($null) }
function Picture($label) {
    $size = $label.GetPreferredSize([Drawing.Size]::Empty)
    $label.Size = $size
    $bitmap = New-Object Drawing.Bitmap $size.Width, $size.Height
    $label.DrawToBitmap($bitmap, (New-Object Drawing.Rectangle 0, 0, $size.Width, $size.Height))
    return $bitmap
}
function Dress($label, $font, [string]$role) {
    $label.Font = $font
    $label.AutoSize = $true
    $label.BackColor = Colour 'Card'
    if ($role -eq 'savebar') { $label.ForeColor = Colour 'Secondary'; $label.TextAlign = [Drawing.ContentAlignment]::MiddleLeft }
    else { $label.ForeColor = Colour 'Ink'; $label.Margin = New-Object Windows.Forms.Padding 0, 3, 0, 3 }
}
$base = [Drawing.SystemFonts]::MessageBoxFont
$out = @{ face = $base.FontFamily.Name; cases = @(); plain = @() }
foreach ($design in (ConvertFrom-Json $env:CAR_DESIGNS)) {
  foreach ($theme in (ConvertFrom-Json $env:CAR_THEMES)) {
    $null = $palette.GetMethod('AdoptDesign', $static).Invoke($null, [object[]]@([string]$design))
    $null = $palette.GetMethod('Adopt', $static).Invoke($null, [object[]]@([string]$theme))
    $card = Colour 'Card'; $secondary = Colour 'Secondary'; $ink = Colour 'Ink'; $accent = Colour 'Accent'
    foreach ($text in (ConvertFrom-Json $env:CAR_TEXT)) {
      $font = New-Object Drawing.Font $base.FontFamily, ([float]($base.SizeInPoints * $text)), $base.Style, ([Drawing.GraphicsUnit]::Point)
      # The version's padding either side as Label draws one line, and a space of its font.
      $line = [Windows.Forms.TextFormatFlags]::SingleLine
      $bare = $line -bor [Windows.Forms.TextFormatFlags]::NoPadding
      $huge = New-Object Drawing.Size ([int]::MaxValue), ([int]::MaxValue)
      $versionPad = [Math]::Floor(([Windows.Forms.TextRenderer]::MeasureText([string]$env:CAR_VERSION, $font, $huge, $line).Width -
                                   [Windows.Forms.TextRenderer]::MeasureText([string]$env:CAR_VERSION, $font, $huge, $bare).Width) / 2)
      $space = [Windows.Forms.TextRenderer]::MeasureText('x x', $font, $huge, $bare).Width - [Windows.Forms.TextRenderer]::MeasureText('xx', $font, $huge, $bare).Width
      foreach ($role in @('savebar', 'diagnostics')) {
        # The version as the label drew it before it had an edition to show: a WrapLabel with the version alone.
        $before = [Activator]::CreateInstance($wrapType, $true)
        Dress $before $font $role
        $before.Text = [string]$env:CAR_VERSION
        $beforePicture = Picture $before
        foreach ($word in (ConvertFrom-Json $env:CAR_WORDS)) {
          $label = [Activator]::CreateInstance($labelType, $true)
          Dress $label $font $role
          $null = $set.Invoke($label, [object[]]@([string]$env:CAR_VERSION, [string]$word))
          $picture = Picture $label
          $boxes = [object[]]@([Drawing.Rectangle]::Empty, [Drawing.Rectangle]::Empty, $false)
          $null = $placed.Invoke($label, $boxes)
          $v = $boxes[0]; $e = $boxes[1]
          $far = [Ink]::Farthest($picture, $e.Left, $e.Right, $card)
          $out.cases += ,@{ design = [string]$design; theme = [string]$theme; text = [double]$text; role = $role
                            word = [string]$word; label = [string]$label.Text; split = [bool]$split.GetValue($label, $null)
                            below = [bool]$boxes[2]
                            version = [double]$label.Font.SizeInPoints
                            edition = [double]$aside.GetValue($label, $null).SizeInPoints
                            face = [string]$aside.GetValue($label, $null).FontFamily.Name
                            drawn = [int]$drawn.GetValue($label, $null).ToArgb(); secondary = [int]$secondary.ToArgb()
                            accent = [int]$accent.ToArgb()
                            toSecondary = [Ink]::Distance($far, $secondary); toAccent = [Ink]::Distance($far, $accent)
                            toInk = [Ink]::Distance($far, $ink); inkIsSecondary = ($ink.ToArgb() -eq $secondary.ToArgb())
                            versionBottom = [Ink]::Bottom($picture, $v.Left, $e.Left, $card, $label.ForeColor)
                            editionBottom = [Ink]::Bottom($picture, $e.Left, $e.Right, $card, $secondary)
                            versionRight = $v.Right; editionLeft = $e.Left; versionPad = [int]$versionPad; space = [int]$space
                            height = $picture.Height; heightBefore = $beforePicture.Height
                            changed = [Ink]::Differing($picture, $beforePicture, [Math]::Min($e.Left, $beforePicture.Width)) }
          $picture.Dispose(); $label.Dispose()
        }
        # Without an edition it is the label it was.
        $plain = [Activator]::CreateInstance($labelType, $true)
        Dress $plain $font $role
        $null = $set.Invoke($plain, [object[]]@([string]$env:CAR_VERSION, $null))
        $plainPicture = Picture $plain
        $out.plain += ,@{ text = [string]$plain.Text; split = [bool]$split.GetValue($plain, $null)
                          size = @($plainPicture.Width, $plainPicture.Height); before = @($beforePicture.Width, $beforePicture.Height)
                          changed = [Ink]::Differing($plainPicture, $beforePicture, $plainPicture.Width) }
        $plainPicture.Dispose(); $plain.Dispose(); $beforePicture.Dispose(); $before.Dispose()
      }
    }
  }
}
# v0.6.14: the window's own ShowVersion, as the save bar and Diagnostics call it, for each code the status carries and
# for none - on a form whose constructor never ran, given the catalog's edition words and nothing else.
$formType = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$form = [Runtime.Serialization.FormatterServices]::GetUninitializedObject($formType)
$strings = [System.Collections.Generic.Dictionary[string,object]]::new()
foreach ($pair in (ConvertFrom-Json $env:CAR_EDITION_WORDS).PSObject.Properties) { $strings[[string]$pair.Name] = [string]$pair.Value }
$formType.GetField('strings', $instance).SetValue($form, $strings)
$showVersion = $formType.GetMethod('ShowVersion', $instance)
$out.shown = @()
foreach ($code in (ConvertFrom-Json $env:CAR_CODES)) {
  $status = [System.Collections.Generic.Dictionary[string,object]]::new()
  $status['version'] = [string]$env:CAR_STATUS_VERSION
  if ([string]$code) { $status['edition'] = [string]$code }
  $label = [Activator]::CreateInstance($labelType, $true)
  $null = $showVersion.Invoke($form, [object[]]@($label, $status))
  $out.shown += ,@{ code = [string]$code; text = [string]$label.Text; split = [bool]$split.GetValue($label, $null) }
  $label.Dispose()
}
$out | ConvertTo-Json -Depth 5 -Compress
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class QuietEditionTests(unittest.TestCase):
    """The owner's decision of 2026-10-02 on "v0.6.11 · Standard", in the window: the edition after the version as
    quiet secondary text - smaller, in the secondary colour in both editions, its baseline on the version's - while the
    version itself is drawn exactly where and as it was. The real compiled window's VersionLabel, drawn into bitmaps."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64",
                        "/out:" + str(exe), "/reference:System.dll",
                        "/reference:System.Drawing.dll", "/reference:System.Windows.Forms.dll",
                        *[str(path) for path in guiscan.sources()]],
                       check=True, capture_output=True, timeout=300,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        probe = work / "probe.ps1"
        probe.write_text(QUIET_PROBE, encoding="utf-8-sig")
        cls.result = subprocess.run(
            [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=dict(os.environ, CAR_EXE=str(exe), CAR_VERSION=QUIET_VERSION, CAR_WORDS=json.dumps(QUIET_WORDS),
                     CAR_TEXT=json.dumps(QUIET_TEXT), CAR_THEMES=json.dumps(QUIET_THEMES),
                     CAR_DESIGNS=json.dumps(list(brand.DESIGNS)),
                     CAR_STATUS_VERSION=QUIET_VERSION[1:], CAR_CODES=json.dumps(list(CODES) + [""]),
                     CAR_EDITION_WORDS=json.dumps({"edition." + code: word for code, word in zip(CODES, QUIET_WORDS)})))
        ok = cls.result.returncode == 0 and cls.result.stdout.strip()
        cls.answer = json.loads(cls.result.stdout) if ok else {}

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-2000:])

    def each(self, check):
        """`check` on every case, each a subtest of its own."""
        cases = self.answer["cases"]
        self.assertEqual(len(cases), len(brand.DESIGNS) * len(QUIET_THEMES) * len(QUIET_TEXT) * 2 * len(QUIET_WORDS))
        for case in cases:
            with self.subTest(design=case["design"], theme=case["theme"], text=case["text"], role=case["role"],
                              word=case["word"]):
                check(case)

    def test_the_line_is_the_version_and_the_edition_with_no_separator(self):
        def check(case):
            self.assertEqual(case["label"], QUIET_VERSION + " " + case["word"])
            self.assertTrue(case["split"])
            self.assertFalse(case["below"], "both on one line")
            # A space of the version's font after its last letter: past the version's own box less its padding, and
            # never as far as a second space.
            self.assertGreater(case["editionLeft"], case["versionRight"] - case["versionPad"])
            self.assertLess(case["editionLeft"], case["versionRight"] - case["versionPad"] + 2 * case["space"])
        self.each(check)

    def test_the_edition_is_smaller_than_the_version(self):
        def check(case):
            self.assertLess(case["edition"], case["version"])
            self.assertAlmostEqual(case["edition"], max(7.5, case["version"] * 0.62), places=3)
            self.assertEqual(case["face"], self.answer["face"], "the version's own face")
            if case["text"] == 1.0:
                self.assertAlmostEqual(case["edition"], 7.5, places=3)
        self.each(check)

    def test_the_edition_is_drawn_in_the_secondary_colour_in_both_editions(self):
        def check(case):
            self.assertEqual(case["drawn"], case["secondary"])
            self.assertNotEqual(case["drawn"], case["accent"])
            # And that is the colour the edition's pixels are: nearer the secondary text than the accent, and - where
            # the theme tells them apart - than the page's ink.
            self.assertLess(case["toSecondary"], case["toAccent"])
            if not case["inkIsSecondary"]:
                self.assertLess(case["toSecondary"], case["toInk"])
        self.each(check)

    def test_the_edition_shares_the_versions_baseline(self):
        def check(case):
            self.assertGreaterEqual(case["versionBottom"], 0)
            self.assertGreaterEqual(case["editionBottom"], 0)
            self.assertLessEqual(abs(case["versionBottom"] - case["editionBottom"]), 1)
        self.each(check)

    def test_the_version_is_drawn_where_and_as_it_was(self):
        def check(case):
            self.assertEqual(case["height"], case["heightBefore"], "the line is as tall as the version's")
            self.assertEqual(case["changed"], 0, "the version's own pixels")
        self.each(check)

    def test_the_window_names_no_standard_edition(self):
        """v0.6.14 (the owner, 2026-10-05): the window's own ShowVersion - the save bar's and Diagnostics' Version row -
        shows the standard edition's version alone, exactly as a status with no edition, and an advanced one's word."""
        shown = {case["code"]: case for case in self.answer["shown"]}
        self.assertEqual(set(shown), set(CODES) | {""})
        for code in ("standard", ""):
            with self.subTest(code=code):
                self.assertEqual(shown[code]["text"], QUIET_VERSION)
                self.assertFalse(shown[code]["split"])
                self.assertNotIn("Standard", shown[code]["text"])
        for code, word in zip(CODES, QUIET_WORDS):
            if code in NAMED:
                with self.subTest(code=code):
                    self.assertEqual(shown[code]["text"], QUIET_VERSION + " " + word)
                    self.assertTrue(shown[code]["split"])

    def test_without_an_edition_it_is_the_label_it_was(self):
        self.assertTrue(self.answer["plain"])
        for case in self.answer["plain"]:
            with self.subTest(case=case):
                self.assertEqual(case["text"], QUIET_VERSION)
                self.assertFalse(case["split"])
                self.assertEqual(case["size"], case["before"])
                self.assertEqual(case["changed"], 0)


if __name__ == "__main__":
    unittest.main()
