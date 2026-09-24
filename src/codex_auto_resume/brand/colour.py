"""Colour arithmetic on #RRGGBB, and nothing that decides a colour.

The bottom of this package: it imports nothing else here, and everything else that mixes,
brightens or measures contrast comes through it.
"""
from __future__ import annotations

import math



def rgb(value: str) -> tuple[int, int, int]:
    """`#RRGGBB` to a byte triple."""
    text = value.lstrip("#")
    if len(text) != 6:
        raise ValueError("expected #RRGGBB, got %r" % value)
    return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))


def mix(one: str, other: str, amount: float) -> str:
    """`one` moved `amount` of the way toward `other`, per channel, rounded half up."""
    return "#%02X%02X%02X" % tuple(int(math.floor(a + (b - a) * amount + 0.5))
                                   for a, b in zip(rgb(one), rgb(other)))


def brighten(value: str, factor: float) -> str:
    """Every channel times `factor`, rounded half up and held at 255: CSS `brightness()`."""
    return "#%02X%02X%02X" % tuple(min(255, int(math.floor(channel * factor + 0.5)))
                                   for channel in rgb(value))


def _channel(byte: int) -> float:
    part = byte / 255.0
    return part / 12.92 if part <= 0.04045 else ((part + 0.055) / 1.055) ** 2.4


def luminance(value: str) -> float:
    red, green, blue = (_channel(channel) for channel in rgb(value))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(one: str, other: str) -> float:
    """WCAG contrast ratio, so the tests can assert readability rather than taste."""
    first, second = luminance(one), luminance(other)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)
