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
from .values import (AGENT_CREATED_THREAD, COMPOSER, KNOWN_STATUSES, MAX_ITEM_BYTES, MAX_META_BYTES,  # noqa: F401
                     MAX_SCAN_BYTES, PROGRESS_ITEM_TYPES, _json, _turn_status,
                     epoch, normalize)
from .paths import DB_KINDS, _safe_path  # noqa: F401
from .payload import _choose_reset, _content_has_marker, _queue_has_marker, admissible, detect  # noqa: F401
from .schema import SchemaMixin
from . import eligibility, rollout
from ..domain import ids


class LocalSource(SchemaMixin, HistoryMixin):
    """Codex's own files, read read-only.
    """
    # P19 (v0.6.16-beta.3): which conversations besides a person's own `_eligibility` takes up (values.taken_thread_source)
    # - the engine sets it from its plug each tick; empty, the standard edition's always, it is A15 as ever.
    widened = frozenset()
    # P18 (v0.6.16-beta.4): the kinds of conversation besides the app's `_eligibility` takes up (codex/eligibility.py),
    # set by the engine from its plug each tick; empty, the standard edition's always.
    session_kinds = frozenset()

    def newer_than_engine(self, thread_id: str, kinds, engine_version) -> bool:
        """Whether a conversation of one of `kinds` (P18) says a Codex newer than `engine_version` (the engine's
        `codex --version`) wrote it - the version skew guard (eligibility.newer_than_engine); False with no kind."""
        return bool(kinds) and eligibility.newer_than_engine(self.written_by(thread_id, kinds), engine_version)

    def written_by(self, thread_id: str, kinds):
        """The Codex version a conversation of one of `kinds` (P18) - a terminal's, VS Code's, never the app's own -
        says wrote it: its file's first line's `cli_version` (B6, the line `_eligibility` reads), or None. Read only for
        a kind a plug names, so the standard edition, which names none, never reads it."""
        if not kinds or self.taken(thread_id, frozenset()) or not self.taken(thread_id, kinds):
            return None
        path = self._rollout_path(thread_id)
        payload = None if path is None else rollout.session_meta(path)
        version = payload.get("cli_version") if isinstance(payload, dict) else None
        return version if isinstance(version, str) else None

    def _composed(self, thread_id: str, row, turn_id=None, strict=False) -> bool:
        """Whether a conversation an agent made (thread_source agent_created_thread) is the person's in the turn
        `turn_id` - else its latest, the one a recovery is about - which they started from the input box, by the
        trigger the rollout records for it (issue #54, rollout.turn_trigger). Unknown, and any other kind, is False; a
        strict read that cannot read raises SourceError, so the engine defers."""
        if row["thread_source"] != AGENT_CREATED_THREAD:
            return False
        try:
            path = rollout.confined(self.home, thread_id, row["rollout_path"])
            return path is not None and rollout.turn_trigger(path, turn_id) == COMPOSER
        except OSError:
            if strict:
                raise SourceError("Codex local state unavailable or unsupported") from None
            return False

    def rescan_evidence(self, thread_id: str, turn_id: str) -> str:
        """What the conversation's current file says of the failed turn `turn_id` (rollout.superseded_in), for a person's
        Rescan and reconcile (v0.6.16, issue #39) while Codex's history is behind it: the file `_eligibility` names, so
        one confined to the sessions folder whose first line says it is this conversation's - a split's A_B file too
        (issue #30). rollout.UNREADABLE for anything that cannot be read, or for a conversation not taken up."""
        if not ids.is_uuid(turn_id):
            return rollout.UNREADABLE
        try:
            path = self._eligibility(thread_id, strict=True)[0]
        except Exception:
            return rollout.UNREADABLE
        return rollout.UNREADABLE if path is None else rollout.superseded_in(path, turn_id)

    def elsewhere(self, codex_home) -> "LocalSource":
        """A reader of another Codex home, made as this one is (v0.6.15-beta): for the labels of that home's records,
        where the control layer, which builds no reader of its own, is handed this one."""
        return type(self)(codex_home, chains=self.chains)
