"""Putting the state back for an older release: schema 4 for v0.6.11 to v0.6.14, schema 3 for
v0.6.0 to v0.6.10, schema 2 for v0.5.

It is asked for by hand (`codex-auto-resume downgrade-state --to 4`, `--to 3` or `--to 2`) and never done on
its own: the rows an older release cannot read are the ones it would misread, so they are left
behind rather than translated - and what an older release could act on wrongly is made into
something it will not act on at all.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3
import time

from .. import machine
from ..domain import ids
from .columns import _SCHEMA_4_COLUMNS, _SCHEMA_5_COLUMNS, _V2_COLUMNS
from .errors import StoreError
from .schema import MARK, SchemaMixin, _TABLES_V4, _TABLES_V5
from .validate import _validated_record


# What each schema-3 state means to a schema-2 reader. "resumed" meant "our message was
# delivered", which is true of every state a correlated turn can be in.
_DOWNGRADE_STATES = {
    "turn_started": "resumed", "turn_completed": "resumed", "recovered": "resumed",
    "completed_no_progress": "resumed", "recovery_turn_failed": "resumed",
    "stopped_by_user": "resumed", "outcome_unverified": "resumed",
    "handed_over": "superseded_by_user",
    "withdrawn_unconfirmed": "submission_unknown",
}

TARGETS = (2, 3, 4)

# Withdrawal reasons a schema-4 reader does not know (v0.6.15-beta), as the one it settles the same way.
_NEW_WITHDRAWALS = {"window_ended": "expired", "not_delivered_on_open": "not_loaded"}

# A withdrawal for Observe only (v0.6.11), as the Pause's v0.6.10 knows: the same promise, its words.
_OBSERVE_WITHDRAWALS = {"observe_only": "paused", "observe_only_unknown": "paused_unknown"}


def downgrade_state(state_dir: Path, target: int) -> dict:
    """Rewrite a newer state as schema `target`, for going back to an older release.

    The caller must hold the watcher's mutex. Every row is kept - cancelled, exhausted, unknown
    and hidden ones included - because those rows are what stop an old failure from being
    detected and recovered again, and disabled conversations stay disabled. Deleting the state
    instead would undo all of that, which is why this exists. A forensic copy is taken first; it
    is not a restore path. One transaction: the file is the old schema or the new, never between.

    Returns {"changed": False, "rows": None} for a state already at `target` or older, and
    otherwise what was done: "rows" kept, and - from schema 4 - what an older release could not
    have kept as it was (`_to_v3`).
    """
    if target not in TARGETS:
        raise StoreError("A state can be downgraded to schema 4, 3 or 2 only")
    path = Path(state_dir) / "state.sqlite"
    if Path(state_dir).is_symlink() or path.is_symlink() or not path.is_file():
        raise StoreError("Cannot open valid auto-resume state")
    connection = sqlite3.connect(path, timeout=10, isolation_level=None)
    try:
        connection.execute("PRAGMA trusted_schema=OFF")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version in range(1, target + 1):
            return {"changed": False, "rows": None}
        # Literals, never SCHEMA_VERSION: each step reads one schema and writes the one before.
        if version not in (3, 4, 5):
            raise StoreError("Only a schema-5, schema-4 or schema-3 state can be downgraded")
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        connection.execute("VACUUM INTO ?", (str(Path(state_dir) / ("state.v%d-backup-%s.sqlite"
                                                                    % (version, stamp))),))
        connection.execute("BEGIN IMMEDIATE")
        try:
            if connection.execute("PRAGMA user_version").fetchone()[0] != version:
                raise StoreError("The state changed while it was being downgraded")
            report = {"changed": True}
            now = time.time()
            if version == 5:
                report.update(_to_v4(connection, now))
            if version in (4, 5) and target <= 3:
                fours = report.get("made_final", 0)
                report.update(_to_v3(connection, now))
                report["made_final"] += fours
            if target == 2:
                report["rows"] = _to_v2(connection)
            else:
                report["rows"] = connection.execute("SELECT count(*) FROM interruptions").fetchone()[0]
            connection.execute("PRAGMA user_version=%d" % target)
            # The readable-from mark (schema.READABLE_FROM, v0.6.18) taken off with the schema it named: the state is
            # an older release's now, readable from its own version alone, as every state that release wrote.
            if connection.execute("PRAGMA application_id").fetchone()[0] & 0xFFFF0000 == MARK:
                connection.execute("PRAGMA application_id=0")
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        return report
    except sqlite3.Error as exc:
        raise StoreError("The state could not be downgraded") from exc
    finally:
        connection.close()


def downgrade_to_v3(state_dir: Path) -> dict:
    """For going back to a v0.6.0 to v0.6.10 release."""
    return downgrade_state(state_dir, 3)


def downgrade_to_v2(state_dir: Path) -> dict:
    """For going back to a v0.5 release."""
    return downgrade_state(state_dir, 2)


def _to_v4(connection, now: float) -> dict:
    """Schema 5 as schema 4, inside the caller's transaction (for v0.6.11 to v0.6.14).

    An older release watches one Codex home and reads every record as that home's. So:

    * It is refused while a record of another home may be in Codex's queue (machine.WATCHED): the
      older release could neither find nor take back what is queued in a home it does not watch.
    * Every record of another home is kept - a failure already recovered stays known, so going back
      and coming forward again never recovers it a second time (A23) - and none is left for the older
      release to act on: a waiting one is made final, cancelled (home_not_watched), and one whose
      recovery turn runs ends unverified (E6). Its terminal ones stay as they are.
    * A withdrawal reason the older release does not know is written as the one it settles the same way.
    """
    if {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")} != _TABLES_V5:
        raise StoreError("Unsupported or malformed state schema")
    watched = tuple(sorted(machine.WATCHED))
    if connection.execute("SELECT count(*) FROM interruptions WHERE home_key<>'' AND state IN (%s)"
                          % ",".join("?" for _ in watched), watched).fetchone()[0]:
        raise StoreError("A continuation sent to another Codex home may still be in its queue; "
                         "let it settle first")
    extra = connection.execute("SELECT count(*) FROM interruptions WHERE home_key<>''").fetchone()[0]
    report = {"made_final": 0, **({"extra_home_rows": extra} if extra else {})}
    waiting, observing = tuple(sorted(machine.WAITING)), tuple(sorted(machine.OBSERVING))
    report["made_final"] += connection.execute(
        "UPDATE interruptions SET state='cancelled', last_error='home_not_watched', cancel_requested=1, "
        "outcome_at=? WHERE home_key<>'' AND state IN (%s)" % ",".join("?" for _ in waiting),
        (now,) + waiting).rowcount
    report["made_final"] += connection.execute(
        "UPDATE interruptions SET state='outcome_unverified', outcome_at=? WHERE home_key<>'' AND state IN (%s)"
        % ",".join("?" for _ in observing), (now,) + observing).rowcount
    for new, old in sorted(_NEW_WITHDRAWALS.items()):
        connection.execute("UPDATE interruptions SET withdraw_reason=? WHERE withdraw_reason=?", (old, new))
    for table, name, _definition in reversed(_SCHEMA_5_COLUMNS):
        connection.execute("ALTER TABLE %s DROP COLUMN %s" % (table, name))
    connection.execute("PRAGMA user_version=4")
    return report


def _to_v3(connection, now: float) -> dict:
    """Schema 4 as schema 3, inside the caller's transaction. What v0.6.10 cannot keep is made
    into what it keeps and will not act on; nothing is made into anything that sends more.

    * A short marker (v0.6.11) is one v0.6.10's store refuses to open and its history reader
      never finds, so every record gets the marker of its whole id - true of a continuation never
      sent, which is all a waiting record is. A continuation that went out, or may have, with the
      short marker would never be found again, so it is made final: an uncertain submission,
      never sent again (A6), or an unverified outcome (E6) for one whose turn had started.
    * And one not yet followed to the turn it started (machine.WATCHED) switches its conversation
      off. v0.6.10 knows a turn for a continuation's only by the record's turn id or by finding
      its marker in it, and has neither, so when Codex delivers it and that turn fails, the failure
      would be a new task: a cancel before the downgrade forgotten, the budgets started again (A23),
      and nothing left to take the queued message back. With the conversation off v0.6.10 detects
      nothing there and sends nothing until a person switches it back on.
    * Observe-only becomes a Pause: v0.6.10 has no way to watch without sending but that one. So
      does a continuation taken back for it: its withdrawal reads as a Pause's, which v0.6.10
      settles the same way - back to waiting once nothing ran, final over an uncertain submission.
    * A hold on a waiting record, and a conversation's tier other than automatic, switch that
      conversation off: v0.6.10 asks nobody first, and turning it back on is a person's act,
      as releasing a hold is. Its waiting records stay as they are, never cancelled.
    * A postponement becomes the record's schedule, which only ever makes it later.
    * The notices go: v0.6.10 raises no needs-you notice and reads none.
    """
    if {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")} != _TABLES_V4:
        raise StoreError("Unsupported or malformed state schema")
    report = {"short_markers": 0, "made_final": 0, "postponed": 0, "conversations_off": 0,
              "unfollowed_off": 0, "observe_only_paused": False}
    connection.row_factory = sqlite3.Row
    try:
        # Schema 4's rows, read as this release reads every row: of the default home, which they all are now.
        rows = [_validated_record(dict(row, home_key="")) for row in connection.execute("SELECT * FROM interruptions")]
    finally:
        connection.row_factory = None
    held, unfollowed = set(), set()
    for row in rows:
        key, state, changes = row["interruption_id"], row["state"], {}
        if row["marker"] != ids.marker(key):
            report["short_markers"] += 1
            changes["marker"] = ids.marker(key)
            if state in machine.WATCHED:
                unfollowed.add(row["thread_id"])
            if state in machine.CLAIMED | machine.IN_FLIGHT:
                changes.update(state="submission_unknown", queue_id=None,
                               last_error="queue_result_unknown_do_not_resend")
            elif state in machine.OBSERVING:
                changes.update(state="outcome_unverified", outcome_at=now)
            elif state == "submission_unknown":
                changes["queue_id"] = None
            if "state" in changes:
                report["made_final"] += 1
        observed = _OBSERVE_WITHDRAWALS.get(row["withdraw_reason"])
        if observed is not None:
            changes["withdraw_reason"] = observed
            if row["last_error"] in _OBSERVE_WITHDRAWALS and "last_error" not in changes:
                changes["last_error"] = _OBSERVE_WITHDRAWALS[row["last_error"]]
        if state in machine.WAITING:
            if row["not_before"] is not None and row["not_before"] > row["next_retry_at"]:
                changes["next_retry_at"] = row["not_before"]
                report["postponed"] += 1
            if row["hold"] is not None:
                held.add(row["thread_id"])
        if changes:
            columns = sorted(changes)
            connection.execute("UPDATE interruptions SET %s WHERE interruption_id=?"
                               % ", ".join("%s=?" % name for name in columns),
                               tuple(changes[name] for name in columns) + (key,))
    held |= {row[0] for row in connection.execute(
        "SELECT thread_id FROM threads WHERE tier IS NOT NULL AND tier<>'automatic'")}
    for thread in sorted(held | unfollowed):
        connection.execute("INSERT INTO threads (thread_id, enabled) VALUES (?,0) "
                           "ON CONFLICT(thread_id) DO UPDATE SET enabled=0", (thread,))
    report["conversations_off"], report["unfollowed_off"] = len(held), len(unfollowed)
    if connection.execute("SELECT observe_only FROM settings WHERE singleton=1").fetchone()[0]:
        connection.execute("UPDATE settings SET enabled=0 WHERE singleton=1")
        report["observe_only_paused"] = True
    connection.execute("DROP TABLE notices")
    # Each column schema 4 added, taken off its table the way it was put on: none is indexed or
    # named by another, so the table is left exactly as schema 3 made it.
    for table, name, _definition in reversed(_SCHEMA_4_COLUMNS):
        connection.execute("ALTER TABLE %s DROP COLUMN %s" % (table, name))
    connection.execute("PRAGMA user_version=3")
    return report


def _to_v2(connection) -> int:
    """Schema 3 as schema 2, inside the caller's transaction. Returns the rows kept."""
    mapping = " ".join("WHEN '%s' THEN '%s'" % item for item in sorted(_DOWNGRADE_STATES.items()))
    columns = ",".join(_V2_COLUMNS)
    selected = ",".join("CASE state %s ELSE state END" % mapping if name == "state" else name
                        for name in _V2_COLUMNS)
    SchemaMixin._create_interruptions_named(connection, "interruptions_v2")
    connection.execute("INSERT INTO interruptions_v2 (%s) SELECT %s FROM interruptions"
                       % (columns, selected))
    rows = connection.execute("SELECT count(*) FROM interruptions_v2").fetchone()[0]
    connection.execute("DROP TABLE interruptions")
    connection.execute("DROP TABLE events")
    connection.execute("DROP TABLE watcher_status")
    connection.execute("ALTER TABLE interruptions_v2 RENAME TO interruptions")
    connection.execute("CREATE INDEX interruptions_thread ON interruptions(thread_id)")
    v2 = tuple(sorted(machine.V2_STATES))
    if connection.execute("SELECT count(*) FROM interruptions WHERE state NOT IN (%s)"
                          % ",".join("?" for _ in v2), v2).fetchone()[0]:
        raise StoreError("A state has no schema-2 meaning")
    connection.execute("PRAGMA user_version=2")
    return rows
