"""One record as every interface shows it, and the three listings built from it.

`describe_record` is the wire shape the window, the panel and the command line all read, held
to the byte by `tests/golden/`; nothing here may add a key without those moving with it.
"""
from __future__ import annotations

import time

from .. import machine
from ..store import MAX_BUDGET_RESETS
from .errors import ControlError, _identifier



# The journal entries that change a schedule or a flag and never the record's stored
# reason. Every other same-state event really did change the reason - `Store.update`
# writes one whenever `last_error` changed - and so really did change the public code.
_REASON_UNCHANGED = frozenset({"retry_now", "cancel_requested", "would_send"})


def receipts(rows) -> list:
    """What delivery showed of each continuation of one chain (v0.6.11), oldest first: when it was
    seen starting a turn in its conversation, that its delivery is uncertain - watched for a day and
    never sent again - or, handed to Codex and not seen yet, when it was handed over. Times and kinds
    from the records' own columns; no content, and nothing read from the journal."""
    found = []
    for row in sorted(rows, key=lambda row: (row["detected_at"], row["interruption_id"])):
        entry = {"interruption_id": row["interruption_id"]}
        if row.get("recovery_turn_id") and row.get("turn_started_at"):
            found.append(dict(entry, kind="seen", at=row["turn_started_at"]))
        elif row["state"] == "submission_unknown":
            found.append(dict(entry, kind="uncertain", at=row.get("submitted_at") or row.get("last_claim_at")))
        elif row.get("first_queued_at"):
            found.append(dict(entry, kind="queued", at=row["first_queued_at"]))
    return found


def describe_record(row, *, enabled=True, thread_enabled=True, watcher=None) -> dict:
    """One record as every interface shows it: stable machine values only."""
    described = machine.describe(row, enabled=enabled, thread_enabled=thread_enabled, watcher=watcher)
    gates = machine.decode_gates(row.get("gate_eval")) if row.get("gate_eval") else None
    return {
        "interruption_id": row["interruption_id"],
        "thread_id": row["thread_id"],
        "state": row["state"],
        "code": described["code"],
        "reason": described["reason"],
        "overlays": described["overlays"],
        "eligible_at": described["eligible_at"],
        "terminal": described["terminal"],
        "category": row["category"],
        "detected_at": row["detected_at"],
        "reset_at": row["reset_at"],
        "next_retry_at": row["next_retry_at"],
        "recovery_attempts": row["recovery_attempts"],
        "no_progress_count": row["no_progress_count"],
        "chain_continuations": row["chain_continuations"],
        "chain_origin_id": row["chain_origin_id"],
        "parent_interruption_id": row["parent_interruption_id"],
        "budget_resets": row["budget_resets"],
        # So a front end can disable "Give attempts back" when the store would certainly
        # refuse it, instead of offering a button whose only answer is an error.
        "budget_resets_left": max(0, MAX_BUDGET_RESETS - row["budget_resets"]),
        "cancel_requested": bool(row["cancel_requested"]),
        "recovery_turn_status": row["recovery_turn_status"],
        "user_joined": bool(row["user_joined"]),
        "after_user_work": bool(row["after_user_work"]),
        "outcome_at": row["outcome_at"],
        "first_queued_at": row["first_queued_at"],
        "gates": {name: list(result) for name, result in gates.items()} if gates else None,
        "gates_at": row["gate_eval_at"],
        # v0.6.11: not before this time, a person's postponement or an objection window's - and
        # whether it waits for a person to let it continue. Empty at the defaults.
        "not_before": row.get("not_before"),
        "hold": row.get("hold"),
        # v0.6.11: observe only - when every check but consent last passed, so it would have been
        # sent; None for every record that is not only observed.
        "would_send_at": machine.would_send_at(row),
        # v0.6.11: its conversation's token count, as the context-cost guard read it (guards.py);
        # None unless that guard was on.
        "context_tokens": row.get("context_tokens"),
    }


class RecordsMixin:
    """Pending, history, the timeline and the statistics."""

    # ------------------------------------------------------------------- pending
    def _described(self, store, rows, source=None) -> list:
        settings_row = store.settings()
        disabled = store.disabled_threads()
        tiers = store.thread_tiers()
        watcher = self._watcher(store)
        # v0.6.11: the attempts a temporary failure may have now, beside what it has used - which may
        # be more, after the limit was lowered ("19/6"): a count is never cut down to the limit.
        attempts = self.get_settings().get("max_recovery_attempts")
        listed = []
        for row in rows:
            identity = {}
            if source is not None:
                try:
                    identity = source.identity(row["thread_id"]) or {}
                except Exception:
                    identity = {}
            item = describe_record(row, enabled=settings_row["enabled"],
                                   thread_enabled=row["thread_id"] not in disabled,
                                   watcher=watcher)
            item.update({"thread_enabled": row["thread_id"] not in disabled,
                         # Its conversation's own tier, or None: the default in Settings.
                         "tier": tiers.get(row["thread_id"]),
                         # None for a usage limit, which spends no attempt.
                         "attempt_limit": None if row["category"] == "usage_limit" else attempts,
                         "name": identity.get("name"), "project": identity.get("project"),
                         "cwd_basename": identity.get("cwd_basename")})
            listed.append(item)
        return listed

    def list_pending(self, include_terminal: bool = False, source=None) -> list:
        """Pending recoveries, with display labels attached where available.

        Labels are decoration: every action below addresses a record by its exact
        interruption id, never by anything shown here.
        """
        with self._open() as store:
            rows = store.all_records() if include_terminal else store.pending()
            return self._described(store, rows, source)

    def history(self, limit: int = 200, include_hidden: bool = False, source=None) -> list:
        """Recent recoveries, newest first, for the History view. Clear history hides
        rows here and nowhere else."""
        with self._open() as store:
            return self._described(store, store.history(include_hidden=include_hidden, limit=limit), source)

    def timeline(self, interruption_id: str) -> dict:
        """The content-free journal of one recovery's whole chain, oldest first."""
        key = _identifier(interruption_id)
        with self._open() as store:
            record = store.get(key)
            if record is None:
                raise ControlError("no such interruption", code="no_such_interruption")
            events = store.events(chain_origin_id=record["chain_origin_id"])
            chain = [row for row in store.all_records() if row["chain_origin_id"] == record["chain_origin_id"]]
        # Each state an event moved to, also as the public code every interface already
        # has words for - the stored state names are the engine's, not a person's.
        #
        # The code is derived the way the lists derive it, from the state and the reason
        # that was stored with it, so a release after a queue process that never started
        # reads "failed_retryable" here exactly as it does in Pending. The two entries
        # that move only a schedule or a flag keep whatever code that interruption
        # already had: their reason describes the action, not the record.
        previous = {}
        for event in events:
            to_state = event.get("to_state")
            owner = event.get("interruption_id")
            if (to_state and event.get("from_state") == to_state
                    and event.get("code") in _REASON_UNCHANGED and owner in previous):
                code = previous[owner]
            elif to_state:
                code = machine.public_code({"state": to_state, "last_error": event.get("reason")})
            else:
                code = None
            event["to_code"] = code
            if code is not None:
                previous[owner] = code
        return {"interruption_id": key, "chain_origin_id": record["chain_origin_id"], "events": events,
                "receipts": receipts(chain)}

    def statistics(self, days: float | None = None) -> dict:
        since = 0.0 if not days else max(0.0, time.time() - float(days) * 86400)
        with self._open() as store:
            result = store.statistics(since)
        result["period_days"] = days
        return result
