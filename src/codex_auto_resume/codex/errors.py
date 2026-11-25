"""What the reader refuses with: one exception, for one reason - and the one case of it that is no failure yet."""
from __future__ import annotations

# Raised by the platform as well as by this reader, so it is declared below both.
from ..domain.errors import AdapterError

__all__ = ["AdapterError", "HistoryNotYet", "SourceError"]


class SourceError(RuntimeError):
    """Safe diagnostic: never include database contents or underlying errors."""


class HistoryNotYet(SourceError):
    """v0.6.26 final: no history database yet in a home whose newest state database holds no conversation - Codex makes
    it with the first conversation it saves (thread_history_1.sqlite is opened lazily, never at start), so a fresh
    home has nothing to read yet, not a history that cannot be read. One whose state holds a conversation is still
    the plain refusal: there Codex moved, renamed or dropped it."""
