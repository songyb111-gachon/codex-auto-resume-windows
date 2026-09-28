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
