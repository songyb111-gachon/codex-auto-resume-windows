# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""P11: the one claim, counted across both editions' records and paid for before it is granted.

Core asks the plug's ledger last, inside `reserve_detailed`'s BEGIN IMMEDIATE and on its
connection, once every check of core's own has passed (store/claims.py). The ledger ATTACHes
advanced.sqlite to that connection there, so everything below is read and written under the one
lock the claim already holds, and commits with the claim or not at all - core takes back what it
wrote with a savepoint when it holds, or raises.

Two things are decided:

* The caps on one conversation, counted across both tables. Core allows one continuation in
  flight per conversation, five claims in 24 hours and fifteen minutes between them, and counts
  them in its own rows. This edition's records are claims too, so the claim is held when one of
  them is in flight on the conversation, or when they make the difference to the five or the
  fifteen minutes. With no record of this edition's on the conversation it holds nothing, so an
  installation with nothing on claims exactly what the standard edition claims.
* Spend before send. Each armed capability whose answer this dispatch carries - its words, its
  channel - pays one unit here, in the spend ledger, before the claim that leads to the send is
  granted. No unit left under its own ceilings or the global one, or a capability turned off
  since it answered, and the claim is held: a disarm always wins, and a ceiling is never passed.

* A person's Send now (v0.6.14), SEND_NOW at P7: only with that capability's request of this very
  record, unused, under fifteen minutes old and made since the capability last stood where it stands
  (control/sendnow.py), which the claim uses - one click, one claim.
* A resend (v0.6.14), RESEND at P7: only one per standard record, by any capability - no RESEND_ONCE
  of it yet, and one written now, open for the sweep's duplicate watch (arming.py); and, for one paid
  by a capability that does not resend itself, only while it is kept on with Send again in the row
  this claim reads - not in the runtime's few seconds old states - so Send again turned off after P7
  answered sends nothing.

HOLD is all this can say. It never grants anything core would refuse.
"""
from __future__ import annotations

from codex_auto_resume.domain.plug import DEFER, Alternative

from .registry import CORE_COOLDOWN_SECONDS, CORE_DAILY_CAP
from .control.sendnow import fresh
from .state import ATTACHED
from .vocabulary import ArmingState, Ceiling, KeepOn, OverrideKind, RecordState

DAY = 86400


def ceiling_reached(counts, definition, global_hourly):
    """The ceiling that leaves `definition` no unit, or None. The global one first: it is the
    one a person set."""
    if counts["global_hour"] >= global_hourly:
        return Ceiling.GLOBAL_HOUR
    if counts["capability_day"] >= definition.ceilings.per_day:
        return Ceiling.CAPABILITY_DAY
    if counts["conversation_day"] >= definition.ceilings.per_conversation:
        return Ceiling.CONVERSATION_DAY
    return None


def held_by_records(connection, thread_id, now) -> bool:
    """Whether this edition's records on `thread_id` hold a claim core's own rows allow."""
    row = connection.execute(
        "SELECT coalesce(sum(state=?), 0), "
        "coalesce(sum(CASE WHEN claimed_at > ? THEN max(claims, 1) ELSE 0 END), 0), "
        "max(claimed_at) FROM %s.records WHERE thread_id=?" % ATTACHED,
        (RecordState.IN_FLIGHT, now - DAY, thread_id)).fetchone()
    in_flight, recent, last = row[0], row[1], row[2]
    if in_flight:
        return True
    if recent:
        # Core's count, as core counts it (store/claims.py, recent_claim_count), on the same
        # connection and so under the same lock.
        core = connection.execute(
            "SELECT coalesce(sum(max(attempt_count, 1)), 0) FROM main.interruptions "
            "WHERE thread_id=? AND coalesce(submitted_at, last_claim_at) > ?",
            (thread_id, now - DAY)).fetchone()[0]
        if core + recent >= CORE_DAILY_CAP:
            return True
    return last is not None and now - last < CORE_COOLDOWN_SECONDS


class ClaimLedger:
    def __init__(self, state):
        self.state = state
        self.registry = state.registry

    def claim(self, connection, record, now, acted=()) -> object:
        """HOLD or DEFER for one claim of core's. `acted` is the capabilities whose answers the
        dispatch that claims it carries: {capability: the words it answered}, or a set of them, which
        answered no word."""
        acted = acted if isinstance(acted, dict) else {capability: frozenset() for capability in acted}
        if not isinstance(record, dict) or not self.state.attach(connection):
            # No advanced state, so no record and no spend: nothing to count. An answer that was
            # taken cannot be paid for without one, and is not sent.
            return Alternative.HOLD if acted else DEFER
        thread_id, key = record.get("thread_id"), record.get("interruption_id")
        if held_by_records(connection, thread_id, now):
            return Alternative.HOLD
        if not acted:
            return DEFER
        global_hourly = connection.execute("SELECT global_hourly FROM %s.meta" % ATTACHED).fetchone()[0]
        for capability in sorted(acted):
            definition = self.registry.get(capability)
            row = connection.execute("SELECT state, since FROM %s.arming WHERE capability=?" % ATTACHED,
                                     (capability,)).fetchone()
            if definition is None or row is None or row[0] != ArmingState.ARMED:
                return Alternative.HOLD
            counts = self.state.counts(connection, ATTACHED, capability, thread_id, now)
            if ceiling_reached(counts, definition, global_hourly) is not None:
                return Alternative.HOLD
            if Alternative.RESEND in acted[capability] and not self._resend(connection, definition, key, now):
                return Alternative.HOLD
            if Alternative.SEND_NOW in acted[capability] and not self._sent_now(connection, capability, key, row[1], now):
                return Alternative.HOLD
            self.state.record_spend(connection, ATTACHED, capability, thread_id, key, now)
        return DEFER

    @staticmethod
    def _sent_now(connection, capability, key, since, now) -> bool:
        """Whether a person's Send now of standard record `key` stands for this claim, used if so: the
        capability's FORCE_ONCE of it, unused, fresh and made since `since` (control/sendnow.fresh)."""
        found = connection.execute("SELECT kind, created_at, used_at FROM %s.overrides WHERE interruption_id=? "
                                   "AND capability=?" % ATTACHED, (key, capability)).fetchone()
        if found is None or not fresh({"kind": found[0], "created_at": found[1], "used_at": found[2]}, since, now):
            return False
        connection.execute("UPDATE %s.overrides SET used_at=? WHERE interruption_id=? AND capability=?" % ATTACHED,
                           (now, key, capability))
        return True

    @staticmethod
    def _resend(connection, definition, key, now) -> bool:
        """Whether `definition` may pay for sending standard record `key` once more, written if so: no
        resend of it by any capability yet; for one that does not resend itself, Keep on and Send again
        both in its row now. The resend's RESEND_ONCE is written in the claim, open."""
        if not definition.resends:
            kept = {row[0] for row in connection.execute(
                "SELECT choice FROM %s.options WHERE capability=?" % ATTACHED, (definition.id,))}
            if not {str(KeepOn.KEEP_ON), str(KeepOn.SEND_AGAIN)} <= kept:
                return False
        if connection.execute("SELECT 1 FROM %s.overrides WHERE interruption_id=? AND kind=?" % ATTACHED,
                              (key, OverrideKind.RESEND_ONCE)).fetchone() is not None:
            return False
        connection.execute("INSERT OR REPLACE INTO %s.overrides (interruption_id, capability, kind, created_at, "
                           "used_at) VALUES (?,?,?,?,NULL)" % ATTACHED,
                           (key, definition.id, OverrideKind.RESEND_ONCE, now))
        return True
