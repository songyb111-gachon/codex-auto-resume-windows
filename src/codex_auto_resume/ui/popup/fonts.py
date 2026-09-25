"""Which face each script is drawn in, and what Windows actually has.

A face named in a table is a face somebody hopes for; `_face_exists` asks Windows, once, and
remembers. Nothing here draws - it answers which name to draw with.
"""
from __future__ import annotations

import ctypes as C
import os
from ... import brand
from .win32 import NONCLIENTMETRICSW, SPI_GETNONCLIENTMETRICS, _declare, _dll


_SCRIPT_FACES = {"ko": "Malgun Gothic", "ja": "Yu Gothic UI", "zh-CN": "Microsoft YaHei UI",
                 "zh-TW": "Microsoft JhengHei UI"}


_ON_EVERY_WINDOWS = "Segoe UI"


_ASK_WINDOWS = object()


def font_faces(locale, system=_ASK_WINDOWS) -> tuple:
    """The typefaces to try for a locale, best first. The last one is on every Windows.

    A script with a face of its own (Korean, Japanese, Chinese) is set in that face. Every
    other language follows the panel's type stack - `system-ui`, then "Segoe UI Variable
    Text", then "Segoe UI" - where `system-ui` is Windows' UI font: the message font the
    window is drawn in (SystemFonts.MessageBoxFont), which `message_face` asks Windows for.
    So English on a Korean Windows is Malgun Gothic here too, as it is in the window and the
    panel, and Segoe UI on an English one. `system` stands in Windows' answer; None or ""
    means Windows could not be asked, and the stack goes on to its next choices.
    """
    if locale in _SCRIPT_FACES:
        return (_SCRIPT_FACES[locale], _ON_EVERY_WINDOWS)
    first = message_face() if system is _ASK_WINDOWS else system
    faces = []
    for face in (first, "Segoe UI Variable Text"):
        if not isinstance(face, str) or not face.strip():
            continue                                   # no answer: the stack's next choice
        if face.lower() == _ON_EVERY_WINDOWS.lower():
            break                                      # Windows' UI font is the last resort itself
        if face.lower() not in [known.lower() for known in faces]:
            faces.append(face)
    return tuple(faces) + (_ON_EVERY_WINDOWS,)


def font_candidates(locale, weight, system=_ASK_WINDOWS) -> tuple:
    """(face, weight) pairs to try for one font role, best first.

    GDI has no semibold inside a family it lists as regular: Segoe UI Variable Text asked
    for weight 600 answers with its bold. The semibold instances are families of their
    own and are asked for at their regular weight. Malgun Gothic and the Chinese UI faces
    have no semibold at all, so their emphasis is their bold - the window's own rule
    (Soft.Weighted: a Segoe UI face's semibold family, the face's bold otherwise).
    """
    faces = font_faces(locale, system)
    if weight < 600:
        return tuple((face, 400) for face in faces)
    if locale == "ja":
        return (("Yu Gothic UI Semibold", 400), ("Yu Gothic UI", 600), ("Segoe UI Semibold", 400),
                ("Segoe UI", 600))
    if locale in _SCRIPT_FACES:
        return ((faces[0], 700), ("Segoe UI Semibold", 400), ("Segoe UI", 600))
    heavy = []
    for face in faces[:-1]:
        segoe = face.lower().startswith("segoe ui") and not face.lower().endswith("semibold")
        heavy.append((face + " Semibold", 400) if segoe else (face, 700))
    return tuple(heavy) + (("Segoe UI Semibold", 400), ("Segoe UI", 600))


# Font roles: size in px at 96 DPI and weight. The title - the state's word, since v0.6.10 - is
# smaller than TYPE's because this is a flyout, not a window. A button and a chip are bold (600),
# the popup's and the notification card's own look: the sizes are brand's, as the window's and the
# panel's are, but not the weight - brand.TYPE_ROLES' 500 is drawn Regular here (font_candidates),
# which v0.6.10 tried and gave back.
ROLES = {
    "title": (15, 600),
    "label": (brand.TYPE["small"], 400),
    "value": (brand.TYPE["heading"], 600),
    "name": (brand.TYPE["body"], 600),
    "chip": (brand.TYPE["small"], 600),
    "body": (brand.TYPE["body"], 400),
    "small": (brand.TYPE["small"], 400),
    "button": (brand.TYPE["body"], 600),
}


# Ideographic and Hangul text at 11-12 px loses strokes; these scripts get one pixel more.
_DENSE_SCRIPTS = frozenset({"ko", "ja", "zh-CN", "zh-TW"})


def role_size(role, locale) -> int:
    size, _ = ROLES[role]
    return size + 1 if locale in _DENSE_SCRIPTS and size <= 12 else size


def message_face():
    """The face of Windows' message font, or None when Windows cannot be asked.

    The window's every font is a variant of this one (SystemFonts.MessageBoxFont reads the
    same field), and the panel's `system-ui` resolves to it, so text set in it here is set in
    the face the other two surfaces use: Segoe UI on an English Windows, Malgun Gothic -
    by its Korean name - on a Korean one. Asked each time fonts are made; nothing is cached.
    """
    if os.name != "nt":
        return None
    try:
        _declare()
        metrics = NONCLIENTMETRICSW()
        metrics.cbSize = C.sizeof(NONCLIENTMETRICSW)
        if not _dll("user32").SystemParametersInfoW(SPI_GETNONCLIENTMETRICS, metrics.cbSize,
                                                    C.byref(metrics), 0):
            return None
        face = metrics.lfMessageFont.lfFaceName
        return face if face and face.strip() else None
    except Exception:
        return None


_FACE_CACHE = {}


_SUBSTITUTE = {}


_NO_SUCH_FACE = "CodexAutoResume No Such Face"


def _realized_face(dc, face) -> str:
    gdi32 = _dll("gdi32")
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


def _face_exists(dc, face) -> bool:
    """Whether GDI has this face itself rather than a substitute for it.

    `GetTextFaceW` answers with a family's localized name - Malgun Gothic is reported as
    its Korean name on a Korean system - so a face counts as present when the answer is its
    own name, or is anything other than what a face that does not exist is mapped to.
    """
    if face not in _FACE_CACHE:
        if "name" not in _SUBSTITUTE:
            _SUBSTITUTE["name"] = _realized_face(dc, _NO_SUCH_FACE)
        realized = _realized_face(dc, face)
        _FACE_CACHE[face] = bool(realized) and (realized.lower() == face.lower()
                                                or realized != _SUBSTITUTE["name"])
    return _FACE_CACHE[face]


class _Fonts:
    def __init__(self, dc, locale, scale):
        gdi32 = _dll("gdi32")
        self.key = (locale, scale)
        self.handles = {}
        self.faces = {}
        system = message_face()                  # once for every role, so they cannot disagree
        try:
            for role, (_, weight) in ROLES.items():
                candidates = font_candidates(locale, weight, system)
                face, actual = next(((name, value) for name, value in candidates if _face_exists(dc, name)),
                                    candidates[-1])
                height = -max(1, int(round(role_size(role, locale) * scale)))
                handle = gdi32.CreateFontW(height, 0, 0, 0, actual, 0, 0, 0, 1, 0, 0, 5, 0, face)
                if not handle:
                    raise OSError("CreateFontW")
                self.handles[role] = handle
                self.faces[role] = face
        except Exception:
            self.close()
            raise

    def close(self):
        gdi32 = _dll("gdi32")
        for handle in self.handles.values():
            gdi32.DeleteObject(handle)
        self.handles = {}
