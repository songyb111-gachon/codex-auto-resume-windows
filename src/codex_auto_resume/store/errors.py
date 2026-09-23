"""What the store refuses with.

Four, and each is a different answer: the state is unreadable, it belongs to a newer release,
an older one still owns it, or a row is not shaped the way this release writes rows.
"""
from __future__ import annotations


class StoreError(RuntimeError):
    """Invalid or unavailable local state; automatic resumes must stop."""


class UpgradePending(StoreError):
    """The state is an older schema and this caller may not migrate it."""


class StateFromNewerVersion(StoreError):
    """The state was written by a newer version of this tool. Never a corruption."""


class RecordSchemaMismatch(StoreError):
    """A row has columns this version never wrote: a newer version changed the state."""
