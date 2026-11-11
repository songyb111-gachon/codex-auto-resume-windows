"""One face for a language on every surface (v0.6.11, win/typeface.py).

An East Asian Windows sets its interface - the message font - in an East Asian face: Malgun Gothic, Yu
Gothic UI, the Chinese UI faces. Each has every letter of the languages v0.6.10 spoke, but not of every
language v0.6.11 adds: Malgun Gothic has no `ế`, `ї`, `ą` or `ş`, Microsoft JhengHei UI no Cyrillic. GDI
draws a letter its face lacks from a face linked to it, a browser from the next face of its stack - in
that face's shape and weight, so one word ends up in two faces ("Tiếng Việt", its `ế` and `ệ` heavier
than the letters beside them). Nothing is a box, so the glyph coverage tests pass through it.

So a language whose letters Windows' UI font does not all have, and Segoe UI does, is set in Segoe UI -
on the Dashboard, the popup, the card and the panel alike - and every other language exactly as before.
Here: the rule, pure; GDI's answer against an independent reading of it; the popup's faces under every
message font Windows sets; the panel's rule; and the window's, compiled and asked through reflection,
letter for letter the same as Python's.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import unittest.mock

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import l10n  # noqa: E402
from codex_auto_resume.mcp import panel as mcpui  # noqa: E402
from codex_auto_resume.ui import popup  # noqa: E402
from codex_auto_resume.win import typeface  # noqa: E402
import test_glyph_coverage as coverage  # noqa: E402
from test_gui_v0611_access import CSC, POWERSHELL, compile_window, reply, run_probe  # noqa: E402

EAST_ASIAN = ("Malgun Gothic", "Yu Gothic UI", "Microsoft YaHei UI", "Microsoft JhengHei UI")
# The languages v0.6.10 spoke outside a script face: each keeps Windows' UI font, whichever it is.
V0610 = ("en", "es", "de", "fr", "pt-BR")


def lacking(table):
    """A stand-in for GDI: the characters of a text each face in `table` has no glyph for."""
    return lambda face, text: "".join(char for char in text if char in table.get(face, ""))


class RuleTests(unittest.TestCase):
    def test_the_letters_are_what_is_drawn_once_each_in_order(self):
        self.assertEqual(typeface.letters(["b a\n", "a​c‎", None, 7]), "abc")
        self.assertEqual(typeface.letters([]), "")

    def test_a_face_with_every_letter_keeps_the_language_and_one_without_hands_it_to_segoe_ui(self):
        lacks = lacking({"Malgun Gothic": "ế", "Yu Gothic UI": "ếД", "Segoe UI": "한"})
        self.assertEqual(typeface.face_for("Malgun Gothic", "Tiếng", lacks), "Segoe UI")
        self.assertEqual(typeface.face_for("Malgun Gothic", "Deutsch", lacks), "Malgun Gothic")
        # A script Segoe UI lacks too keeps its own face: nothing would be gained.
        self.assertEqual(typeface.face_for("Malgun Gothic", "한ế", lacks), "Malgun Gothic")
        for face in ("Segoe UI", "segoe ui", None, "", "  "):
            self.assertEqual(typeface.face_for(face, "Tiếng", lacks), face)
        self.assertEqual(typeface.face_for("Malgun Gothic", "", lacks), "Malgun Gothic")

    def test_the_popup_follows_the_rule_and_without_an_answer_keeps_v0610s_faces(self):
        lacks = lacking({"Malgun Gothic": "ếệ"})
        self.assertEqual(popup.font_faces("vi", "Malgun Gothic", lacks), ("Segoe UI",))
        self.assertEqual(popup.font_candidates("vi", 600, "Malgun Gothic", lacks),
                         (("Segoe UI Semibold", 400), ("Segoe UI", 600)))
        self.assertEqual(popup.font_faces("en", "Malgun Gothic", lacks), ("Malgun Gothic", "Segoe UI Variable Text", "Segoe UI"))
        self.assertEqual(popup.font_faces("vi", "Malgun Gothic"),
                         ("Malgun Gothic", "Segoe UI Variable Text", "Segoe UI"), "no one asked: as before")
        self.assertEqual(popup.font_faces("ko", "Segoe UI", lacks), ("Malgun Gothic", "Segoe UI"))
        self.assertEqual(popup.font_faces("vi", None, lacks), ("Segoe UI Variable Text", "Segoe UI"))

    def test_the_panel_sets_what_the_ui_font_lacks_in_segoe_ui_by_the_pages_language(self):
        with unittest.mock.patch.object(typeface, "lacks", lacking({"Malgun Gothic": "ếệĐ"})):
            style = mcpui.typeface_style("Malgun Gothic")
            self.assertEqual(mcpui.typeface_style("Segoe UI"), "")
        self.assertEqual(style, '<style>:root:lang(vi) { --font: "Segoe UI", %s; }</style>' % mcpui.FONT_STACK)
        self.assertTrue(mcpui.FONT_STACK.startswith("system-ui, "), "Windows' UI font first, as before")
        self.assertEqual(mcpui.typeface_style(None), "")
        with unittest.mock.patch.object(typeface, "lacks", lacking({"Malgun Gothic": "ếệĐ"})):
            page = mcpui.settings_page(text=1.0, face="Malgun Gothic")
            self.assertIn("</style>" + style + "</head>", page)
            self.assertEqual(mcpui.settings_page(text=1.0, face="Segoe UI").count("<style>"), 1,
                             "a Windows set in Segoe UI is served the page as it always was")


@unittest.skipUnless(os.name == "nt", "the faces are Windows' own, asked through GDI")
class WindowsFacesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gdi = coverage._Gdi()
        cls.faces = [face for face in coverage.MESSAGE_FACES if cls.gdi.installed(face)]

    @classmethod
    def tearDownClass(cls):
        cls.gdi.close()

    def test_gdi_is_asked_what_a_face_lacks_as_the_coverage_tests_ask_it(self):
        self.assertEqual(typeface.lacks("Segoe UI", "A͸"), "͸", "a probe that finds a missing glyph")
        for face in self.faces:
            for locale in l10n.LOCALES:
                text = typeface.letters(l10n.catalog(locale).values())
                with self.subTest(face=face, locale=locale):
                    self.assertEqual(typeface.lacks(face, text), self.gdi.lacks(face, text))

    def test_the_ui_font_is_the_one_the_popup_and_the_window_start_from(self):
        self.assertEqual(typeface.ui_face(), popup.message_face())

    def test_every_language_is_set_whole_in_the_face_the_popup_and_the_card_choose(self):
        """Under this Windows' UI font and every other one Windows sets, every letter of each language not set
        in a script face is in the face its words are drawn in - none is borrowed through a font link."""
        for system in [popup.message_face()] + self.faces:
            for locale in l10n.LOCALES:
                if locale in coverage.SCRIPT_FACED:
                    continue
                for weight in (400, 600):
                    candidates = popup.font_candidates(locale, weight, system, typeface.lacks)
                    face, actual = next(((name, value) for name, value in candidates if self.gdi.installed(name)),
                                        candidates[-1])
                    with self.subTest(system=system, locale=locale, face=face, weight=actual):
                        self.assertEqual(self.gdi.lacks(face, coverage.characters(locale), actual), "")

    def test_a_language_the_ui_font_has_whole_keeps_it_as_v0610_did(self):
        for system in [face for face in EAST_ASIAN if face in self.faces]:
            for locale in V0610 + ("it", "id"):
                with self.subTest(system=system, locale=locale):
                    self.assertEqual(popup.font_faces(locale, system, typeface.lacks)[0], system)
        self.assertEqual(popup.font_faces("vi", "Segoe UI", typeface.lacks), ("Segoe UI",))

    def test_the_panel_names_the_languages_the_popup_sets_in_segoe_ui(self):
        for system in [popup.message_face()] + self.faces:
            moved = [locale for locale in l10n.OFFERED
                     if popup.font_faces(locale, system, typeface.lacks) == ("Segoe UI",)
                     and locale not in coverage.SCRIPT_FACED and system and system.lower() != "segoe ui"]
            style = mcpui.typeface_style(system)
            with self.subTest(system=system):
                self.assertEqual(style.split(" {")[0].replace("<style>", "").split(", ") if style else [],
                                 [":root:lang(%s)" % locale for locale in moved])
        if "Malgun Gothic" in self.faces:
            self.assertIn(":root:lang(vi)", mcpui.typeface_style("Malgun Gothic"))


PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$flags = [Reflection.BindingFlags]'Instance,Static,NonPublic,Public'
$T = $assembly.GetType('CodexAutoResume.Typeface', $true)
$F = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$S = $assembly.GetType('CodexAutoResume.Soft', $true)
$PB = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
$BT = $assembly.GetType('CodexAutoResume.Bridge', $true)
$J = $assembly.GetType('CodexAutoResume.Json', $true)
$utf8 = New-Object Text.UTF8Encoding $false
function Parse($name) { return ,$J.GetMethod('Parse', $flags).Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $env:CAR_WORK $name), $utf8))) }
function Static($type, $name, $arguments) {
  $given = New-Object 'object[]' $arguments.Count
  for ($i = 0; $i -lt $arguments.Count; $i++) {
    $value = $arguments[$i]
    if ($null -ne $value -and $value -is [psobject]) { $value = $value.PSObject.BaseObject }
    $given[$i] = $value
  }
  return $type.GetMethod($name, $flags).Invoke($null, $given)
}
$ask = Parse 'ask.json'
$out = @{ letters = @{}; lacks = @{}; chosen = @{}; window = @{} }
foreach ($locale in $ask['locales']) {
  $strings = (Parse ('strings-' + $locale + '.json'))['strings']
  $letters = [string](Static $T 'Letters' @($strings))
  $out.letters[$locale] = $letters
  foreach ($face in $ask['faces']) {
    $out.lacks[$face + '|' + $locale] = [string](Static $T 'Lacks' @($face, $letters))
    $font = New-Object Drawing.Font($face, [float]9, [Drawing.FontStyle]::Regular, [Drawing.GraphicsUnit]::Point)
    $out.chosen[$face + '|' + $locale] = [string](Static $T 'For' @($font, $strings)).FontFamily.Name
  }
}
# The window itself, built and never shown in each language with each face as Windows' UI font.
[string]$nowhere = Join-Path $env:CAR_WORK 'nowhere'
$bridge = $BT.GetConstructor($flags, $null, [type[]]@([string]), $null).Invoke([object[]]@($nowhere))
$persistent = $PB.GetConstructor($flags, $null, [type[]]@([string], $BT), $null).Invoke([object[]]@($nowhere, $bridge))
$make = $F.GetConstructor($flags, $null, [type[]]@($PB, [Collections.Generic.Dictionary[string,object]], [Drawing.Font]), $null)
foreach ($pair in $ask['windows']) {
  $face = $pair[0]; $locale = $pair[1]
  $font = New-Object Drawing.Font($face, [float]9, [Drawing.FontStyle]::Regular, [Drawing.GraphicsUnit]::Point)
  $form = $make.Invoke([object[]]@($persistent.PSObject.BaseObject, (Parse ('strings-' + $locale + '.json')), $font.PSObject.BaseObject))
  $out.window[$face + '|' + $locale] = @{ form = [string]$form.Font.FontFamily.Name; size = [double]$form.Font.SizeInPoints
    base = [string]$S.GetProperty('BaseFont', $flags).GetValue($null).FontFamily.Name
    heading = [string](Static $S 'RoleFont' @('heading')).FontFamily.Name }
  $form.Dispose()
}
[IO.File]::WriteAllText((Join-Path $env:CAR_WORK 'result.json'), ($out | ConvertTo-Json -Depth 6 -Compress), $utf8)
"""


@unittest.skipUnless(os.name == "nt" and CSC.is_file() and POWERSHELL.is_file(),
                     "needs Windows' faces, the in-box compiler and PowerShell")
class WindowTests(unittest.TestCase):
    """The compiled window's own answers, against win/typeface.py's."""

    LOCALES = ("en", "de", "ru", "tr", "pl", "uk", "vi", "id", "ko", "ja", "zh-TW")

    @classmethod
    def setUpClass(cls):
        gdi = coverage._Gdi()
        try:
            cls.faces = [face for face in coverage.MESSAGE_FACES if gdi.installed(face)]
        finally:
            gdi.close()
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = compile_window(work)
        for locale in cls.LOCALES:
            (work / ("strings-%s.json" % locale)).write_text(json.dumps(reply(locale), ensure_ascii=False), encoding="utf-8")
        windows = [[face, locale] for face in cls.faces for locale in ("en", "vi", "uk")]
        (work / "ask.json").write_text(json.dumps({"locales": list(cls.LOCALES), "faces": cls.faces, "windows": windows},
                                                  ensure_ascii=False), encoding="utf-8")
        cls.answer = run_probe(PROBE, work, 600, CAR_EXE=str(exe))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_the_window_reads_the_same_letters_as_python(self):
        for locale in self.LOCALES:
            with self.subTest(locale=locale):
                self.assertEqual(self.answer["letters"][locale], typeface.letters(l10n.catalog(locale).values()))

    def test_the_window_asks_gdi_what_a_face_lacks_and_hears_what_python_hears(self):
        for face in self.faces:
            for locale in self.LOCALES:
                with self.subTest(face=face, locale=locale):
                    self.assertEqual(self.answer["lacks"][face + "|" + locale],
                                     typeface.lacks(face, typeface.letters(l10n.catalog(locale).values())))

    def segoe(self, face, locale) -> bool:
        """Whether win/typeface.py sets `locale` in Segoe UI where Windows' UI font is `face`. (The window
        reports a face it keeps by the name Windows gives it, Malgun Gothic's Korean one on a Korean Windows.)"""
        return typeface.face_for(face, typeface.letters(l10n.catalog(locale).values()), typeface.lacks) != face

    def test_the_window_sets_each_language_in_the_face_the_popup_and_the_panel_do(self):
        for face in self.faces:
            for locale in self.LOCALES:
                with self.subTest(face=face, locale=locale):
                    self.assertEqual(self.answer["chosen"][face + "|" + locale] == "Segoe UI",
                                     self.segoe(face, locale) or face == "Segoe UI")

    def test_the_window_opens_in_that_face_at_its_size_and_every_role_follows_it(self):
        for key, found in self.answer["window"].items():
            face, locale = key.split("|")
            with self.subTest(face=face, locale=locale):
                self.assertEqual(found["form"] == "Segoe UI", self.segoe(face, locale) or face == "Segoe UI")
                self.assertEqual(found["base"], found["form"], "every role is a variant of the window's font")
                self.assertTrue(found["heading"].startswith(found["form"]), found["heading"])
                self.assertEqual(found["size"], 9.0)
        if "Malgun Gothic" in self.faces:
            self.assertEqual(self.answer["window"]["Malgun Gothic|vi"]["form"], "Segoe UI")
            self.assertNotEqual(self.answer["window"]["Malgun Gothic|en"]["form"], "Segoe UI")


if __name__ == "__main__":
    unittest.main()
