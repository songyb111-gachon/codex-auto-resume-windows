# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Codex's turn history, read-only (v0.6.15-beta): what kinds of item a conversation's latest turn left, which
conversations finished a turn lately, and the statuses of a plan's steps - never what any of it says.

The empty-response recovery (engine/emptyreply.py) and keep going (engine/keepgoing.py) judge a turn by the kinds of
item it left alone, counted per `item_type` (no content column); keep going stops on a finished plan, read by
`plan_statuses`, whose one statement selects only `json_extract(step.value, '$.status')` over the newest plan
item's steps - never a step's words. Every statement this module runs is one of `STATEMENTS` below, which
advanced/tests/test_advanced_codex_reads.py holds to that.

v0.6.16-beta.3: a conversation Codex split (issue #30) is read as core reads it - every id its turns are recorded
under, in order, from core's own `turn_chain` (codex/history.py), and a later id's turn after every earlier id's
(codex/rollout.SPAN) - and a split id that finished a turn lately is named as its conversation (`owner_of`).

The file is found as core finds every Codex database (codex/paths.newest_generation): the newest generation, a
symbolic link never followed, the columns read required, opened read-only with query_only on and trusted_schema off
(B1). Anything that goes wrong is TurnsUnavailable, which every capability reads as "do nothing".
"""
from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import NamedTuple

from codex_auto_resume import failures
from codex_auto_resume.codex import LocalSource, SourceError
from codex_auto_resume.codex.values import _json
from codex_auto_resume.codex.paths import _safe_path, newest_generation
from codex_auto_resume.codex.rollout import SPAN
from codex_auto_resume.domain import ids, states

# The columns read, and the only ones (thread_items' item_json only through the plan statement's json_each).
TURN_COLUMNS = frozenset({"thread_id", "turn_id", "status", "error_json", "completed_at", "rollout_ordinal",
                          "final_agent_item_id", "started_at"})
ITEM_COLUMNS = frozenset({"thread_id", "turn_id", "item_type", "item_json", "rollout_ordinal"})
LATEST = ("SELECT turn_id, status, error_json IS NOT NULL AND error_json NOT IN ('', 'null'), completed_at, "
          "final_agent_item_id IS NOT NULL, rollout_ordinal, started_at FROM thread_turns WHERE thread_id=? "
          "ORDER BY rollout_ordinal DESC LIMIT 1")
KINDS = "SELECT item_type, count(*) FROM thread_items WHERE thread_id=? AND turn_id=? GROUP BY item_type"
RECENT = ("SELECT thread_id FROM thread_turns WHERE status='completed' AND completed_at >= ? "
          "GROUP BY thread_id ORDER BY max(completed_at) DESC LIMIT ?")
PLAN_ITEM_TYPE = "plan"
HAS_PLAN = "SELECT EXISTS(SELECT 1 FROM thread_items WHERE thread_id=? AND item_type=?)"
PLAN = ("SELECT json_extract(step.value, '$.status') FROM (SELECT item_json FROM thread_items WHERE thread_id=? "
        "AND item_type=? ORDER BY rollout_ordinal DESC LIMIT 1) AS newest, json_each(newest.item_json, '$.steps') "
        "AS step")
BETWEEN = "SELECT count(*) FROM thread_turns WHERE thread_id=? AND rollout_ordinal > ? AND rollout_ordinal < ?"
# v0.6.16-beta.3 (usage_wrap_up): the conversations whose latest turn is running - status words and ids only.
# v0.6.20 final: with each turn's start, so one begun before Windows last started is left out (states.ended_by_boot),
# newest first, so a crash leftover never crowds a live turn out of the limit.
RUNNING = ("SELECT t.thread_id, t.started_at FROM thread_turns t WHERE t.status='inProgress' AND NOT EXISTS (SELECT 1 "
           "FROM thread_turns n WHERE n.thread_id=t.thread_id AND n.rollout_ordinal > t.rollout_ordinal) "
           "ORDER BY t.started_at DESC LIMIT ?")
# v0.6.16-beta.4 (model_fallback): one failed turn's error, read only to be dropped to Codex's code at once (core's
# failures.shape - a tag of letters and digits, never a word of its message, B9).
ERROR = "SELECT error_json FROM thread_turns WHERE thread_id=? AND turn_id=?"
# v0.6.20 (power_after_tasks, Discussion #57): one turn's status by its id - a status word, never a word of the turn.
STATUS = "SELECT status FROM thread_turns WHERE thread_id=? AND turn_id=?"
STATEMENTS = (LATEST, KINDS, RECENT, HAS_PLAN, PLAN, BETWEEN, RUNNING, ERROR, STATUS)
# The statuses Codex writes a turn in; anything else reads "other".
TURN_STATUSES = frozenset({"completed", "failed", "interrupted", "inProgress"})
# A plan step's statuses as Codex writes them; anything else reads "unknown".
STEP_STATUSES = frozenset({"pending", "in_progress", "completed"})
UNKNOWN = "unknown"
# How many conversations `recent` names at most.
RECENT_LIMIT = 50
# A kind word as Codex spells one: letters, at most this long. Anything else is counted as "other".
KIND_MAX = 64


class TurnsUnavailable(RuntimeError):
    """The turn history could not be read as this reads it. A static reason only."""


class Turn(NamedTuple):
    turn_id: str
    status: str                 # completed, failed, interrupted, inProgress - or "other"
    errored: bool               # an error was recorded (its words are never read)
    completed_at: int | None
    final_agent: bool           # Codex recorded a final agent item
    ordinal: int
    kinds: dict                 # {item_type: count}, a kind of no shape this knows counted as "other"
    started_at: int | None = None   # when it began, in seconds (v0.6.22: steer_send's "this turn, never a later one")


def connect(home, kind, tables):
    """A read-only connection to the newest generation of core's `kind` database in the Codex home `home`, its
    `tables` ({name: columns}) required - or TurnsUnavailable."""
    root = _safe_path(Path(home))
    try:
        path = newest_generation(root, kind)
    except OSError:
        raise TurnsUnavailable("the Codex home cannot be listed") from None
    if path is None:
        raise TurnsUnavailable("no %s database" % kind)
    path = _safe_path(path)
    if path.parent != root:
        raise TurnsUnavailable("the database is outside the Codex home")
    connection = None
    try:
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3)
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        for table, columns in tables.items():
            found = {row[1] for row in connection.execute("PRAGMA table_info(%s)" % table)}
            if not columns <= found:
                raise TurnsUnavailable("the %s table has moved on" % table)
    except (sqlite3.Error, OSError, ValueError):
        if connection is not None:
            connection.close()
        raise TurnsUnavailable("the database cannot be read") from None
    except TurnsUnavailable:
        connection.close()
        raise
    return connection


def _kind(value) -> str:
    return value if isinstance(value, str) and 0 < len(value) <= KIND_MAX and value.isalpha() else "other"


def booted_of(paths):
    """When Windows last started, as the watcher's heartbeat records it (store.watcher_status's booted_at, the time core's
    power action reads, engine/freshness) - or None where it cannot be read (v0.6.20 final)."""
    try:
        from codex_auto_resume.store import Store
        with Store(paths.state_dir) as store:
            return (store.watcher_status() or {}).get("booted_at")
    except Exception:
        return None


class Turns:
    """The turn history of the Codex home `home`."""

    def __init__(self, home):
        self.home = home

    def _core(self, ask, *arguments):
        """`ask` of core's reader of this home (its split mapping, issue #30), or TurnsUnavailable. A home whose
        state database core does not read (none, or of a schema it refuses) maps nothing: ids are read as they are."""
        core = LocalSource(Path(self.home))
        try:
            core.resolve("state")
        except SourceError:
            return (arguments[0],) if ask == "turn_chain" else None
        try:
            return getattr(core, ask)(*arguments)
        except (SourceError, sqlite3.Error, OSError, ValueError):
            raise TurnsUnavailable("the conversation cannot be read") from None

    def _read(self, run):
        connection = connect(self.home, "history", {"thread_turns": TURN_COLUMNS, "thread_items": ITEM_COLUMNS})
        try:
            return run(connection)
        except (sqlite3.Error, OSError, ValueError):
            raise TurnsUnavailable("the turn history cannot be read") from None
        finally:
            connection.close()

    def latest(self, thread_id) -> Turn | None:
        """The latest turn of conversation `thread_id` and the kinds of item it left, or None where it has none."""
        if not ids.is_uuid(thread_id):
            raise TurnsUnavailable("not a conversation")

        chain = self._core("turn_chain", thread_id)

        def run(connection):
            for index in range(len(chain) - 1, -1, -1):     # the newest id with a turn has the latest one
                row = connection.execute(LATEST, (chain[index],)).fetchone()
                if row is not None:
                    break
            else:
                return None
            turn_id, status, errored, completed, final, ordinal, started = row
            if not ids.is_uuid(turn_id) or type(ordinal) is not int:
                raise TurnsUnavailable("a turn of no shape this knows")
            kinds = {}
            for kind, count in connection.execute(KINDS, (chain[index], turn_id)).fetchall():
                kinds[_kind(kind)] = kinds.get(_kind(kind), 0) + int(count)
            status = status if status in ("completed", "failed", "interrupted", "inProgress") else "other"
            completed = completed if type(completed) is int and completed > 0 else None
            started = started if states.epoch(started, *states.EPOCH_STORE) else None
            return Turn(turn_id, status, bool(errored), completed, bool(final), index * SPAN + ordinal, kinds, started)
        return self._read(run)

    def turn_code(self, thread_id, turn_id):
        """Codex's code for the error of turn `turn_id` (core's failures.shape: a known code, or one of its shape), or
        None - the error itself dropped at once, never kept or returned."""
        if not ids.is_uuid(thread_id) or not ids.is_uuid(turn_id):
            raise TurnsUnavailable("not a turn")

        def run(connection):
            row = connection.execute(ERROR, (thread_id, turn_id)).fetchone()
            return row[0] if row is not None else None
        raw = self._read(run)
        error = _json(raw) if isinstance(raw, str) else None
        info = error.get("codexErrorInfo") if isinstance(error, dict) else None
        return failures.shape(info)["code"]

    def status(self, thread_id, turn_id):
        """The status of turn `turn_id` of conversation `thread_id` - completed, failed, interrupted, inProgress or
        "other" - looked for under every id the conversation's turns are recorded under (a split, issue #30), or None
        where no such turn is recorded (v0.6.20, power_after_tasks)."""
        if not ids.is_uuid(thread_id) or not ids.is_uuid(turn_id):
            raise TurnsUnavailable("not a turn")
        chain = self._core("turn_chain", thread_id)

        def run(connection):
            for other in reversed(chain):
                row = connection.execute(STATUS, (other, turn_id)).fetchone()
                if row is not None:
                    return row[0] if row[0] in TURN_STATUSES else "other"
            return None
        return self._read(run)

    def recent(self, since) -> list:
        """The conversations with a turn completed at `since` or later (Codex's seconds), the latest first, at
        most RECENT_LIMIT - the candidates the edition looks at, never a list of every conversation."""
        return self._named(self._read(lambda connection: connection.execute(
            RECENT, (int(since), RECENT_LIMIT)).fetchall()))

    def _named(self, rows) -> list:
        """Each row's conversation, once: a split id's turns are its conversation's (issue #30, `owner_of`)."""
        found = []
        for row in rows:
            named = (self._core("owner_of", row[0]) or row[0]) if ids.is_uuid(row[0]) else None
            if named is not None and named not in found:
                found.append(named)
        return found

    def running(self, booted=None) -> list:
        """The conversations whose latest turn is running now, at most RECENT_LIMIT (v0.6.16-beta.3, the wrap-up's
        candidates): ids, never a word of any turn - a split id's named as its conversation (`_named`). v0.6.20 final: a
        latest turn begun before Windows last started (`booted`, the heartbeat's boot time, `booted_of`) is a crash's
        leftover and is not running (states.ended_by_boot, as core's activity reads it); with no boot time every one
        counts, as before."""
        rows = self._read(lambda connection: connection.execute(RUNNING, (RECENT_LIMIT,)).fetchall())
        return self._named([row for row in rows if not states.ended_by_boot(row[1], booted)])

    def between(self, thread_id, after, before) -> int:
        """How many turns of `thread_id` lie strictly between the turns at ordinals `after` and `before` - 0 where
        the second is the very next turn after the first (a chain, engine/emptyreply.py)."""
        if not ids.is_uuid(thread_id) or type(after) is not int or type(before) is not int:
            raise TurnsUnavailable("not a conversation")
        chain = self._core("turn_chain", thread_id)
        (first, low), (last, high) = divmod(after, SPAN), divmod(before, SPAN)
        if not first <= last < len(chain):
            raise TurnsUnavailable("a turn of no shape this knows")
        # Within one id, between the two ordinals; across a split, the rest of the first id, every id between and
        # the start of the last.
        spans = ([(chain[first], low, high)] if first == last else
                 [(chain[first], low, SPAN)] + [(other, -1, SPAN) for other in chain[first + 1:last]]
                 + [(chain[last], -1, high)])
        return int(self._read(lambda connection: sum(
            connection.execute(BETWEEN, span).fetchone()[0] for span in spans)))

    def plan_statuses(self, thread_id) -> tuple | None:
        """The statuses of the newest plan item's steps in `thread_id`, in order, each a STEP_STATUSES word or
        "unknown" - None where the conversation has no plan item. A plan item there whose steps cannot be read
        is TurnsUnavailable: what stops on a finished plan stops on an unreadable one too (fail closed)."""
        if not ids.is_uuid(thread_id):
            raise TurnsUnavailable("not a conversation")

        chain = self._core("turn_chain", thread_id)

        def run(connection):
            held = [other for other in chain if connection.execute(HAS_PLAN, (other, PLAN_ITEM_TYPE)).fetchone()[0]]
            if not held:
                return None
            statuses = tuple(row[0] if row[0] in STEP_STATUSES else UNKNOWN
                             for row in connection.execute(PLAN, (held[-1], PLAN_ITEM_TYPE)).fetchall())
            if not statuses:
                raise TurnsUnavailable("a plan item with no steps this reads")
            return statuses
        return self._read(run)
