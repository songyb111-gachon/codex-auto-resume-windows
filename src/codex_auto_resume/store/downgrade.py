"""Putting the state back to v2, for somebody going back to an older release.

It is asked for by hand (`codex-auto-resume downgrade-state`) and never done on its own: the
rows an older release cannot read are the ones it would misread, so they are left behind
rather than translated.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3
import time

from .. import machine
from .columns import _V2_COLUMNS
from .errors import StoreError
from .schema import SCHEMA_VERSION, SchemaMixin


# What each schema-3 state means to a schema-2 reader. "resumed" meant "our message was
# delivered", which is true of every state a correlated turn can be in.
_DOWNGRADE_STATES = {
    "turn_started": "resumed", "turn_completed": "resumed", "recovered": "resumed",
    "completed_no_progress": "resumed", "recovery_turn_failed": "resumed",
    "stopped_by_user": "resumed", "outcome_unverified": "resumed",
    "handed_over": "superseded_by_user",
    "withdrawn_unconfirmed": "submission_unknown",
}


def downgrade_to_v2(state_dir: Path) -> dict:
    """Rewrite a schema-3 state as schema 2, for going back to a v0.5 release.

    The caller must hold the watcher's mutex. Every row is kept - cancelled, exhausted,
    unknown and hidden ones included - because those rows are what stop an old failure
    from being detected and recovered again, and disabled conversations stay disabled.
    Deleting the state instead would undo all of that, which is why this exists. A
    forensic copy is taken first; it is not a restore path.
    """
    path = Path(state_dir) / "state.sqlite"
    if Path(state_dir).is_symlink() or path.is_symlink() or not path.is_file():
        raise StoreError("Cannot open valid auto-resume state")
    connection = sqlite3.connect(path, timeout=10, isolation_level=None)
    try:
        connection.execute("PRAGMA trusted_schema=OFF")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version == 2:
            return {"changed": False, "rows": None}
        if version != SCHEMA_VERSION:
            raise StoreError("Only a schema-3 state can be downgraded")
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        connection.execute("VACUUM INTO ?", (str(Path(state_dir) / ("state.v3-backup-%s.sqlite" % stamp)),))
        mapping = " ".join("WHEN '%s' THEN '%s'" % item for item in sorted(_DOWNGRADE_STATES.items()))
        columns = ",".join(_V2_COLUMNS)
        selected = ",".join("CASE state %s ELSE state END" % mapping if name == "state" else name
                            for name in _V2_COLUMNS)
        connection.execute("BEGIN IMMEDIATE")
        try:
            if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                raise StoreError("The state changed while it was being downgraded")
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
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        return {"changed": True, "rows": rows}
    except sqlite3.Error as exc:
        raise StoreError("The state could not be downgraded") from exc
    finally:
        connection.close()
