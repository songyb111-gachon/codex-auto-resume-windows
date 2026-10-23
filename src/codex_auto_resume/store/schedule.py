"""A record made later, held for a person and let go (schema 4, v0.6.11).

A person's postponement, the objection window the engine opens before a first send, and a hold:
each only ever keeps a record back. The one write here that brings a record sooner is a person's
Don't postpone, and it goes back no further than what the schedule says without that person's
postponement - never past an objection window, a retry's wait or a usage reset (`unpostpone`).
Out of store/actions.py at its 300 lines. And (v0.6.19, issue #50) a usage reading a person's Retry now asks for, which
lifts a usage reset only where Codex's reading says the limit has lifted (A12, amended by the owner on 2026-10-24).
"""
from __future__ import annotations

from .. import quiet
from ..domain import ids
from ..machine import IN_FLIGHT, OBSERVING, TERMINAL, WAITING, own_postponement
from .validate import _timestamp, _uuid


# v0.6.19 (issue #50; A12 amended by the owner on 2026-10-24): a person's Retry now on a recovery that waits for a usage
# reset asks the watcher to read usage once, at that moment. The request is a file named by the record's opaque id in this
# folder beside the state - written by the click, taken by the watcher when it looks - so the store's tables are as they
# were. What the reading said is journalled (USAGE_CHECKED), never an input to a decision.
USAGE_CHECKS = "usage-checks"
# What a reading said, as the journal keeps it: the limit lifted, still limited, or nothing could be told.
USAGE_READ_AVAILABLE, USAGE_READ_LIMITED, USAGE_READ_UNKNOWN = "usage_available", "usage_unavailable", "usage_unknown"
USAGE_READS = (USAGE_READ_AVAILABLE, USAGE_READ_LIMITED, USAGE_READ_UNKNOWN)
# A request no watcher took within a day is dropped: a check is asked for now, not for whenever.
USAGE_CHECK_LONGEST = 86400


class ScheduleMixin:
    @staticmethod
    def _not_waiting(row) -> str:
        """Why a record that is not waiting cannot be made to wait longer, in the retry's words."""
        state = row["state"]
        return ("finished" if state in TERMINAL else "observing" if state in OBSERVING
                else "in_flight" if state in IN_FLIGHT else "claimed")

    def _bound(self, connection, interruption_id: str, thread_id: str):
        """The record a row's action names, and why it cannot be acted on - (row, None) or
        (row or None, detail). Bound to both identities, as a person's switch is: a record that
        is gone, or belongs to another conversation, is refused and nothing changes."""
        row = self._row(connection, interruption_id)
        if row is None:
            return None, "unknown_record"
        if row["thread_id"] != thread_id:
            return row, "thread_mismatch"
        if row["state"] in TERMINAL:
            return row, "finished"
        if row["cancel_requested"]:
            return row, "cancel_requested"
        return row, None

    def postpone(self, interruption_id: str, thread_id: str, until, now: float, *,
                 actor: str = "gui") -> tuple:
        """Wait until `until` at the earliest (schema 4). Returns (accepted, detail).

        A person's, for one exact record, and only ever later: a time that is not later than now
        and than the postponement the record already has, or more than a week ahead, is refused
        (quiet.postponement_problem). Only a record still waiting can wait longer. It writes the
        time and nothing else - no gate is skipped, nothing is sent, the schedule it had still
        holds (domain/gates.py, gate_schedule) - and on acceptance `detail` is the time."""
        _uuid(thread_id, "thread_id")
        _timestamp(now, "now")
        with self._transaction() as connection:
            row, problem = self._bound(connection, interruption_id, thread_id)
            if problem is not None:
                return False, problem
            if row["state"] not in WAITING:
                return False, self._not_waiting(row)
            problem = quiet.postponement_problem(until, now, row["not_before"])
            if problem is not None:
                return False, problem
            connection.execute("UPDATE interruptions SET not_before=? WHERE interruption_id=?",
                               (float(until), interruption_id))
            self._event(connection, now, "postponed", record=row, from_state=row["state"],
                        to_state=row["state"], actor=actor, value=float(until))
            return True, float(until)

    def unpostpone(self, interruption_id: str, thread_id: str, now: float, *,
                   actor: str = "gui") -> tuple:
        """Take a person's postponement away (v0.6.11, Don't postpone). Returns (accepted, detail).

        Bound to both identities, for a record still waiting whose `not_before` is a person's and
        still ahead. It goes back to what the schedule says without it - the end of an objection
        window still ahead, or nothing - and to nothing sooner: the retry's wait, a usage reset and
        quiet hours are left as they are, every gate still runs and nothing is sent now. On
        acceptance `detail` is the `not_before` it leaves, or None."""
        _uuid(thread_id, "thread_id")
        _timestamp(now, "now")
        with self._transaction() as connection:
            row, problem = self._bound(connection, interruption_id, thread_id)
            if problem is not None:
                return False, problem
            if row["state"] not in WAITING:
                return False, self._not_waiting(row)
            if own_postponement(row, now) is None:
                return False, "not_postponed"
            window = row["objection_until"]
            left = window if window is not None and window > now else None
            connection.execute("UPDATE interruptions SET not_before=? WHERE interruption_id=?",
                               (left, interruption_id))
            self._event(connection, now, "unpostponed", record=row, from_state=row["state"],
                        to_state=row["state"], actor=actor, value=left)
            return True, left

    def open_objection_window(self, interruption_id: str, until: float, now: float) -> bool:
        """The engine's: an objection-window tier's minutes before a record's first send.

        Opened once (`objection_at`, and its end `objection_until`), and only while the record
        waits unsent - also after a postponement a person made before it, which only ever held the
        record back and never took the window's place. It is written as a postponement to `until`,
        or kept at a later one a person chose in the meantime, so every check that asks about a
        postponement asks about it too. False when it was not opened."""
        _timestamp(now, "now")
        _timestamp(until, "until")
        with self._transaction() as connection:
            row = self._row(connection, interruption_id)
            if (row is None or row["state"] not in WAITING or row["objection_at"] is not None
                    or row["submitted_at"] is not None or until <= now):
                return False
            later = max(until, row["not_before"] or 0)
            connection.execute("UPDATE interruptions SET not_before=?, objection_at=?, objection_until=? "
                               "WHERE interruption_id=?", (later, now, until, interruption_id))
            self._event(connection, now, "postponed", record=row, from_state=row["state"],
                        to_state=row["state"], value=later)
            return True

    def release_hold(self, interruption_id: str, thread_id: str, now: float, *,
                     actor: str = "gui") -> tuple:
        """Let one held record continue (schema 4). Returns (released, detail).

        Bound to both identities, as a person's switch is. It takes the hold away and nothing
        else: every gate still runs, nothing is sent now, and a postponement or quiet hours still
        hold. A record that is not held, finished, cancelled or another conversation's is refused
        and nothing changes. On acceptance `detail` is the record's state."""
        _uuid(thread_id, "thread_id")
        _timestamp(now, "now")
        with self._transaction() as connection:
            row, problem = self._bound(connection, interruption_id, thread_id)
            if problem is not None:
                return False, problem
            if row["hold"] is None:
                return False, "not_held"
            connection.execute("UPDATE interruptions SET hold=NULL WHERE interruption_id=?",
                               (interruption_id,))
            self._event(connection, now, "hold_released", record=row, from_state=row["state"],
                        to_state=row["state"], actor=actor)
            return True, row["state"]

    # ------------------------------------------------------------ a person's usage check (v0.6.19)
    def _usage_checks(self):
        folder = self.state_dir / USAGE_CHECKS
        if folder.is_symlink():
            raise OSError("the usage checks' folder is a symbolic link")
        return folder

    def ask_usage_check(self, interruption_id: str) -> bool:
        """A person's Retry now asks the watcher to read usage once for this record (USAGE_CHECKS). False where it
        could not be asked - an id of no shape, or a folder that cannot be written."""
        if not ids.is_interruption_id(interruption_id):
            return False
        try:
            folder = self._usage_checks()
            folder.mkdir(exist_ok=True)
            (folder / interruption_id).write_bytes(b"")
            return True
        except OSError:
            return False

    def usage_checks_asked(self, now: float) -> set:
        """The records a person asked to have usage read for and no watcher took yet: their ids. A request older than a
        day is dropped, and anything in the folder that is not exactly an id is left alone and not read."""
        found = set()
        try:
            folder = self._usage_checks()
            entries = list(folder.iterdir()) if folder.is_dir() else []
        except OSError:
            return found
        for entry in entries:
            if not ids.is_interruption_id(entry.name) or entry.is_symlink():
                continue
            try:
                if now - entry.stat().st_mtime > USAGE_CHECK_LONGEST:
                    entry.unlink()
                    continue
            except OSError:
                continue
            found.add(entry.name)
        return found

    def usage_check_taken(self, interruption_id: str) -> None:
        """The request for this record taken: whatever its reading says, it is asked once."""
        if not ids.is_interruption_id(interruption_id):
            return
        try:
            (self._usage_checks() / interruption_id).unlink(missing_ok=True)
        except OSError:
            pass

    def usage_checked(self, interruption_id: str, now: float, read: str) -> dict | None:
        """What a reading taken at a person's request said of a record that waits for a usage reset, written in one
        transaction: journalled as USAGE_CHECKED with the word it read (none for available, so the journal's reasons
        stay the closed list the public reporter reads); and only where it says usage is available and
        the record still waits unsent for a reset ahead, that reset replaced by the newer one Codex's reading shows -
        now - and its next look brought to now, so it goes on through every gate as usual (A12, amended by the owner on
        2026-10-24). Still limited or unknown changes nothing. The record as it stands after, or None where it moved."""
        _timestamp(now, "now")
        read = read if read in USAGE_READS else USAGE_READ_UNKNOWN
        with self._transaction() as connection:
            row = self._row(connection, interruption_id)
            if row is None or row["cancel_requested"] or row["state"] not in WAITING:
                return None
            lifted = (read == USAGE_READ_AVAILABLE and row["reset_at"] is not None and row["reset_at"] > now
                      and row["submitted_at"] is None)
            if lifted:
                connection.execute("UPDATE interruptions SET reset_at=?, next_retry_at=? WHERE interruption_id=?",
                                   (now, now, interruption_id))
            self._event(connection, now, "usage_checked", record=row, from_state=row["state"], to_state=row["state"],
                        reason=None if read == USAGE_READ_AVAILABLE else read, actor="engine", flags=1 if lifted else 0,
                        value=row["reset_at"])
            return self._row(connection, interruption_id)
