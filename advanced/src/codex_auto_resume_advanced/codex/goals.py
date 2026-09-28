# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Codex's goals database, read-only: which goal a conversation has, and its status - never what
it says.

Codex keeps each conversation's goal in goals_<N>.sqlite in the Codex home, beside its other
databases (codex-rs state/goals_migrations: `thread_goals`, one row a conversation). The goal
continuation (engine/goal.py) needs three of its columns - which goal it is, its status, and when
it last changed - and this reads exactly those and nothing else: never `objective`, the goal's
own words, which are the person's (the stance core keeps for titles and first messages, B8;
advanced/tests/test_advanced_goal.py holds the one statement to it).

The file is found as core finds every Codex database (codex/schema.py): the newest generation by
its name, a symbolic link never followed, the columns this reads required, and opened read-only
with query_only on and trusted_schema off (B1). Anything that goes wrong is GoalsUnavailable,
which the capability reads as "do what the standard edition does".
"""
from __future__ import annotations

from pathlib import Path
import re
import sqlite3
from typing import NamedTuple

from codex_auto_resume.codex.paths import _safe_path

from ..vocabulary import GoalStatus

PATTERN = re.compile(r"goals_(\d+)\.sqlite\Z")
TABLE = "thread_goals"
# The columns read, and the only ones: `objective` is never among them.
COLUMNS = frozenset({"thread_id", "goal_id", "status", "updated_at_ms"})
SELECT = "SELECT goal_id, status, updated_at_ms FROM thread_goals WHERE thread_id=?"
# A goal id is Codex's own opaque token; it is compared, never stored, and anything longer than
# this is no id Codex makes.
MAX_GOAL_ID = 128


class GoalsUnavailable(RuntimeError):
    """The goals database could not be read as this reads it. A static reason only."""


class Goal(NamedTuple):
    goal_id: str
    status: GoalStatus
    updated_at_ms: int


class Goals:
    """The goals database of the Codex home `home`."""

    def __init__(self, home):
        self.home = _safe_path(Path(home))

    def _path(self) -> Path:
        candidates = []
        try:
            for entry in self.home.iterdir():
                match = PATTERN.fullmatch(entry.name)
                if match and entry.is_file() and not entry.is_symlink():
                    candidates.append((int(match.group(1)), entry))
        except OSError:
            raise GoalsUnavailable("the Codex home cannot be listed") from None
        if not candidates:
            raise GoalsUnavailable("no goals database")
        path = _safe_path(max(candidates, key=lambda item: item[0])[1])
        if path.parent != self.home:
            raise GoalsUnavailable("the goals database is outside the Codex home")
        return path

    @staticmethod
    def _connect(path):
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3)
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        return connection

    def read(self, thread_id) -> Goal | None:
        """The goal of conversation `thread_id`, or None where it has none. GoalsUnavailable when
        the database is missing, has moved on from these columns, cannot be read, or holds a status
        or an id of no shape this knows."""
        connection = None
        try:
            connection = self._connect(self._path())
            found = {row[1] for row in connection.execute("PRAGMA table_info(%s)" % TABLE)}
            if not COLUMNS <= found:
                raise GoalsUnavailable("the goals table has moved on")
            row = connection.execute(SELECT, (thread_id,)).fetchone()
        except (sqlite3.Error, OSError, ValueError):
            raise GoalsUnavailable("the goals database cannot be read") from None
        finally:
            if connection is not None:
                connection.close()
        if row is None:
            return None
        goal_id, status, updated = row
        if (not isinstance(goal_id, str) or not goal_id or len(goal_id) > MAX_GOAL_ID
                or not isinstance(updated, int) or isinstance(updated, bool)):
            raise GoalsUnavailable("a goal of no shape this knows")
        try:
            status = GoalStatus(status)
        except ValueError:
            raise GoalsUnavailable("a goal status this does not know") from None
        return Goal(goal_id, status, updated)
