"""The window mirrored for a language written right to left (v0.6.20, W8a: phase A of plans/v0619-design/D-rtl.md).

Arabic and Hebrew read from the right, so a window in either is mirrored: what stands at the left in every other language
stands at the right - a table's columns, a row's buttons, a card's light and its words, a switch's knob, the scroll bar - and
its words read right to left (gui/SoftMirror.cs). Measured in v0.6.11 (plans/v0611-sources/s2c_rtl_gaps.md): Windows' own
mirroring (Form.RightToLeftLayout, WS_EX_LAYOUTRTL) reaches only a form's direct children and draws GDI+ text reversed in
a double-buffered control, so the window sets RightToLeft on each form - which mirrors every table, flowing row and anchor
in them - and each of its own layout engines and painters asks Mirror where a thing goes.

Two kinds of test:
* the source's shape: the mirror is taken from the words' language before anything is built, every window and dialog takes
  it, and every painter and layout engine of the controls asks it (`MirrorSourceTests`);
* the window itself, built and never shown (`MirrorAuditTests`): in Arabic and in Hebrew, at every scaling, every page,
  Settings section and dialog the layout audit lays out stands where the same window laid out left to right had it,
  mirrored - within a pixel, as wide and as tall - each list's first column at its right and each row's first button at its
  left (SettingsForm.MirrorAudit); the layout audit laid out right to left finds nothing cut off, no button out of its
  (mirrored) corner and the header's light at its (mirrored) place; and English is not mirrored at all.
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

from codex_auto_resume import l10n, settings

import test_gui_layout

ROOT = Path(__file__).resolve().parents[1]
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
SCALES = test_gui_layout.SCALES
RIGHT_TO_LEFT = sorted(l10n.RIGHT_TO_LEFT)


class MirrorSourceTests(unittest.TestCase):
    def setUp(self):
        self.mirror = guiscan.read("gui/SoftMirror.cs")

    def test_the_mirror_is_one_of_the_controls(self):
        self.assertIn("gui/SoftMirror.cs", guiscan.group("controls"))
        self.assertIn("internal static class Mirror", self.mirror)

    def test_the_languages_it_mirrors_are_the_catalogs_written_right_to_left(self):
        language = guiscan.member_body("Mirror", "Language")
        for locale in l10n.RIGHT_TO_LEFT:
            self.assertIn('"%s"' % locale, language)
        # `iw`, the older code some systems still give for Hebrew (l10n's _LANGUAGE_HOME).
        self.assertIn('"iw"', language)

    def test_the_window_takes_it_from_its_words_before_anything_is_built(self):
        window = guiscan.read("gui/SettingsApp.cs")
        taken = window.index("Mirror.Window = Mirror.Language(wordsLanguage);")
        self.assertLess(window.index("Typeface.ForLanguage(Font, strings, wordsLanguage)"), taken,
                        "the words' language is known only once the strings are adopted")
        self.assertLess(taken, window.index("Mirror.Apply(this);"))
        self.assertLess(window.index("Mirror.Apply(this);"), window.index("BuildFooter();"),
                        "what is built inherits the form's RightToLeft only if the form has it first")

    def test_every_window_and_dialog_takes_it(self):
        """Every form here calls Soft.TitleBar - the window, each dialog and the setup window - and a dialog is a window of
        its own, which does not inherit its owner's RightToLeft."""
        title = guiscan.member_body("Soft", "TitleBar")
        self.assertLess(title.index("Mirror.Apply(form);"), title.index("if (!Palette.Dark"),
                        "mirrored in light as in dark")
        for source in guiscan.sources() + [ROOT / name for name in advanced_sources()]:
            text = source.read_text(encoding="utf-8")
            for match in re.finditer(r"var dialog = new Form\(\);|using \(var dialog = new Form\(\)\)", text):
                with self.subTest(source=source.name, at=match.start()):
                    self.assertIn("Soft.TitleBar(dialog);", text[match.start():match.start() + 800])

    def test_left_to_right_never_reaches_the_mirror(self):
        """Every answer of Mirror is its argument unchanged when not mirrored, so a window in a language written left to
        right is the window it was."""
        for member in ("X", "Box", "Within", "Sides", "Words", "Align", "Anchor"):
            with self.subTest(member):
                body = guiscan.member_body("Mirror", member)
                self.assertRegex(body, r"if \(!mirrored\) return \w+;|return mirrored \?",
                                 "a left-to-right answer is the argument itself")
        self.assertIn("if (form == null || !Window) return;", guiscan.member_body("Mirror", "Apply"))

    def test_the_light_still_falls_from_the_top_left(self):
        """The decision recorded for the owner in v0.6.11, the same on the popup, the card and the panel: the brand's lift
        is the room's light, not the reading direction, so no shadow offset asks the mirror."""
        depth = guiscan.read("gui/SoftDepth.cs")
        self.assertNotIn("Mirror.", depth)

    def test_every_painter_and_layout_engine_of_the_controls_asks_it(self):
        asked = {
            "SoftPage": ("Mirror.Of(this) ? Padding.Right + gutter : Padding.Left",  # what it holds past the bar's gutter
                         "Mirror.Box(Mirror.Of(this), ClientSize.Width,",         # the bar at the left
                         "if (Mirror.Of(this)) PlaceMirrored();"),               # a placed child at the right
            "SoftPin": ("Mirror.X(Mirror.Of(this), width, width - size.Width, size.Width)",),   # pinned at the bottom left
            "SoftCard": ("Bar(e.Graphics, ClientRectangle, radius, Mirror.Of(this))",            # Classic's bar inside
                         "mirrored ? inner.Right - wide : inner.X",                              # the right hairline
                         "Mirror.Display(this, base.DisplayRectangle)",                          # its padding mirrored
                         "Mirror.Caps(this);"),                                                  # a capped line at the right
            "SoftStack": ("Mirror.Display(this, base.DisplayRectangle)",),
            "SoftRows": ("Mirror.Display(this, base.DisplayRectangle)",),
            "SoftFlow": ("Mirror.Display(this, base.DisplayRectangle)",                         # its padding mirrored
                         "if (Soft.OwnVisible(child)) child.Left += Padding.Left;"),             # a row from the right
            "SoftListHost": ("clip.SetBounds(mirrored ? Width - rows : 0", "Mirror.Box(Mirror.Of(this), Width,",
                             "MirrorColumns();"),
            "SoftButton": ("Mirror.Words(Mirror.Of(this),",),
            "SoftCheck": ("return Mirror.Box(Mirror.Of(this), Width, glyph);",                   # the glyph at the right
                          "Palette.Card, mirrored);",                                             # the knob travelling left
                          "Mirror.Box(mirrored, Width, new Rectangle(wide, 0,"),                  # the words left of it
            "SoftNumber": ("Mirror.X(Mirror.Of(this), Width, left, width)",),
            "ChoiceCard": ("Mirror.Box(mirrored, Width, TextColumn(Width))",),
            "SoftTextArea": ("int clipX = mirrored ? Width - Padding.Left - shown : Padding.Left;",
                             "int boxX = mirrored ? -native : 0;"),
            "SoftQuote": ("Mirror.Words(mirrored, Words)",),
            "SoftCallout": ("Mirror.Box(mirrored, (float)Width,",),
            "SoftCombo": ("Mirror.X(mirrored, face.Width, left, room)", "left1 = Mirror.X(true, (float)face.Width, left1, wedge);"),
            "SoftDropList": ("mirrored = Mirror.Of(combo);", "int left = scrolls ? TrackRect.Right + Soft.Px(Brand.SpaceXs) : pad;",
                             "mirrored ? field.Right + pad - width : field.X - pad"),
            "WrapLabel": ("return Mirror.Words(Mirror.Of(this), flags);",                          # aligned as Label is
                          "return Mirror.Of(this) ? Agreed(proposedSize) : Remembered(proposedSize);"),  # its answers agree
            "VersionLabel": ("versionBox = Mirror.Box(mirrored, block.Width, versionBox);",),
            "NavButton": ("Mirror.Words(Mirror.Of(this),",),
            "GateList": ("row[1], Font, tone, ground, mirrored);",),
            "OutcomeChart": ("Width - labelWidth - Px(12) - bodyWidth",),
        }
        for type_name, fragments in asked.items():
            body = guiscan.type_body(type_name)
            for fragment in fragments:
                with self.subTest(type=type_name, fragment=fragment):
                    self.assertIn(fragment, body)
        self.assertIn("if (mirrored) x = track.X + track.Right - x - size;", guiscan.type_body("Soft"))
        self.assertIn("if (Mirror.Window) RightToLeft = RightToLeft.Yes;", guiscan.type_body("SoftMenu"))

    def test_a_list_is_never_mirrored_by_windows(self):
        """Windows would move a mirrored list's own bar to its left, into the clip that hides it (SoftListHost); its columns
        go the other way instead, and its first column's cell is worked out from the columns' order - Windows answers it
        as the whole row from the left edge."""
        host = guiscan.type_body("SoftListHost")
        self.assertIn("list.RightToLeft = RightToLeft.No;", host)
        self.assertIn("MirrorColumns", host)
        cell = guiscan.member_body("SettingsForm", "DrawCell")
        self.assertIn("CellBounds(list, e)", cell)


def advanced_sources() -> list:
    lines = (ROOT / "advanced" / "gui" / "window.sources").read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith(("#", "["))]


PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$static = [Reflection.BindingFlags]'Static,NonPublic,Public'
$form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$mirror = $assembly.GetType('CodexAutoResume.Mirror', $true)
$audit = $form.GetMethod('MirrorAudit', $static)
$layout = $form.GetMethod('LayoutAudit', $static)
$compared = $form.GetField('AuditedMirror', $static)
$window = $mirror.GetField('Window', $static)
$work = [string]$env:CAR_WORK
$utf8 = New-Object Text.UTF8Encoding $false
$schema = [IO.File]::ReadAllText((Join-Path $work 'schema.json'), $utf8)
$current = [IO.File]::ReadAllText((Join-Path $work 'settings.json'), $utf8)
$snapshot = [IO.File]::ReadAllText((Join-Path $work 'snapshot.json'), $utf8)
$out = @{ mirror = @{}; compared = @{}; english = @{} }
foreach ($locale in (ConvertFrom-Json $env:CAR_LOCALES)) {
    $catalog = [IO.File]::ReadAllText((Join-Path $work ('strings-' + $locale + '.json')), $utf8)
    $out.mirror[$locale] = @{}
    $out.compared[$locale] = @{}
    foreach ($scale in (ConvertFrom-Json $env:CAR_SCALES)) {
        $key = ([double]$scale).ToString('0.00', [Globalization.CultureInfo]::InvariantCulture)
        $out.mirror[$locale][$key] = [string]$audit.Invoke($null, [object[]]@($schema, $current, $catalog, $snapshot, [double]$scale))
        $out.compared[$locale][$key] = [int]$compared.GetValue($null)
    }
}
# English: built as it always was, never mirrored.
$english = [IO.File]::ReadAllText((Join-Path $work 'strings-en.json'), $utf8)
$layout.Invoke($null, [object[]]@($schema, $current, $english, $snapshot, [double]1.0)) | Out-Null
$out.english.window = [bool]$window.GetValue($null)
$out | ConvertTo-Json -Depth 6 -Compress | Set-Content -Encoding UTF8 (Join-Path $work 'result.json')
"""


class MirrorAuditTests(unittest.TestCase):
    """The window built and never shown, in each language written right to left at every scaling (SettingsForm.MirrorAudit)."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll",
                        "/reference:System.Windows.Forms.dll",
                        *[str(path) for path in guiscan.sources()]],
                       check=True, capture_output=True, timeout=300)
        current = dict(settings.defaults(), continuation_style="custom", custom_message_mode="per_reason")
        (work / "schema.json").write_text(json.dumps(settings.describe(), ensure_ascii=False), encoding="utf-8")
        (work / "settings.json").write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
        for locale in RIGHT_TO_LEFT + ["en"]:
            reply = {"ok": True, "language": locale, "strings": l10n.catalog(locale), "endonyms": dict(l10n.ENDONYMS),
                     "preference": locale, "system_language": locale}
            (work / ("strings-%s.json" % locale)).write_text(json.dumps(reply, ensure_ascii=False), encoding="utf-8")
        (work / "snapshot.json").write_text(json.dumps(test_gui_layout.fullest_snapshot(time.time()), ensure_ascii=False),
                                            encoding="utf-8")
        probe = work / "probe.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        cls.result = subprocess.run(
            [str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900 * len(RIGHT_TO_LEFT),
            env=dict(os.environ, CAR_EXE=str(exe), CAR_WORK=str(work),
                     CAR_LOCALES=json.dumps(RIGHT_TO_LEFT), CAR_SCALES=json.dumps(list(SCALES))))
        answer = work / "result.json"
        cls.answer = (json.loads(answer.read_text(encoding="utf-8-sig"))
                      if cls.result.returncode == 0 and answer.is_file() else {})

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-3000:])

    def test_every_page_section_and_dialog_is_the_left_to_right_window_mirrored(self):
        self.assertEqual(sorted(self.answer["mirror"]), RIGHT_TO_LEFT)
        for locale in RIGHT_TO_LEFT:
            for scale in SCALES:
                with self.subTest(locale=locale, scale=scale):
                    report = self.answer["mirror"][locale]["%.2f" % scale]
                    self.assertEqual(report, "", "\n" + report[:6000])

    def test_the_comparison_looked_at_the_whole_window(self):
        """Every page, Settings section and dialog the audit lays out: well over a thousand controls."""
        for locale in RIGHT_TO_LEFT:
            for scale in SCALES:
                with self.subTest(locale=locale, scale=scale):
                    self.assertGreater(self.answer["compared"][locale]["%.2f" % scale], 1000)

    def test_english_is_not_mirrored(self):
        self.assertFalse(self.answer["english"]["window"])


if __name__ == "__main__":
    unittest.main()
