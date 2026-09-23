"""Codex's own files, read.

`source.py` was 728 lines. It is the same reader, composed here from two mixins, so every
`from .source import LocalSource` and every call reads exactly as it did:

    paths       where Codex keeps its files, and the columns each must have
    schema      finding a database, and refusing one whose schema has moved
    history     every statement this product sends to Codex - and nowhere else
    values      Codex's words and numbers, read one way
    labels      the name a person would recognise, cut to a length
    payload     one interruption, read out of what Codex recorded
    errors      the one refusal

Nothing here writes to Codex. Every connection is opened read-only.
"""
from __future__ import annotations

from .errors import SourceError  # noqa: F401
from .history import HistoryMixin
from .labels import MAX_LABEL_CHARS, _label  # noqa: F401
from .values import (KNOWN_STATUSES, MAX_ITEM_BYTES, MAX_META_BYTES,  # noqa: F401
                     MAX_SCAN_BYTES, PROGRESS_ITEM_TYPES, _json, _turn_status,
                     epoch, normalize)
from .paths import DB_KINDS, _safe_path  # noqa: F401
from .payload import _choose_reset, _content_has_marker, _queue_has_marker, detect  # noqa: F401
from .schema import SchemaMixin


class LocalSource(SchemaMixin, HistoryMixin):
    """Codex's own files, read read-only.
    """
