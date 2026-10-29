# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""A person's own conversations and their names, read-only (v0.6.20, issue #50), for the Dashboard's Find a conversation
alone - the pickers beside Pending's and History's, which name only the conversations those two list.

One statement per ordering selects, from Codex's `threads` table, a conversation's id, its name and the four columns
core judges whether a conversation is a person's own by (codex/eligibility.row_problem: the app's source, not archived,
a person's thread source, paginated) - and nothing else: not its title, its first message, its folder, its rollout. The
name is core's own label (codex/labels), a single short line or nothing, and a conversation with none is left out: there
would be nothing to find it by. Newest first by the column Codex keeps its last change in, else by the order it was
written. Every statement this module runs is one of `STATEMENTS` below, which advanced/tests/test_advanced_conversations.py
holds to that.

The file is found and opened as every read of Codex's databases here is (codex/turns.connect): the newest generation,
read-only, query_only on and trusted_schema off, the columns read required. Anything that goes wrong is TurnsUnavailable.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3

from codex_auto_resume.codex import eligibility
from codex_auto_resume.codex.labels import _label
from codex_auto_resume.domain import ids

from .turns import TurnsUnavailable, connect

THREAD_COLUMNS = frozenset({"id", "name", "source", "thread_source", "archived", "history_mode"})
_SELECT = "SELECT id, name, source, thread_source, archived, history_mode FROM threads WHERE archived=0 ORDER BY "
BY_UPDATED_MS = _SELECT + "updated_at_ms DESC, rowid DESC"
BY_UPDATED = _SELECT + "updated_at DESC, rowid DESC"
BY_CREATED_MS = _SELECT + "created_at_ms DESC, rowid DESC"
BY_CREATED = _SELECT + "created_at DESC, rowid DESC"
BY_WRITTEN = _SELECT + "rowid DESC"
STATEMENTS = (BY_UPDATED_MS, BY_UPDATED, BY_CREATED_MS, BY_CREATED, BY_WRITTEN)
# At most this many rows are looked at, so a home with a great many conversations is not read whole.
SCAN = 5000


class Threads:
    """The conversations of the Codex home `home`, as Find a conversation reads them."""

    def __init__(self, home):
        self.home = Path(home)

    def own(self, limit, skip=frozenset()) -> list:
        """The person's own conversations, newest first, none in `skip` and at most `limit`: [(thread id, name)]."""
        connection = connect(self.home, "state", {"threads": THREAD_COLUMNS})
        try:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(threads)")}
            connection.row_factory = sqlite3.Row
            if "updated_at_ms" in columns:
                cursor = connection.execute(BY_UPDATED_MS)
            elif "updated_at" in columns:
                cursor = connection.execute(BY_UPDATED)
            elif "created_at_ms" in columns:
                cursor = connection.execute(BY_CREATED_MS)
            elif "created_at" in columns:
                cursor = connection.execute(BY_CREATED)
            else:
                cursor = connection.execute(BY_WRITTEN)
            found = []
            for number, row in enumerate(cursor):
                if number >= SCAN or len(found) >= limit:
                    break
                thread, name = row["id"], _label(row["name"])
                if name is None or not ids.is_uuid(thread) or thread in skip:
                    continue
                if eligibility.row_problem(row) is not None:
                    continue
                found.append((thread, name))
            return found
        except (sqlite3.Error, ValueError):
            raise TurnsUnavailable("the conversations cannot be read") from None
        finally:
            connection.close()
