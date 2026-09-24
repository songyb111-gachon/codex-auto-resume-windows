"""Light or dark, motion or none, and the colours High Contrast takes over.

Each of these is a question for Windows, asked once and adopted - the popup never decides its
own appearance while it is open.
"""
from __future__ import annotations

from ctypes import wintypes as W
import ctypes as C
from ... import brand
from .win32 import (HCF_HIGHCONTRASTON,
                    HIGHCONTRASTW,
                    HKEY_CURRENT_USER,
                    RRF_RT_REG_DWORD,
                    SPI_GETCLIENTAREAANIMATION,
                    SPI_GETHIGHCONTRAST,
                    _declare,
                    _dll)


# ------------------------------------------------------------------------- High Contrast
# With High Contrast on, the popup draws the way the settings window does (gui/SoftTheme.cs,
# Palette): every token is the system colour below, and nothing is drawn that a system colour
# cannot say - no shadow, no tint, no glow. The state dot takes brand's STATUS_SYSTEM.
SYSTEM_COLOURS = {"Window": 5, "WindowFrame": 6, "WindowText": 8, "Highlight": 13, "HighlightText": 14,
                  "Control": 15, "GrayText": 17}          # GetSysColor indices


CONTRAST_COLOURS = {
    "ink": "WindowText", "muted": "GrayText", "line": "WindowFrame", "surface": "Window",
    "canvas": "Control", "raised": "Window", "inset": "Window", "shadow_dark": "WindowFrame",
    "shadow_light": "Window", "accent": "Highlight", "accent_hover": "Highlight",
    "accent_pressed": "Highlight", "accent_soft": "Highlight", "on_accent": "HighlightText",
    "focus": "WindowText", "active": "Highlight", "idle": "GrayText", "attention": "WindowText",
    "success": "WindowText", "waiting": "WindowText", "warning": "WindowText", "danger": "WindowText",
    "paused": "GrayText",
}


def contrast_colour(token) -> str:
    """The system colour a brand token is drawn in while High Contrast is on."""
    return CONTRAST_COLOURS.get(token, "WindowText")


# --------------------------------------------------------------------------------- theme
# v0.6.4. The Theme setting is "system", "light" or "dark". "system" follows Windows' app mode
# (AppsUseLightTheme: 0 is dark, anything else or nothing at all is light), and High Contrast
# outranks every choice. The popup resolves it each time it opens, again whenever Windows says a
# setting changed while it is open, and whenever it reads the settings - so a new choice, or a
# flip of Windows' mode, never needs the watcher restarted. The icon does not change.
THEME_SYSTEM = "system"


THEME_CHOICES = (THEME_SYSTEM,) + brand.THEMES


def theme_choice(value) -> str:
    """The stored choice as one of THEME_CHOICES; anything else is "system", as settings reads it."""
    return value if isinstance(value, str) and value in THEME_CHOICES else THEME_SYSTEM


def effective_theme(choice, apps_use_light=None) -> str:
    """"light" or "dark": a choice of either, or for "system" what Windows' app mode says.

    `apps_use_light` is True, False, or None when Windows does not say - which Windows itself
    draws as light, so only an explicit False is dark.
    """
    choice = theme_choice(choice)
    if choice != THEME_SYSTEM:
        return choice
    return "dark" if apps_use_light is False else "light"


def appearance(choice, apps_use_light=None, contrast=False) -> str:
    """What the popup draws with: "contrast" whenever High Contrast is on, else the theme."""
    return "contrast" if contrast else effective_theme(choice, apps_use_light)


PERSONALIZE_KEY = "Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize"


APP_MODE_VALUE = "AppsUseLightTheme"


# The product's own Reduce motion setting, adopted by the watcher whenever it reads its
# settings. Windows' own switch is honoured as well; either one stops all motion.
_reduce_motion_setting = False


def set_reduce_motion(value) -> None:
    global _reduce_motion_setting
    _reduce_motion_setting = value is True


# The product's Theme setting, adopted the same way: by the watcher when it reads its settings,
# by the icon each time somebody opens the popup or its menu, and by the popup from every read.
_theme_setting = THEME_SYSTEM


def set_theme(value) -> None:
    global _theme_setting
    _theme_setting = theme_choice(value)


def theme_setting() -> str:
    return _theme_setting


def adopt_settings(values) -> None:
    """Take up the stored Theme and Reduce motion from a settings dict; anything else is ignored."""
    if isinstance(values, dict):
        set_theme(values.get("theme"))
        set_reduce_motion(values.get("reduce_motion"))


def apps_use_light_theme():
    """Windows' app mode: True for light, False for dark, None when Windows does not say."""
    try:
        _declare()
        data, size = W.DWORD(0), W.DWORD(C.sizeof(W.DWORD))
        status = _dll("advapi32").RegGetValueW(C.c_void_p(HKEY_CURRENT_USER), PERSONALIZE_KEY, APP_MODE_VALUE,
                                               RRF_RT_REG_DWORD, None, C.byref(data), C.byref(size))
        if status != 0:
            return None
        return data.value != 0
    except Exception:
        return None


def reduced_motion() -> bool:
    """True when Windows, or this product's Reduce motion setting, asks for fewer animations."""
    if _reduce_motion_setting:
        return True
    try:
        _declare()
        value = W.BOOL(1)
        if not _dll("user32").SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, C.byref(value), 0):
            return False
        return not value.value
    except Exception:
        return False


def high_contrast() -> bool:
    """True while Windows' High Contrast is on."""
    try:
        _declare()
        info = HIGHCONTRASTW()
        info.cbSize = C.sizeof(HIGHCONTRASTW)
        if not _dll("user32").SystemParametersInfoW(SPI_GETHIGHCONTRAST, info.cbSize, C.byref(info), 0):
            return False
        return bool(info.dwFlags & HCF_HIGHCONTRASTON)
    except Exception:
        return False


def system_rgb(name) -> tuple:
    """A system colour, by the name Windows Forms gives it, as (red, green, blue)."""
    _declare()
    value = _dll("user32").GetSysColor(SYSTEM_COLOURS[name])
    return (value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF)
