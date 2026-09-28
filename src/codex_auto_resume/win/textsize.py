"""Windows' text size (v0.6.11): Settings > Accessibility > Text size, "Make text bigger".

One content-free value, read and never written: `TextScaleFactor` under
HKCU\\Software\\Microsoft\\Accessibility, a percentage from 100 to 225 that Windows writes when the
slider moves. The notification-area popup, its card and the panel in Codex draw at it, as the
Dashboard does (gui/SoftTheme.cs, TextScale), so all four are one size. Nothing there - the slider
never moved - or anything outside the range is 1: the size everything had before.
"""
from __future__ import annotations

KEY = "Software\\Microsoft\\Accessibility"
VALUE = "TextScaleFactor"
LOWEST, HIGHEST = 100, 225


def factor(percent) -> float:
    """A TextScaleFactor percentage as a factor: 100 to 225 as itself, anything else as 1. Pure."""
    if isinstance(percent, bool) or not isinstance(percent, int) or not LOWEST <= percent <= HIGHEST:
        return 1.0
    return percent / 100.0


def read() -> float:
    """Windows' text size now, as a factor from 1 to 2.25; 1 when Windows cannot be asked."""
    try:
        import winreg
    except ImportError:                       # not Windows: text at its usual size
        return 1.0
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as key:
            value, kind = winreg.QueryValueEx(key, VALUE)
    except OSError:
        return 1.0
    return factor(value) if kind == winreg.REG_DWORD else 1.0


def fitting(text, needs, room) -> float:
    """The text size a surface draws at: `text`, but no larger than lets what it `needs` at the usual
    size - (width, height) - grow into the `room` it has, and never below 1. Pure.

    A surface drawn at a text size is drawn larger as a whole - its words and what holds them, which is
    what keeps any of it from being cut - so a screen too small for it at the size asked gets the
    largest that fits there instead.
    """
    size = text if isinstance(text, (int, float)) and not isinstance(text, bool) and text > 1.0 else 1.0
    for need, has in zip(needs, room):
        if need > 0 and has > 0:
            size = min(size, has / float(need))
    return max(1.0, size)
