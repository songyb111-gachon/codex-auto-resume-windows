"""Windows' interface font, and whether a face can set a language whole (v0.6.11).

Windows' UI font - the message font the Dashboard is drawn in (SystemFonts.MessageBoxFont), the
panel's `system-ui` resolves to and the popup and the card ask for (`ui_face`) - is Segoe UI on an
English Windows and on one set to any language Segoe UI covers, and an East Asian face on an East
Asian one: Malgun Gothic, Yu Gothic UI, the Chinese UI faces. Those have every letter of English and
of the other languages v0.6.10 spoke, but not of every language v0.6.11 adds: Malgun Gothic has no
`ế`, `ї`, `ą` or `ş`, Microsoft JhengHei UI no Cyrillic at all. A letter a face lacks is still drawn -
GDI takes it from a face linked to it, a browser from the next face of its stack - but in that face's
shape and weight, so one word is set in two faces.

So a language whose letters Windows' UI font does not all have, and Segoe UI does, is set in Segoe
UI (`face_for`) - as it is on every Windows set to that language - on the Dashboard (gui/SoftTheme.cs,
Typeface, the same rule), the popup, the card and the panel alike. Every language the UI font has
whole is set in it, exactly as before; on an English Windows that is every language.

And since v0.6.17 (#48) a language with a script face of its own - Korean, Japanese, Chinese - is set
in the face Windows itself sets it in on a Windows set to that language (`SCRIPT_FACES`, `language_face`):
Malgun Gothic, Yu Gothic UI, Microsoft YaHei UI, Microsoft JhengHei UI - whatever Windows' UI font is,
where that face is installed, and as before where it is not. Until then Japanese on an English Windows
was set in Segoe UI with every kana and kanji borrowed through a font link, as the window measured and
drew it, and a click on the Advanced page in Japanese waited seconds for those measurements.

GDI is asked which glyphs a face has (GetGlyphIndicesW) once per face and text, and the answer is
remembered. Read, never written; nothing here draws, and nothing here raises: what cannot be asked
is taken as whole, which keeps the face v0.6.10 used.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import os
import threading
import unicodedata

from .dll import library

# The face every Windows has, with every letter of every language not set in a script face of its own.
SEGOE = "Segoe UI"
# The face Windows sets each language with a script face of its own in, on a Windows set to that language (v0.6.17,
# #48): the window (gui/SoftTheme.cs, Typeface.ScriptFaces), the popup and the card (ui/popup/fonts.py) and the panel
# (mcp/assets/panel.css, a rule on the page's language) all set these languages in them.
SCRIPT_FACES = {"ko": "Malgun Gothic", "ja": "Yu Gothic UI", "zh-CN": "Microsoft YaHei UI", "zh-TW": "Microsoft JhengHei UI"}
SPI_GETNONCLIENTMETRICS = 0x0029
GGI_MARK_NONEXISTING_GLYPHS = 0x1
_NO_GLYPH = 0xFFFF

_dll = library()
_LOCK = threading.Lock()
_LACKING = {}                                   # (face, text) -> the characters of text the face has no glyph for
_declared = False


class LOGFONTW(C.Structure):
    _fields_ = [("lfHeight", W.LONG), ("lfWidth", W.LONG), ("lfEscapement", W.LONG),
                ("lfOrientation", W.LONG), ("lfWeight", W.LONG), ("lfItalic", W.BYTE),
                ("lfUnderline", W.BYTE), ("lfStrikeOut", W.BYTE), ("lfCharSet", W.BYTE),
                ("lfOutPrecision", W.BYTE), ("lfClipPrecision", W.BYTE), ("lfQuality", W.BYTE),
                ("lfPitchAndFamily", W.BYTE), ("lfFaceName", W.WCHAR * 32)]


class NONCLIENTMETRICSW(C.Structure):
    _fields_ = [("cbSize", W.UINT), ("iBorderWidth", C.c_int), ("iScrollWidth", C.c_int),
                ("iScrollHeight", C.c_int), ("iCaptionWidth", C.c_int), ("iCaptionHeight", C.c_int),
                ("lfCaptionFont", LOGFONTW), ("iSmCaptionWidth", C.c_int), ("iSmCaptionHeight", C.c_int),
                ("lfSmCaptionFont", LOGFONTW), ("iMenuWidth", C.c_int), ("iMenuHeight", C.c_int),
                ("lfMenuFont", LOGFONTW), ("lfStatusFont", LOGFONTW), ("lfMessageFont", LOGFONTW),
                ("iPaddedBorderWidth", C.c_int)]


def letters(texts) -> str:
    """Every character of `texts` that is drawn - less white space and the control and format characters,
    which draw nothing - once each, in order. Pure."""
    found = {char for text in texts if isinstance(text, str) for char in text
             if not char.isspace() and ord(char) <= 0xFFFF and unicodedata.category(char) not in ("Cc", "Cf")}
    return "".join(sorted(found))


def face_for(face, text, lacks) -> str:
    """The face `text` is set in when Windows' UI font is `face`: `face` when it has every character of
    `text`, or when Segoe UI lacks one too (a script with a face of its own); Segoe UI otherwise. `lacks`
    answers which characters a face has no glyph for. Pure, given `lacks`."""
    if not isinstance(face, str) or not face.strip() or face.strip().lower() == SEGOE.lower() or not text:
        return face
    return SEGOE if lacks(face, text) and not lacks(SEGOE, text) else face


def language_face(locale, face, text, lacks, installed) -> str:
    """The face the words of `locale`, whose letters are `text`, are set in when Windows' UI font is `face`: the
    language's own script face (SCRIPT_FACES) where `installed` says Windows has it, and otherwise what `face_for`
    chooses, as before v0.6.17. `lacks` and `installed` answer for GDI. Pure, given them."""
    own = SCRIPT_FACES.get(str(locale)) if locale is not None else None
    if own and installed(own):
        return own
    return face_for(face, text, lacks)


_INSTALLED = {}                                 # face -> whether GDI has it itself
_NO_SUCH_FACE = "CodexAutoResume No Such Face"


def _realized(gdi32, dc, face) -> str:
    font = gdi32.CreateFontW(-12, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, face)
    if not font:
        return ""
    previous = gdi32.SelectObject(dc, font)
    try:
        buffer = C.create_unicode_buffer(64)
        gdi32.GetTextFaceW(dc, 64, buffer)
        return buffer.value
    finally:
        gdi32.SelectObject(dc, previous)
        gdi32.DeleteObject(font)


def installed(face) -> bool:
    """Whether GDI has the face `face` itself rather than a stand-in for it: the face it realizes for the name is the
    name, or - a face Windows reports by its localized name, Malgun Gothic's Korean one on a Korean Windows - anything
    but what a face that does not exist is realized as. False when Windows cannot be asked. Asked once per face."""
    if os.name != "nt" or not isinstance(face, str) or not face.strip():
        return False
    with _LOCK:
        if face in _INSTALLED:
            return _INSTALLED[face]
        found = False
        try:
            gdi32 = _dll("gdi32")
            _declare(gdi32, _dll("user32"))
            dc = gdi32.CreateCompatibleDC(None)
            if dc:
                try:
                    stand_in = _realized(gdi32, dc, _NO_SUCH_FACE)
                    realized = _realized(gdi32, dc, face)
                    found = bool(realized) and (realized.lower() == face.lower() or realized != stand_in)
                finally:
                    gdi32.DeleteDC(dc)
        except Exception:
            found = False
        _INSTALLED[face] = found
        return found


def _declare(gdi32, user32):
    global _declared
    if _declared:
        return
    gdi32.CreateCompatibleDC.restype, gdi32.CreateCompatibleDC.argtypes = C.c_void_p, [C.c_void_p]
    gdi32.DeleteDC.restype, gdi32.DeleteDC.argtypes = W.BOOL, [C.c_void_p]
    gdi32.CreateFontW.restype = C.c_void_p
    gdi32.CreateFontW.argtypes = [C.c_int] * 5 + [W.DWORD] * 8 + [W.LPCWSTR]
    gdi32.SelectObject.restype, gdi32.SelectObject.argtypes = C.c_void_p, [C.c_void_p, C.c_void_p]
    gdi32.DeleteObject.restype, gdi32.DeleteObject.argtypes = W.BOOL, [C.c_void_p]
    gdi32.GetGlyphIndicesW.restype = W.DWORD
    gdi32.GetGlyphIndicesW.argtypes = [C.c_void_p, W.LPCWSTR, C.c_int, C.POINTER(W.WORD), W.DWORD]
    gdi32.GetTextFaceW.restype = C.c_int
    gdi32.GetTextFaceW.argtypes = [C.c_void_p, C.c_int, W.LPWSTR]
    user32.SystemParametersInfoW.restype = W.BOOL
    user32.SystemParametersInfoW.argtypes = [W.UINT, W.UINT, C.c_void_p, W.UINT]
    _declared = True


def lacks(face, text) -> str:
    """The characters of `text` the face `face` has no glyph of its own for - not one it would borrow
    through a font link. "" when Windows cannot be asked. Asked once per face and text."""
    if os.name != "nt" or not isinstance(face, str) or not face.strip() or not text:
        return ""
    key = (face, text)
    with _LOCK:
        if key in _LACKING:
            return _LACKING[key]
        missing = ""
        try:
            gdi32 = _dll("gdi32")
            _declare(gdi32, _dll("user32"))
            dc = gdi32.CreateCompatibleDC(None)
            if dc:
                try:
                    font = gdi32.CreateFontW(-12, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, face)
                    if font:
                        previous = gdi32.SelectObject(dc, font)
                        try:
                            glyphs = (W.WORD * len(text))()
                            if gdi32.GetGlyphIndicesW(dc, text, len(text), glyphs,
                                                      GGI_MARK_NONEXISTING_GLYPHS) != 0xFFFFFFFF:
                                missing = "".join(char for char, glyph in zip(text, glyphs) if glyph == _NO_GLYPH)
                        finally:
                            gdi32.SelectObject(dc, previous)
                            gdi32.DeleteObject(font)
                finally:
                    gdi32.DeleteDC(dc)
        except Exception:
            missing = ""
        _LACKING[key] = missing
        return missing


def ui_face():
    """The face of Windows' message font, or None when Windows cannot be asked: Segoe UI on an English
    Windows, Malgun Gothic - by its Korean name - on a Korean one. Asked each time; nothing is cached."""
    if os.name != "nt":
        return None
    try:
        user32 = _dll("user32")
        with _LOCK:
            _declare(_dll("gdi32"), user32)
        metrics = NONCLIENTMETRICSW()
        metrics.cbSize = C.sizeof(NONCLIENTMETRICSW)
        if not user32.SystemParametersInfoW(SPI_GETNONCLIENTMETRICS, metrics.cbSize, C.byref(metrics), 0):
            return None
        face = metrics.lfMessageFont.lfFaceName
        return face if face and face.strip() else None
    except Exception:
        return None
