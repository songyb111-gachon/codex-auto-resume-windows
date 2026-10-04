"""The recovery state machine: the stored states, the legal moves between them, and
what each one means to a person.

Everything here is a pure function of values that are already in our own store. No
Codex database is read, no settings file is opened and no clock is consulted, so the
answer a user interface shows for a record is the answer every other interface shows
for the same row.

Three layers, kept apart on purpose:

* **Stored states** are the engine's working vocabulary. They are precise about what
  the engine knows - "a send may be in progress", "the turn is running" - and they are
  the only thing the store validates.
* **Public codes** are what a person is told. They are stable, they never depend on a
  setting, and several stored states can share one.
* **Overlays** are facts about the surroundings - recovery is paused, the watcher is
  not running - that change what a waiting record will do next without changing what
  it is. They never apply to a record that may already have been sent.
Since v0.6.10-alpha this is the front, and the three layers above are three files:

    domain/states.py   the stored states and the legal moves between them
    domain/gates.py    what is checked before anything is sent, and the stored vector
    domain/public.py   the public codes and the overlays, as every interface shows them

Which is what "kept apart on purpose" had always said, said in the tree rather than in a
comment: one 416-line module was three of the eight parts `docs/ROADMAP.md` says the Rust core
is built from, and `tests/test_stack.py` is what holds it to being three. Everything is
re-exported here, so nothing that imports `machine` changes.
"""
from __future__ import annotations

from .domain.gates import (BLOCK, GATE_REASONS, GATE_RESULTS, GATES, HELD, NOT_CHECKED,
                           OBSERVE_ONLY, PASS, PLUGGED, POSTPONED, QUIET_HOURS, RESEND, RESENDABLE,
                           UNKNOWN, WAIT, birth_stop, counted_from, decode_gates, encode_gates,
                           first_refusal, gate, gate_budgets, gate_consent, gate_schedule,
                           gate_submission_safe, inherited, over_ceiling, resend_candidate,
                           waited_aside, was_resent, would_send_at)
from .domain.public import (ACTORS, EVENT_CODES, FLAG_AFTER_USER_WORK, FLAG_LEGACY,
                            FLAG_USER_JOINED, FLAG_WITHDRAW_DELETED, HOLDS, IMPORTANCE_TIERS,
                            OVERLAYS, PAGES,
                            PUBLIC_CODES, REASONS, RELEASABLE_WITHDRAWALS, SUPERSEDE_WITHDRAWALS,
                            TURN_STATUSES, WAITING_CODES, WITHDRAW_REASONS, actor_code, describe,
                            eligible_at, event_code, hold_for_tier, overlays, own_postponement,
                            public_code, public_reason, reason_code,
                            turn_status)
from .domain.states import (CLAIMED, EPOCH_CODEX, EPOCH_STORE, EPOCH_USAGE, EXHAUSTED,
                            IN_FLIGHT, OBSERVING, OUTCOMES, PLAIN_MOVES, POSSIBLY_SENT, STATES,
                            TERMINAL, V2_STATES, WAITING, WATCHED, epoch, may_be_queued,
                            plain_move_allowed, still_followed, waiting_state)

__all__ = ["ACTORS", "BLOCK", "CLAIMED", "EPOCH_CODEX", "EPOCH_STORE", "EPOCH_USAGE", "EVENT_CODES",
           "EXHAUSTED", "FLAG_AFTER_USER_WORK", "FLAG_LEGACY", "FLAG_USER_JOINED",
           "FLAG_WITHDRAW_DELETED", "GATES", "GATE_REASONS", "GATE_RESULTS", "HELD", "HOLDS",
           "IMPORTANCE_TIERS", "IN_FLIGHT", "NOT_CHECKED", "OBSERVE_ONLY", "OBSERVING", "OUTCOMES",
           "OVERLAYS", "PAGES", "PASS", "PLAIN_MOVES", "PLUGGED", "POSSIBLY_SENT", "POSTPONED",
           "PUBLIC_CODES",
           "QUIET_HOURS", "REASONS", "RELEASABLE_WITHDRAWALS", "RESEND", "RESENDABLE", "STATES",
           "SUPERSEDE_WITHDRAWALS",
           "TERMINAL", "TURN_STATUSES", "UNKNOWN", "V2_STATES", "WAIT", "WAITING",
           "WAITING_CODES", "WATCHED",
           "WITHDRAW_REASONS", "actor_code", "birth_stop", "counted_from", "decode_gates", "describe", "eligible_at",
           "encode_gates", "epoch", "event_code", "first_refusal", "gate", "gate_budgets",
           "gate_consent", "gate_schedule", "gate_submission_safe", "hold_for_tier", "inherited",
           "may_be_queued",
           "over_ceiling", "overlays", "own_postponement",
           "plain_move_allowed", "public_code", "public_reason", "reason_code", "resend_candidate",
           "still_followed", "turn_status", "waited_aside", "waiting_state", "was_resent", "would_send_at"]
