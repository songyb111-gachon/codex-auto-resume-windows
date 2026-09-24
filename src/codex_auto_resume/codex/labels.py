"""The name a person would recognise a conversation by, cut to a length.

Only ever shown back to the person whose conversation it is: a label never leaves the machine,
and never reaches a log.
"""
from __future__ import annotations

import re


MAX_LABEL_CHARS = 72


def _label(value):
    """A display label, or None. Never a paragraph, never multi-line.

    A defensive cap: if a future schema starts putting prompt-like text in the field
    this reads, a long or multi-line value is dropped rather than shown. Control
    characters are stripped so a label can never rearrange a notification.
    """
    if not isinstance(value, str):
        return None
    cleaned = "".join(character for character in value if character.isprintable()).strip()
    if not cleaned or any(ch in value for ch in ("\n", "\r", "\t")):
        return None
    if len(cleaned) > MAX_LABEL_CHARS:
        cleaned = cleaned[:MAX_LABEL_CHARS - 1].rstrip() + "…"
    return cleaned
