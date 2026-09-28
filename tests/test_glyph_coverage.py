"""Every character of every catalog has a glyph in the fonts each surface draws it with (v0.6.11).

Nine languages joined in v0.6.11, four of them in scripts the product had never drawn: Cyrillic
(Russian, Ukrainian), Vietnamese - Latin with two marks stacked on one letter, as in `ệ` and `ỗ` -
and, held until every surface mirrors, Arabic and Hebrew. A catalog that is complete and correct is
still a row of boxes on a surface whose font has no glyph for its letters, and no other test would
see it: the layout audits measure the boxes as happily as the letters.

What each surface draws with:

* **The window, the popup and the card** draw with GDI in Windows' message font - Segoe UI on an
  English Windows, and on every Windows set to one of these languages - or, in the popup and the
  card, a script's own face (Malgun Gothic, Yu Gothic UI, the Chinese UI faces). A letter the face
  lacks is drawn from the faces Windows links to it (FontLink\\SystemLink) - every East Asian UI face
  links Segoe UI first - so "Segoe UI and its fallbacks" is the whole of what the three can show.
  (A borrowed letter still sets one word in two faces, so a language the message font lacks a letter
  of is set in Segoe UI instead, on every surface: tests/test_typeface.py.)
* **The panel** asks its browser for a stack of faces (panel.css `--font`), `system-ui` - that same
  message font - first, and a browser draws each character from the first face in the stack that
  has it.

So every character of every catalog, the advanced edition's included, is looked for through each
surface's own faces - on this Windows, and as it would be on a Windows whose message font is each of
the East Asian faces - and the four scripts are drawn, to see ink and not the box a missing glyph
draws.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import re
import sys
import unicodedata
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_auto_resume import l10n  # noqa: E402
from codex_auto_resume.mcp import panel as mcpui  # noqa: E402
from codex_auto_resume.ui import popup  # noqa: E402

ADVANCED = ROOT / "advanced" / "src" / "codex_auto_resume_advanced" / "locales"
# The message fonts a Windows sets: Segoe UI, and the East Asian UI faces an East Asian Windows sets instead.
MESSAGE_FACES = ("Segoe UI", "Malgun Gothic", "Yu Gothic UI", "Microsoft YaHei UI", "Microsoft JhengHei UI")
# A script's own face in the popup and the card (ui/popup/fonts.py); every other language is set in the
# message font, as the window and the panel set it.
SCRIPT_FACED = frozenset({"ko", "ja", "zh-CN", "zh-TW"})
# The four scripts v0.6.11 brought, each by a catalog written in it.
SCRIPTS = {"Cyrillic": ("ru", "uk"), "Vietnamese": ("vi",), "Arabic": ("ar",), "Hebrew": ("he",)}
LINK_KEY = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\FontLink\SystemLink"
GGI_MARK_NONEXISTING_GLYPHS = 0x1
MISSING = 0xFFFF


def characters(locale) -> str:
    """Every character a surface may draw from `locale`: its catalog, English under it, and the advanced
    edition's words in it - less white space and the invisible format characters, which draw nothing."""
    values = list(l10n.catalog(locale).values())
    extra = ADVANCED / ("%s.json" % locale)
    if extra.is_file():
        values += [value for value in json.loads(extra.read_text(encoding="utf-8")).values() if isinstance(value, str)]
    values.append(l10n.ENDONYMS[locale])
    found = {char for value in values for char in value
             if not char.isspace() and unicodedata.category(char) not in ("Cc", "Cf")}
    return "".join(sorted(found))


class _Gdi:
    """GDI asked what a face has: its own DLL handles, so nothing here changes what the product declared."""

    def __init__(self):
        self.gdi32, self.user32 = C.WinDLL("gdi32"), C.WinDLL("user32")
        self.gdi32.CreateCompatibleDC.restype = W.HDC
        self.gdi32.CreateCompatibleDC.argtypes = [W.HDC]
        self.gdi32.CreateFontW.restype = W.HFONT
        self.gdi32.CreateFontW.argtypes = [C.c_int] * 5 + [W.DWORD] * 8 + [W.LPCWSTR]
        self.gdi32.SelectObject.restype = W.HGDIOBJ
        self.gdi32.SelectObject.argtypes = [W.HDC, W.HGDIOBJ]
        self.gdi32.DeleteObject.argtypes = [W.HGDIOBJ]
        self.gdi32.DeleteDC.argtypes = [W.HDC]
        self.gdi32.GetTextFaceW.argtypes = [W.HDC, C.c_int, W.LPWSTR]
        self.gdi32.GetGlyphIndicesW.argtypes = [W.HDC, W.LPCWSTR, C.c_int, C.POINTER(W.WORD), W.DWORD]
        self.gdi32.GetGlyphIndicesW.restype = W.DWORD
        self.dc = self.gdi32.CreateCompatibleDC(None)
        self._faces = {}

    def close(self):
        self.gdi32.DeleteDC(self.dc)

    def _font(self, face, weight=400, height=-40):
        return self.gdi32.CreateFontW(height, 0, 0, 0, weight, 0, 0, 0, 1, 0, 0, 5, 0, face)

    def realized(self, face) -> str:
        """The face GDI gives for `face`, by the name Windows reports it by - Malgun Gothic's is Korean on a
        Korean Windows."""
        font = self._font(face)
        previous = self.gdi32.SelectObject(self.dc, font)
        try:
            buffer = C.create_unicode_buffer(64)
            self.gdi32.GetTextFaceW(self.dc, 64, buffer)
            return buffer.value
        finally:
            self.gdi32.SelectObject(self.dc, previous)
            self.gdi32.DeleteObject(font)

    def installed(self, face) -> bool:
        """Whether Windows has this face itself rather than a substitute for it, as the popup asks
        (fonts._face_exists): its own name back, or anything but what a face that does not exist becomes."""
        if face not in self._faces:
            realized = self.realized(face)
            self._faces[face] = bool(realized) and (realized.lower() == face.lower()
                                                    or realized != self.realized(popup.fonts._NO_SUCH_FACE))
        return self._faces[face]

    def english(self, face) -> str:
        """A face by the name Windows' font links are written under: a localized name (the message font's,
        on a Korean Windows) back to the English one it is reported for."""
        for known in MESSAGE_FACES:
            if face and face != known and self.realized(known) == face:
                return known
        return face

    def lacks(self, face, text, weight=400) -> str:
        """The characters of `text` this face has no glyph for."""
        font = self._font(face, weight)
        previous = self.gdi32.SelectObject(self.dc, font)
        try:
            glyphs = (W.WORD * len(text))()
            self.gdi32.GetGlyphIndicesW(self.dc, text, len(text), glyphs, GGI_MARK_NONEXISTING_GLYPHS)
            return "".join(char for char, glyph in zip(text, glyphs) if glyph == MISSING)
        finally:
            self.gdi32.SelectObject(self.dc, previous)
            self.gdi32.DeleteObject(font)

    def ink(self, face, text):
        """What DrawText draws of `text` in `face` - links and all - as rows of 0 and 1, cropped to its ink.
        White on black, into a 32-bit DIB: any pixel not black is ink."""
        gdi32, user32 = self.gdi32, self.user32
        width, height = 60 * len(text) + 40, 80

        class Header(C.Structure):
            _fields_ = [("biSize", W.DWORD), ("biWidth", W.LONG), ("biHeight", W.LONG), ("biPlanes", W.WORD),
                        ("biBitCount", W.WORD), ("biCompression", W.DWORD), ("biSizeImage", W.DWORD),
                        ("biXPelsPerMeter", W.LONG), ("biYPelsPerMeter", W.LONG), ("biClrUsed", W.DWORD),
                        ("biClrImportant", W.DWORD)]

        header = Header(C.sizeof(Header), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        bits = C.c_void_p()
        gdi32.CreateDIBSection.restype = W.HBITMAP
        gdi32.CreateDIBSection.argtypes = [W.HDC, C.c_void_p, W.UINT, C.POINTER(C.c_void_p), W.HANDLE, W.DWORD]
        gdi32.SetBkMode.argtypes = [W.HDC, C.c_int]
        gdi32.SetTextColor.argtypes = [W.HDC, W.COLORREF]
        user32.DrawTextW.argtypes = [W.HDC, W.LPCWSTR, C.c_int, C.POINTER(W.RECT), W.UINT]
        dc = gdi32.CreateCompatibleDC(None)
        bitmap = gdi32.CreateDIBSection(dc, C.byref(header), 0, C.byref(bits), None, 0)
        font = self._font(face)
        try:
            gdi32.SelectObject(dc, bitmap)
            gdi32.SelectObject(dc, font)
            gdi32.SetBkMode(dc, 1)
            gdi32.SetTextColor(dc, 0xFFFFFF)
            rect = W.RECT(0, 0, width, height)
            user32.DrawTextW(dc, text, -1, C.byref(rect), 0x800 | 0x20)       # DT_NOPREFIX | DT_SINGLELINE
            gdi32.GdiFlush()
            raw = C.string_at(bits, width * height * 4)
        finally:
            gdi32.DeleteObject(font)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(dc)
        rows = [tuple(1 if raw[(y * width + x) * 4:(y * width + x) * 4 + 3] != bytes(3) else 0
                      for x in range(width)) for y in range(height)]
        inked = [y for y, row in enumerate(rows) if any(row)]
        if not inked:
            return ()
        columns = [x for x in range(width) if any(row[x] for row in rows)]
        return tuple(row[columns[0]:columns[-1] + 1] for row in rows[inked[0]:inked[-1] + 1])


def linked(face) -> tuple:
    """The faces Windows draws a character from when `face` has none (FontLink\\SystemLink), in order."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, LINK_KEY) as key:
            entries, _ = winreg.QueryValueEx(key, face)
    except OSError:
        return ()
    faces = []
    for entry in entries:
        parts = entry.split(",")
        if len(parts) >= 2 and parts[1].strip() and parts[1].strip() not in faces:
            faces.append(parts[1].strip())
    return tuple(faces)


def panel_stack() -> tuple:
    """The panel's type stack as its stylesheet asks for it, generic families left out."""
    found = re.search(r"--font:\s*([^;]+);", mcpui._STYLE)
    faces = [part.strip().strip('"') for part in found.group(1).split(",")]
    return tuple(face for face in faces if face not in ("sans-serif", "serif", "monospace"))


@unittest.skipUnless(os.name == "nt", "the faces are Windows' own, asked through GDI")
class GlyphCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gdi = _Gdi()

    @classmethod
    def tearDownClass(cls):
        cls.gdi.close()

    def reached(self, faces, text, weight=400) -> str:
        """The characters of `text` none of `faces` has, each face asked only for what those before it lacked."""
        left = text
        for face in faces:
            if not left:
                break
            if self.gdi.installed(face):
                left = self.gdi.lacks(face, left, weight)
        return left

    def gdi_faces(self, face) -> tuple:
        """A face GDI draws in, then the faces it links to."""
        return (face,) + linked(self.gdi.english(face))

    def test_the_probe_finds_a_missing_glyph(self):
        """So a quiet report is GDI having looked: no face has a glyph for an unassigned code point."""
        self.assertTrue(self.gdi.installed("Segoe UI"))
        self.assertEqual(self.gdi.lacks("Segoe UI", "A͸Б"), "͸")
        self.assertEqual(self.reached(self.gdi_faces("Segoe UI"), "͸"), "͸")

    def test_segoe_ui_alone_has_every_letter_of_every_language_not_set_in_a_script_face(self):
        """The Cyrillic, Vietnamese, Arabic and Hebrew catalogs included: on an English Windows - and on
        one in any of these languages, whose message font is Segoe UI - nothing is borrowed from a link."""
        for locale in l10n.LOCALES:
            if locale in SCRIPT_FACED:
                continue
            for face in ("Segoe UI", "Segoe UI Semibold"):
                for weight in (400, 700):
                    with self.subTest(locale=locale, face=face, weight=weight):
                        self.assertEqual(self.gdi.lacks(face, characters(locale), weight), "")

    def test_the_window_has_a_glyph_for_every_character_in_every_message_font(self):
        """The window draws every language in Windows' message font (SystemFonts.MessageBoxFont) and its
        Semibold or Bold, whichever Windows sets: each character is in the face or a face it links to."""
        for system in MESSAGE_FACES:
            if not self.gdi.installed(system):
                continue
            weighted = [(system, 400), (system + " Semibold", 400) if system == "Segoe UI" else (system, 700)]
            for locale in l10n.LOCALES:
                for face, weight in weighted:
                    with self.subTest(system=system, locale=locale, face=face, weight=weight):
                        self.assertEqual(self.reached(self.gdi_faces(face), characters(locale), weight), "")

    def test_the_popup_and_the_card_have_a_glyph_for_every_character_in_every_message_font(self):
        """The popup and the card: the face each of their type roles is made in (popup.font_candidates, the
        first Windows has), for this Windows' message font and for each other one, and what it links to."""
        for system in (popup.message_face(),) + MESSAGE_FACES:
            for locale in l10n.LOCALES:
                for weight in (400, 600):
                    candidates = popup.font_candidates(locale, weight, system)
                    face, actual = next(((name, value) for name, value in candidates if self.gdi.installed(name)),
                                        candidates[-1])
                    with self.subTest(system=system, locale=locale, face=face, weight=actual):
                        self.assertEqual(self.reached(self.gdi_faces(face), characters(locale), actual), "")

    def test_the_panel_has_a_glyph_for_every_character_in_its_type_stack(self):
        """A browser draws each character from the first face of the stack that has it; `system-ui` is the
        message font - this Windows' and each other one's."""
        stack = panel_stack()
        self.assertEqual(stack[0], "system-ui")
        self.assertIn("Segoe UI", stack)
        for system in (popup.message_face(),) + MESSAGE_FACES:
            faces = tuple(system if face == "system-ui" else face for face in stack if system or face != "system-ui")
            for locale in l10n.LOCALES:
                with self.subTest(system=system, locale=locale):
                    self.assertEqual(self.reached(faces, characters(locale)), "")

    def test_vietnamese_stacks_its_marks_in_single_letters(self):
        """Vietnamese puts two marks on one letter. Each such letter in its catalog is one precomposed
        character (NFC), which Segoe UI draws as its own glyph, rather than a letter and two combining marks
        left to be positioned."""
        text = "".join(l10n.catalog("vi").values())
        self.assertEqual(unicodedata.normalize("NFC", text), text)
        stacked = {char for char in text if len(unicodedata.normalize("NFD", char)) >= 3}
        self.assertGreaterEqual(len(stacked), 10, "the check has stacked letters to look at")
        self.assertFalse(any(unicodedata.category(char) == "Mn" for char in text), "no loose combining mark")
        self.assertEqual(self.gdi.lacks("Segoe UI", "".join(sorted(stacked))), "")

    def test_each_new_script_is_drawn_as_ink_and_not_as_the_missing_glyph_box(self):
        """Drawn, not only looked up: each script's letters, in every message font Windows has, links and all,
        against what that face draws for a character no face has."""
        for system in MESSAGE_FACES:
            if not self.gdi.installed(system):
                continue
            box = self.gdi.ink(system, "͸")
            for script, locales in SCRIPTS.items():
                letters = [char for locale in locales for char in characters(locale)
                           if unicodedata.name(char, "").split(" ")[0] in ("CYRILLIC", "LATIN", "ARABIC", "HEBREW")
                           and ord(char) > 0x7F]
                for char in sorted(set(letters))[:40]:
                    with self.subTest(system=system, script=script, char="U+%04X" % ord(char)):
                        drawn = self.gdi.ink(system, char)
                        self.assertTrue(drawn, "nothing drawn")
                        self.assertNotEqual(drawn, box, "the missing glyph's box")

    def test_every_script_the_catalogs_need_is_one_of_these_four_or_already_shipped(self):
        """So a later catalog in a fifth script cannot pass here unlooked-at: each language's letters beyond
        ASCII come from the scripts its catalog is known to use."""
        known = {"LATIN", "CYRILLIC", "ARABIC", "HEBREW", "HANGUL", "CJK", "HIRAGANA", "KATAKANA", "FULLWIDTH",
                 "IDEOGRAPHIC", "HALFWIDTH", "KATAKANA-HIRAGANA", "BOPOMOFO"}
        for locale in l10n.LOCALES:
            for char in characters(locale):
                if ord(char) < 0x80 or unicodedata.category(char)[0] != "L":
                    continue
                with self.subTest(locale=locale, char="U+%04X" % ord(char)):
                    self.assertIn(unicodedata.name(char, "?").split(" ")[0], known)


if __name__ == "__main__":
    unittest.main()
