"""The edition's plug's own work, claimed and guarded as core's is (v0.6.14).

What a plug answers and core carries out of its own is held to the same write lock as core's claims and
launches: P8's errand makes its one irrevocable write - a request to Codex - inside `errand_guard`, which
a Pause, Observe only or quiet hours that committed first refuse; and a record of the plug's own (P2) is
claimed in `reserve_record`, which reads consent and quiet hours again and asks the plug's ledger, and
launched inside `record_guard`, which reads consent again and asks the ledger once more. The standard
edition's plug answers none of it, so none of this runs there.
"""
from __future__ import annotations

from contextlib import contextmanager

from .. import machine
from ..domain.plug import Point, guard
from .validate import _timestamp, _uuid


class PlugClaimsMixin:
    @contextmanager
    def errand_guard(self, *, held=None):
        """The guard of P8's errand (v0.6.14): the one thing an errand of the edition's plug cannot take
        back - a request it makes of Codex - is made inside this, as the queue launch is made inside
        `submission_guard`. `permitted` is recovery on and not only observed, read under the store's
        write lock, and nothing `held` says: what the engine knows and the store does not - an
        administrator's DisableAutoResume, Observe only as the settings say it, quiet hours
        (engine/options.py, errand_held). A Pause that commits first refuses it; the errand waits for
        its answer outside, as the transport lets the launch guard go before its receipt."""
        with self._transaction() as connection:
            settings = self._read_settings(connection)
            permitted = bool(settings["enabled"] and not settings["observe_only"])
            if permitted and held is not None:
                permitted = not held()
            yield permitted

    def reserve_record(self, record: dict, now: float, *, ledger=None, quiet_until: float | None = None) -> tuple:
        """Claim the right to send a record of the edition's plug's own (P2, engine/plugrecords.py):
        (claimed, refusing gate, reason), as `reserve_detailed` answers for core's.

        Core holds no row for it, so nothing of core's is written: the claim is this transaction, in
        which consent is read again - recovery on, not only observed, the conversation on - and quiet
        hours, and nothing of core's may be queued in the conversation; then the plug's ledger is asked
        on this connection, told the record with `phase` "claim" and that the send carries RECORDS, and
        it claims the record in its own store there, counted against core's rows under this one lock
        (P11). Anything but DEFER, or a ledger that raised, holds it; the standard edition's plug, which
        holds no record, claims none."""
        _timestamp(now, "now")
        ledger = guard(ledger)
        if ledger.null:
            return False, "submission_safe", machine.HELD
        thread = _uuid(record["thread_id"], "thread_id")
        with self._transaction() as connection:
            settings = self._read_settings(connection)
            if not settings["enabled"]:
                return False, "consent", "paused"
            if settings["observe_only"]:
                return False, "consent", machine.OBSERVE_ONLY
            if not self._thread_enabled(connection, thread):
                return False, "consent", "thread_disabled"
            if quiet_until is not None:
                return False, "schedule", machine.QUIET_HOURS
            if self._others_in_flight(connection, thread, record["record_id"]):
                return False, "submission_safe", "other_recovery_in_flight"
            if self._ledger_holds(connection, ledger, dict(record, phase="claim"), now, frozenset({Point.RECORDS})):
                return False, "submission_safe", machine.HELD
            return True, None, None

    @contextmanager
    def record_guard(self, record: dict, ledger, now: float):
        """The launch guard of a record of the plug's own (P2): consent read under the store's write
        lock, as `submission_guard` reads it for core's, and the plug's ledger asked in the same
        transaction with `phase` "launch" - which writes when the launch began, in its own store, and
        holds it if the record is no longer the one it claimed. A Pause, Observe only or the
        conversation switched off that commits first stops the launch; the transport lets this go before
        it waits for a receipt."""
        ledger = guard(ledger)
        with self._transaction() as connection:
            settings = self._read_settings(connection)
            permitted = bool(not ledger.null and settings["enabled"] and not settings["observe_only"]
                             and self._thread_enabled(connection, record["thread_id"]))
            if permitted:
                permitted = not self._ledger_holds(connection, ledger, dict(record, phase="launch"), now,
                                                   frozenset({Point.RECORDS}))
            yield permitted
