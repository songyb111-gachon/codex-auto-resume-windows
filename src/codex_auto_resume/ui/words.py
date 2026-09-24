"""Words every surface writes the same way.

A remaining time is the first of them. The icon's tooltip and the popup both show one, and
they showed it through the same function - which lived in the icon, so the popup imported the
icon to draw a clock. That is one of the import cycles `tests/test_layers.py` lists.

Locale-neutral on purpose: digits and a colon read the same in all nine languages, and a
duration that says "3 minutes" in one of them would have to be translated to say anything at
all in the others.
"""
from __future__ import annotations


def countdown(seconds: float) -> str:
    """A short, locale-neutral duration: 45s, 12:04, 3:05:00."""
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return "%d:%02d:%02d" % (hours, minutes, secs)
    if minutes:
        return "%d:%02d" % (minutes, secs)
    return "%ds" % secs
