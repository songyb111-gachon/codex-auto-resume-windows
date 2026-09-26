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

from .domain.gates import (BLOCK, GATE_REASONS, GATE_RESULTS, GATES, HELD, NOT_CHECKED, PASS,
                           UNKNOWN, WAIT, decode_gates, encode_gates, first_refusal,
                           gate, gate_budgets, gate_consent, gate_schedule,
                           gate_submission_safe)
from .domain.public import (ACTORS, EVENT_CODES, FLAG_AFTER_USER_WORK, FLAG_LEGACY,
                            FLAG_USER_JOINED, FLAG_WITHDRAW_DELETED, OVERLAYS, PAGES,
                            PUBLIC_CODES, REASONS, SUPERSEDE_WITHDRAWALS, TURN_STATUSES,
                            WAITING_CODES, WITHDRAW_REASONS, actor_code, describe, eligible_at,
                            event_code, overlays, public_code, public_reason, reason_code,
                            turn_status)
from .domain.states import (CLAIMED, EPOCH_CODEX, EPOCH_STORE, EPOCH_USAGE, EXHAUSTED,
                            IN_FLIGHT, OBSERVING, OUTCOMES, PLAIN_MOVES, POSSIBLY_SENT, STATES,
                            TERMINAL, V2_STATES, WAITING, WATCHED, epoch, may_be_queued,
                            plain_move_allowed, waiting_state)

__all__ = ["ACTORS", "BLOCK", "CLAIMED", "EPOCH_CODEX", "EPOCH_STORE", "EPOCH_USAGE", "EVENT_CODES",
           "EXHAUSTED", "FLAG_AFTER_USER_WORK", "FLAG_LEGACY", "FLAG_USER_JOINED",
           "FLAG_WITHDRAW_DELETED", "GATES", "GATE_REASONS", "GATE_RESULTS", "HELD", "IN_FLIGHT",
           "NOT_CHECKED", "OBSERVING", "OUTCOMES", "OVERLAYS", "PAGES", "PASS", "PLAIN_MOVES",
           "POSSIBLY_SENT", "PUBLIC_CODES", "REASONS", "STATES", "SUPERSEDE_WITHDRAWALS",
           "TERMINAL", "TURN_STATUSES", "UNKNOWN", "V2_STATES", "WAIT", "WAITING",
           "WAITING_CODES", "WATCHED",
           "WITHDRAW_REASONS", "actor_code", "decode_gates", "describe", "eligible_at",
           "encode_gates", "epoch", "event_code", "first_refusal", "gate", "gate_budgets",
           "gate_consent", "gate_schedule", "gate_submission_safe", "may_be_queued", "overlays",
           "plain_move_allowed", "public_code", "public_reason", "reason_code", "turn_status",
           "waiting_state"]
