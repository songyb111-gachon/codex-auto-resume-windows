"""The popup's own words: the catalogue, and how a line is cut and broken.

Korean and Chinese break between characters and the rest of the world between words, so a line
that fits in one language is not the same line in another.
"""
from __future__ import annotations

from .. import l10n


def say(strings, key, **fields) -> str:
    """One string from the catalog the icon was given, English underneath it.

    The icon can be built with an empty vocabulary (some watcher paths do), and a window
    that shows a key name, or raises, in front of a person is worse than one in English.
    """
    value = (strings or {}).get(key)
    if not isinstance(value, str) or not value:
        value = l10n.catalog(l10n.DEFAULT).get(key, key)
    for name, supplied in fields.items():
        value = value.replace("{%s}" % name, str(supplied))
    return value


def one_line(text, limit=120) -> str:
    """A conversation name as a single, bounded line."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[:limit - 1] + "…"


_LOCALE_PROBES = ("activity.monitoring", "popup.nothing", "action.pause", "popup.open_dashboard")


def locale_of(strings) -> str:
    """Which shipped catalog a vocabulary is, so the window can pick a typeface for it."""
    if not strings:
        return l10n.DEFAULT
    best, score = l10n.DEFAULT, -1
    for locale in l10n.LOCALES:
        table = l10n.catalog(locale)
        found = sum(1 for key in _LOCALE_PROBES
                    if strings.get(key) is not None and strings.get(key) == table.get(key))
        if found > score:
            best, score = locale, found
    return best


def vocabulary(language) -> dict:
    """The catalog a stored Interface language speaks, resolved exactly as the watcher resolves it."""
    chosen = language if isinstance(language, str) and language in l10n.CHOICES else l10n.SYSTEM
    return l10n.catalog(l10n.resolve(chosen))


# ------------------------------------------------------------------------------- layout
def _breaks_anywhere(char) -> bool:
    """A character a line may break before or after: Chinese and Japanese are set without spaces."""
    code = ord(char)
    return 0x2E80 <= code <= 0x9FFF or 0xF900 <= code <= 0xFAFF or 0xFF00 <= code <= 0xFFEF


def unbroken(text):
    """The pieces of a label no line may break inside: its words, and in a run of Chinese or Japanese
    each character (Korean is set with spaces, and Renderer.lines breaks it only there)."""
    pieces = []
    for word in str(text).split():
        if any(_breaks_anywhere(char) for char in word):
            pieces.extend(word)
        else:
            pieces.append(word)
    return pieces or [""]
