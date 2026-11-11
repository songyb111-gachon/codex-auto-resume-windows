"""v0.6.17 (#48): each language in the face Windows sets it in - Korean in Malgun Gothic, Japanese in Yu Gothic UI,
Simplified Chinese in Microsoft YaHei UI, Traditional Chinese in Microsoft JhengHei UI - whatever Windows' UI font is.

Until v0.6.17 the window set every language in Windows' UI font unless that lacked its letters and Segoe UI had them
(v0.6.11, win/typeface.py face_for): on an English Windows Japanese was set in Segoe UI, every kana and kanji borrowed
through a font link - in the linked face's shape - and measured that way, 10 to 45 ms a wrapped line, so a click on the
Advanced page waited seconds. Now win/typeface.py (SCRIPT_FACES, language_face) and the window's Typeface
(gui/SoftTheme.cs: ScriptFaces, ForLanguage) set those four languages in their own face where this
machine has it, and as before where it has not; the popup and the card take the same table (ui/popup/fonts.py) and the
panel names each face first for its language (mcp/assets/panel.css). Every other language is set as before.

* RuleTests - the rule, pure: the language's own face where installed, today's choice where not, every other language
  as face_for has it; the popup's table is the same table; the panel's stylesheet names each face for its language.
* InstalledTests - GDI is asked whether a face is there (typeface.installed).
* WindowTests - the compiled window's Typeface and the window itself, asked through reflection in a PowerShell: each
  language in its face under Segoe UI and under Malgun Gothic as Windows' UI font, a missing face falling back to the
  choice before v0.6.17, and the same answers as win/typeface.py's. No window is shown.

GUI test module: WindowTests compiles the window with the in-box C# compiler (csc.exe), so it runs on its own.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import l10n  # noqa: E402
from codex_auto_resume.mcp import panel as mcpui  # noqa: E402
from codex_auto_resume.ui import popup  # noqa: E402
from codex_auto_resume.ui.popup import fonts  # noqa: E402
from codex_auto_resume.win import typeface  # noqa: E402
from test_gui_v0611_access import CSC, POWERSHELL, compile_window, reply, run_probe  # noqa: E402

FACES = {"ko": "Malgun Gothic", "ja": "Yu Gothic UI", "zh-CN": "Microsoft YaHei UI", "zh-TW": "Microsoft JhengHei UI",
         # v0.6.23: Thai, whose letters Segoe UI does not have.
         "th": "Leelawadee UI"}
MISSING = "CodexAutoResume No Such Face"


def letters(locale) -> str:
    return typeface.letters(l10n.catalog(locale).values())


def lacking(table):
    return lambda face, text: "".join(char for char in text if char in table.get(face, ""))


class RuleTests(unittest.TestCase):
    def test_each_script_language_has_the_face_windows_sets_it_in(self):
        self.assertEqual(typeface.SCRIPT_FACES, FACES)

    def test_a_script_language_is_set_in_its_own_face_whatever_the_ui_font(self):
        lacks = lacking({"Segoe UI": "日本語한국어中文"})
        for locale, face in FACES.items():
            for system in ("Segoe UI", "Malgun Gothic", "Yu Gothic UI", None):
                with self.subTest(locale=locale, system=system):
                    self.assertEqual(typeface.language_face(locale, system, letters(locale), lacks, lambda name: True), face)

    def test_a_missing_face_falls_back_to_the_choice_before_v0617(self):
        lacks = lacking({"Segoe UI": "日本語"})
        for locale in FACES:
            for system in ("Segoe UI", "Malgun Gothic"):
                with self.subTest(locale=locale, system=system):
                    self.assertEqual(typeface.language_face(locale, system, letters(locale), lacks, lambda name: False),
                                     typeface.face_for(system, letters(locale), lacks))

    def test_every_other_language_is_set_as_before(self):
        lacks = lacking({"Malgun Gothic": "ếệĐ"})
        for locale in l10n.LOCALES:
            if str(locale) in FACES:
                continue
            for system in ("Segoe UI", "Malgun Gothic"):
                with self.subTest(locale=locale, system=system):
                    self.assertEqual(typeface.language_face(str(locale), system, letters(locale), lacks, lambda name: True),
                                     typeface.face_for(system, letters(locale), lacks))

    def test_the_popup_and_the_card_take_the_same_table(self):
        self.assertIs(fonts._SCRIPT_FACES, typeface.SCRIPT_FACES)
        for locale, face in FACES.items():
            with self.subTest(locale=locale):
                self.assertEqual(popup.font_faces(locale, "Segoe UI")[0], face)

    def test_the_panel_names_each_face_first_for_its_language(self):
        for locale, face in FACES.items():
            with self.subTest(locale=locale):
                self.assertIn(':root:lang(%s) { --font: "%s", system-ui, ' % (locale, face), mcpui._STYLE)
        self.assertTrue(mcpui.FONT_STACK.startswith("system-ui, "), "every other language: Windows' UI font first")


@unittest.skipUnless(os.name == "nt", "the faces are Windows' own, asked through GDI")
class InstalledTests(unittest.TestCase):
    def test_gdi_says_which_faces_are_there(self):
        self.assertTrue(typeface.installed("Segoe UI"))
        self.assertFalse(typeface.installed(MISSING))
        self.assertFalse(typeface.installed(""))


PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$flags = [Reflection.BindingFlags]'Instance,Static,NonPublic,Public'
$T = $assembly.GetType('CodexAutoResume.Typeface', $true)
$F = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$PB = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
$BT = $assembly.GetType('CodexAutoResume.Bridge', $true)
$J = $assembly.GetType('CodexAutoResume.Json', $true)
$utf8 = New-Object Text.UTF8Encoding $false
function Parse($name) { return ,$J.GetMethod('Parse', $flags).Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $env:CAR_WORK $name), $utf8))) }
$for3 = $T.GetMethod('ForLanguage', $flags)
$for2 = $T.GetMethod('For', $flags, $null, [type[]]@([Drawing.Font], [Collections.Generic.Dictionary[string,object]]), $null)
if (-not $for3) { throw 'Typeface has no ForLanguage(font, strings, language)' }
function Call($method, $arguments) {
  $given = New-Object 'object[]' $arguments.Count
  for ($i = 0; $i -lt $arguments.Count; $i++) {
    $value = $arguments[$i]
    if ($null -ne $value -and $value -is [psobject]) { $value = $value.PSObject.BaseObject }
    $given[$i] = $value
  }
  return $method.Invoke($null, $given)
}
$ask = Parse 'ask.json'
$out = @{ chosen = @{}; before = @{}; missing = @{}; names = @{}; window = @{} }
foreach ($face in $ask['faces']) { $out.names[$face] = (New-Object Drawing.FontFamily $face).Name }
foreach ($locale in $ask['locales']) {
  $strings = (Parse ('strings-' + $locale + '.json'))['strings']
  foreach ($system in $ask['systems']) {
    $font = New-Object Drawing.Font($system, [float]9, [Drawing.FontStyle]::Regular, [Drawing.GraphicsUnit]::Point)
    $chosen = (Call $for3 @($font, $strings, [string]$locale))
    $out.chosen[$system + '|' + $locale] = @{ face = [string]$chosen.FontFamily.Name; size = [double]$chosen.SizeInPoints }
    $out.before[$system + '|' + $locale] = [string](Call $for2 @($font, $strings)).FontFamily.Name
  }
}
# A face this machine does not have: the choice before v0.6.17.
$table = $T.GetField('ScriptFaces', $flags).GetValue($null)
foreach ($locale in @('ja', 'zh-CN', 'ko')) {
  $kept = $table[$locale]
  $table[$locale] = $env:CAR_MISSING
  $strings = (Parse ('strings-' + $locale + '.json'))['strings']
  foreach ($system in $ask['systems']) {
    $font = New-Object Drawing.Font($system, [float]9, [Drawing.FontStyle]::Regular, [Drawing.GraphicsUnit]::Point)
    $out.missing[$system + '|' + $locale] = @{ chosen = [string](Call $for3 @($font, $strings, [string]$locale)).FontFamily.Name
                                               before = [string](Call $for2 @($font, $strings)).FontFamily.Name }
  }
  $table[$locale] = $kept
}
# The window itself, built and never shown, with Segoe UI as Windows' UI font.
[string]$nowhere = Join-Path $env:CAR_WORK 'nowhere'
$bridge = $BT.GetConstructor($flags, $null, [type[]]@([string]), $null).Invoke([object[]]@($nowhere))
$persistent = $PB.GetConstructor($flags, $null, [type[]]@([string], $BT), $null).Invoke([object[]]@($nowhere, $bridge))
$make = $F.GetConstructor($flags, $null, [type[]]@($PB, [Collections.Generic.Dictionary[string,object]], [Drawing.Font]), $null)
foreach ($locale in $ask['locales']) {
  $font = New-Object Drawing.Font('Segoe UI', [float]9, [Drawing.FontStyle]::Regular, [Drawing.GraphicsUnit]::Point)
  $form = $make.Invoke([object[]]@($persistent.PSObject.BaseObject, (Parse ('strings-' + $locale + '.json')), $font.PSObject.BaseObject))
  $out.window[$locale] = [string]$form.Font.FontFamily.Name
  $form.Dispose()
}
[IO.File]::WriteAllText((Join-Path $env:CAR_WORK 'result.json'), ($out | ConvertTo-Json -Depth 6 -Compress), $utf8)
"""


@unittest.skipUnless(os.name == "nt" and CSC.is_file() and POWERSHELL.is_file(),
                     "needs Windows' faces, the in-box compiler and PowerShell")
class WindowTests(unittest.TestCase):
    """The compiled window's own answers, against win/typeface.py's."""

    LOCALES = ("ko", "ja", "zh-CN", "zh-TW", "th", "en", "vi")
    SYSTEMS = ("Segoe UI", "Malgun Gothic")

    @classmethod
    def setUpClass(cls):
        cls.installed = {face: typeface.installed(face) for face in list(FACES.values()) + list(cls.SYSTEMS)}
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = compile_window(work)
        for locale in cls.LOCALES:
            (work / ("strings-%s.json" % locale)).write_text(json.dumps(reply(locale), ensure_ascii=False), encoding="utf-8")
        systems = [face for face in cls.SYSTEMS if cls.installed[face]]
        faces = [face for face, there in cls.installed.items() if there]
        (work / "ask.json").write_text(json.dumps({"locales": list(cls.LOCALES), "systems": systems, "faces": faces},
                                                  ensure_ascii=False), encoding="utf-8")
        cls.systems = systems
        cls.answer = run_probe(PROBE, work, 600, CAR_EXE=str(exe), CAR_MISSING=MISSING)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def name(self, face) -> str:
        """The name the window reports a face by (Malgun Gothic's Korean one on a Korean Windows)."""
        return self.answer["names"].get(face, face)

    def test_each_language_is_set_in_the_face_win_typeface_chooses(self):
        for system in self.systems:
            for locale in self.LOCALES:
                expected = typeface.language_face(locale, system, letters(locale), typeface.lacks, typeface.installed)
                with self.subTest(system=system, locale=locale):
                    found = self.answer["chosen"][system + "|" + locale]
                    self.assertEqual(found["face"], self.name(expected))
                    self.assertEqual(found["size"], 9.0)

    def test_a_script_language_is_in_its_own_face_under_segoe_ui(self):
        for locale, face in FACES.items():
            if not self.installed[face]:
                continue
            with self.subTest(locale=locale):
                self.assertEqual(self.answer["chosen"]["Segoe UI|" + locale]["face"], self.name(face))
                self.assertNotEqual(self.answer["before"]["Segoe UI|" + locale], self.name(face),
                                    "the choice before v0.6.17 was Windows' UI font")

    def test_a_missing_face_falls_back_to_the_choice_before_v0617(self):
        for key, found in self.answer["missing"].items():
            with self.subTest(case=key):
                self.assertEqual(found["chosen"], found["before"])

    def test_the_window_opens_in_its_languages_face(self):
        for locale in self.LOCALES:
            expected = typeface.language_face(locale, "Segoe UI", letters(locale), typeface.lacks, typeface.installed)
            with self.subTest(locale=locale):
                self.assertEqual(self.answer["window"][locale], self.name(expected))


if __name__ == "__main__":
    unittest.main()
