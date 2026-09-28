"""Needs-you notices (schema 4): each raised once, and let go once nothing could raise it again.

A notice tells a person something. It is never a record, never a claim and never read by anything
that decides a send (store/columns.py, _UNREAD_BY_DISPATCH): it is kept only so that the same
failure, or the same turn that stopped moving, is told once - across restarts of the watcher too.
"""
from __future__ import annotations

from .. import needsyou
from .validate import _validated_notice


class NoticesMixin:
    def raise_notice(self, key: str, thread_id: str, kind: str, now: float) -> bool:
        """Keep the notice `key` - True the first time, when it is to be told, and False every time
        after. Ids, a closed word and a time; nothing else (D2). A notice older than anything the
        engine still looks at is let go in the same write, so the table stays small."""
        row = _validated_notice({"interruption_id": key, "thread_id": thread_id, "category": kind,
                                 "raised_at": now, "seen_at": None})
        with self._transaction() as connection:
            connection.execute("DELETE FROM notices WHERE raised_at<?", (now - needsyou.KEEP_SECONDS,))
            cursor = connection.execute(
                "INSERT OR IGNORE INTO notices (interruption_id, thread_id, category, raised_at, seen_at) "
                "VALUES (?,?,?,?,NULL)", (row["interruption_id"], row["thread_id"], row["category"],
                                          row["raised_at"]))
            return cursor.rowcount == 1
